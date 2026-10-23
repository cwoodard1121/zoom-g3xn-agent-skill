// The pedal's tuner, big enough to read from where you stand.
// The tuner is on while this view is open and off when you leave it.
import { useEffect } from "react";
import { api } from "../api";
import { usePedal } from "../pedal";

// The pedal reports how far off the note is as -8..7; 0 is in tune.
const SEGMENTS = Array.from({ length: 15 }, (_, i) => i - 7);

export function Tuner() {
  const { tuner, status, act } = usePedal();
  const connected = status?.connection === "connected";

  useEffect(() => {
    if (!connected) return;
    act(() => api.tuner(true));
    return () => {
      api.tuner(false).catch(() => {});
    };
  }, [connected, act]);

  const meter = tuner?.note ? tuner.meter : null;
  const verdict = meter === null ? "Play a string" : meter === 0 ? "In tune" : meter < 0 ? "Flat" : "Sharp";

  return (
    <section className="tuner" aria-labelledby="tuner-note">
      <div id="tuner-note" className={`tuner-note${meter === 0 ? " in-tune" : ""}`} aria-live="polite">
        {connected ? tuner?.note ?? "–" : "–"}
      </div>
      <div className="tuner-meter" aria-hidden="true">
        {SEGMENTS.map((s) => (
          <span
            key={s}
            className={[
              "seg",
              s === 0 ? "center" : "",
              meter !== null && (s === meter || (s === 0 && meter === 0)) ? "lit" : "",
            ].join(" ")}
          />
        ))}
      </div>
      <p className="tuner-verdict">{connected ? verdict : "Connect the pedal to tune."}</p>
    </section>
  );
}
