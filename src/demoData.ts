import patchedPage from "./patched/comap-page.html?raw";

export type ComapRow = {
  time: string;
  inside_temperature: number;
  temperature_instruction: number;
  heating_commands: "heating" | "idle";
};

export type WeatherPoint = {
  t: number;
  temp: number;
  rad: number;
  sun_min: number;
  precip: number;
  code: number;
  day: number;
  sun_hour_min?: number;
  sun_day_min?: number;
  rain_day_mm?: number;
};

type DemoPayload = {
  measures: string[];
  heat_key: string;
  battery: { value: number; time: string } | null;
  live: {
    zone: string;
    heating: "heating" | "idle";
    temperature: number;
    setpoint: number;
    transmission_error: null;
    at: string;
  };
  refresh: number;
  weather: { points: WeatherPoint[]; lat: number; lon: number };
  weather_error: string;
  offset: number;
  setpoint_offset: number;
  points: ComapRow[];
  updated: string;
};

export type PreviewOptions = {
  batteryVoltage?: number;
  /** Météo réelle Open-Meteo ; si absente, météo de démonstration. */
  weather?: WeatherPoint[] | null;
  weatherError?: string;
};

const STEP_MINUTES = 10;
const DAY_MS = 86_400_000;
const HOUR_MS = 3_600_000;
const LAT = 47.8736;
const LON = -3.5486;

function setpointAt(date: Date) {
  const hour = date.getHours() + date.getMinutes() / 60;
  if (hour < 6.5) return 16.5;
  if (hour < 9) return 20.5;
  if (hour < 17) return 19.5;
  if (hour < 22.5) return 20.5;
  return 16.5;
}

function outsideAt(ms: number) {
  const hour = new Date(ms).getHours() + new Date(ms).getMinutes() / 60;
  const daily = Math.sin(((hour - 9) / 24) * Math.PI * 2) * 3.1;
  const dayIndex = Math.floor(ms / DAY_MS);
  const weather = Math.sin(dayIndex * 1.7) * 0.8;
  return Number((4.2 + daily + weather).toFixed(2));
}

function buildWeather(now: number): WeatherPoint[] {
  const points: WeatherPoint[] = [];
  const firstHour = Math.floor((now - 7 * DAY_MS) / HOUR_MS) * HOUR_MS;
  const lastHour = Math.floor((now + 7 * DAY_MS) / HOUR_MS) * HOUR_MS;
  const daily = new Map<string, { sun: number; rain: number }>();

  for (let t = firstHour; t <= lastHour; t += HOUR_MS) {
    const date = new Date(t);
    const hour = date.getHours() + date.getMinutes() / 60;
    const dayIndex = Math.floor(t / DAY_MS);
    const temp = outsideAt(t);
    const sunlight = Math.max(0, Math.sin(((hour - 7) / 12) * Math.PI));
    const cloudFactor = 0.45 + 0.35 * Math.abs(Math.sin(dayIndex * 2.3 + hour / 9));
    const rad = Math.round(sunlight * 620 * cloudFactor);
    const sunHour = Math.round((rad / 620) * 45);
    const rainHour = rad > 380 ? 0 : Math.round((Math.sin(dayIndex + hour / 2.7) + 1) * 3) / 10;
    const key = `${date.getFullYear()}-${date.getMonth() + 1}-${date.getDate()}`;
    const bucket = daily.get(key) ?? { sun: 0, rain: 0 };
    bucket.sun += sunHour;
    bucket.rain += rainHour;
    daily.set(key, bucket);
    points.push({
      t: Math.floor(t / 1000),
      temp,
      rad,
      sun_min: sunHour,
      precip: rainHour,
      code: [2, 3, 2, 1, 3, 45, 2][Math.abs(dayIndex + Math.floor(hour / 3)) % 7],
      day: hour >= 8 && hour <= 18 ? 1 : 0,
      sun_hour_min: sunHour,
      sun_day_min: bucket.sun,
      rain_day_mm: Math.round(bucket.rain * 10) / 10,
    });
  }
  return points;
}

