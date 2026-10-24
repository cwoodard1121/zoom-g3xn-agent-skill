// What the guitar sounds like right now, on VFD glass: a spectrum of amber segments with peaks that
// hang and fall, and the level. It listens to an audio input of this computer: the G3Xn sends no
// sound over USB, so that's a mic near the amp, or the pedal's output into an audio interface. The
// browser asks once for permission. Nothing is recorded or sent.
// While it listens, the level of the playing (not the silences) goes to `onLevel` a few times a
// second, so the recap can say which patches sit louder or quieter than the rest of the set.
import { useEffect, useRef, useState } from "react";

const BANDS = 40;
const LOW = 70; // Hz
const HIGH = 9000;
const SEGMENTS = 14;
const DEVICE_KEY = "g3xn.scopeInput";

interface Input {
  analyser: AnalyserNode;
  stop: () => void;
}

async function listen(deviceId: string | null): Promise<Input> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { deviceId: deviceId ? { exact: deviceId } : undefined, echoCancellation: false, noiseSuppression: false, autoGainControl: false },
  });
  const ctx = new AudioContext();
  await ctx.resume().catch(() => {});           // made after the click, so it may start suspended
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 4096;
  analyser.smoothingTimeConstant = 0.55;
  ctx.createMediaStreamSource(stream).connect(analyser);
  return {
    analyser,
    stop: () => {
      stream.getTracks().forEach((t) => t.stop());
      ctx.close().catch(() => {});
    },
  };
}

const PLAYING = -50; // dB: quieter than this is the guitar resting, not playing

export function Scope({ onLevel }: { onLevel?: (db: number) => void }) {
  const [on, setOn] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [inputs, setInputs] = useState<MediaDeviceInfo[]>([]);
  const [device, setDevice] = useState<string | null>(() => {
    try {
      return localStorage.getItem(DEVICE_KEY);
    } catch {
      return null;
    }
  });
  const canvas = useRef<HTMLCanvasElement>(null);
  const level = useRef<HTMLSpanElement>(null);
  const report = useRef(onLevel);
  report.current = onLevel;

  useEffect(() => {
    if (!on) return;
    let input: Input | null = null;
    let frame = 0;
    let gone = false;
    listen(device).then(
      async (i) => {
        if (gone) return i.stop();
        input = i;
        setProblem(null);
        const all = await navigator.mediaDevices.enumerateDevices();
        setInputs(all.filter((d) => d.kind === "audioinput"));
        draw(i.analyser);
      },
      (err) => {
        setProblem(err?.name === "NotAllowedError" ? "The browser wasn't allowed to listen. Allow the microphone for this page." : "No audio input to listen to.");
        setOn(false);
      },
    );

    const draw = (analyser: AnalyserNode) => {
      const c = canvas.current;
      if (!c) return;
      const g = c.getContext("2d")!;
      const bins = new Float32Array(analyser.frequencyBinCount);
      const wave = new Float32Array(analyser.fftSize);
      const nyquist = analyser.context.sampleRate / 2;
      const edges = Array.from({ length: BANDS + 1 }, (_, i) => LOW * Math.pow(HIGH / LOW, i / BANDS));
      const peaks = new Array(BANDS).fill(0);
      let lastReport = 0;
      const held = new Array(BANDS).fill(0);
      const css = getComputedStyle(c);
      const lit = css.getPropertyValue("--vfd").trim() || "#ffb000";
      const bright = css.getPropertyValue("--vfd-bright").trim() || "#ffd27a";
      const ghost = css.getPropertyValue("--vfd-ghost").trim() || "#3a2700";

      const tick = () => {
        const dpr = window.devicePixelRatio || 1;
        const w = c.clientWidth, h = c.clientHeight;
        if (c.width !== Math.round(w * dpr) || c.height !== Math.round(h * dpr)) {
          c.width = Math.round(w * dpr);
          c.height = Math.round(h * dpr);
        }
        g.setTransform(dpr, 0, 0, dpr, 0, 0);
        g.clearRect(0, 0, w, h);
        analyser.getFloatFrequencyData(bins);
        analyser.getFloatTimeDomainData(wave);

        const gap = 3;
        const bw = (w - gap * (BANDS - 1)) / BANDS;
        const sh = (h - 2 * (SEGMENTS - 1)) / SEGMENTS;
        for (let b = 0; b < BANDS; b++) {
          const from = Math.floor((edges[b] / nyquist) * bins.length);
          const to = Math.max(from + 1, Math.floor((edges[b + 1] / nyquist) * bins.length));
          let top = -Infinity;
          for (let k = from; k < to && k < bins.length; k++) top = Math.max(top, bins[k]);
          const v = Math.max(0, Math.min(1, (top + 95) / 70)); // -95 dB .. -25 dB
          const segs = Math.round(v * SEGMENTS);
          if (segs >= peaks[b]) {
            peaks[b] = segs;
            held[b] = 24;
          } else if (held[b] > 0) held[b]--;
          else peaks[b] = Math.max(0, peaks[b] - 0.25);
          const x = b * (bw + gap);
          for (let s = 0; s < SEGMENTS; s++) {
            const y = h - (s + 1) * sh - s * 2;
            const on = s < segs;
            const peak = s === Math.round(peaks[b]) - 1 && !on;
            g.fillStyle = on ? (s >= SEGMENTS - 3 ? bright : lit) : peak ? lit : ghost;
            g.globalAlpha = on ? 1 : peak ? 0.7 : 0.55;
            g.shadowColor = lit;
            g.shadowBlur = on ? 8 : 0;
            g.fillRect(x, y, bw, sh);
          }
        }
        g.globalAlpha = 1;
        g.shadowBlur = 0;

        let sum = 0;
        for (const s of wave) sum += s * s;
        const db = 20 * Math.log10(Math.sqrt(sum / wave.length) || 1e-6);
        if (level.current) level.current.textContent = db < -80 ? "–∞" : `${db.toFixed(0)} dB`;
        const now = performance.now();
        if (db > PLAYING && now - lastReport > 250) {
          lastReport = now;
          report.current?.(db);
        }
        frame = requestAnimationFrame(tick);
      };
      frame = requestAnimationFrame(tick);
    };

    return () => {
      gone = true;
      cancelAnimationFrame(frame);
      input?.stop();
    };
  }, [on, device]);

  const pick = (id: string) => {
    setDevice(id || null);
    try {
      if (id) localStorage.setItem(DEVICE_KEY, id);
      else localStorage.removeItem(DEVICE_KEY);
    } catch {
      /* private window */
    }
  };

  return (
    <div className={`scope${on ? " on" : ""}`}>
      <div className="scope-bar">
        <button className="button" aria-pressed={on} onClick={() => setOn(!on)} title="Show what the guitar sounds like: a mic near the amp, or the pedal's output into an audio interface">
          Scope
        </button>
        {on && inputs.length > 1 && (
          <select className="scope-input" aria-label="Listen to" value={device ?? ""} onChange={(e) => pick(e.target.value)}>
            <option value="">Default input</option>
            {inputs.map((d) => (
              <option key={d.deviceId} value={d.deviceId}>{d.label || "Audio input"}</option>
            ))}
          </select>
        )}
        {on && <span className="scope-level" ref={level} aria-label="Level" />}
        {problem && <span className="scope-problem">{problem}</span>}
      </div>
      {on && <canvas ref={canvas} className="scope-glass" aria-label="The guitar's sound, as a spectrum" role="img" />}
    </div>
  );
}
