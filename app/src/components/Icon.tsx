// Small line icons, drawn on a 16px grid in one stroke weight.
const PATHS = {
  up: "M4 10l4-4 4 4",
  down: "M4 6l4 4 4-4",
  swap: "M3 5.5h9.5M10 3l2.5 2.5L10 8M13 10.5H3.5M6 8l-2.5 2.5L6 13",
  close: "M4 4l8 8M12 4l-8 8",
  plus: "M8 3v10M3 8h10",
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({ name, size = 16 }: { name: IconName; size?: number }) {
  return (
    <svg className="icon" width={size} height={size} viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path d={PATHS[name]} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
