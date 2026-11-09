"""
Cœur de l'application mobile « Comap chauffage » (Android, via Chaquopy).

Interroge Comap Smart Home (ex-Qivivo) et Open-Meteo, et sert la page (valeurs actuelles, graphique) sur 127.0.0.1 pour la WebView de l'application.
Aucun fichier n'est lu ni écrit : tout reste en mémoire. Les réglages (identifiants...) sont passés
par l'application Android via des variables d'environnement (voir comap_android.py).

Lecture seule : ne modifie aucun réglage de chauffage. Programme non officiel.
"""
import json
import os
import threading
import urllib.parse
import urllib.request
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

try:
    from comapsmarthome_public_api.client_auth import ClientAuth
    from comapsmarthome_public_api.measurement_service import MeasurementsService
    from comapsmarthome_public_api.park_service_client import ParkServiceClient
    from comapsmarthome_public_api.thermal_service import ThermalService
except ImportError:
    raise RuntimeError("Module Python manquant : comapsmarthome-public-api")

SERIAL = os.environ.get("COMAP_SERIAL", "").strip()
ZONE_ID = os.environ.get("COMAP_ZONE_ID", "").strip()
MEASURES = [m.strip() for m in os.environ.get("COMAP_MEASUREMENTS", "inside_temperature,temperature_instruction").split(",") if m.strip()]
HEAT_KEY = "heating_commands"  # commande de chauffe, utilisée pour marquer début et fin de chauffe
DISPLAY = [m for m in MEASURES if m != HEAT_KEY] or ["inside_temperature"]
REQUEST = DISPLAY + [HEAT_KEY]
# Identifiant d'application (ClientId) de l'appli web Comap. Le module PyPI contient un ancien
# identifiant (2023) ; celui-ci est celui qu'utilise l'extension Home Assistant (2024).
CLIENT_ID = os.environ.get("COMAP_CLIENT_ID", "56jcvrtejpracljtirq7qnob44").strip()
CACHE_SECONDS = 30  # évite de solliciter Comap à chaque rafraîchissement
try:
    # Correction de la température intérieure (°C), ajoutée à la mesure de Comap. 0,5 par défaut.
    INSIDE_OFFSET = float(os.environ.get("COMAP_OFFSET_INSIDE", "0.5").replace(",", "."))
except ValueError:
    INSIDE_OFFSET = 0.0
try:
    # Correction de la température de consigne (°C), ajoutée à la valeur de Comap. 0,5 par défaut.
    SETPOINT_OFFSET = float(os.environ.get("COMAP_OFFSET_SETPOINT", "0.5").replace(",", "."))
except ValueError:
    SETPOINT_OFFSET = 0.0
# Météo Open-Meteo (gratuit, sans clé, usage non commercial) : température extérieure et ensoleillement.
WEATHER = os.environ.get("COMAP_WEATHER", "1").strip().lower() not in ("0", "false", "non", "no")
try:
    # Quimperlé (coordonnées de Wikipédia). À modifier avec COMAP_LAT et COMAP_LON.
    LAT = float(os.environ.get("COMAP_LAT", "47.8736").replace(",", "."))
    LON = float(os.environ.get("COMAP_LON", "-3.5486").replace(",", "."))
except ValueError:
    LAT, LON = 47.8736, -3.5486
REFRESH = max(20, int(os.environ.get("COMAP_REFRESH", "60")))  # secondes entre deux actualisations de la page

for var in ("COMAP_SMART_HOME_USERNAME", "COMAP_SMART_HOME_PASSWORD"):
    if not os.environ.get(var):
        raise RuntimeError(f"Réglage manquant : {var}")
if not SERIAL and not ZONE_ID:
    raise RuntimeError("Il manque le numéro de série (ou l'identifiant de zone) du thermostat.")

_lock = threading.Lock()
_service = None
_cache = {}  # hours -> (timestamp, payload)
_auth = None
_blocked_until = 0.0  # après un échec de connexion, on arrête d'insister
_last_auth_error = ""  # message exact renvoyé par Comap lors du dernier refus
BLOCK_SECONDS = 20 * 60


class AuthBlocked(Exception):
    pass


def _offset_value(v, offset):
    """Ajoute offset à v si c'est un nombre ; sinon renvoie v tel quel."""
    if offset and isinstance(v, (int, float)) and not isinstance(v, bool):
        return round(v + offset, 2)
    return v


def _apply_offset(rows):
    """Ajoute les corrections à la température intérieure et à la consigne (les autres mesures restent inchangées)."""
    for key, offset in (("inside_temperature", INSIDE_OFFSET), ("temperature_instruction", SETPOINT_OFFSET)):
        if not offset:
            continue
        for r in rows:
            v = r.get(key)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                r[key] = round(v + offset, 2)
    return rows


def _get_auth():
    global _auth
    if _auth is None:
        _auth = ClientAuth()
        _auth.client_id = CLIENT_ID
    return _auth


def _fetch(hours, measures=None, start=None, end=None):
    """Interroge Comap. Se reconnecte une fois si la session a expiré.

    Par défaut : les `hours` dernières heures. Avec start et end (datetime), une plage précise.
    """
    global _service
    end = end or datetime.now().astimezone()
    start = start or end - timedelta(hours=hours)
    fmt = lambda d: d.isoformat(timespec="minutes")
    global _blocked_until, _last_auth_error
    for attempt in (1, 2):
        try:
            if _service is None:
                _service = MeasurementsService(_get_auth())
            return _service.get_measurements(
                fmt(start), fmt(end),
                zone_id=ZONE_ID or None, serial_number=SERIAL or None, measurements=measures or REQUEST,
            )
        except Exception as exc:
            _service = None
            text = str(exc)
            # Erreur d'identifiant ou compte verrouillé : on ne réessaie surtout pas,
            # chaque nouvel essai compte comme une tentative échouée chez Comap.
            if "NotAuthorized" in text or "Password attempts" in text or "Incorrect username" in text:
                _blocked_until = time.time() + BLOCK_SECONDS
                _last_auth_error = text
                print("\n[Comap] Connexion refusée. Message complet :\n" + text + "\n", flush=True)
                raise AuthBlocked(
                    "Comap a refusé la connexion : " + text + " — "
                    "vérifiez l'e-mail et le mot de passe, attendez 20 minutes, puis relancez l'application."
                )
            if attempt == 2:
                raise


_live = {"t": 0.0, "value": None, "housing": None}
LIVE_SECONDS = 20


