"use client";

import { useEffect, useState } from "react";
import Badge from "../Badge";
import Spinner from "../Spinner";
import { ApiError, useApi } from "@/lib/api/client";
import {
  channelLabel,
  getNextBestAction,
  listLeadSignals,
  signalTypeLabel,
  type NextBestActionOut,
  type SignalOut,
} from "@/lib/api/pulse";

function ageDays(iso: string): number {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return 0;
  return Math.max(0, Math.floor((Date.now() - then) / 86_400_000));
}

function ageLabel(iso: string): string {
  const d = ageDays(iso);
  if (d <= 0) return "today";
  if (d === 1) return "1 day ago";
  if (d < 30) return `${d} days ago`;
  const m = Math.floor(d / 30);
  return m === 1 ? "1 month ago" : `${m} months ago`;
}

/** Signals + Next-Best-Action for one lead — the Pulse intelligence surface
 * on the Lead detail page. Signals are read-only evidence (each links to its
 * source); the NBA is generated on demand via the existing LLMClient and
 * degrades to a deterministic recommendation when no AI key is configured. */
export default function LeadSignalsPanel({ leadId }: { leadId: string }) {
  const api = useApi();
  const [signals, setSignals] = useState<SignalOut[] | null | undefined>(undefined);
  const [nba, setNba] = useState<NextBestActionOut | null>(null);
  const [nbaLoading, setNbaLoading] = useState(false);
  const [nbaError, setNbaError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional: fetch/reset state when inputs change
    setSignals(undefined);
    listLeadSignals(api, leadId)
      .then((rows) => {
        if (!cancelled) setSignals(rows);
      })
      .catch(() => {
        if (!cancelled) setSignals(null);
      });
    return () => {
      cancelled = true;
    };
  }, [api, leadId]);

  function recommend() {
    setNbaLoading(true);
    setNbaError(null);
    getNextBestAction(api, leadId)
      .then(setNba)
      .catch((err: unknown) => {
        setNbaError(err instanceof ApiError ? err.message : "Couldn't generate a recommendation.");
      })
      .finally(() => setNbaLoading(false));
  }

  const sorted = signals
    ? [...signals].sort((a, b) => new Date(b.captured_at).getTime() - new Date(a.captured_at).getTime())
    : [];

  return (
    <>
      {/* Next-Best-Action */}
      <div className="card">
        <div className="card-head">
          <h3>Next best action</h3>
          <div className="spacer" />
          <button className="btn primary sm" onClick={recommend} disabled={nbaLoading}>
            {nbaLoading ? "Thinking…" : nba ? "Regenerate" : "Recommend"}
          </button>
        </div>
        <div className="card-pad">
          {nbaError && <div className="help err" style={{ marginBottom: 12 }}>{nbaError}</div>}
          {!nba && !nbaLoading && !nbaError && (
            <div className="t-muted" style={{ fontSize: 13.5 }}>
              Generate the single best next move for this lead, grounded in its signals and score.
            </div>
          )}
          {nba && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                <Badge variant="blue">{channelLabel(nba.channel)}</Badge>
                <span className="t-muted" style={{ fontSize: 12.5 }}>
                  Due in {nba.due_in_days} {nba.due_in_days === 1 ? "day" : "days"}
                </span>
                {nba.recommended_practice && <Badge variant="teal">{nba.recommended_practice}</Badge>}
                <span className="t-muted" style={{ fontSize: 11.5, marginLeft: "auto" }}>
                  {nba.source === "ai" ? "AI-generated" : "Rule-based"}
                </span>
              </div>
              <div style={{ fontSize: 15, fontWeight: 600 }}>{nba.action}</div>
              <div
                style={{
                  padding: "10px 12px",
                  background: "var(--surface-2)",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  fontSize: 13,
                }}
              >
                <span className="t-muted">Why now — </span>
                {nba.why_now}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Signals */}
      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-head">
          <h3>Signals</h3>
          <div className="spacer" />
          {signals && signals.length > 0 && (
            <span className="t-muted" style={{ fontSize: 12.5 }}>
              {signals.length} verified {signals.length === 1 ? "signal" : "signals"}
            </span>
          )}
        </div>
        <div className="card-pad">
          {signals === undefined && (
            <div className="loading-inline"><Spinner /> Loading signals…</div>
          )}
          {(signals === null || (signals && signals.length === 0)) && (
            <div className="t-muted" style={{ fontSize: 13.5 }}>
              No external signals captured for this lead yet. Run a sourcing pass from Radar to pull
              hiring, funding, tech-stack, RFP and intent signals.
            </div>
          )}
          {sorted.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {sorted.map((s) => (
                <div
                  key={s.id}
                  style={{
                    display: "flex",
                    gap: 12,
                    padding: "10px 12px",
                    border: "1px solid var(--border)",
                    borderRadius: 8,
                    background: "var(--surface-1)",
                  }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4, flexWrap: "wrap" }}>
                      <Badge variant="violet">{signalTypeLabel(s.type)}</Badge>
                      <span className="t-muted" style={{ fontSize: 12 }}>{s.source}</span>
                      <span className="t-muted" style={{ fontSize: 12 }}>· {ageLabel(s.captured_at)}</span>
                    </div>
                    <div style={{ fontSize: 13.5 }}>{s.summary}</div>
                    {s.url && (
                      <a href={s.url} target="_blank" rel="noopener noreferrer" style={{ fontSize: 12.5 }}>
                        View source ↗
                      </a>
                    )}
                  </div>
                  <div style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                    <div className="num t-strong" style={{ fontSize: 15 }}>+{s.score_points}</div>
                    <div className="t-muted" style={{ fontSize: 11 }}>points</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
