"use client";

import { useEffect, useState, useTransition } from "react";
import Badge from "../Badge";
import Modal from "../Modal";
import RoleOnly from "../RoleOnly";
import Spinner from "../Spinner";
import { ApiError, useApi } from "@/lib/api/client";
import {
  LEAD_SCORING_FIELDS,
  LEAD_SCORING_OPERATORS,
  createLeadScoringRule,
  deleteLeadScoringRule,
  listLeadScoringRules,
  updateLeadScoringRule,
  type LeadScoringRuleOut,
} from "@/lib/api/crm";

function humanizeField(field: string): string {
  return field
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

export default function LeadScoringRules() {
  const api = useApi();
  const [rows, setRows] = useState<LeadScoringRuleOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [editing, setEditing] = useState<LeadScoringRuleOut | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  function load() {
    setRows(null);
    setError(null);
    listLeadScoringRules(api)
      .then(setRows)
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : "Failed to load lead scoring rules.");
      });
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional: fetch/reset state when inputs change
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api]);

  function remove(rule: LeadScoringRuleOut) {
    if (!window.confirm(`Delete the rule "${rule.name}"? This can't be undone.`)) return;
    setDeletingId(rule.id);
    deleteLeadScoringRule(api, rule.id)
      .then(() => setRows((prev) => (prev ?? []).filter((r) => r.id !== rule.id)))
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : "Failed to delete rule.");
      })
      .finally(() => setDeletingId(null));
  }

  return (
    <section className="page active">
      <div className="pagehead">
        <div>
          <h1 title="Each active rule checks one lead field against a comparison value; when it matches, its points are added to that lead's total score. Scores help reps and managers prioritize which leads to work first.">
            Lead Scoring Rules
          </h1>
          <div className="sub">Config that adds up into each lead&apos;s score</div>
        </div>
        <RoleOnly roles={["ADMIN"]}>
          <button className="btn primary" onClick={() => setShowNew(true)}>New rule</button>
        </RoleOnly>
      </div>
      {error && <div className="help err" style={{ margin: "12px 0" }}>{error}</div>}
      {rows === null && !error ? (
        <div className="card card-pad loading-inline"><Spinner /> Loading…</div>
      ) : (
        <div className="card">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th title="Which lead attribute this rule inspects.">Field</th>
                <th title="How the field's value is compared against the comparison value.">Operator</th>
                <th title="The value being compared against — not used for the Is Set operator.">Comparison value</th>
                <th title="Added to a matching lead's total score.">Points</th>
                <th title="Inactive rules are kept for reference but never scored.">Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {(rows ?? []).map((rule) => (
                <tr key={rule.id}>
                  <td>{rule.name}</td>
                  <td className="mono">{humanizeField(rule.field_name)}</td>
                  <td>{rule.operator.replace(/_/g, " ")}</td>
                  <td className="t-muted">{rule.comparison_value ?? "—"}</td>
                  <td className="num">{rule.points}</td>
                  <td><Badge variant={rule.is_active ? "green" : "gray"}>{rule.is_active ? "Active" : "Inactive"}</Badge></td>
                  <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                    <RoleOnly roles={["ADMIN"]}>
                      <button className="btn sm" onClick={() => setEditing(rule)}>Edit</button>{" "}
                      <button
                        className="btn sm"
                        disabled={deletingId === rule.id}
                        onClick={() => remove(rule)}
                      >
                        {deletingId === rule.id ? "Deleting…" : "Delete"}
                      </button>
                    </RoleOnly>
                  </td>
                </tr>
              ))}
              {rows?.length === 0 && (
                <tr>
                  <td colSpan={7} className="empty-hint">No lead scoring rules configured yet.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      <RuleModal
        mode="new"
        open={showNew}
        rule={null}
        onClose={() => setShowNew(false)}
        onSaved={(created) => setRows((prev) => (prev ? [...prev, created] : [created]))}
      />
      <RuleModal
        mode="edit"
        open={editing !== null}
        rule={editing}
        onClose={() => setEditing(null)}
        onSaved={(updated) => setRows((prev) => (prev ?? []).map((r) => (r.id === updated.id ? updated : r)))}
      />
    </section>
  );
}

function RuleModal({
  mode,
  open,
  rule,
  onClose,
  onSaved,
}: {
  mode: "new" | "edit";
  open: boolean;
  rule: LeadScoringRuleOut | null;
  onClose: () => void;
  onSaved: (rule: LeadScoringRuleOut) => void;
}) {
  const api = useApi();
  const [name, setName] = useState("");
  const [fieldName, setFieldName] = useState<string>(LEAD_SCORING_FIELDS[0]);
  const [operator, setOperator] = useState<string>(LEAD_SCORING_OPERATORS[0]);
  const [comparisonValue, setComparisonValue] = useState("");
  const [points, setPoints] = useState("");
  const [isActive, setIsActive] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    if (!open) return;
    if (mode === "edit" && rule) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional: fetch/reset state when inputs change
      setName(rule.name);
      setFieldName(rule.field_name);
      setOperator(rule.operator);
      setComparisonValue(rule.comparison_value ?? "");
      setPoints(String(rule.points));
      setIsActive(rule.is_active);
    } else {
      setName("");
      setFieldName(LEAD_SCORING_FIELDS[0]);
      setOperator(LEAD_SCORING_OPERATORS[0]);
      setComparisonValue("");
      setPoints("");
      setIsActive(true);
    }
    setError(null);
  }, [open, mode, rule]);

  const needsComparisonValue = operator !== "IS_SET";

  function submit() {
    if (!name.trim()) {
      setError("Name is required.");
      return;
    }
    if (needsComparisonValue && !comparisonValue.trim()) {
      setError("Comparison value is required for this operator.");
      return;
    }
    if (points.trim() === "" || Number.isNaN(Number(points))) {
      setError("Points must be a number.");
      return;
    }
    startTransition(async () => {
      try {
        const payload = {
          name: name.trim(),
          field_name: fieldName,
          operator,
          comparison_value: needsComparisonValue ? comparisonValue.trim() : null,
          points: Number(points),
        };
        const saved =
          mode === "edit" && rule
            ? await updateLeadScoringRule(api, rule.id, { ...payload, is_active: isActive })
            : await createLeadScoringRule(api, payload);
        onSaved(saved);
        onClose();
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to save rule.");
      }
    });
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={mode === "edit" ? `Edit ${rule?.name ?? "rule"}` : "New lead scoring rule"}
      footer={
        <>
          <button className="btn sm" onClick={onClose} disabled={isPending}>Cancel</button>
          <div className="spacer" />
          <button className="btn primary sm" onClick={submit} disabled={isPending}>{isPending ? "Saving…" : "Save"}</button>
        </>
      }
    >
      <div className="fields" style={{ gridTemplateColumns: "1fr 1fr" }}>
        <div className="field" style={{ gridColumn: "1 / -1" }}>
          <div className="lab">Name <span className="req">*</span></div>
          <input className="inp" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
        </div>
        <div className="field">
          <div className="lab" title="Which lead attribute this rule inspects.">Field <span className="req">*</span></div>
          <select className="inp" value={fieldName} onChange={(e) => setFieldName(e.target.value)}>
            {LEAD_SCORING_FIELDS.map((f) => (
              <option key={f} value={f}>{humanizeField(f)}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <div className="lab" title="How the field's value is compared against the comparison value below (Is Set matches whenever the field has any value at all).">Operator <span className="req">*</span></div>
          <select className="inp" value={operator} onChange={(e) => setOperator(e.target.value)}>
            {LEAD_SCORING_OPERATORS.map((op) => (
              <option key={op} value={op}>{op.replace(/_/g, " ")}</option>
            ))}
          </select>
        </div>
        {needsComparisonValue && (
          <div className="field">
            <div className="lab" title="The value the field is compared against.">Comparison value <span className="req">*</span></div>
            <input className="inp" value={comparisonValue} onChange={(e) => setComparisonValue(e.target.value)} />
          </div>
        )}
        <div className="field">
          <div className="lab" title="Added to a lead's total score whenever this rule matches. Use negative points to penalize.">Points <span className="req">*</span></div>
          <input className="inp" type="number" value={points} onChange={(e) => setPoints(e.target.value)} />
        </div>
        {mode === "edit" && (
          <div className="field">
            <label className="val" style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} />
              Active
            </label>
          </div>
        )}
        {error && <div className="help err" style={{ gridColumn: "1 / -1" }}>{error}</div>}
      </div>
    </Modal>
  );
}
