// A knurled pedal knob. Drag up/down (Shift = fine), scroll, or use the arrow keys;
// double-click puts it back to the effect's default.
import { useRef } from "react";
import type { KeyboardEvent, PointerEvent, WheelEvent } from "react";

const SWEEP = 270; // degrees from 0 to max, like a real pot
const DRAG_PX = 180; // pixels of drag for the full range

interface Props {
  label: string;
  value: number;
  max: number;
  text: string; // what the pedal's screen shows for this value
  defaultValue?: number;
  hint?: string;
  disabled?: boolean;
  onChange: (value: number) => void;
  onGrab?: (held: boolean) => void; // pointer pressed / released
}

export function Knob({ label, value, max, text, defaultValue, hint, disabled, onChange, onGrab }: Props) {
  const drag = useRef<{ y: number; start: number } | null>(null);
  const clamp = (v: number) => Math.max(0, Math.min(max, Math.round(v)));
  const set = (v: number) => {
    const next = clamp(v);
    if (next !== value) onChange(next);
  };

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (disabled) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { y: e.clientY, start: value };
    onGrab?.(true);
  };
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    const scale = (e.shiftKey ? 0.2 : 1) * Math.max(max, 1) / DRAG_PX;
    set(drag.current.start + (drag.current.y - e.clientY) * scale);
  };
  const onPointerUp = () => {
    if (drag.current) onGrab?.(false);
    drag.current = null;
  };
  const onWheel = (e: WheelEvent<HTMLDivElement>) => {
    if (disabled) return;
    set(value + (e.deltaY < 0 ? 1 : -1) * Math.max(1, Math.round(max / 100)));
  };
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (disabled) return;
    const big = Math.max(1, Math.round(max / 10));
    const moves: Record<string, number> = {
      ArrowUp: value + 1, ArrowRight: value + 1, ArrowDown: value - 1, ArrowLeft: value - 1,
      PageUp: value + big, PageDown: value - big, Home: 0, End: max,
    };
    if (e.key in moves) {
      e.preventDefault();
      set(moves[e.key]);
    }
  };

  const angle = -SWEEP / 2 + (max ? value / max : 0) * SWEEP;
  const ticks = 11;
  return (
    <div className="knob" title={hint}>
      <div
        className="knob-dial"
        role="slider"
        tabIndex={disabled ? -1 : 0}
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={max}
        aria-valuenow={value}
        aria-valuetext={text}
        aria-disabled={disabled || undefined}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onWheel={onWheel}
        onKeyDown={onKeyDown}
        onDoubleClick={() => defaultValue !== undefined && !disabled && set(defaultValue)}
      >
        <svg viewBox="-32 -32 64 64" aria-hidden="true">
          {Array.from({ length: ticks }, (_, i) => {
            const a = ((-SWEEP / 2 + (i / (ticks - 1)) * SWEEP - 90) * Math.PI) / 180;
            const lit = max && i / (ticks - 1) <= value / max + 1e-9;
            return (
              <line
                key={i}
                className={lit ? "tick lit" : "tick"}
                x1={Math.cos(a) * 26}
                y1={Math.sin(a) * 26}
                x2={Math.cos(a) * 30}
                y2={Math.sin(a) * 30}
              />
            );
          })}
          <circle className="knob-skirt" r="21" />
          <circle className="knob-knurl" r="18.5" />
          <circle className="knob-cap" r="14" />
          <line className="knob-pointer" x1="0" y1="-6" x2="0" y2="-19" transform={`rotate(${angle})`} />
        </svg>
      </div>
      <div className="knob-lcd">{text}</div>
      <div className="knob-label">{label}</div>
    </div>
  );
}
