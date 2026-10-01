"use client";

import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

/**
 * Generic anchored dropdown: a trigger plus a panel that opens/closes on
 * click, dismisses on outside-click or Escape. Extracted from Topbar's two
 * ad-hoc avatar-menu/notification-menu implementations, which duplicated
 * this exact ref+outside-click+Escape wiring — new anchored panels (the App
 * Launcher) should use this instead of a third hand-rolled copy.
 */
export default function Popover({
  trigger,
  children,
  align = "right",
  panelStyle,
  panelClassName,
}: {
  trigger: (args: { open: boolean; toggle: () => void }) => ReactNode;
  children: ReactNode | ((close: () => void) => ReactNode);
  align?: "left" | "right";
  panelStyle?: CSSProperties;
  panelClassName?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("click", handleClick);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("click", handleClick);
      document.removeEventListener("keydown", handleKey);
    };
  }, [open]);

  function toggle() {
    setOpen((o) => !o);
  }

  return (
    <div className="popover-wrap" ref={ref}>
      {trigger({ open, toggle })}
      {open && (
        <div
          className={`popover-panel${align === "left" ? " left" : ""}${panelClassName ? ` ${panelClassName}` : ""}`}
          style={panelStyle}
        >
          {typeof children === "function" ? children(() => setOpen(false)) : children}
        </div>
      )}
    </div>
  );
}
