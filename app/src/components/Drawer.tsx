// A panel that slides in from the right, over the board. Escape closes it.
import { useEffect } from "react";
import type { ReactNode } from "react";
import { Icon } from "./Icon";

export function Drawer({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <aside className="drawer" aria-label={title}>
      <header className="drawer-head">
        <h2 className="drawer-title">{title}</h2>
        <button className="drawer-close" onClick={onClose} aria-label={`Close ${title.toLowerCase()}`}><Icon name="close" size={20} /></button>
      </header>
      <div className="drawer-body">{children}</div>
    </aside>
  );
}
