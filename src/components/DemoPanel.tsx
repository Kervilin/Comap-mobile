import {
  ArrowDownToLine,
  ArrowUpRight,
  BatteryMedium,
  BatteryWarning,
  Check,
  CloudSun,
  ExternalLink,
  FileCode2,
  GitBranch,
  Loader2,
  RefreshCw,
  X,
} from "lucide-react";
import { HOURLY_VARIABLES } from "../openMeteo";
import { cn } from "../utils/cn";

export const LOW_VOLTAGE = 4.1;

type DemoPanelProps = {
  open: boolean;
  voltage: number;
  low: boolean;
  batteryTest: boolean;
  onClose: () => void;
  onVoltageChange: (value: number) => void;
  onBatteryTestChange: (value: boolean) => void;
  onOpenStandalone: () => void;
  weatherStatus: "loading" | "live" | "fallback";
  weatherFetchedAt: string | null;
  weatherError: string;
  onRefreshWeather: () => void;
};

const PRESETS = [
  { value: 4.03, label: "4,03 V" },
  { value: 4.1, label: "4,10 V" },
  { value: 4.24, label: "4,24 V" },
];

function volts(value: number) {
  return value.toFixed(2).replace(".", ",") + " V";
}

export function DemoPanel({
  open,
  voltage,
  low,
  batteryTest,
  onClose,
  onVoltageChange,
  onBatteryTestChange,
  onOpenStandalone,
  weatherStatus,
  weatherFetchedAt,
  weatherError,
  onRefreshWeather,
}: DemoPanelProps) {
  const ratio = Math.max(0, Math.min(100, ((voltage - 3.85) / (4.4 - 3.85)) * 100));
  const accent = !batteryTest ? "#6f8179" : low ? "#b3392b" : "#1f6f8b";
  const showLow = batteryTest && low;

  return (
    <div
      className={cn(
        "fixed inset-0 z-[60] transition-opacity duration-200",
        open ? "pointer-events-auto opacity-100" : "pointer-events-none opacity-0",
      )}
      aria-hidden={!open}
    >
      <button
        type="button"
        className="absolute inset-0 cursor-default bg-[#0c1b16]/25 backdrop-blur-[1.5px]"
        onClick={onClose}
        aria-label="Fermer le panneau de démonstration"
        tabIndex={open ? 0 : -1}
      />

      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="demo-panel-title"
        className={cn(
          "absolute inset-x-0 bottom-0 mx-auto flex max-h-[92dvh] w-full flex-col overflow-hidden rounded-t-2xl border border-[#dbe3de] bg-white shadow-[0_-18px_60px_-24px_rgba(12,32,26,0.45)] transition-transform duration-300 sm:inset-x-auto sm:bottom-4 sm:right-4 sm:max-h-[calc(100dvh-2rem)] sm:w-[384px] sm:rounded-2xl sm:shadow-[0_24px_70px_-30px_rgba(12,32,26,0.6)]",
          open ? "translate-y-0" : "translate-y-full sm:translate-y-4",
        )}
      >
        <div className="flex items-start justify-between gap-3 border-b border-[#e7ece8] px-4 py-3.5">
          <div className="flex items-center gap-2.5">
            <span
              className={cn(
                "grid h-8 w-8 shrink-0 place-items-center rounded-lg",
                showLow ? "bg-[#faecea] text-[#b3392b]" : "bg-[#eef3ef] text-[#3a5a4e]",
              )}
            >
              {showLow ? (
                <BatteryWarning className="h-4 w-4" strokeWidth={2.2} />
              ) : (
                <BatteryMedium className="h-4 w-4" strokeWidth={2.2} />
              )}
            </span>
            <div>
              <h2
                id="demo-panel-title"
                className="text-[12px] font-bold leading-tight text-[#17251f]"
              >
                Aperçu de démonstration
              </h2>
              <p className="mt-0.5 text-[9.5px] text-[#78887f]">
                La page du dépôt, sans habillage autour.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="grid h-7 w-7 shrink-0 place-items-center rounded-md text-[#7d8c84] transition-colors hover:bg-[#f2f5f2] hover:text-[#253b31]"
            aria-label="Fermer"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>

        <div className="thin-scroll flex-1 overflow-y-auto overscroll-contain">
          <div className="border-b border-[#e9eeea] px-4 py-3.5">
            <div className="flex items-center justify-between gap-2">
              <p className="text-[9px] font-bold uppercase tracking-[0.13em] text-[#7e8e85]">
                Test pile
              </p>
              <span
                className={cn(
                  "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[8.5px] font-bold uppercase tracking-[0.04em]",
                  showLow
                    ? "bg-[#faecea] text-[#a3362a]"
                    : batteryTest
                      ? "bg-[#eaf4ee] text-[#2f6b4e]"
                      : "bg-[#eef2ef] text-[#66786f]",
                )}
              >
                <span
                  className={cn(
                    "h-1 w-1 rounded-full",
                    showLow
                      ? "animate-pulse bg-[#b3392b]"
                      : batteryTest
                        ? "bg-[#4b9670]"
                        : "bg-[#84928b]",
                  )}
                />
                {!batteryTest ? "démonstration" : showLow ? "rouge clignotant" : "normal"}
              </span>
            </div>

            <div className="mt-2 flex items-end justify-between gap-2">
              <p
                className={cn(
                  "font-mono text-[26px] font-semibold leading-none tracking-[-0.04em]",
                  showLow ? "bat-blink text-[#b3392b]" : "text-[#182821]",
                )}
                aria-live="polite"
              >
                {volts(voltage)}
              </p>
              <p className="mb-0.5 text-right text-[8.5px] leading-tight text-[#7a8b82]">
                {batteryTest ? (
                  showLow ? (
                    <>
                      rouge + clignotant
                      <br />
                      <span className="text-[#a06760]">piles à remplacer</span>
                    </>
                  ) : (
                    <>
                      seuil respecté
                      <br />
                      <span className="text-[#4b9670]">≥ 4,10 V</span>
                    </>
                  )
                ) : (
                  <>
                    règle désactivée
                    <br />
                    <span>couleur d’origine</span>
                  </>
                )}
              </p>
            </div>

            <input
              id="demo-voltage"
              className="battery-test-range mt-3.5 w-full disabled:cursor-not-allowed disabled:opacity-50"
              type="range"
              min={3.85}
              max={4.4}
              step={0.01}
              value={voltage}
              disabled={!batteryTest}
              onChange={(event) => onVoltageChange(Number(event.target.value))}
              style={{
                background: `linear-gradient(to right, ${accent} 0%, ${accent} ${ratio}%, #e4e9e5 ${ratio}%, #e4e9e5 100%)`,
                ["--thumb" as string]: accent,
              }}
              aria-valuetext={`${volts(voltage)}, ${
                showLow ? "sous le seuil de 4,10 V" : "au-dessus du seuil"
              }`}
            />
            <div className="mt-1.5 flex items-center justify-between text-[8px] text-[#93a199]">
              <span className="font-mono">3,85 V</span>
              <span className="font-semibold text-[#64776d]">seuil 4,10 V</span>
              <span className="font-mono">4,40 V</span>
            </div>

            <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
              {PRESETS.map((preset) => {
                const selected = Math.abs(voltage - preset.value) < 0.001;
                const presetLow = preset.value < LOW_VOLTAGE;
                return (
                  <button
                    key={preset.value}
                    type="button"
                    disabled={!batteryTest}
                    onClick={() => onVoltageChange(preset.value)}
                    aria-pressed={selected}
                    className={cn(
                      "rounded-full border px-2 py-1 font-mono text-[9px] font-semibold transition-colors disabled:opacity-50",
                      selected
                        ? presetLow
                          ? "border-[#cf9a91] bg-[#faecea] text-[#a3362a]"
                          : "border-[#9fc1b2] bg-[#eef6f1] text-[#316950]"
                        : "border-[#e1e7e2] bg-white text-[#63776d] hover:bg-[#f5f8f5]",
                    )}
                  >
                    {preset.label}
                  </button>
                );
              })}
              <span className="ml-auto text-[8px] text-[#93a199]">
                4,10 V exactement&nbsp;: normal
              </span>
            </div>

            <button
              type="button"
              role="switch"
              aria-checked={batteryTest}
              onClick={() => onBatteryTestChange(!batteryTest)}
              className="mt-3 flex w-full items-center justify-between gap-3 rounded-lg border border-[#e3e9e4] bg-[#f8faf8] px-2.5 py-2 text-left"
            >
              <span className="min-w-0">
                <span className="block text-[10px] font-semibold text-[#263b31]">
                  Afficher le test pile
                </span>
                <span className="mt-0.5 block text-[8.5px] leading-tight text-[#7c8c84]">
                  Rouge clignotant strictement sous 4,10 V
                </span>
              </span>
              <span
                className={cn(
                  "relative inline-flex h-[18px] w-8 shrink-0 items-center rounded-full transition-colors",
                  batteryTest ? "bg-[#2b6b4e]" : "bg-[#c9d3cd]",
                )}
                aria-hidden="true"
              >
                <span
                  className={cn(
                    "grid h-[14px] w-[14px] place-items-center rounded-full bg-white shadow-sm transition-transform",
                    batteryTest ? "translate-x-[16px]" : "translate-x-[2px]",
                  )}
                >
                  {batteryTest && (
                    <Check className="h-2 w-2 text-[#2b6b4e]" strokeWidth={3.5} />
                  )}
                </span>
              </span>
            </button>
          </div>

          <div className="border-b border-[#e9eeea] px-4 py-3.5">
            <div className="flex items-center justify-between gap-2">
              <p className="flex items-center gap-1.5 text-[9px] font-bold uppercase tracking-[0.13em] text-[#7e8e85]">
                <CloudSun className="h-3 w-3" />
                Météo Open-Meteo
              </p>
              <span
                className={cn(
                  "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[8.5px] font-bold",
                  weatherStatus === "live"
                    ? "bg-[#eaf4ee] text-[#2f6b4e]"
                    : weatherStatus === "loading"
                      ? "bg-[#eef3f8] text-[#3a6277]"
                      : "bg-[#fdf3e5] text-[#8a631f]",
                )}
              >
                {weatherStatus === "loading" ? (
                  <Loader2 className="h-2.5 w-2.5 animate-spin" />
                ) : (
                  <span
                    className={cn(
                      "h-1 w-1 rounded-full",
                      weatherStatus === "live" ? "bg-[#4b9670]" : "bg-[#b8862e]",
                    )}
                  />
                )}
                {weatherStatus === "live"
                  ? "en direct"
                  : weatherStatus === "loading"
                    ? "chargement"
                    : "repli démo"}
              </span>
            </div>
            <p className="mt-1.5 text-[9px] leading-relaxed text-[#7a8b82]">
              {weatherStatus === "live"
                ? "Valeurs réelles reçues pour Quimperlé (47,8736 / -3,5486)."
                : weatherStatus === "loading"
                  ? "Récupération des prévisions horaires…"
                  : "API inaccessible depuis ce navigateur : valeurs de démonstration utilisées."}
            </p>
            <code className="mt-2 block break-words rounded-md bg-[#f4f7f4] px-2 py-1.5 font-mono text-[8.5px] leading-relaxed text-[#4d6659]">
              hourly: {HOURLY_VARIABLES.join(", ")}
            </code>
            <div className="mt-1.5 flex items-center justify-between gap-2">
              <span className="text-[8px] text-[#93a199]">
                {weatherStatus === "live" && weatherFetchedAt
                  ? "Reçu à " +
                    new Date(weatherFetchedAt).toLocaleTimeString("fr-FR", {
                      hour: "2-digit",
                      minute: "2-digit",
                    })
                  : weatherStatus === "fallback" && weatherError
                    ? weatherError.slice(0, 46)
                    : "past_days 7 · forecast_days 8 · Europe/Paris"}
              </span>
              <button
                type="button"
                onClick={onRefreshWeather}
                disabled={weatherStatus === "loading"}
                className="inline-flex shrink-0 items-center gap-1 rounded-md border border-[#dde5e0] bg-white px-2 py-1 text-[8.5px] font-semibold text-[#3d5a4d] transition-colors hover:bg-[#f5f8f5] disabled:opacity-50"
              >
                <RefreshCw
                  className={cn("h-2.5 w-2.5", weatherStatus === "loading" && "animate-spin")}
                />
                Actualiser
              </button>
            </div>
            <p className="mt-1.5 text-[8px] leading-relaxed text-[#93a199]">
              T° ext. ← temperature_2m · Soleil ← weather_code / is_day, durée et rayonnement ·
              Pluie ← precipitation.
            </p>
            <a
              href="https://open-meteo.com/"
              target="_blank"
              rel="noreferrer noopener"
              className="mt-1 inline-flex items-center gap-1 text-[8px] font-medium text-[#6d8378] hover:underline"
            >
              Weather data by Open-Meteo.com
              <ArrowUpRight className="h-2.5 w-2.5" />
            </a>
          </div>

          <div className="border-b border-[#e9eeea] px-4 py-3.5">
            <p className="flex items-center gap-1.5 text-[9px] font-bold uppercase tracking-[0.13em] text-[#7e8e85]">
              <RefreshCw className="h-3 w-3" />
              Actualisation
            </p>
            <p className="mt-1.5 text-[9.5px] leading-relaxed text-[#63756c]">
              Le bouton d’actualisation a été retiré de la page. Comme dans l’application
              Android, <strong className="font-semibold text-[#33483f]">tirez la page vers le bas</strong>{" "}
              depuis le haut pour actualiser. Cette gestuelle fonctionne sur écran tactile.
            </p>
          </div>

          <div className="px-4 py-3.5">
            <p className="text-[9px] font-bold uppercase tracking-[0.13em] text-[#7e8e85]">
              Fichiers
            </p>
            <div className="mt-2 grid grid-cols-2 gap-1.5">
              <a
                href="/comap_mobile_core_4.1V.py"
                download="comap_mobile_core_4.1V.py"
                className="inline-flex items-center justify-center gap-1.5 rounded-md border border-[#cfe2d7] bg-[#f1f8f3] px-2 py-2 text-[9.5px] font-semibold text-[#2a6147] transition-colors hover:bg-[#e7f3eb]"
              >
                <FileCode2 className="h-3 w-3" />
                Python corrigé
              </a>
              <a
                href="/comap-piles-4.1v.patch"
                download="comap-piles-4.1v.patch"
                className="inline-flex items-center justify-center gap-1.5 rounded-md border border-[#e1e7e2] bg-white px-2 py-2 text-[9.5px] font-semibold text-[#3c5147] transition-colors hover:bg-[#f5f8f5]"
              >
                <ArrowDownToLine className="h-3 w-3" />
                Patch
              </a>
            </div>
            <p className="mt-1.5 text-[8px] leading-relaxed text-[#93a199]">
              La version corrigée contient le test pile, la tendance sur deux lignes et le retrait du bouton d’actualisation.
              Reconstruisez l’APK après remplacement du fichier.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 border-t border-[#e7ece8] bg-[#fbfcfb] px-4 py-2.5">
          <a
            href="https://github.com/Kervilin/Comap-mobile"
            target="_blank"
            rel="noreferrer noopener"
            className="inline-flex min-w-0 items-center gap-1.5 text-[9px] font-semibold text-[#5d7369] hover:text-[#22392f]"
          >
            <GitBranch className="h-3 w-3 shrink-0" />
            <span className="truncate">main @ 4ed244f</span>
          </a>
          <button
            type="button"
            onClick={onOpenStandalone}
            className="ml-auto inline-flex shrink-0 items-center gap-1 text-[9px] font-semibold text-[#2c6577] hover:underline"
          >
            <ExternalLink className="h-3 w-3" />
            Plein écran
            <ArrowUpRight className="h-2.5 w-2.5" />
          </button>
        </div>
      </section>
    </div>
  );
}
