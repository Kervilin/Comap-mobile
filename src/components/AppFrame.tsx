import { useEffect, useRef, useState } from "react";

type AppFrameProps = {
  srcDoc: string;
  reloadKey: number;
  voltage: number;
  batteryTest: boolean;
};

const MIN_WIDTH = 428;

/**
 * Affiche la page du dépôt en plein écran. En dessous de 428 px, elle est
 * réduite sans être réécrite : le dépôt n'a pas de mise en page portrait
 * dédiée et ses colonnes mesurent au minimum ~425 px.
 */
export function AppFrame({ srcDoc, reloadKey, voltage, batteryTest }: AppFrameProps) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [scale, setScale] = useState(1);

  useEffect(() => {
    const element = wrapRef.current;
    if (!element) return;
    const update = () => {
      const width = element.clientWidth;
      setScale(width > 0 && width < MIN_WIDTH ? width / MIN_WIDTH : 1);
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(element);
    window.addEventListener("orientationchange", update);
    return () => {
      observer.disconnect();
      window.removeEventListener("orientationchange", update);
    };
  }, []);

  useEffect(() => {
    iframeRef.current?.contentWindow?.postMessage(
      { type: "comap:voltage", value: voltage },
      "*",
    );
  }, [voltage]);

  useEffect(() => {
    iframeRef.current?.contentWindow?.postMessage(
      { type: "comap:test", enabled: batteryTest },
      "*",
    );
  }, [batteryTest]);

  const scaled = scale < 1;

  return (
    <div ref={wrapRef} className="absolute inset-0 overflow-hidden bg-[#eef1f0]">
      <iframe
        key={reloadKey}
        ref={iframeRef}
        title="Application Comap chauffage"
        srcDoc={srcDoc}
        sandbox="allow-scripts allow-same-origin allow-modals allow-downloads"
        onLoad={(event) => {
          event.currentTarget.contentWindow?.postMessage(
            { type: "comap:voltage", value: voltage },
            "*",
          );
          event.currentTarget.contentWindow?.postMessage(
            { type: "comap:test", enabled: batteryTest },
            "*",
          );
        }}
        className="block border-0 bg-[#eef1f0]"
        style={{
          width: scaled ? `${MIN_WIDTH}px` : "100%",
          height: scaled ? `${100 / scale}%` : "100%",
          transform: scaled ? `scale(${scale})` : undefined,
          transformOrigin: "top left",
        }}
      />
    </div>
  );
}
