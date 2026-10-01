"use client";

import { useState, type ReactNode } from "react";

export interface TabDef {
  id: string;
  label: ReactNode;
  content: ReactNode;
}

export default function Tabs({
  tabs,
  defaultTab,
  activeId,
  onChange,
}: {
  tabs: TabDef[];
  defaultTab?: string;
  /** Pass to control the active tab from a parent (e.g. an action jumps to a specific tab). */
  activeId?: string;
  onChange?: (id: string) => void;
}) {
  const [internalActive, setInternalActive] = useState(defaultTab ?? tabs[0].id);
  const active = activeId ?? internalActive;

  function select(id: string) {
    if (onChange) onChange(id);
    else setInternalActive(id);
  }

  return (
    <>
      <div className="tabs">
        {tabs.map((t) => (
          <button
            key={t.id}
            className={`tab${active === t.id ? " active" : ""}`}
            onClick={() => select(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tabs.map((t) => (
        <div
          key={t.id}
          className={`tabpane${active === t.id ? " active" : ""}`}
          id={t.id}
        >
          {t.content}
        </div>
      ))}
    </>
  );
}