def get_live():
    """État instantané de la zone, tel que l'affiche l'appli Comap : chauffe en cours, consigne.

    Les mesures archivées (courbes) arrivent avec quelques minutes de retard ; cet état est plus frais.
    """
    global _blocked_until, _last_auth_error
    if time.time() - _live["t"] < LIVE_SECONDS:
        return _live["value"]
    _live["t"] = time.time()
    try:
        auth = _get_auth()
        if not _live["housing"]:
            housings = ParkServiceClient(auth).get_housings()
            _live["housing"] = housings[0]["id"]
        details = ThermalService(auth).get_housing_thermal_details(_live["housing"])
        zones = details.get("zones", []) if isinstance(details, dict) else []
        zone = next((z for z in zones if ZONE_ID and z.get("id") == ZONE_ID), None) or (zones[0] if zones else None)
        if zone:
            sp = zone.get("set_point")
            _live["value"] = {
                "zone": zone.get("title"),
                "heating": zone.get("heating_status"),
                "temperature": (round(zone["temperature"] + INSIDE_OFFSET, 2)
                                if isinstance(zone.get("temperature"), (int, float)) else zone.get("temperature")),
                "setpoint": _offset_value(sp.get("instruction"), SETPOINT_OFFSET) if isinstance(sp, dict) else None,
                "transmission_error": zone.get("transmission_error"),
                "at": datetime.now().astimezone().isoformat(timespec="seconds"),
            }
        else:
            _live["value"] = None
    except Exception as exc:
        text = str(exc)
        _live["value"] = None
        if "NotAuthorized" in text or "Password attempts" in text or "Incorrect username" in text:
            _blocked_until = time.time() + BLOCK_SECONDS
            _last_auth_error = text
            raise AuthBlocked("Comap a refusé la connexion : " + text)
    return _live["value"]


_page_error = {"msg": ""}
_battery = {"t": 0.0, "value": None}


