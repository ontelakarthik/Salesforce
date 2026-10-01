"use client";

import { useEffect, useState } from "react";
import { useApi, type Api } from "./client";
import { listEmployeeDirectory, type EmployeeDirectoryEntry } from "./admin";

/** Cached at module scope so every component using useEmployeeDirectory()
 * shares one fetch per session instead of each re-fetching the same list —
 * a page reload picks up any employees added since, which is an
 * acceptable trade-off for a display-name lookup, not a security boundary. */
let cachedEntries: EmployeeDirectoryEntry[] | null = null;
let inFlight: Promise<EmployeeDirectoryEntry[]> | null = null;

function loadDirectory(api: Api): Promise<EmployeeDirectoryEntry[]> {
  if (cachedEntries) return Promise.resolve(cachedEntries);
  if (!inFlight) {
    inFlight = listEmployeeDirectory(api)
      .then((rows) => {
        cachedEntries = rows;
        return cachedEntries;
      })
      .finally(() => {
        inFlight = null;
      });
  }
  return inFlight;
}

/** Resolves employee ids to real display names via GET /employees/directory
 * — replaces a handful of hardcoded fake names that never matched a real
 * employee id. Call once per page/component; `label()` returns "—" until
 * the directory has loaded (or if the id isn't found), then the component
 * re-renders with the real name once it resolves. `entries` is the same
 * data as a plain, name-sorted array — for building an owner-picker
 * dropdown rather than just resolving a single id to a name. */
export function useEmployeeDirectory() {
  const api = useApi();
  const [entries, setEntries] = useState<EmployeeDirectoryEntry[] | null>(cachedEntries);

  useEffect(() => {
    if (entries) return;
    let cancelled = false;
    loadDirectory(api)
      .then((d) => {
        if (!cancelled) setEntries(d);
      })
      .catch(() => {
        // A name failing to resolve isn't worth surfacing as a page error —
        // affected labels just stay "—".
      });
    return () => {
      cancelled = true;
    };
  }, [api, entries]);

  const directory = entries ? new Map(entries.map((e) => [e.id, e.full_name])) : null;
  const sortedEntries = entries ? [...entries].sort((a, b) => a.full_name.localeCompare(b.full_name)) : [];

  function label(employeeId: string | null | undefined): string {
    if (!employeeId) return "—";
    return directory?.get(employeeId) ?? "—";
  }

  return { label, directory, entries: sortedEntries };
}