function buildPoints(now: number): ComapRow[] {
  const end = Math.floor(now / 60000) * 60000;
  const start = end - 168 * HOUR_MS;
  const points: ComapRow[] = [];
  let temperature = setpointAt(new Date(start)) - 0.4;
  let heating = false;

  for (let time = start; time <= end; time += STEP_MINUTES * 60000) {
    const date = new Date(time);
    const setpoint = setpointAt(date);
    const outside = outsideAt(time);

    if (heating) {
      if (temperature > setpoint + 0.05) heating = false;
    } else if (temperature < setpoint - 0.08) {
      heating = true;
    }

    const loss = Math.max(0, (temperature - outside) * 0.0017);
    if (heating) {
      temperature += 0.075 + 0.055 * Math.max(0, Math.min(1.2, setpoint - temperature)) - loss;
    } else {
      temperature -= 0.008 + loss;
    }
    temperature = Math.max(15.8, Math.min(22.6, temperature));

    points.push({
      time: date.toISOString(),
      inside_temperature: Math.round(temperature * 100) / 100,
      temperature_instruction: setpoint,
      heating_commands: heating ? "heating" : "idle",
    });
  }
  return points;
}

export function buildDemoData(now = Date.now(), options: PreviewOptions = {}): DemoPayload {
  const points = buildPoints(now);
  const realWeather =
    options.weather && options.weather.length > 1
      ? options.weather.filter(
          (point) =>
            Number.isFinite(point.t) &&
            Number.isFinite(point.temp) &&
            Number.isFinite(point.code),
        )
      : null;
  const weatherPoints = realWeather && realWeather.length > 1 ? realWeather : buildWeather(now);
  const last = points[points.length - 1];
  return {
    measures: ["inside_temperature", "temperature_instruction"],
    heat_key: "heating_commands",
    battery: {
      value: options.batteryVoltage ?? 4.03,
      time: new Date(now - 2 * HOUR_MS).toISOString(),
    },
    live: {
      zone: "Salon",
      heating: last.heating_commands,
      temperature: last.inside_temperature,
      setpoint: last.temperature_instruction,
      transmission_error: null,
      at: new Date(now).toISOString(),
    },
    refresh: 60,
    weather: {
      points: weatherPoints,
      lat: LAT,
      lon: LON,
    },
    weather_error: realWeather ? "" : options.weatherError ?? "Météo de démonstration (Open-Meteo indisponible)",
    offset: 0,
    setpoint_offset: 0,
    points,
    updated: new Date(now).toISOString(),
  };
}

/**
 * Pont de démonstration, exécuté dans l'iframe AVANT la page d'origine.
 * Il remplace uniquement les endpoints HTTP `/api/*` normalement servis par
 * comap_mobile_core.py (Python) et le pont Android `openSettings`.
 * Le HTML, le CSS et le JavaScript de la page ne sont pas modifiés.
 */
function buildBridge(data: DemoPayload) {
  const serialized = JSON.stringify(data).replace(/</g, "\\u003c");
  return `(() => {
  const DEMO = ${serialized};
  window.__COMAP_DEMO__ = DEMO;
  const nativeFetch = window.fetch ? window.fetch.bind(window) : null;
  const answer = (body, status) => new Response(JSON.stringify(body), {
    status: status || 200,
    headers: { "Content-Type": "application/json; charset=utf-8" }
  });
  const readHours = (url) => {
    const match = String(url).match(/[?&]hours=(\\d+)/);
    return match ? Number(match[1]) : 24;
  };
  window.fetch = function (input, init) {
    const url = typeof input === "string" ? input : (input && input.url) || "";
    if (url.indexOf("/api/temporary/cancel") !== -1) {
      return Promise.resolve(answer({
        ok: true,
        warning: "Aperçu local : aucune consigne temporaire réelle n’a été annulée."
      }));
    }
    if (url.indexOf("/api/temporary") !== -1) {
      return Promise.resolve(answer({
        ok: true,
        sent: false,
        warning: "Aperçu local : la consigne n’a pas été envoyée à Comap."
      }));
    }
    if (url.indexOf("/api/data") !== -1) {
      const hours = readHours(url);
      const cutoff = Date.now() - hours * 3600000;
      const points = DEMO.points.filter((point) => new Date(point.time).getTime() >= cutoff);
      return Promise.resolve(answer(Object.assign({}, DEMO, {
        points,
        live: Object.assign({}, DEMO.live, { at: new Date().toISOString() }),
        updated: new Date().toISOString()
      })));
    }
    return nativeFetch ? nativeFetch(input, init) : Promise.reject(new Error("Aperçu hors ligne"));
  };
  window.Android = {
    openSettings: function () {
      if (typeof window.toast === "function") {
        window.toast("Les réglages sont gérés par l’application Android, pas par cette page.");
      }
    }
  };
  window.__COMAP_SHIM__ = true;
})();`;
}

