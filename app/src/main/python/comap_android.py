"""Point d'entrée Python de l'application Android : démarre (ou redémarre) le serveur local."""
import importlib
import json
import os
import sys
import threading

_server = None


def start(cfg_json):
    """Applique les réglages saisis dans l'application et démarre le serveur sur 127.0.0.1.

    Renvoie le port local à charger dans la WebView. Lève RuntimeError si un réglage manque.
    """
    global _server
    cfg = json.loads(cfg_json)
    email = str(cfg.get("email", "")).strip()
    password = str(cfg.get("password", ""))
    serial = str(cfg.get("serial", "")).strip()
    zone = str(cfg.get("zone", "")).strip()
    if not email or not password:
        raise RuntimeError("Saisissez l'e-mail et le mot de passe de votre compte Comap.")
    if not serial and not zone:
        raise RuntimeError("Saisissez le numéro de série du thermostat (ou l'identifiant de zone).")

    if _server is not None:  # changement de réglages : on arrête l'ancien serveur
        _server.shutdown()
        _server.server_close()
        _server = None

    os.environ["COMAP_SMART_HOME_USERNAME"] = email
    os.environ["COMAP_SMART_HOME_PASSWORD"] = password
    os.environ["COMAP_SERIAL"] = serial
    os.environ["COMAP_ZONE_ID"] = zone
    for env, key, default in (("COMAP_LAT", "lat", "47.8736"), ("COMAP_LON", "lon", "-3.5486"),
                              ("COMAP_OFFSET_INSIDE", "off_in", "0.5"), ("COMAP_OFFSET_SETPOINT", "off_sp", "0.5")):
        os.environ[env] = str(cfg.get(key) or default).strip()

    # la bibliothèque Comap lit les identifiants au moment de son import : on la recharge avec les nouveaux
    for name in [n for n in sys.modules if n == "comap_mobile_core" or n.startswith("comapsmarthome_public_api")]:
        del sys.modules[name]
    core = importlib.import_module("comap_mobile_core")
    _server = core.make_server()
    threading.Thread(target=_server.serve_forever, daemon=True).start()
    return _server.server_address[1]
