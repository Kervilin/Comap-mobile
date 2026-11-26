import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BatteryMedium, Settings2 } from "lucide-react";
import { buildPreviewDocument } from "./demoData";
import { AppFrame } from "./components/AppFrame";
import { DemoPanel, LOW_VOLTAGE } from "./components/DemoPanel";
import {
  DEFAULT_LAT,
  DEFAULT_LON,
  fetchOpenMeteoWeather,
  type OpenMeteoDataset,
} from "./openMeteo";
import { cn } from "./utils/cn";

export default function App() {
  const [batteryTest, setBatteryTest] = useState(true);
  const [voltage, setVoltage] = useState(4.03);
  const [panelOpen, setPanelOpen] = useState(false);
  const [reloadKey] = useState(0);
  const buildTime = useRef(Date.now()).current;
  const blobUrl = useRef<string | null>(null);
  const [weather, setWeather] = useState<OpenMeteoDataset | null>(null);
  const [weatherStatus, setWeatherStatus] = useState<
    "loading" | "live" | "fallback"
  >("loading");
  const [weatherError, setWeatherError] = useState("");
  const weatherRequest = useRef<AbortController | null>(null);

  const loadWeather = useCallback(async () => {
    weatherRequest.current?.abort();
    const controller = new AbortController();
    weatherRequest.current = controller;
    setWeatherStatus("loading");
    try {
      const dataset = await fetchOpenMeteoWeather(DEFAULT_LAT, DEFAULT_LON, controller.signal);
      if (controller.signal.aborted) return;
      setWeather(dataset);
      setWeatherStatus("live");
      setWeatherError("");
    } catch (error) {
      if (controller.signal.aborted) return;
      setWeatherStatus("fallback");
      setWeatherError(error instanceof Error ? error.message : "Open-Meteo indisponible");
    }
  }, []);

  useEffect(() => {
    loadWeather();
    return () => weatherRequest.current?.abort();
  }, [loadWeather]);

  const preview = useMemo(
    () =>
      buildPreviewDocument(buildTime, {
        batteryTest: true,
        weather: weather?.points ?? null,
        weatherError,
      }),
    [buildTime, weather, weatherError],
  );

  const low = batteryTest && voltage < LOW_VOLTAGE;

  const openStandalone = () => {
    try {
      if (blobUrl.current) URL.revokeObjectURL(blobUrl.current);
      const blob = new Blob([preview.document], { type: "text/html;charset=utf-8" });
      blobUrl.current = URL.createObjectURL(blob);
      const opened = window.open(blobUrl.current, "_blank", "noopener,noreferrer");
      if (!opened) {
        setPanelOpen(false);
        return;
      }
      setPanelOpen(false);
    } catch {
      setPanelOpen(false);
    }
  };

  return (
    <main className="fixed inset-0 overflow-hidden bg-[#eef1f0]">
      <AppFrame
        srcDoc={preview.document}
        reloadKey={reloadKey}
        voltage={voltage}
        batteryTest={batteryTest}
      />

      <button
        type="button"
        onClick={() => setPanelOpen(true)}
        className={cn(
          "absolute bottom-3 right-3 z-40 inline-flex items-center gap-1.5 rounded-full border bg-white/90 px-3 py-2 text-[10px] font-semibold text-[#33483f] shadow-[0_6px_20px_-8px_rgba(20,38,31,0.35)] backdrop-blur transition-colors hover:bg-white",
          low ? "border-[#e2c3bd]" : "border-[#d7e0db]",
        )}
        aria-label="Ouvrir le panneau de démonstration"
        aria-expanded={panelOpen}
      >
        <span className="relative inline-flex">
          {low ? (
            <span className="absolute -right-0.5 -top-0.5 h-1.5 w-1.5 rounded-full border border-white bg-[#b3392b]" />
          ) : null}
          <BatteryMedium className="h-3.5 w-3.5" strokeWidth={2.1} />
        </span>
        Démo
        <Settings2 className="h-3 w-3 text-[#85958c]" />
      </button>

      <DemoPanel
        open={panelOpen}
        voltage={voltage}
        low={low}
        batteryTest={batteryTest}
        onClose={() => setPanelOpen(false)}
        onVoltageChange={setVoltage}
        onBatteryTestChange={setBatteryTest}
        onOpenStandalone={openStandalone}
        weatherStatus={weatherStatus}
        weatherFetchedAt={weather?.fetchedAt ?? null}
        weatherError={weatherError}
        onRefreshWeather={loadWeather}
      />
    </main>
  );
}
