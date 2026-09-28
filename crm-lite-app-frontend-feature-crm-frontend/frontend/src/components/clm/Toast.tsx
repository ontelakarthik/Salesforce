"use client";

import { useEffect } from "react";
import { Icon } from "./icons";
import { useAppDispatch, useAppSelector } from "@/lib/hooks";
import { dismissToast } from "@/lib/features/toastSlice";

const AUTO_DISMISS_MS = 4000;

/** Renders every queued toast (see lib/features/toastSlice.ts) — mounted
 * once in Shell.tsx so any component can raise one via
 * dispatch(showToast("...")) without owning its own popup UI. Each toast
 * auto-dismisses after AUTO_DISMISS_MS, or immediately on click. */
export default function Toast() {
  const items = useAppSelector((state) => state.toast.items);
  const dispatch = useAppDispatch();

  if (items.length === 0) return null;

  return (
    <div className="toast-stack" role="status" aria-live="polite">
      {items.map((t) => (
        <ToastRow key={t.id} id={t.id} message={t.message} onDismiss={() => dispatch(dismissToast(t.id))} />
      ))}
    </div>
  );
}

function ToastRow({ message, onDismiss }: { id: string; message: string; onDismiss: () => void }) {
  useEffect(() => {
    const timer = setTimeout(onDismiss, AUTO_DISMISS_MS);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="toast-item" onClick={onDismiss}>
      <Icon name="checkCircle" />
      <span>{message}</span>
    </div>
  );
}
