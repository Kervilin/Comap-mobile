import type { WeatherPoint } from "./demoData";

/** Coordonnées par défaut de comap_mobile_core.py (Quimperlé). */
export const DEFAULT_LAT = 47.8736;
export const DEFAULT_LON = -3.5486;

/**
 * Variables horaires demandées à Open-Meteo, exactement celles du dépôt :
 * temperature_2m, shortwave_radiation, sunshine_duration,
 * precipitation, weather_code, is_day.
 */
export const HOURLY_VARIABLES = [
  "temperature_2m",
  "shortwave_radiation",
  "sunshine_duration",
  "precipitation",
  "weather_code",
  "is_day",
] as const;

export type OpenMeteoDataset = {
  points: WeatherPoint[];
  lat: number;
  lon: number;
  fetchedAt: string;
  timezone: string;
};

type OpenMeteoResponse = {
  hourly?: {
    time?: Array<number | string>;
    temperature_2m?: Array<number | null>;
    shortwave_radiation?: Array<number | null>;
    sunshine_duration?: Array<number | null>;
    precipitation?: Array<number | null>;
    weather_code?: Array<number | null>;
    is_day?: Array<number | null>;
  };
  reason?: string;
};

function toEpochSeconds(value: number | string): number {
  if (typeof value === "number") return value;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? Math.floor(parsed / 1000) : Number.NaN;
}

function numberOrNull(value: number | null | undefined) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function buildOpenMeteoUrl(lat = DEFAULT_LAT, lon = DEFAULT_LON) {
  const params = new URLSearchParams({
    latitude: String(lat),
    longitude: String(lon),
    hourly: HOURLY_VARIABLES.join(","),
    past_days: "7",
    forecast_days: "8",
    timeformat: "unixtime",
    timezone: "Europe/Paris",
  });
  return `https://api.open-meteo.com/v1/forecast?${params.toString()}`;
}

export function parseOpenMeteo(
  payload: OpenMeteoResponse,
  lat = DEFAULT_LAT,
  lon = DEFAULT_LON,
): OpenMeteoDataset {
  const hourly = payload.hourly;
  if (!hourly || !Array.isArray(hourly.time)) {
    throw new Error(payload.reason || "Réponse Open-Meteo incomplète");
  }

  const points: WeatherPoint[] = [];
  // regroupe l'ensoleillement et la pluie sur la journée locale de chaque heure
  const daily = new Map<string, { sun: number; rain: number }>();
  hourly.time.forEach((rawTime, index) => {
    const t = toEpochSeconds(rawTime);
    if (!Number.isFinite(t)) return;
    const date = new Date(t * 1000);
    const key = `${date.getFullYear()}-${date.getMonth() + 1}-${date.getDate()}`;
    const bucket = daily.get(key) ?? { sun: 0, rain: 0 };
    const sun = numberOrNull(hourly.sunshine_duration?.[index]);
    const rain = numberOrNull(hourly.precipitation?.[index]);
    bucket.sun += sun ?? 0;
    bucket.rain += rain ?? 0;
    daily.set(key, bucket);
  });
  hourly.time.forEach((rawTime, index) => {
    const t = toEpochSeconds(rawTime);
    if (!Number.isFinite(t)) return;
    const sunSeconds = numberOrNull(hourly.sunshine_duration?.[index]);
    const temp = numberOrNull(hourly.temperature_2m?.[index]);
    const rad = numberOrNull(hourly.shortwave_radiation?.[index]);
    const precip = numberOrNull(hourly.precipitation?.[index]);
    const code = numberOrNull(hourly.weather_code?.[index]);
    const day = numberOrNull(hourly.is_day?.[index]);
    if (temp === null && rad === null && code === null) return;
    const date = new Date(t * 1000);
    const bucket = daily.get(`${date.getFullYear()}-${date.getMonth() + 1}-${date.getDate()}`);
    const point: WeatherPoint & {
      sun_hour_min: number;
      sun_day_min: number;
      rain_day_mm: number;
    } = {
      t,
      temp: temp ?? Number.NaN,
      rad: rad ?? 0,
      sun_min: sunSeconds === null ? 0 : Math.round(sunSeconds / 60),
      precip: precip ?? 0,
      code: code === null ? 3 : Math.round(code),
      day: day === null ? 1 : Math.round(day),
      sun_hour_min: sunSeconds === null ? 0 : Math.round(sunSeconds / 60),
      sun_day_min: bucket ? Math.round(bucket.sun / 60) : 0,
      rain_day_mm: bucket ? Math.round(bucket.rain * 10) / 10 : 0,
    };
    points.push(point);
  });

  if (!points.length) throw new Error("Aucune mesure météo exploitable");
  points.sort((a, b) => a.t - b.t);
  return {
    points,
    lat,
    lon,
    fetchedAt: new Date().toISOString(),
    timezone: "Europe/Paris",
  };
}

export async function fetchOpenMeteoWeather(
  lat = DEFAULT_LAT,
  lon = DEFAULT_LON,
  signal?: AbortSignal,
): Promise<OpenMeteoDataset> {
  const response = await fetch(buildOpenMeteoUrl(lat, lon), {
    signal,
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`Open-Meteo : erreur ${response.status}`);
  }
  return parseOpenMeteo((await response.json()) as OpenMeteoResponse, lat, lon);
}