def _ts(row):
    try:
        return datetime.fromisoformat(str(row["time"]).replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _num(value):
    return f"{value:.1f}".replace(".", ",") if isinstance(value, (int, float)) else ""


def get_battery():
    """Dernière tension relevée sur 7 jours (le thermostat ne l'envoie pas à chaque mesure)."""
    if time.time() - _battery["t"] < 600:
        return _battery["value"]
    _battery["t"] = time.time()  # même en cas d'échec, on n'insiste pas avant 10 minutes
    try:
        rows = _fetch(168, ["voltage"]) or []
        rows = [r for r in rows if r.get("time") and isinstance(r.get("voltage"), (int, float))]
        rows.sort(key=_ts)
        _battery["value"] = {"value": rows[-1]["voltage"], "time": rows[-1]["time"]} if rows else None
    except AuthBlocked:
        raise
    except Exception:
        _battery["value"] = None
    return _battery["value"]


_weather = {"t": 0.0, "value": None}


def _om_time(value):
    """Heure d'Open-Meteo en secondes (epoch) : nombre (unixtime) ou texte ISO local."""
    if isinstance(value, (int, float)):
        return float(value)
    return datetime.fromisoformat(str(value)).timestamp()


def get_weather():
    """Météo horaire Open-Meteo pour LAT/LON : température, rayonnement solaire, ensoleillement,
    précipitations et code météo (jusqu'à 48 h de prévision).

    Les valeurs de rayonnement et d'ensoleillement à l'heure T portent sur l'heure PRÉCÉDENTE (T-1 h à T).
    Mise en cache 30 min (quelques dizaines d'appels par jour, très en dessous de la limite gratuite).
    """
    if not WEATHER:
        return None
    if _weather["value"] and time.time() - _weather["t"] < 1800:
        return _weather["value"]
    query = urllib.parse.urlencode({
        "latitude": LAT, "longitude": LON,
        "hourly": "temperature_2m,shortwave_radiation,sunshine_duration,precipitation,weather_code,is_day",
        "past_days": 3, "forecast_days": 8,
        "timeformat": "unixtime", "timezone": "Europe/Paris",
    })
    request = urllib.request.Request(os.environ.get("COMAP_WEATHER_URL", "https://api.open-meteo.com/v1/forecast") + "?" + query,
                                     headers={"User-Agent": "comap-dashboard (usage personnel)"})
    try:
        with urllib.request.urlopen(request, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        hourly = data["hourly"]
        points = []
        for i, t in enumerate(hourly["time"]):
            sun = hourly["sunshine_duration"][i]
            points.append({"t": _om_time(t), "temp": hourly["temperature_2m"][i],
                           "rad": hourly["shortwave_radiation"][i],
                           "sun_min": None if sun is None else round(sun / 60, 1),
                           "precip": hourly["precipitation"][i],   # mm sur l'heure précédente
                           "code": hourly["weather_code"][i],      # code météo WMO
                           "day": hourly["is_day"][i]})            # 1 = jour, 0 = nuit
        points.sort(key=lambda p: p["t"])
        _weather["value"] = {"points": points, "lat": LAT, "lon": LON}
        _weather["t"] = time.time()
    except Exception:
        if _weather["value"] and time.time() - _weather["t"] < 6 * 3600:
            _weather["t"] = time.time() - 1800 + 300  # on garde les dernières valeurs et on réessaie dans 5 min
            return _weather["value"]
        raise
    return _weather["value"]


def weather_for(weather, ts):
    """(température extérieure, rayonnement W/m², minutes de soleil) à l'instant ts ; chaînes vides si hors plage."""
    points = weather["points"] if weather else []
    if not points or ts < points[0]["t"] or ts > points[-1]["t"]:
        return "", "", ""
    for i in range(1, len(points)):
        if points[i]["t"] >= ts:
            a, b = points[i - 1], points[i]
            temp = ""
            if a["temp"] is not None and b["temp"] is not None:
                temp = _num(a["temp"] + (b["temp"] - a["temp"]) * (ts - a["t"]) / ((b["t"] - a["t"]) or 1))
            # l'heure qui contient ts est celle qui se termine à b["t"]
            rad = "" if b["rad"] is None else round(b["rad"])
            sun = "" if b["sun_min"] is None else round(b["sun_min"])
            return temp, rad, sun
    return "", "", ""


def get_data(hours):
    with _lock:
        if time.time() < _blocked_until:
            raise AuthBlocked(
                "Connexion suspendue après ce refus de Comap : " + _last_auth_error + " — "
                "corrigez la cause, attendez 20 minutes, puis relancez l'application."
            )
        cached = _cache.get(hours)
        if cached and time.time() - cached[0] < CACHE_SECONDS:
            return cached[1]
        rows = _apply_offset(_fetch(hours) or [])
        weather_info = {"weather": None, "error": ""}
        try:
            weather_info["weather"] = get_weather()
        except Exception as exc:
            weather_info["error"] = f"{type(exc).__name__} : {exc}"
        payload = {
            "measures": DISPLAY,
            "heat_key": HEAT_KEY,
            "battery": get_battery(),
            "live": get_live(),
            "refresh": REFRESH,
            "weather": weather_info["weather"],
            "weather_error": weather_info["error"],
            "offset": INSIDE_OFFSET,
            "setpoint_offset": SETPOINT_OFFSET,
            "points": rows,
            "updated": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        _cache[hours] = (time.time(), payload)
        return payload


PAGE = """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<title>Chauffage</title>
<style>
  :root {
    --bg: #eef1f0; --panel: #ffffff; --ink: #1b2326; --muted: #5f6e74;
    --line: #dde3e2; --accent: #1f6f8b; --accent-ink: #ffffff; --warn: #b3392b;
    --hot: #d03a2f; --cool: #2c6bd6; --sun: #d99a00; --chip: #f2f5f4;
    --shadow: 0 1px 2px rgba(0,0,0,.06), 0 4px 14px rgba(0,0,0,.05);
  }
  @media (prefers-color-scheme: dark) {
    :root { --bg: #0f1416; --panel: #192024; --ink: #e8ecee; --muted: #93a2a8;
            --line: #2a353a; --accent: #6cc3de; --accent-ink: #0c1b21; --warn: #f08a7c;
            --hot: #ff6b5e; --cool: #6aa8ff; --sun: #ffd24d; --chip: #222c31;
            --shadow: 0 1px 2px rgba(0,0,0,.4); }
  }
  * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
  html, body { margin: 0; min-height: 100%; background: var(--bg); color: var(--ink);
               overscroll-behavior: none; -webkit-user-select: none; user-select: none;
               -webkit-touch-callout: none; }
  body { font: 15px/1.4 Roboto, system-ui, "Segoe UI", sans-serif; }
  #app { display: flex; flex-direction: column; gap: 12px; padding: 12px; max-width: 900px; margin: 0 auto; }
  .card { background: var(--panel); border-radius: 18px; box-shadow: var(--shadow); padding: 14px 16px; }

  /* ---- valeurs actuelles ---- */
  .hero { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; }
  .lab { color: var(--muted); font-size: .78rem; letter-spacing: .02em; }
  .big { font-size: 3.2rem; font-weight: 500; line-height: 1.05; letter-spacing: -.02em; }
  .big small { font-size: 1.2rem; font-weight: 400; color: var(--muted); margin-left: 3px; letter-spacing: 0; }
  .sub { color: var(--muted); font-size: .78rem; }
  .heroside { display: flex; flex-direction: column; align-items: flex-end; gap: 8px; }
  .icons { display: flex; gap: 4px; }
  .iconbtn { width: 40px; height: 40px; padding: 0; border-radius: 50%; display: grid; place-items: center;
             border: 0; background: var(--chip); color: var(--ink); }
  .iconbtn svg { width: 20px; height: 20px; fill: none; stroke: currentColor; stroke-width: 2;
                 stroke-linecap: round; stroke-linejoin: round; }
  .iconbtn.spin svg { animation: spin .9s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .chip { display: inline-block; padding: 5px 12px; border-radius: 999px; font-size: .85rem; font-weight: 600;
          background: var(--chip); color: var(--muted); white-space: nowrap; }
  .chip.on { background: var(--hot); color: #fff; }
  .stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
  .stat { padding: 10px 12px; }
  .stat .v { font-size: 1.25rem; font-weight: 500; margin-top: 2px; white-space: nowrap; }
  .stat .sub { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

  /* ---- graphique ---- */
  .chartcard { display: flex; flex-direction: column; padding: 12px; }
  .bar { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; }
  .seg { display: flex; background: var(--chip); border-radius: 12px; padding: 3px; gap: 2px; flex: 1; }
  .seg button { flex: 1; }
  button { font: inherit; color: var(--ink); background: transparent; border: 0; border-radius: 10px;
           padding: 8px 6px; cursor: pointer; transition: transform .08s, background .15s; }
  button:active { transform: scale(.96); }
  .seg button[aria-pressed="true"] { background: var(--panel); color: var(--accent); font-weight: 600;
                                     box-shadow: 0 1px 3px rgba(0,0,0,.18); }
  .pill { background: var(--chip); padding: 9px 14px; font-weight: 500; }
  .pill[aria-pressed="true"] { background: var(--accent); color: var(--accent-ink); }
  .pill:disabled { opacity: .4; }
  .tip { height: 3.9em; overflow: hidden; font-size: .8rem; line-height: 1.3; color: var(--ink); margin-bottom: 4px; }
  .tip.idle { color: var(--muted); display: flex; align-items: center; }
  .tip .t { font-weight: 600; margin-right: 8px; }
  .tip .it { display: inline-block; margin-right: 12px; white-space: nowrap; }
  .tip .sw { display: inline-block; width: 14px; height: 0; border-top: 3px solid var(--ink); margin-right: 5px;
             vertical-align: middle; }
  .tip .sw.curve-out, .tip .sw.curve-sp { border-top-style: dashed; }
  .sw.curve-in { border-color: var(--hot); } .sw.curve-out { border-color: var(--cool); } .sw.curve-sp { border-color: var(--accent); }
  .tip .soft { color: var(--muted); }
  .tip .hot { color: var(--hot); font-weight: 600; }
  .chartwrap { position: relative; height: clamp(220px, 36vh, 380px); }
  #chart { position: absolute; inset: 0; width: 100%; height: 100%; touch-action: pan-y; }
  svg text { fill: var(--muted); font-size: 11px; }
  svg text.wxicon { font-size: 16px; fill: initial; }
  .grid { stroke: var(--line); stroke-width: 1; }
  .curve-in { fill: none; stroke: var(--hot); stroke-width: 2.4; stroke-linejoin: round; }
  .curve-out { fill: none; stroke: var(--cool); stroke-width: 2.2; stroke-dasharray: 7 4; }
  .curve-sp { fill: none; stroke: var(--accent); stroke-width: 2; stroke-dasharray: 5 3; }
  .curve, .curve-alt, .curve-dot { fill: none; stroke: var(--muted); stroke-width: 2; }
  .future { stroke-width: 2.5; stroke-dasharray: 1 4; stroke-linecap: round; }
  .dot-curve-in { fill: var(--hot); stroke: var(--panel); stroke-width: 2; }
  .dot-curve-out { fill: var(--cool); stroke: var(--panel); stroke-width: 2; }
  .dot-curve-sp { fill: var(--accent); stroke: var(--panel); stroke-width: 2; }
  .dot-curve, .dot-curve-alt, .dot-curve-dot { fill: var(--muted); stroke: var(--panel); stroke-width: 2; }
  .cursor { stroke: var(--ink); stroke-width: 1; opacity: .45; }
  .nowline { stroke: var(--muted); stroke-width: 1; stroke-dasharray: 2 3; }
  .band { fill: var(--hot); opacity: .12; }
  .edge-start { stroke: var(--hot); stroke-width: 1.5; }
  .edge-end { stroke: var(--hot); stroke-width: 1.5; stroke-dasharray: 4 3; }
  .sunbar { fill: var(--sun); opacity: .4; }
  .rainbar { fill: var(--cool); opacity: .55; }
  .legend { color: var(--muted); font-size: .72rem; margin: 8px 0 0; }

  /* ---- pied de page ---- */
  footer { color: var(--muted); font-size: .72rem; padding: 0 6px 8px; }
  footer a { color: inherit; }
  #status.err { display: block; background: var(--warn); color: #fff; padding: 8px 12px; border-radius: 12px;
                margin-bottom: 6px; font-size: .8rem; }

  /* ---- paysage : valeurs à gauche, graphique pleine hauteur à droite ---- */
  @media (orientation: landscape) and (max-height: 560px) {
    html, body { height: 100%; overflow: hidden; }
    #app { display: grid; grid-template-columns: minmax(210px, 30%) 1fr; grid-template-rows: 1fr auto;
           grid-template-areas: "side chart" "foot chart"; height: 100vh; max-width: none; gap: 8px 10px; padding: 8px 10px; }
    #side { grid-area: side; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; min-height: 0; }
    .chartcard { grid-area: chart; min-height: 0; }
    footer { grid-area: foot; padding: 0 4px; overflow: hidden; max-height: 5.5em; }
    .chartwrap { flex: 1; height: auto; min-height: 0; }
    .big { font-size: 2.6rem; }
    .stats { grid-template-columns: 1fr 1fr 1fr; gap: 6px; }
    .stat { padding: 6px 8px; }
    .stat .v { font-size: 1rem; }
    .stat .sub { display: none; }
    .card { padding: 10px 12px; border-radius: 14px; }
    .tip { height: 2.7em; }
    .legend { display: none; }
    .seg button { padding: 6px 4px; }
    .pill { padding: 7px 12px; }
  }
</style>
</head>
<body>
<div id="app">
  <div id="side">
    <section class="card hero" aria-label="Température intérieure">
      <div>
        <div class="lab">Température intérieure</div>
        <div class="big"><span id="tIn">–</span><small>°C</small></div>
        <div class="sub" id="tInSub">&nbsp;</div>
      </div>
      <div class="heroside">
        <div class="icons">
          <button class="iconbtn" id="refbtn" aria-label="Actualiser" title="Actualiser">
            <svg viewBox="0 0 24 24"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 3v6h-6"/></svg>
          </button>
          <button class="iconbtn" id="setbtn" aria-label="Réglages" title="Réglages">
            <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>
          </button>
        </div>
        <span class="chip" id="heat">Chauffage –</span>
        <div class="sub" id="heatSub" style="text-align:right">&nbsp;</div>
      </div>
    </section>
    <section class="stats" aria-label="Autres valeurs">
      <div class="card stat"><div class="lab">Consigne</div><div class="v" id="sp">–</div><div class="sub" id="spSub">&nbsp;</div></div>
      <div class="card stat"><div class="lab">Extérieur</div><div class="v" id="tOut">–</div><div class="sub" id="tOutSub">&nbsp;</div></div>
      <div class="card stat"><div class="lab">Piles</div><div class="v" id="bat">–</div><div class="sub" id="batSub">&nbsp;</div></div>
    </section>
  </div>

  <section class="card chartcard">
    <div class="bar">
      <div class="seg tabs" role="group" aria-label="Période">
        <button data-h="6" aria-pressed="false">6 h</button>
        <button data-h="24" aria-pressed="true">24 h</button>
        <button data-h="72" aria-pressed="false">3 j</button>
        <button data-h="168" aria-pressed="false">7 j</button>
      </div>
      <button id="wxbtn" class="pill" aria-pressed="false">Météo</button>
    </div>
    <div class="tip idle" id="tip"></div>
    <div class="chartwrap"><svg id="chart" role="img" aria-label="Courbe des températures"></svg></div>
    <p class="legend" id="legend"></p>
  </section>

  <footer>
    <span id="status" role="status">Chargement…</span>
    <span id="foot"></span>
  </footer>
</div>

<script>
const LABELS = { inside_temperature: "Température intérieure", inside_humidity: "Humidité intérieure",
                 temperature_instruction: "Consigne", outside_temperature: "Température extérieure",
                 outside_humidity: "Humidité extérieure", voltage: "Tension", presence: "Présence",
                 heating_commands: "Commande de chauffe" };
const SHORT = { inside_temperature: "Intérieure", temperature_instruction: "Consigne", outside_temperature: "Extérieure" };
const UNITS = { inside_temperature: " °C", inside_humidity: " %", temperature_instruction: " °C",
                outside_temperature: " °C", outside_humidity: " %", voltage: " V" };
let hours = 24;
// bouton « Météo » : 0 = sans météo, 1 = prévision à 48 h, 2 = prévision à 7 jours, puis retour à 0
let weatherMode = 0;
const WX_HORIZONS = [0, 48 * 3600000, 7 * 24 * 3600000];
const WX_BTN = ["Météo", "Météo 48 h", "Météo 7 j"];
// code météo WMO (Open-Meteo) -> [libellé, icône]
function wxInfo(code, isDay) {
  const d = isDay !== 0;
  const pick = (txt, day, night) => [txt, d ? day : night];
  if (code === 0) return pick("Ciel dégagé", "☀️", "🌙");
  if (code === 1) return pick("Plutôt dégagé", "🌤️", "🌙");
  if (code === 2) return pick("Partiellement nuageux", "⛅", "☁️");
  if (code === 3) return pick("Couvert", "☁️", "☁️");
  if (code === 45 || code === 48) return pick("Brouillard", "🌫️", "🌫️");
  if (code >= 51 && code <= 57) return pick("Bruine", "🌦️", "🌧️");
  if (code >= 61 && code <= 67) return pick("Pluie", "🌧️", "🌧️");
  if (code >= 71 && code <= 77) return pick("Neige", "🌨️", "🌨️");
  if (code >= 80 && code <= 82) return pick("Averses", "🌦️", "🌧️");
  if (code === 85 || code === 86) return pick("Averses de neige", "🌨️", "🌨️");
  if (code >= 95) return pick("Orage", "⛈️", "⛈️");
  return pick("Météo inconnue", "❓", "❓");
}
const $ = (id) => document.getElementById(id);
const label = (k) => LABELS[k] || k;
const num = (v, d = 1) => (typeof v === "number" ? v.toFixed(d).replace(".", ",") : "–");
const fmtVal = (k, v) => (typeof v === "number" ? num(v) + (UNITS[k] || "") : "–");
const fmtTime = (t) => new Date(t).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
const fmtHM = (t) => new Date(t).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
const signed = (v) => (v > 0 ? "+" : "") + num(v);

function setStatus(text, isError) {
  const s = $("status");
  s.textContent = text;
  s.className = isError ? "err" : "";
}

const tms = (p) => new Date(p.time).getTime();

// ---- météo Open-Meteo (températures horaires ; rayonnement et soleil portent sur l'heure précédente)
function weatherTempAt(ms) {
  const w = window.WEATHER;
  if (!w || !w.points.length) return null;
  const P = w.points, s = ms / 1000;
  if (s < P[0].t || s > P[P.length - 1].t) return null;
  for (let i = 1; i < P.length; i++) {
    if (P[i].t >= s) {
      const a = P[i - 1], b = P[i];
      if (a.temp == null || b.temp == null) return null;
      return a.temp + (b.temp - a.temp) * ((s - a.t) / (b.t - a.t || 1));
    }
  }
  return null;
}
// heure (T-1 h, T] qui contient l'instant ms
function weatherHourAt(ms) {
  const w = window.WEATHER;
  if (!w) return null;
  return w.points.find((p) => p.t * 1000 >= ms && p.t * 1000 - 3600000 < ms) || null;
}

function isOn(v) {
  if (typeof v === "boolean") return v;
  if (typeof v === "number") return v > 0;
  if (typeof v === "string") return ["on", "true", "1", "heat", "heating", "chauffe", "marche"].includes(v.trim().toLowerCase());
  return false;
}

// Une période commence à la première mesure où la chauffe est active
// et se termine à la DERNIÈRE mesure où elle était encore active.
function computePeriods(pts, heatKey) {
  const known = pts.filter((p) => p[heatKey] !== undefined && p[heatKey] !== null);
  const periods = [];
  let cur = null;
  known.forEach((p) => {
    const on = isOn(p[heatKey]);
    if (on && !cur) cur = { start: p, end: null, last: p };
    else if (on && cur) cur.last = p;
    else if (!on && cur) { cur.end = cur.last; periods.push(cur); cur = null; }
  });
  if (cur) periods.push(cur);
  return { known: known.length, periods };
}

// L'historique de Comap arrive avec quelques minutes de retard. Si l'état instantané diffère de
// la dernière période de l'historique, on la clôt (ou on en ouvre une) à l'heure où le changement a été constaté.
function reconcileLive(heat, live, tempKey) {
  if (!live || !live.at) return;
  const running = live.heating === "heating";
  const last = heat.periods[heat.periods.length - 1];
  const histRunning = !!(last && !last.end);
  const mk = () => {
    const p = { time: live.at, synthetic: true };
    if (tempKey === "inside_temperature" && typeof live.temperature === "number") p[tempKey] = live.temperature;
    return p;
  };
  if (!running && histRunning) {
    last.end = Object.assign({}, last.last, { synthetic: true });
    last.reconciled = true;
  } else if (running && !histRunning) {
    const p = mk();
    heat.periods.push({ start: p, end: null, last: p, reconciled: true });
  }
  heat.known = Math.max(heat.known, 1);
}

const INSTRUCTIONS = { night: "Nuit", stop: "Arrêt" };
const instructionText = (v) => (typeof v === "number" ? fmtVal("temperature_instruction", v)
                                 : INSTRUCTIONS[v] ? INSTRUCTIONS[v] : String(v));

function renderNow(measures, pts, heat, battery, live) {
  const lastWith = (m) => { for (let i = pts.length - 1; i >= 0; i--) if (typeof pts[i][m] === "number") return pts[i]; return null; };
  // température intérieure + tendance sur environ 1 h
  const main = measures.includes("inside_temperature") ? "inside_temperature" : measures[0];
  const last = lastWith(main) || pts[pts.length - 1];
  $("tIn").textContent = num(last[main]);
  let sub = "mesure de " + fmtHM(last.time);
  const ref = pts.find((p) => tms(p) >= tms(last) - 3600000 && typeof p[main] === "number");
  if (ref && ref !== last && typeof last[main] === "number") sub += " · " + signed(last[main] - ref[main]) + " sur 1 h";
  $("tInSub").textContent = sub;

  // état du chauffage : l'état instantané de Comap prime sur l'historique, qui a du retard
  const hasLive = !!(live && live.at);
  const chip = $("heat"), hsub = $("heatSub");
  if (hasLive || heat.known > 0) {
    const lastPeriod = heat.periods[heat.periods.length - 1];
    const histRunning = !!(lastPeriod && !lastPeriod.end);
    const running = hasLive ? live.heating === "heating" : histRunning;
    chip.textContent = running ? "Chauffe en cours" : "À l'arrêt";
    chip.className = "chip" + (running ? " on" : "");
    let t = "";
    if (lastPeriod && lastPeriod.reconciled) t = (running ? "démarré vers " : "arrêté vers ") + fmtHM((running ? lastPeriod.start : lastPeriod.end).time);
    else if (lastPeriod) t = "depuis " + fmtTime(running ? lastPeriod.start.time : lastPeriod.end.time);
    hsub.textContent = t || " ";
  } else {
    chip.textContent = "Chauffage –";
    chip.className = "chip";
    hsub.textContent = " ";
  }

  // consigne : état instantané si disponible, sinon dernière mesure archivée
  const spLast = lastWith("temperature_instruction");
  const spVal = live && live.setpoint !== null && live.setpoint !== undefined ? live.setpoint : (spLast ? spLast.temperature_instruction : null);
  $("sp").textContent = spVal === null ? "–" : instructionText(spVal);
  $("spSub").textContent = live && live.setpoint != null ? "en ce moment" : (spLast ? "mesure de " + fmtHM(spLast.time) : " ");

  // température extérieure : Open-Meteo (interpolée) si disponible, sinon dernière mesure
  const wNow = window.WEATHER ? weatherTempAt(Date.now()) : null;
  if (wNow !== null) {
    $("tOut").textContent = fmtVal("outside_temperature", wNow);
    const before = weatherTempAt(Date.now() - 3600000);
    $("tOutSub").textContent = before !== null ? signed(wNow - before) + " sur 1 h" : "Open-Meteo";
  } else {
    const o = lastWith("outside_temperature");
    $("tOut").textContent = o ? fmtVal("outside_temperature", o.outside_temperature) : "–";
    $("tOutSub").textContent = o ? "mesure de " + fmtHM(o.time) : " ";
  }

  // niveau des piles : tension relevée par le thermostat
  if (battery && typeof battery.value === "number") {
    const v = battery.value > 50 ? battery.value / 1000 : battery.value;
    $("bat").textContent = num(v, 2) + " V";
    $("batSub").textContent = fmtTime(battery.time);
  } else {
    $("bat").textContent = "–";
    $("batSub").textContent = "pas de mesure (7 j)";
  }
}

const TEMP_KEYS = ["inside_temperature", "outside_temperature", "temperature_instruction"];
const CURVE_CLASSES = ["curve", "curve-alt", "curve-dot"];
const CURVE_BY_KEY = { inside_temperature: "curve-in", outside_temperature: "curve-out", temperature_instruction: "curve-sp" };
const SAMPLE_BY_CLASS = { "curve-in": "───", "curve-out": "╌╌╌", "curve-sp": "╌╌╌", "curve-alt": "╌╌╌", "curve-dot": "···", "curve": "───" };
const IDLE_TIP = "Touchez le graphique pour lire les valeurs";

let lastChartArgs = null;
function redrawSoon() {
  clearTimeout(window.__rz);
  window.__rz = setTimeout(() => { if (lastChartArgs) renderChart(...lastChartArgs); }, 150);
}
window.addEventListener("resize", redrawSoon);
if (window.ResizeObserver) new ResizeObserver(redrawSoon).observe(document.querySelector(".chartwrap"));

function tipIdle() {
  const tip = $("tip");
  tip.className = "tip idle";
  tip.textContent = IDLE_TIP;
}

function renderChart(measures, pts, periods, nowT, heatKnown, live) {
  lastChartArgs = [measures, pts, periods, nowT, heatKnown, live];
  const svg = $("chart");
  svg.replaceChildren();
  const ns = "http://www.w3.org/2000/svg";
  const temps = measures.filter((m) => TEMP_KEYS.includes(m));
  const keys = temps.length ? temps : [measures[0]];
  const first = pts.length ? tms(pts[0]) : nowT - 24 * 3600000;
  const series = keys.map((k, i) => {
    const cls = CURVE_BY_KEY[k] || CURVE_CLASSES[i] || "curve-dot";
    let data = pts.filter((p) => typeof p[k] === "number").map((p) => ({ t: tms(p), v: p[k] }));
    if (k === "outside_temperature" && window.WEATHER) {
      data = window.WEATHER.points
        .filter((p) => typeof p.temp === "number" && p.t * 1000 >= first - 3600000 && p.t * 1000 <= nowT + (weatherMode ? WX_HORIZONS[weatherMode] : 6 * 3600000))
        .map((p) => ({ t: p.t * 1000, v: p.temp }));
    }
    // la consigne est en escalier : on prolonge sa dernière valeur jusqu'à maintenant
    if (k === "temperature_instruction" && data.length && data[data.length - 1].t < nowT) {
      data.push({ t: nowT, v: data[data.length - 1].v, ext: true });
    }
    return { k, cls, step: k === "temperature_instruction", sample: SAMPLE_BY_CLASS[cls] || "···", data };
  }).filter((s) => s.data.length > 1);
  // repli : si Comap ne fournit pas l'historique de la consigne, trait horizontal à la consigne actuelle
  if (!series.some((s) => s.k === "temperature_instruction") && live && typeof live.setpoint === "number") {
    series.push({ k: "temperature_instruction", cls: "curve-sp", step: true, flat: true, sample: SAMPLE_BY_CLASS["curve-sp"],
                  data: [{ t: first, v: live.setpoint }, { t: nowT, v: live.setpoint, ext: true }] });
  }
  const wx = weatherMode > 0 && window.WEATHER;
  if (wx && !series.some((s) => s.k === "outside_temperature")) {
    const data = window.WEATHER.points
      .filter((p) => typeof p.temp === "number" && p.t * 1000 >= first - 3600000 && p.t * 1000 <= nowT + WX_HORIZONS[weatherMode])
      .map((p) => ({ t: p.t * 1000, v: p.temp }));
    if (data.length > 1) series.push({ k: "outside_temperature", cls: "curve-out", sample: SAMPLE_BY_CLASS["curve-out"], data });
  }
  if (!series.length) { $("legend").textContent = ""; tipIdle(); return; }
  const all = series.flatMap((s) => s.data);
  // le dessin épouse exactement la zone du graphique (portrait comme paysage)
  const box = svg.getBoundingClientRect();
  const W = Math.max(240, Math.round(box.width || 320));
  const H = Math.max(160, Math.round(box.height || 260));
  const wxEvery = weatherMode === 2 ? (W < 600 ? 24 : 6) : (W < 600 ? 6 : 3);
  const L = W < 600 ? 36 : 46, R = 10, T = wx ? 30 : 10, B = 24;
  svg.setAttribute("viewBox", "0 0 " + W + " " + H);
  const t0 = Math.min(...all.map((d) => d.t)), t1 = Math.max(...all.map((d) => d.t));
  let lo = Math.min(...all.map((d) => d.v)), hi = Math.max(...all.map((d) => d.v));
  if (hi - lo < 1) { lo -= 0.5; hi += 0.5; }
  const pad = (hi - lo) * 0.1; lo -= pad; hi += pad;
  const x = (t) => L + ((t - t0) / (t1 - t0 || 1)) * (W - L - R);
  const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const clamp = (t) => Math.min(Math.max(t, t0), t1);
  const el = (name, attrs, text) => {
    const e = document.createElementNS(ns, name);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (text) e.textContent = text;
    svg.append(e);
  };
  const nTicks = H < 220 ? 3 : 4;
  for (let i = 0; i <= nTicks; i++) {
    const v = lo + ((hi - lo) * i) / nTicks;
    el("line", { x1: L, x2: W - R, y1: y(v), y2: y(v), class: "grid" });
    el("text", { x: L - 5, y: y(v) + 4, "text-anchor": "end" }, num(v));
  }
  const steps = W < 520 ? 2 : W < 800 ? 3 : 5;
  for (let i = 0; i <= steps; i++) {
    const t = t0 + ((t1 - t0) * i) / steps;
    const txt = hours > 24 || (t1 - t0) > 30 * 3600000
      ? new Date(t).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })
      : fmtHM(t);
    el("text", { x: x(t), y: H - 7, "text-anchor": i === 0 ? "start" : i === steps ? "end" : "middle" }, txt);
  }
  // ensoleillement Open-Meteo : une barre par heure
  let hasSun = false;
  if (window.WEATHER) {
    const plotH = H - T - B;
    window.WEATHER.points.forEach((p) => {
      if (typeof p.rad !== "number" || p.rad <= 0) return;
      const a = p.t * 1000 - 3600000, b = p.t * 1000;
      if (b < t0 || a > t1) return;
      const xa = x(clamp(a)), xb = x(clamp(b));
      const h = Math.min(p.rad / 1000, 1) * plotH * 0.25;
      el("rect", { x: xa, y: H - B - h, width: Math.max(xb - xa - 1, 1), height: h, class: "sunbar" });
      hasSun = true;
    });
  }
  // météo : précipitations (barres bleues suspendues en haut) et icônes
  let hasRain = false;
  if (wx) {
    const plotH = H - T - B;
    window.WEATHER.points.forEach((p) => {
      if (typeof p.precip !== "number" || p.precip <= 0) return;
      const a = p.t * 1000 - 3600000, b = p.t * 1000;
      if (b < t0 || a > t1) return;
      const xa = x(clamp(a)), xb = x(clamp(b));
      const h = Math.max(4, Math.sqrt(Math.min(p.precip / 5, 1)) * plotH * 0.3);
      el("rect", { x: xa, y: T, width: Math.max(xb - xa - 1, 1), height: h, class: "rainbar" });
      hasRain = true;
    });
    window.WEATHER.points.forEach((p) => {
      const ms = p.t * 1000;
      if (ms < t0 || ms > t1 || typeof p.code !== "number") return;
      if (new Date(ms).getHours() % wxEvery !== 0) return;
      el("text", { x: x(ms), y: 18, "text-anchor": "middle", class: "wxicon" }, wxInfo(p.code, p.day)[1]);
    });
  }
  // périodes de chauffe : bande colorée, trait plein au début, pointillé à la fin
  (periods || []).forEach((pr) => {
    const ts = tms(pr.start), te = pr.end ? tms(pr.end) : tms(pr.last);
    if (te < t0 || ts > t1) return;
    const x0 = x(clamp(ts)), x1 = x(clamp(te));
    el("rect", { x: x0, y: T, width: Math.max(x1 - x0, 2), height: H - T - B, class: "band" });
    if (ts >= t0) el("line", { x1: x0, x2: x0, y1: T, y2: H - B, class: "edge-start" });
    if (pr.end && te <= t1) el("line", { x1: x1, x2: x1, y1: T, y2: H - B, class: "edge-end" });
  });
  const toPoints = (arr, step) => {
    const out = [];
    arr.forEach((d, i) => {
      if (step && i > 0) out.push(x(d.t).toFixed(1) + "," + y(arr[i - 1].v).toFixed(1));
      out.push(x(d.t).toFixed(1) + "," + y(d.v).toFixed(1));
    });
    return out.join(" ");
  };
  let hasFuture = false;
  // la consigne est dessinée en dessous, la température intérieure par-dessus
  series.slice().reverse().forEach((s) => {
    const past = s.data.filter((d) => d.t <= nowT), fut = s.data.filter((d) => d.t > nowT);
    if (past.length > 1) el("polyline", { class: s.cls, points: toPoints(past, s.step) });
    if (fut.length && !s.step) {
      hasFuture = true;
      el("polyline", { class: s.cls + " future", points: toPoints(past.length ? [past[past.length - 1], ...fut] : fut) });
    }
  });
  if (hasFuture && nowT > t0 && nowT < t1) {
    el("line", { x1: x(nowT), x2: x(nowT), y1: T, y2: H - B, class: "nowline" });
    el("text", { x: x(nowT) - 4, y: T + 10, "text-anchor": "end" }, "maintenant");
  }
  // légende
  const parts = series.map((s) => s.sample + " " + label(s.k));
  if (window.OFFSET && keys.includes("inside_temperature")) parts.push("intérieure corrigée de " + signed(window.OFFSET) + " °C");
  if (window.SP_OFFSET && keys.includes("temperature_instruction")) parts.push("consigne corrigée de " + signed(window.SP_OFFSET) + " °C");
  if (wx) {
    const fp = window.WEATHER.points.filter((p) => p.t * 1000 > nowT && p.t * 1000 <= t1);
    const total = fp.reduce((a, p) => a + (typeof p.precip === "number" ? p.precip : 0), 0);
    if (hasRain) parts.push("barres bleues : pluie par heure (cumul prévu " + num(total) + " mm)");
    else parts.push("aucune précipitation prévue");
    parts.push("icônes : météo toutes les " + wxEvery + " h");
  }
  if (hasSun) parts.push("barres jaunes : soleil");
  if (periods && periods.length) parts.push("zone rouge : chauffage en marche");
  $("legend").textContent = parts.join("  ·  ");

  // ---- lecture des valeurs : barre fixe au-dessus du graphique (jamais sous le doigt) ----
  const hover = document.createElementNS(ns, "g");
  svg.append(hover);
  const tip = $("tip");
  const real = (sr) => sr.data.filter((d) => !d.ext);
  const nearest = (arr, t) => {
    let best = arr[0], bd = Math.abs(arr[0].t - t);
    for (const d of arr) { const dd = Math.abs(d.t - t); if (dd < bd) { best = d; bd = dd; } }
    return best;
  };
  const allT = [...new Set(series.flatMap((sr) => (sr.flat ? [] : real(sr)).map((d) => d.t)))];
  const clearHover = () => { hover.replaceChildren(); window.__sel = null; tipIdle(); };
  const item = (parent, cls, text) => {
    const s = document.createElement("span");
    s.className = cls;
    if (text !== undefined) s.textContent = text;
    parent.append(s);
    return s;
  };
  const show = (snapped) => {
    window.__sel = snapped;
    hover.replaceChildren();
    const mk = (name, attrs) => {
      const e = document.createElementNS(ns, name);
      for (const k in attrs) e.setAttribute(k, attrs[k]);
      hover.append(e);
    };
    mk("line", { x1: x(snapped), x2: x(snapped), y1: T, y2: H - B, class: "cursor" });
    tip.replaceChildren();
    tip.className = "tip";
    item(tip, "t", fmtTime(snapped) + (snapped > nowT ? " (à venir)" : ""));
    series.forEach((sr) => {
      let v, at = snapped;
      if (sr.step) {
        // valeur de consigne en vigueur à cet instant
        const arr = real(sr).filter((d) => d.t <= snapped);
        v = arr.length ? arr[arr.length - 1].v : (sr.flat ? sr.data[0].v : real(sr)[0].v);
        mk("circle", { cx: x(snapped), cy: y(v), r: 4.5, class: "dot-" + sr.cls });
      } else {
        const pt = nearest(real(sr), snapped);
        v = pt.v; at = pt.t;
        mk("circle", { cx: x(pt.t), cy: y(pt.v), r: 4.5, class: "dot-" + sr.cls });
      }
      const it = item(tip, "it");
      item(it, "sw " + sr.cls);
      it.append((SHORT[sr.k] || label(sr.k)) + " " + fmtVal(sr.k, v));
      if (!sr.step && Math.abs(at - snapped) > 5 * 60000) item(it, "soft", " (" + fmtHM(at) + ")");
    });
    if (heatKnown > 0 && snapped <= nowT) {
      const on = (periods || []).some((pr) => tms(pr.start) <= snapped && snapped <= (pr.end ? tms(pr.end) : tms(pr.last)));
      const it = item(tip, "it", "Chauffage : ");
      item(it, on ? "hot" : "", on ? "en marche" : "à l'arrêt");
    }
    const hp = weatherHourAt(snapped);
    if (wx && hp && typeof hp.code === "number") {
      const info = wxInfo(hp.code, hp.day);
      item(tip, "it", info[1] + " " + info[0] + (typeof hp.precip === "number" && hp.precip > 0 ? " · " + num(hp.precip) + " mm" : ""));
    }
    if (hp && typeof hp.rad === "number" && hp.rad > 0) {
      item(tip, "it", "Soleil : " + Math.round(hp.rad) + " W/m²" + (typeof hp.sun_min === "number" ? " · " + Math.round(hp.sun_min) + " min" : ""));
    }
  };
  const onMove = (ev) => {
    const rect = svg.getBoundingClientRect();
    if (!rect.width || !allT.length) return;
    const sx = ((ev.clientX - rect.left) / rect.width) * W;
    if (sx < L - 4 || sx > W - R + 4) { clearHover(); return; }
    const tCursor = t0 + ((Math.min(Math.max(sx, L), W - R) - L) / (W - L - R)) * (t1 - t0);
    let snapped = allT[0];
    for (const t of allT) if (Math.abs(t - tCursor) < Math.abs(snapped - tCursor)) snapped = t;
    show(snapped);
  };
  svg.onpointermove = onMove;
  svg.onpointerdown = onMove;
  // à la souris, la lecture disparaît quand on quitte le graphique ; au doigt, elle reste lisible après le toucher
  svg.onpointerleave = (ev) => { if (ev.pointerType === "mouse") clearHover(); };
  if (window.__sel && allT.length) {
    let snapped = allT[0];
    for (const t of allT) if (Math.abs(t - window.__sel) < Math.abs(snapped - window.__sel)) snapped = t;
    show(snapped);
  } else {
    tipIdle();
  }
}

async function refresh() {
  $("refbtn").classList.add("spin");
  try {
    const r = await fetch("/api/data?hours=" + hours);
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || r.status);
    if (d.refresh) window.REFRESH_SECONDS = d.refresh;
    window.OFFSET = d.offset || 0;
    window.SP_OFFSET = d.setpoint_offset || 0;
    window.WEATHER = d.weather && d.weather.points && d.weather.points.length ? d.weather : null;
    $("wxbtn").disabled = !window.WEATHER;
    $("foot").replaceChildren();
    const corr = [];
    if (window.OFFSET) corr.push("intérieure " + signed(window.OFFSET) + " °C");
    if (window.SP_OFFSET) corr.push("consigne " + signed(window.SP_OFFSET) + " °C");
    if (corr.length) $("foot").append("Corrections : " + corr.join(", ") + ". ");
    if (window.WEATHER) {
      const a = document.createElement("a");
      a.href = "https://open-meteo.com/";
      a.textContent = "Weather data by Open-Meteo.com";
      $("foot").append("Météo : ", a, " (CC BY 4.0)");
    }
    const all = (d.points || []).filter((p) => p.time).sort((a, b) => new Date(a.time) - new Date(b.time));
    // valeurs datées dans le futur (température extérieure) : tracées en pointillés fins seulement
    const limit = Date.now() + 60 * 1000;
    const pts = all.filter((p) => tms(p) <= limit);
    if (!pts.length) {
      setStatus("Aucune mesure reçue. Vérifiez le numéro de série (ou la zone) dans les réglages.", true);
      return;
    }
    const heat = computePeriods(pts, d.heat_key);
    reconcileLive(heat, d.live, d.measures[0]);
    renderNow(d.measures, pts, heat, d.battery, d.live);
    renderChart(d.measures, all, heat.periods, limit, heat.known, d.live);
    setStatus("Actualisé à " + new Date().toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" }) +
              (d.weather_error ? " · météo indisponible" : "") + (window.WEATHER || corr.length ? " · " : ""), false);
  } catch (e) {
    setStatus("Connexion à Comap impossible : " + e.message, true);
  } finally {
    $("refbtn").classList.remove("spin");
  }
}

document.querySelectorAll(".tabs button[data-h]").forEach((b) => {
  b.addEventListener("click", () => {
    hours = Number(b.dataset.h);
    document.querySelectorAll(".tabs button[data-h]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    window.__sel = null;
    loop();
  });
});
$("wxbtn").addEventListener("click", () => {
  weatherMode = (weatherMode + 1) % 3;
  $("wxbtn").setAttribute("aria-pressed", String(weatherMode > 0));
  $("wxbtn").textContent = WX_BTN[weatherMode];
  if (lastChartArgs) renderChart(...lastChartArgs);
});
$("refbtn").addEventListener("click", () => loop());
$("setbtn").addEventListener("click", () => { if (window.Android) window.Android.openSettings(); });

// tirer vers le bas depuis le haut de la page : actualisation
let ptrY = null;
document.addEventListener("touchstart", (e) => {
  ptrY = (window.scrollY === 0 && !e.target.closest(".chartwrap")) ? e.touches[0].clientY : null;
}, { passive: true });
document.addEventListener("touchend", (e) => {
  if (ptrY !== null && e.changedTouches[0].clientY - ptrY > 110) loop();
  ptrY = null;
}, { passive: true });

let timer = null;
async function loop() {
  clearTimeout(timer);
  await refresh();
  timer = setTimeout(loop, (window.REFRESH_SECONDS || 60) * 1000);
}
tipIdle();
loop();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        data = body.encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass  # le navigateur a fermé la page (ou le PC s'est mis en veille) avant la réponse : sans importance

    def do_GET(self):
        try:
            self._do_get()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass

    def _do_get(self):
        url = urlparse(self.path)
        if url.path == "/":
            self._send(200, PAGE, "text/html; charset=utf-8")
        elif url.path == "/api/data":
            try:
                hours = int(parse_qs(url.query).get("hours", ["24"])[0])
                hours = max(1, min(hours, 168))
                self._send(200, json.dumps(get_data(hours)), "application/json")
                _page_error["msg"] = ""
            except Exception as exc:
                # la cause réelle de l'échec est affichée une fois dans la fenêtre (et non l'erreur de connexion qui suit)
                msg = f"{type(exc).__name__} : {exc}"
                if msg != _page_error["msg"]:
                    print("[Page] Lecture des données impossible - " + msg, flush=True)
                    _page_error["msg"] = msg
                self._send(502, json.dumps({"error": str(exc)}), "application/json")
        else:
            self._send(404, "Introuvable", "text/plain; charset=utf-8")

    def log_message(self, fmt, *args):
        pass  # sortie console silencieuse



def make_server():
    """Serveur local sur un port libre de 127.0.0.1 : la page n'est visible que depuis l'application."""
    return ThreadingHTTPServer(("127.0.0.1", 0), Handler)