export function buildPreviewDocument(
  now = Date.now(),
  options: PreviewOptions & { batteryTest?: boolean; voltage?: number } = {},
) {
  const batteryTest = options.batteryTest ?? true;
  const data = buildDemoData(now, {
    batteryVoltage: options.voltage ?? 4.03,
    weather: options.weather,
    weatherError: options.weatherError,
  });
  const bridge = buildBridge(data);
  const controlScript = buildControlScript(batteryTest, data.battery?.value ?? 4.03);
  const token = "apercu-local-" + Math.random().toString(36).slice(2, 10);
  const withToken = patchedPage.replace("__TOKEN__", token);
  const marker = "\n<script>\n";
  const index = withToken.indexOf(marker);
  if (index === -1) {
    throw new Error("Balise script de la page d'origine introuvable");
  }
  const document =
    withToken.slice(0, index) +
    "\n<script>\n" +
    bridge +
    "\n</script>" +
    "\n<script>\n" +
    controlScript +
    "\n</script>" +
    withToken.slice(index);
  return { document, data, token };
}




export const BATTERY_TEST_CSS = `#bat.low, #batSub.low { color: var(--warn); }
#bat.low { animation: batLowBlink 1.1s steps(1, end) infinite; }
@keyframes batLowBlink { 0%, 49% { opacity: 1; } 50%, 100% { opacity: .35; } }
@media (prefers-reduced-motion: reduce) { #bat.low { animation: none; } }`;

export const BATTERY_TEST_JS = `// appliqué à la carte « Piles » après chaque rendu
const v = battery.value > 50 ? battery.value / 1000 : battery.value;
const low = v < 4.1;          // strictement sous 4,10 V
$("bat").classList.toggle("low", low);
$("batSub").classList.toggle("low", low);`;

/**
 * Petit contrôle de démonstration ajouté à la page (hors de son code) :
 * - reçoit la tension choisie dans le panneau et met à jour #bat / #batSub ;
 * - permet de neutraliser visuellement le test pile (mode « dépôt »).
 * La règle rouge clignotante elle-même est dans la page corrigée.
 */
function buildControlScript(batteryTest: boolean, voltage: number) {
  return `(() => {
  const THRESHOLD = 4.1;
  const DEFAULT_VOLTAGE = ${voltage};
  const setEnabled = (enabled) => {
    document.documentElement.classList.toggle("comap-test-off", !enabled);
    window.__COMAP_TEST_ENABLED__ = !!enabled;
  };
  const apply = (value) => {
    const demo = window.__COMAP_DEMO__;
    if (demo && demo.battery && Number.isFinite(value)) demo.battery.value = value;
    const bat = document.getElementById("bat");
    const sub = document.getElementById("batSub");
    if (!bat) return;
    if (Number.isFinite(value)) bat.textContent = value.toFixed(2).replace(".", ",") + " V";
    const low = Number.isFinite(value) && value < THRESHOLD;
    bat.classList.toggle("low", low);
    if (sub) sub.classList.toggle("low", low);
    window.__COMAP_BATTERY_LOW__ = low;
  };
  window.addEventListener("message", (event) => {
    const data = event.data;
    if (!data) return;
    if (data.type === "comap:voltage") apply(Number(data.value));
    if (data.type === "comap:test") setEnabled(!!data.enabled);
  });
  const css = document.createElement("style");
  css.id = "comap-demo-control";
  css.textContent = "html.comap-test-off #bat.low { animation: none !important; color: inherit !important; } html.comap-test-off #batSub.low { color: inherit !important; }";
  document.head.appendChild(css);
  setEnabled(${batteryTest ? 'true' : 'false'});
  apply(DEFAULT_VOLTAGE);
})();`;
}

