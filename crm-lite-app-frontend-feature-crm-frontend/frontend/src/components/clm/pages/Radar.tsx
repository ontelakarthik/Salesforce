"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import AccessDenied from "../AccessDenied";
import Badge from "../Badge";
import DataTable, { TableLink, type DataTableColumn } from "../DataTable";
import Spinner from "../Spinner";
import { Icon } from "../icons";
import { ApiError, useApi } from "@/lib/api/client";
import {
  getRadar,
  gradeVariant,
  ingestSignals,
  signalTypeLabel,
  type IngestResult,
  type RadarRow,
} from "@/lib/api/pulse";

const PRACTICES = ["Data & AI", "Cloud & Platform", "Digital Engineering", "Cybersecurity", "Advisory"];

function leadHref(row: RadarRow): string {
  return `/leads/${row.lead_id}`;
}

function ageLabel(days: number | null): string {
  if (days == null) return "—";
  if (days <= 0) return "today";
  if (days === 1) return "1d ago";
  if (days < 30) return `${days}d ago`;
  return `${Math.floor(days / 30)}mo ago`;
}

export default function Radar() {
  const api = useApi();
  const router = useRouter();
  const [rows, setRows] = useState<RadarRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [forbidden, setForbidden] = useState(false);

  // Filters
  const [mine, setMine] = useState(false);
  const [minScore, setMinScore] = useState(0);
  const [practice, setPractice] = useState("");

  // View + focus mode
  const [view, setView] = useState<"table" | "focus">("table");
  const [focusIdx, setFocusIdx] = useState(0);

  // Sourcing
  const [ingesting, setIngesting] = useState(false);
  const [ingestMsg, setIngestMsg] = useState<string | null>(null);

  const load = useCallback(() => {
    setRows(null);
    setError(null);
    setForbidden(false);
    getRadar(api, { mine, min_score: minScore, practice: practice || undefined })
      .then(setRows)
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.code === "FORBIDDEN") setForbidden(true);
        else setError(err instanceof ApiError ? err.message : "Failed to load Radar.");
      });
  }, [api, mine, minScore, practice]);

  useEffect(() => {
    load();
  }, [load]);

  const ranked = useMemo(() => rows ?? [], [rows]);

  // Keep the focus cursor in range whenever the list changes.
  useEffect(() => {
    setFocusIdx((i) => Math.min(i, Math.max(0, ranked.length - 1)));
  }, [ranked.length]);

  const focusRow: RadarRow | undefined = ranked[focusIdx];

  const stepFocus = useCallback(
    (delta: number) => {
      setFocusIdx((i) => Math.min(ranked.length - 1, Math.max(0, i + delta)));
    },
    [ranked.length]
  );

  // Keyboard navigation for focus mode (j/k or arrows; Enter opens the lead).
  useEffect(() => {
    if (view !== "focus") return;
    function onKey(e: KeyboardEvent) {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "SELECT" || t.tagName === "TEXTAREA")) return;
      if (e.key === "ArrowDown" || e.key === "j") {
        e.preventDefault();
        stepFocus(1);
      } else if (e.key === "ArrowUp" || e.key === "k") {
        e.preventDefault();
        stepFocus(-1);
      } else if (e.key === "Enter" && focusRow) {
        e.preventDefault();
        router.push(leadHref(focusRow));
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [view, stepFocus, focusRow, router]);

  function runIngest() {
    setIngesting(true);
    setIngestMsg(null);
    ingestSignals(api, 30)
      .then((res: IngestResult) => {
        setIngestMsg(
          `Sourced ${res.signals_ingested} signals from ${res.sources_run.join(", ") || "sources"} · ` +
            `${res.leads_created} new leads, ${res.leads_updated} updated, ${res.rescored} rescored.`
        );
        load();
      })
      .catch((err: unknown) => {
        setIngestMsg(err instanceof ApiError ? err.message : "Sourcing run failed.");
      })
      .finally(() => setIngesting(false));
  }

  if (forbidden) return <AccessDenied what="Radar" />;

  const columns: DataTableColumn<RadarRow>[] = [
    {
      key: "grade",
      label: "Grade",
      className: "num",
      sortable: true,
      sortValue: (r) => r.lead_score,
      render: (r) => <Badge variant={gradeVariant(r.grade)}>{r.grade}</Badge>,
    },
    {
      key: "company",
      label: "Company",
      sortable: true,
      sortValue: (r) => r.company_name,
      render: (r) => (
        <div>
          <TableLink href={leadHref(r)}>{r.company_name}</TableLink>
          <div className="t-muted" style={{ fontSize: 11.5 }}>
            {r.industry || "—"}
            {r.annual_revenue != null ? ` · $${Number(r.annual_revenue).toLocaleString()}` : ""}
          </div>
        </div>
      ),
    },
    {
      key: "lead_score",
      label: "Score",
      className: "num",
      sortable: true,
      sortValue: (r) => r.lead_score,
      render: (r) => (
        <div style={{ textAlign: "right" }}>
          <div className="num t-strong">{r.lead_score}</div>
          {r.signal_points > 0 && (
            <div className="t-muted" style={{ fontSize: 11 }}>+{r.signal_points} signal</div>
          )}
        </div>
      ),
    },
    {
      key: "top_signal",
      label: "Top signal",
      sortable: true,
      sortValue: (r) => r.top_signal ?? "",
      render: (r) =>
        r.top_signal ? (
          <div>
            <Badge variant="violet">{signalTypeLabel(r.top_signal)}</Badge>
            <span className="t-muted" style={{ fontSize: 11.5, marginLeft: 6 }}>
              {ageLabel(r.top_signal_age_days)}
              {r.signal_count > 1 ? ` · +${r.signal_count - 1} more` : ""}
            </span>
          </div>
        ) : (
          <span className="t-muted">—</span>
        ),
    },
    {
      key: "why_now",
      label: "Why now",
      render: (r) => <span style={{ fontSize: 12.5 }}>{r.why_now}</span>,
    },
    {
      key: "practice",
      label: "Practice",
      sortable: true,
      sortValue: (r) => r.recommended_practice ?? "",
      render: (r) => (r.recommended_practice ? <Badge variant="teal">{r.recommended_practice}</Badge> : <span className="t-muted">—</span>),
    },
    {
      key: "actions",
      label: "",
      render: (r) => (
        <div style={{ display: "flex", justifyContent: "flex-end" }} onClick={(e) => e.stopPropagation()}>
          <Link href={leadHref(r)} className="btn sm">Open</Link>
        </div>
      ),
    },
  ];

  return (
    <section className="page active">
      <div className="pagehead">
        <div>
          <h1>Radar</h1>
          <div className="sub">Be first to the signal — your leads, ranked by what changed and why now</div>
        </div>
        <div className="spacer" />
        <div style={{ display: "inline-flex", marginRight: 10 }}>
          <button className={`btn sm${view === "table" ? " primary" : ""}`} onClick={() => setView("table")}>Table</button>
          <button className={`btn sm${view === "focus" ? " primary" : ""}`} onClick={() => setView("focus")} style={{ marginLeft: 6 }}>Focus</button>
        </div>
        <button className="btn primary" onClick={runIngest} disabled={ingesting}>
          <Icon name="target" />
          {ingesting ? "Sourcing…" : "Source signals"}
        </button>
      </div>

      {ingestMsg && <div className="help" style={{ margin: "0 0 12px" }}>{ingestMsg}</div>}
      {error && <div className="help err" style={{ margin: "0 0 12px" }}>{error}</div>}

      {/* Filters */}
      <div className="card card-pad" style={{ display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap", marginBottom: 14 }}>
        <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
          <input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} />
          My leads only
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
          Practice
          <select className="inp" value={practice} onChange={(e) => setPractice(e.target.value)} style={{ width: "auto" }}>
            <option value="">All</option>
            {PRACTICES.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
          Min score
          <input
            type="number"
            className="inp"
            value={minScore}
            min={0}
            onChange={(e) => setMinScore(Math.max(0, Number(e.target.value) || 0))}
            style={{ width: 90 }}
          />
        </label>
        <div className="spacer" />
        {rows && <span className="t-muted" style={{ fontSize: 12.5 }}>{ranked.length} leads on Radar</span>}
      </div>

      {rows === null && !error ? (
        <div className="card card-pad loading-inline"><Spinner /> Loading Radar…</div>
      ) : view === "table" ? (
        <DataTable
          columns={columns}
          rows={ranked}
          rowKey={(r) => r.lead_id}
          rowHref={leadHref}
          defaultPageSize={50}
          pageSizeOptions={[25, 50, 100]}
          searchPlaceholder="Search company, signal, why-now..."
          searchValue={(r) => `${r.company_name} ${r.industry ?? ""} ${r.top_signal ?? ""} ${r.why_now} ${r.recommended_practice ?? ""}`}
        />
      ) : (
        <FocusMode
          row={focusRow}
          index={focusIdx}
          total={ranked.length}
          onPrev={() => stepFocus(-1)}
          onNext={() => stepFocus(1)}
        />
      )}
    </section>
  );
}

function FocusMode({
  row,
  index,
  total,
  onPrev,
  onNext,
}: {
  row: RadarRow | undefined;
  index: number;
  total: number;
  onPrev: () => void;
  onNext: () => void;
}) {
  if (!row) {
    return (
      <div className="card card-pad t-muted" style={{ textAlign: "center", padding: 40 }}>
        No leads on Radar. Source signals to build today&apos;s worklist.
      </div>
    );
  }
  return (
    <div className="card">
      <div className="card-head">
        <h3>
          #{index + 1} of {total}
        </h3>
        <div className="spacer" />
        <span className="t-muted" style={{ fontSize: 11.5, marginRight: 12 }}>↑/↓ or j/k to move · Enter to open</span>
        <button className="btn sm" onClick={onPrev} disabled={index === 0}>Prev</button>
        <button className="btn sm" onClick={onNext} disabled={index >= total - 1} style={{ marginLeft: 6 }}>Next</button>
      </div>
      <div className="card-pad">
        <div style={{ display: "flex", alignItems: "flex-start", gap: 16, flexWrap: "wrap" }}>
          <Badge variant={gradeVariant(row.grade)} style={{ fontSize: 18, padding: "6px 14px" }}>{row.grade}</Badge>
          <div style={{ flex: 1, minWidth: 220 }}>
            <div style={{ fontSize: 20, fontWeight: 700 }}>{row.company_name}</div>
            <div className="t-muted" style={{ fontSize: 13 }}>
              {row.industry || "—"}
              {row.annual_revenue != null ? ` · $${Number(row.annual_revenue).toLocaleString()}` : ""}
            </div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div className="num t-strong" style={{ fontSize: 26 }}>{row.lead_score}</div>
            <div className="t-muted" style={{ fontSize: 11.5 }}>
              composite score{row.signal_points > 0 ? ` · +${row.signal_points} from signals` : ""}
            </div>
          </div>
        </div>

        <div
          style={{
            marginTop: 18,
            padding: "14px 16px",
            background: "var(--surface-2)",
            border: "1px solid var(--border)",
            borderRadius: 10,
          }}
        >
          <div className="t-muted" style={{ fontSize: 12, marginBottom: 4, textTransform: "uppercase", letterSpacing: 0.4 }}>Why now</div>
          <div style={{ fontSize: 15 }}>{row.why_now}</div>
        </div>

        <div style={{ display: "flex", gap: 10, marginTop: 16, flexWrap: "wrap", alignItems: "center" }}>
          {row.top_signal && (
            <Badge variant="violet">
              {signalTypeLabel(row.top_signal)} · {ageLabel(row.top_signal_age_days)}
            </Badge>
          )}
          {row.signal_count > 0 && (
            <span className="t-muted" style={{ fontSize: 12.5 }}>
              {row.signal_count} {row.signal_count === 1 ? "signal" : "signals"}
            </span>
          )}
          {row.recommended_practice && <Badge variant="teal">{row.recommended_practice}</Badge>}
          <Badge variant="gray">{row.status}</Badge>
          <div className="spacer" />
          <Link href={leadHref(row)} className="btn primary sm">Open lead & next action →</Link>
        </div>
      </div>
    </div>
  );
}
