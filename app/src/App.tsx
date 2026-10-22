import { useEffect, useState } from "react";
import { api } from "./api";
import { PedalProvider, usePedal } from "./pedal";
import { Gigs } from "./views/Gigs";
import { Library } from "./views/Library";
import { Stage } from "./views/Stage";
import { ToneView } from "./views/ToneView";
import { Tuner } from "./views/Tuner";

const VIEWS = [
  { id: "tone", label: "Tone" },
  { id: "library", label: "Patches" },
  { id: "gigs", label: "Gigs" },
  { id: "stage", label: "Stage" },
  { id: "tuner", label: "Tuner" },
] as const;
type View = (typeof VIEWS)[number]["id"];

export function App() {
  return (
    <PedalProvider>
      <Shell />
    </PedalProvider>
  );
}

function Shell() {
  const [view, setView] = useHashView();
  return (
    <div className="shell">
      <StatusBar />
      <nav className="rail" aria-label="Views">
        <span className="wordmark" aria-hidden="true">g3xn</span>
        {VIEWS.map((v) => (
          <a key={v.id} href={`#${v.id}`} className="rail-link" aria-current={view === v.id ? "page" : undefined}>
            {v.label}
          </a>
        ))}
      </nav>
      <main className="main">
        {view === "tone" && <ToneView />}
        {view === "library" && <Library onTry={() => setView("tone")} />}
        {view === "gigs" && <Gigs onStage={() => setView("stage")} />}
        {view === "stage" && <Stage />}
        {view === "tuner" && <Tuner />}
      </main>
      <Toasts />
    </div>
  );
}

function useHashView(): [View, (v: View) => void] {
  const read = () => {
    const id = location.hash.slice(1);
    return (VIEWS.some((v) => v.id === id) ? id : "tone") as View;
  };
  const [view, setView] = useState<View>(read);
  useEffect(() => {
    const onHash = () => setView(read());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  return [view, (v) => { location.hash = v; }];
}

/** What the pedal is doing, always in view, so nothing happens to it unannounced. */
function StatusBar() {
  const { linked, status, act } = usePedal();
  let light = "off";
  let text = "Can't reach the g3xn daemon. Start it with g3xn-daemon.";
  let action: { label: string; run: () => void } | null = null;

  if (linked && status) {
    if (status.connection === "connected" && status.doing) {
      light = "busy";
      text = status.doing[0].toUpperCase() + status.doing.slice(1) + "…";
    } else if (status.connection === "connected") {
      light = "ok";
      const fw = status.pedal.firmware ? ` · firmware ${status.pedal.firmware}` : "";
      const which = status.pedal.virtual ? "Virtual pedal (not your G3Xn)" : `G3Xn connected${fw}`;
      text = `${which} · on slot ${status.current_slot}${status.current_name ? `, ${status.current_name}` : ""}`;
      action = { label: "Let go of the pedal", run: () => act(() => api.release(), () => "The pedal is free for ToneLib and other programs") };
    } else if (status.connection === "released") {
      text = "The pedal is free for other programs.";
      action = { label: "Take it back", run: () => act(() => api.connect()) };
    } else if (status.connection === "disconnected") {
      light = "error";
      text = status.problem || "No pedal found.";
    } else {
      light = "busy";
      text = "Connecting to the pedal…";
    }
  }

  return (
    <header className={`status${status?.pedal.virtual ? " virtual" : ""}`} role="status">
      <span className={`status-light ${light}`} aria-hidden="true" />
      <span className="status-text">{text}</span>
      {action && (
        <button className="status-action" onClick={action.run}>
          {action.label}
        </button>
      )}
    </header>
  );
}

function Toasts() {
  const { toasts } = usePedal();
  return (
    <div className="toasts" aria-live="polite">
      {toasts.map((t) => (
        <p key={t.id} className={`toast${t.error ? " error" : ""}`} role={t.error ? "alert" : undefined}>
          {t.text}
        </p>
      ))}
    </div>
  );
}
