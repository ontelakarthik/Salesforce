"use client";

import { useEffect, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import RoleOnly from "../RoleOnly";
import Badge, { type BadgeVariant } from "../Badge";
import Modal from "../Modal";
import Tabs from "../Tabs";
import Spinner from "../Spinner";
import { Icon } from "../icons";
import { ApiError, useApi } from "@/lib/api/client";
import { useEmployeeDirectory } from "@/lib/api/identity";
import {
  addNote,
  listNotes,
  sendAgreementForSignature,
  signAgreement,
  supersedeAgreement,
  updateAgreement,
  type AgreementNoteOut,
  type AgreementOut,
} from "@/lib/api/contracts";
import { listContacts, type AccountOut, type ContactOut } from "@/lib/api/crm";
import {
  addRateCard,
  addTeamMember,
  addMilestone,
  getBudget,
  getBudgetConsumption,
  getSowDetail,
  listMilestones,
  listOrders,
  listRateCards,
  listRevenueRecognition,
  listTeam,
  reviseBudget,
  updateMilestone,
  updateRateCard,
  updateTeamMember,
  upsertSowDetail,
  type OrderOut,
  type RevenueRecognitionEntryOut,
  type SowBudgetConsumptionOut,
  type SowBudgetOut,
  type SowDetailOut,
  type SowMilestoneOut,
  type SowRateCardOut,
  type SowTeamMemberOut,
} from "@/lib/api/delivery";

const BILLING_LABEL: Record<string, string> = {
  TIME_AND_MATERIALS: "Time & Materials",
  FIXED: "Fixed price",
  HYBRID: "Hybrid",
};
const BILLING_OPTIONS = ["TIME_AND_MATERIALS", "FIXED", "HYBRID"];

const INVOICING_LABEL: Record<string, string> = {
  MONTHLY: "Monthly",
  MILESTONE: "Milestone-based",
  CUSTOM: "Custom",
};
const INVOICING_OPTIONS = ["MONTHLY", "MILESTONE", "CUSTOM"];

const MILESTONE_BADGE: Record<string, BadgeVariant> = {
  PLANNED: "gray",
  DELIVERED: "blue",
  INVOICED: "blue",
  PAID: "green",
  DELAYED: "red",
};

/** Mirrors the backend's linear state machine (delivery_service.py) so the
 * UI only ever offers valid next steps — PAID is terminal, DELAYED is a
 * side-state reachable from PLANNED/DELIVERED and resumes forward from there. */
const MILESTONE_TRANSITIONS: Record<string, string[]> = {
  PLANNED: ["DELIVERED", "DELAYED"],
  DELIVERED: ["INVOICED", "DELAYED"],
  DELAYED: ["DELIVERED", "INVOICED", "PAID"],
  INVOICED: ["PAID"],
  PAID: [],
};

const MILESTONE_ACTION_LABEL: Record<string, string> = {
  DELIVERED: "Mark delivered",
  INVOICED: "Mark invoiced",
  PAID: "Mark paid",
  DELAYED: "Mark delayed",
};

function formatDate(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

export default function Sow({
  agreement,
  account,
  onAgreementChange,
}: {
  agreement: AgreementOut;
  account: AccountOut;
  onAgreementChange: (agreement: AgreementOut) => void;
}) {
  const api = useApi();
  const router = useRouter();
  const [detail, setDetail] = useState<SowDetailOut | null>(null);
  const [budget, setBudget] = useState<SowBudgetOut | null>(null);
  const [consumption, setConsumption] = useState<SowBudgetConsumptionOut | null>(null);
  const [rateCards, setRateCards] = useState<SowRateCardOut[]>([]);
  const [team, setTeam] = useState<SowTeamMemberOut[]>([]);
  const [milestones, setMilestones] = useState<SowMilestoneOut[]>([]);
  const [notes, setNotes] = useState<AgreementNoteOut[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [isSigning, startSigning] = useTransition();

  useEffect(() => {
    let cancelled = false;
    setLoaded(false);
    Promise.all([
      getSowDetail(api, agreement.id).catch(() => null),
      getBudget(api, agreement.id).catch(() => null),
      getBudgetConsumption(api, agreement.id).catch(() => null),
      listRateCards(api, agreement.id),
      listTeam(api, agreement.id),
      listMilestones(api, agreement.id),
      listNotes(api, agreement.id),
    ]).then(([d, b, c, rc, t, m, n]) => {
      if (cancelled) return;
      setDetail(d);
      setBudget(b);
      setConsumption(c);
      setRateCards(rc);
      setTeam(t);
      setMilestones(m);
      setNotes(n);
      setLoaded(true);
    });
    return () => {
      cancelled = true;
    };
  }, [api, agreement.id]);

  const accountName = account.legal_name?.replace(/ Pvt\. Ltd\.$/, "") ?? "—";
  const consumedPct = consumption?.consumed_percent ?? 0;
  const thresholds = (budget?.alert_threshold_percents ?? "")
    .split(",")
    .map((t) => Number(t))
    .filter((t) => !Number.isNaN(t) && t > 0);
  const crossedThreshold = thresholds.filter((t) => consumedPct >= t).sort((a, b) => b - a)[0];
  const remaining = budget && consumption ? budget.amount - consumption.consumed : null;
  const isSigned = agreement.status === "SIGNED";

  function markSigned() {
    setActionError(null);
    startSigning(async () => {
      try {
        onAgreementChange(await signAgreement(api, agreement.id));
      } catch (err) {
        setActionError(err instanceof ApiError ? err.message : "Failed to mark signed.");
      }
    });
  }

  function sendForSignature() {
    setActionError(null);
    startSigning(async () => {
      try {
        onAgreementChange(await sendAgreementForSignature(api, agreement.id));
      } catch (err) {
        setActionError(err instanceof ApiError ? err.message : "Failed to send for signature.");
      }
    });
  }

  if (!loaded) {
    return (
      <section className="page active">
        <div className="card card-pad loading-inline"><Spinner /> Loading SOW…</div>
      </section>
    );
  }

  function goBack() {
    if (typeof window !== "undefined" && window.history.length > 1) router.back();
    else router.push("/agreements");
  }

  return (
    <section className="page active">
      <div className="banner">
        <button type="button" onClick={goBack} className="banner-back" aria-label="Go back" title="Go back">
          <Icon name="chevronLeft" />
        </button>
        <div>
          <div className="id">{agreement.id} · {accountName}</div>
          <h1>{agreement.title}</h1>
        </div>
        <div className="spacer" />
        <span className="badge">
          <span className="dot" />
          {agreement.status}{detail?.billing_model && ` · ${BILLING_LABEL[detail.billing_model] ?? detail.billing_model}`}
        </span>
      </div>
      {crossedThreshold !== undefined && (
        <div className="alert-strip">
          <Icon name="alertTriangle" />
          Budget at {consumedPct}% — {crossedThreshold}% threshold crossed.
        </div>
      )}
      {actionError && <div className="help err" style={{ margin: "12px 0" }}>{actionError}</div>}
      <div className="card" style={{ marginBottom: 20 }}>
        <div className="card-head">
          <h3>Budget consumption</h3>
          <div className="spacer" />
          <Badge variant="gray">Computed from approved timesheets</Badge>
          <RoleOnly roles={["SALES", "LEADERSHIP"]}>
            <span className="ro-chip">View only</span>
          </RoleOnly>
        </div>
        {budget ? (
          <div className="meter-wrap">
            <div className="meter-top">
              <div>
                <span className="meter-spent">${(consumption?.consumed ?? 0).toLocaleString()}</span>{" "}
                <span className="meter-of">of ${budget.amount.toLocaleString()} budget</span>
              </div>
              <div className="meter-pct">
                <div className="big">{consumedPct}%</div>
                <div className="help" style={{ margin: 0 }}>consumed</div>
              </div>
            </div>
            <div className="meter-track">
              <div className="meter-fill" style={{ width: `${Math.min(100, consumedPct)}%` }} />
              {thresholds.map((t) => (
                <div key={t} className={`thresh${consumedPct >= t ? " crossed" : ""}`} style={{ left: `${t}%` }}>
                  <span>{t}%{consumedPct >= t ? " ✓" : ""}</span>
                </div>
              ))}
            </div>
            <div className="meter-legend">
              <span><b>${(remaining ?? 0).toLocaleString()}</b> remaining</span>
              <span><b>{(consumption?.hours_logged ?? 0).toLocaleString()} hrs</b> logged</span>
              {thresholds.length > 0 && <span>Thresholds: <b>{thresholds.join(", ")}</b></span>}
            </div>
          </div>
        ) : (
          <div className="card-pad t-muted">No budget set yet.</div>
        )}
      </div>
      <Tabs
        tabs={[
          {
            id: "s-details",
            label: "Details",
            content: (
              <Details
                agreement={agreement}
                accountId={account.id}
                detail={detail}
                budget={budget}
                isSigned={isSigned}
                isSigning={isSigning}
                onMarkSigned={markSigned}
                onSendForSignature={sendForSignature}
                onDetailChange={setDetail}
                onAgreementChange={onAgreementChange}
                onBudgetChange={(b) => {
                  setBudget(b);
                  getBudgetConsumption(api, agreement.id)
                    .then(setConsumption)
                    .catch(() => setConsumption(null));
                }}
              />
            ),
          },
          {
            id: "s-rate",
            label: "Rate card",
            content: (
              <Rate
                agreementId={agreement.id}
                rateCards={rateCards}
                onAdded={(r) => setRateCards((prev) => [...prev, r])}
                onUpdated={(r) => setRateCards((prev) => prev.map((x) => (x.id === r.id ? r : x)))}
              />
            ),
          },
          {
            id: "s-team",
            label: "Team",
            content: (
              <Team
                agreementId={agreement.id}
                team={team}
                rateCards={rateCards}
                onAdded={(m) => setTeam((prev) => [...prev, m])}
                onUpdated={(m) => setTeam((prev) => prev.map((x) => (x.id === m.id ? m : x)))}
              />
            ),
          },
          {
            id: "s-miles",
            label: "Milestones",
            content: (
              <Miles
                agreementId={agreement.id}
                milestones={milestones}
                onAdded={(m) => setMilestones((prev) => [...prev, m])}
                onUpdated={(m) => setMilestones((prev) => prev.map((x) => (x.id === m.id ? m : x)))}
              />
            ),
          },
          {
            id: "s-notes",
            label: "Notes",
            content: <Notes agreementId={agreement.id} notes={notes} onAdded={(n) => setNotes((prev) => [...prev, n])} />,
          },
        ]}
      />
    </section>
  );
}

function Details({
  agreement,
  accountId,
  detail,
  budget,
  isSigned,
  isSigning,
  onMarkSigned,
  onSendForSignature,
  onDetailChange,
  onAgreementChange,
  onBudgetChange,
}: {
  agreement: AgreementOut;
  accountId: string;
  detail: SowDetailOut | null;
  budget: SowBudgetOut | null;
  isSigned: boolean;
  isSigning: boolean;
  onMarkSigned: () => void;
  onSendForSignature: () => void;
  onDetailChange: (detail: SowDetailOut) => void;
  onAgreementChange: (agreement: AgreementOut) => void;
  onBudgetChange: (budget: SowBudgetOut) => void;
}) {
  const agreementId = agreement.id;
  const agreementTitle = agreement.title;
  const agreementStatus = agreement.status;
  const api = useApi();
  const router = useRouter();
  const [contacts, setContacts] = useState<ContactOut[]>([]);
  const [editingContract, setEditingContract] = useState(false);
  const [contractDraft, setContractDraft] = useState({
    contract_term_months: "",
    owner_expiration_notice_days: "",
    customer_signed_contact_id: "",
    customer_signed_title: "",
    customer_signed_date: "",
    special_terms: "",
    billing_address: "",
  });
  const [contractError, setContractError] = useState<string | null>(null);
  const [isSavingContract, startSavingContract] = useTransition();

  useEffect(() => {
    let cancelled = false;
    listContacts(api, accountId)
      .then((c) => {
        if (!cancelled) setContacts(c);
      })
      .catch(() => {
        /* the picker just shows no options if this fails */
      });
    return () => {
      cancelled = true;
    };
  }, [api, accountId]);

  function openEditContract() {
    setContractDraft({
      contract_term_months: agreement.contract_term_months != null ? String(agreement.contract_term_months) : "",
      owner_expiration_notice_days: agreement.owner_expiration_notice_days != null ? String(agreement.owner_expiration_notice_days) : "",
      customer_signed_contact_id: agreement.customer_signed_contact_id ?? "",
      customer_signed_title: agreement.customer_signed_title ?? "",
      customer_signed_date: agreement.customer_signed_date ?? "",
      special_terms: agreement.special_terms ?? "",
      billing_address: agreement.billing_address ?? "",
    });
    setContractError(null);
    setEditingContract(true);
  }

  function saveContract() {
    startSavingContract(async () => {
      try {
        const updated = await updateAgreement(api, agreementId, {
          contract_term_months: contractDraft.contract_term_months.trim() ? Number(contractDraft.contract_term_months) : null,
          owner_expiration_notice_days: contractDraft.owner_expiration_notice_days.trim() ? Number(contractDraft.owner_expiration_notice_days) : null,
          customer_signed_contact_id: contractDraft.customer_signed_contact_id || null,
          customer_signed_title: contractDraft.customer_signed_title.trim() || null,
          customer_signed_date: contractDraft.customer_signed_date || null,
          special_terms: contractDraft.special_terms.trim() || null,
          billing_address: contractDraft.billing_address.trim() || null,
        });
        onAgreementChange(updated);
        setEditingContract(false);
      } catch (err) {
        setContractError(err instanceof ApiError ? err.message : "Failed to save contract details.");
      }
    });
  }
  const [editOpen, setEditOpen] = useState(false);
  const [projectId, setProjectId] = useState(detail?.project_id ?? "");
  const [governingMsaId, setGoverningMsaId] = useState(detail?.governing_msa_id ?? "");
  const [billingModel, setBillingModel] = useState(detail?.billing_model ?? "TIME_AND_MATERIALS");
  const [totalValue, setTotalValue] = useState(detail?.total_value?.toString() ?? "");
  const [headcount, setHeadcount] = useState(detail?.headcount?.toString() ?? "");
  const [invoicingFrequency, setInvoicingFrequency] = useState(detail?.invoicing_frequency ?? "MONTHLY");
  const [detailError, setDetailError] = useState<string | null>(null);
  const [isSavingDetail, startSavingDetail] = useTransition();

  const [budgetOpen, setBudgetOpen] = useState(false);
  const [budgetAmount, setBudgetAmount] = useState("");
  const [budgetThresholds, setBudgetThresholds] = useState(budget?.alert_threshold_percents ?? "70,80");
  const [budgetEffectiveFrom, setBudgetEffectiveFrom] = useState("");
  const [budgetReason, setBudgetReason] = useState("");
  const [budgetError, setBudgetError] = useState<string | null>(null);
  const [isSavingBudget, startSavingBudget] = useTransition();

  const [renewOpen, setRenewOpen] = useState(false);
  const [renewTitle, setRenewTitle] = useState("");
  const [renewEffectiveDate, setRenewEffectiveDate] = useState("");
  const [renewExpiryDate, setRenewExpiryDate] = useState("");
  const [renewError, setRenewError] = useState<string | null>(null);
  const [isRenewing, startRenewing] = useTransition();

  function openRenew() {
    setRenewTitle("");
    setRenewEffectiveDate("");
    setRenewExpiryDate("");
    setRenewError(null);
    setRenewOpen(true);
  }

  function submitRenew() {
    startRenewing(async () => {
      try {
        const created = await supersedeAgreement(api, agreementId, {
          title: renewTitle.trim() || undefined,
          effective_date: renewEffectiveDate || null,
          expiry_date: renewExpiryDate || null,
        });
        router.push(`/agreements/${created.id}`);
      } catch (err) {
        setRenewError(err instanceof ApiError ? err.message : "Failed to renew SOW.");
      }
    });
  }

  const canRenew = isSigned || agreementStatus === "EXPIRED";
  const canSign = !isSigned && agreementStatus !== "SUPERSEDED" && agreementStatus !== "EXPIRED";

  function openEdit() {
    setProjectId(detail?.project_id ?? "");
    setGoverningMsaId(detail?.governing_msa_id ?? "");
    setBillingModel(detail?.billing_model ?? "TIME_AND_MATERIALS");
    setTotalValue(detail?.total_value?.toString() ?? "");
    setHeadcount(detail?.headcount?.toString() ?? "");
    setInvoicingFrequency(detail?.invoicing_frequency ?? "MONTHLY");
    setDetailError(null);
    setEditOpen(true);
  }

  function saveDetail() {
    if (!projectId.trim() || !governingMsaId.trim()) {
      setDetailError("Project and governing MSA are both required.");
      return;
    }
    startSavingDetail(async () => {
      try {
        const updated = await upsertSowDetail(api, agreementId, {
          project_id: projectId.trim(),
          governing_msa_id: governingMsaId.trim(),
          billing_model: billingModel,
          total_value: totalValue.trim() ? Number(totalValue) : null,
          headcount: headcount.trim() ? Number(headcount) : null,
          invoicing_frequency: invoicingFrequency,
        });
        onDetailChange(updated);
        setEditOpen(false);
      } catch (err) {
        setDetailError(err instanceof ApiError ? err.message : "Failed to save SOW details.");
      }
    });
  }

  function openBudget() {
    setBudgetAmount(budget?.amount?.toString() ?? "");
    setBudgetThresholds(budget?.alert_threshold_percents ?? "70,80");
    setBudgetEffectiveFrom("");
    setBudgetReason("");
    setBudgetError(null);
    setBudgetOpen(true);
  }

  function saveBudget() {
    if (!budgetAmount.trim() || Number.isNaN(Number(budgetAmount))) {
      setBudgetError("A valid amount is required.");
      return;
    }
    if (!budgetEffectiveFrom) {
      setBudgetError("Effective-from date is required.");
      return;
    }
    if (!budgetReason.trim()) {
      setBudgetError("A reason is required to revise the budget.");
      return;
    }
    startSavingBudget(async () => {
      try {
        const updated = await reviseBudget(api, agreementId, {
          amount: Number(budgetAmount),
          alert_threshold_percents: budgetThresholds || null,
          effective_from: budgetEffectiveFrom,
          reason: budgetReason.trim(),
        });
        onBudgetChange(updated);
        setBudgetOpen(false);
      } catch (err) {
        setBudgetError(err instanceof ApiError ? err.message : "Failed to revise budget.");
      }
    });
  }

  return (
    <div className="card card-pad">
      <div className="fields">
        <div className="field"><div className="lab">Project <span className="req">*</span></div><div className="val">{detail?.project_id ?? "—"}</div></div>
        <div className="field"><div className="lab">Governing MSA <span className="req">*</span></div><div className="val">{detail?.governing_msa_id ?? "—"}</div></div>
        <div className="field"><div className="lab">Billing model</div><div className="val">{detail?.billing_model && <Badge variant="blue">{BILLING_LABEL[detail.billing_model] ?? detail.billing_model}</Badge>}</div></div>
        <div className="field"><div className="lab">Total value</div><div className="val num">{detail?.total_value != null ? `$${detail.total_value.toLocaleString()}` : "—"}</div></div>
        <div className="field"><div className="lab">Headcount</div><div className="val">{detail?.headcount ?? "—"}</div></div>
        <div className="field"><div className="lab">Invoicing</div><div className="val">{detail?.invoicing_frequency && (INVOICING_LABEL[detail.invoicing_frequency] ?? detail.invoicing_frequency)}</div></div>
        {!editingContract && (
          <>
            <div className="field"><div className="lab">Contract term (months)</div><div className="val num">{agreement.contract_term_months ?? "—"}</div></div>
            <div className="field"><div className="lab">Owner expiration notice (days)</div><div className="val num">{agreement.owner_expiration_notice_days ?? "—"}</div></div>
            <div className="field"><div className="lab">Customer signed by</div><div className="val">{contacts.find((c) => c.id === agreement.customer_signed_contact_id)?.full_name ?? "—"}</div></div>
            <div className="field"><div className="lab">Customer signer title</div><div className="val">{agreement.customer_signed_title || "—"}</div></div>
            <div className="field"><div className="lab">Customer signed date</div><div className="val">{formatDate(agreement.customer_signed_date)}</div></div>
            <div className="field"><div className="lab">Billing address</div><div className="val">{agreement.billing_address || "—"}</div></div>
            <div className="field"><div className="lab">Special terms</div><div className="val">{agreement.special_terms || "—"}</div></div>
          </>
        )}
      </div>
      {editingContract && (
        <div style={{ marginTop: 18, paddingTop: 16, borderTop: "1px solid var(--border)" }}>
          <div className="fields" style={{ gridTemplateColumns: "repeat(2, 1fr)" }}>
            <div className="field">
              <div className="lab">Contract term (months)</div>
              <input
                className="inp"
                type="number"
                value={contractDraft.contract_term_months}
                onChange={(e) => setContractDraft({ ...contractDraft, contract_term_months: e.target.value })}
              />
            </div>
            <div className="field">
              <div className="lab">Owner expiration notice (days)</div>
              <input
                className="inp"
                type="number"
                value={contractDraft.owner_expiration_notice_days}
                onChange={(e) => setContractDraft({ ...contractDraft, owner_expiration_notice_days: e.target.value })}
              />
            </div>
            <div className="field">
              <div className="lab">Customer signed by</div>
              <select
                className="inp"
                value={contractDraft.customer_signed_contact_id}
                onChange={(e) => setContractDraft({ ...contractDraft, customer_signed_contact_id: e.target.value })}
              >
                <option value="">—</option>
                {contacts.map((c) => <option key={c.id} value={c.id}>{c.full_name}</option>)}
              </select>
            </div>
            <div className="field">
              <div className="lab">Customer signer title</div>
              <input
                className="inp"
                value={contractDraft.customer_signed_title}
                onChange={(e) => setContractDraft({ ...contractDraft, customer_signed_title: e.target.value })}
              />
            </div>
            <div className="field">
              <div className="lab">Customer signed date</div>
              <input
                type="date"
                className="inp"
                value={contractDraft.customer_signed_date}
                onChange={(e) => setContractDraft({ ...contractDraft, customer_signed_date: e.target.value })}
              />
            </div>
            <div className="field" style={{ gridColumn: "1 / -1" }}>
              <div className="lab">Billing address</div>
              <textarea className="inp" value={contractDraft.billing_address} onChange={(e) => setContractDraft({ ...contractDraft, billing_address: e.target.value })} />
            </div>
            <div className="field" style={{ gridColumn: "1 / -1" }}>
              <div className="lab">Special terms</div>
              <textarea className="inp" rows={3} value={contractDraft.special_terms} onChange={(e) => setContractDraft({ ...contractDraft, special_terms: e.target.value })} />
            </div>
          </div>
          {contractError && <div className="help err" style={{ marginTop: 10 }}>{contractError}</div>}
          <div style={{ display: "flex", gap: 10, marginTop: 14 }}>
            <button className="btn primary sm" onClick={saveContract} disabled={isSavingContract}>
              {isSavingContract ? "Saving…" : "Save"}
            </button>
            <button className="btn sm" onClick={() => setEditingContract(false)} disabled={isSavingContract}>Cancel</button>
          </div>
        </div>
      )}
      <div style={{ marginTop: 18, paddingTop: 16, borderTop: "1px solid var(--border)", display: "flex", gap: 10 }}>
        <RoleOnly roles={["ACCOUNT_EXEC", "ADMIN"]}>
          <button className="btn sm" onClick={openEdit}>Edit details</button>
          <button className="btn sm" onClick={openBudget}>Revise budget</button>
          {!editingContract && (
            <button className="btn sm" onClick={openEditContract}>Edit contract details</button>
          )}
        </RoleOnly>
        <RoleOnly roles={["ACCOUNT_EXEC", "ADMIN", "LEADERSHIP"]}>
          {canSign && (
            <button className="btn primary sm" disabled={isSigning} onClick={onMarkSigned}>Mark signed</button>
          )}
        </RoleOnly>
        <RoleOnly roles={["ACCOUNT_EXEC", "ADMIN"]}>
          {canSign && (
            <button className="btn sm" disabled={isSigning} onClick={onSendForSignature}>Send for signature</button>
          )}
          {canRenew && (
            <button className="btn sm" disabled={isRenewing} onClick={openRenew}>Renew / amend</button>
          )}
        </RoleOnly>
      </div>
      <div className="help" style={{ marginTop: 12 }}>
        Validation — governing MSA and project must belong to this SOW&apos;s account; both required. Revising budget creates a new budget record with a reason (history preserved).
      </div>

      <Modal
        open={editOpen}
        onClose={() => setEditOpen(false)}
        title="Edit SOW details"
        footer={
          <>
            <button className="btn sm" onClick={() => setEditOpen(false)} disabled={isSavingDetail}>Cancel</button>
            <div className="spacer" />
            <button className="btn primary sm" onClick={saveDetail} disabled={isSavingDetail}>{isSavingDetail ? "Saving…" : "Save"}</button>
          </>
        }
      >
        <div className="fields" style={{ gridTemplateColumns: "repeat(2, 1fr)" }}>
          <div className="field">
            <div className="lab">Project id <span className="req">*</span></div>
            <input className="inp" value={projectId} onChange={(e) => setProjectId(e.target.value)} placeholder="PRJ-00017" />
          </div>
          <div className="field">
            <div className="lab">Governing MSA id <span className="req">*</span></div>
            <input className="inp" value={governingMsaId} onChange={(e) => setGoverningMsaId(e.target.value)} placeholder="AGR-00002" />
          </div>
          <div className="field">
            <div className="lab">Billing model</div>
            <select className="inp" value={billingModel} onChange={(e) => setBillingModel(e.target.value)}>
              {BILLING_OPTIONS.map((o) => (
                <option key={o} value={o}>{BILLING_LABEL[o]}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <div className="lab">Total value</div>
            <input className="inp" type="number" value={totalValue} onChange={(e) => setTotalValue(e.target.value)} />
          </div>
          <div className="field">
            <div className="lab">Headcount</div>
            <input className="inp" type="number" value={headcount} onChange={(e) => setHeadcount(e.target.value)} />
          </div>
          <div className="field">
            <div className="lab">Invoicing frequency</div>
            <select className="inp" value={invoicingFrequency} onChange={(e) => setInvoicingFrequency(e.target.value)}>
              {INVOICING_OPTIONS.map((o) => (
                <option key={o} value={o}>{INVOICING_LABEL[o]}</option>
              ))}
            </select>
          </div>
          {detailError && <div className="help err" style={{ gridColumn: "1 / -1" }}>{detailError}</div>}
        </div>
      </Modal>

      <Modal
        open={budgetOpen}
        onClose={() => setBudgetOpen(false)}
        title="Revise budget"
        footer={
          <>
            <button className="btn sm" onClick={() => setBudgetOpen(false)} disabled={isSavingBudget}>Cancel</button>
            <div className="spacer" />
            <button className="btn primary sm" onClick={saveBudget} disabled={isSavingBudget}>{isSavingBudget ? "Saving…" : "Revise"}</button>
          </>
        }
      >
        <div className="fields" style={{ gridTemplateColumns: "repeat(2, 1fr)" }}>
          <div className="field">
            <div className="lab">Amount <span className="req">*</span></div>
            <input className="inp" type="number" value={budgetAmount} onChange={(e) => setBudgetAmount(e.target.value)} autoFocus />
          </div>
          <div className="field">
            <div className="lab">Alert thresholds (%)</div>
            <input className="inp" value={budgetThresholds} onChange={(e) => setBudgetThresholds(e.target.value)} placeholder="70,80" />
          </div>
          <div className="field">
            <div className="lab">Effective from <span className="req">*</span></div>
            <input className="inp" type="date" value={budgetEffectiveFrom} onChange={(e) => setBudgetEffectiveFrom(e.target.value)} />
          </div>
          <div className="field" style={{ gridColumn: "1 / -1" }}>
            <div className="lab">Reason <span className="req">*</span></div>
            <textarea className="inp" rows={3} value={budgetReason} onChange={(e) => setBudgetReason(e.target.value)} />
          </div>
          {budgetError && <div className="help err" style={{ gridColumn: "1 / -1" }}>{budgetError}</div>}
        </div>
      </Modal>

      <Modal
        open={renewOpen}
        onClose={() => setRenewOpen(false)}
        title="Renew / amend SOW"
        footer={
          <>
            <button className="btn sm" onClick={() => setRenewOpen(false)} disabled={isRenewing}>Cancel</button>
            <div className="spacer" />
            <button className="btn primary sm" onClick={submitRenew} disabled={isRenewing}>{isRenewing ? "Creating…" : "Create new draft"}</button>
          </>
        }
      >
        <div className="fields" style={{ gridTemplateColumns: "1fr" }}>
          <div className="field">
            <div className="lab">Title</div>
            <input className="inp" value={renewTitle} onChange={(e) => setRenewTitle(e.target.value)} placeholder={agreementTitle} autoFocus />
          </div>
          <div className="field">
            <div className="lab">New effective date</div>
            <input className="inp" type="date" value={renewEffectiveDate} onChange={(e) => setRenewEffectiveDate(e.target.value)} />
          </div>
          <div className="field">
            <div className="lab">New expiry date</div>
            <input className="inp" type="date" value={renewExpiryDate} onChange={(e) => setRenewExpiryDate(e.target.value)} />
          </div>
          {renewError && <div className="help err">{renewError}</div>}
        </div>
        <div className="help" style={{ marginTop: 12 }}>
          Creates a new DRAFT SOW linked to this one (its sow_detail, budget, rate card, team, and milestones are not copied). This SOW moves to SUPERSEDED.
        </div>
      </Modal>
    </div>
  );
}

function Rate({
  agreementId,
  rateCards,
  onAdded,
  onUpdated,
}: {
  agreementId: string;
  rateCards: SowRateCardOut[];
  onAdded: (rateCard: SowRateCardOut) => void;
  onUpdated: (rateCard: SowRateCardOut) => void;
}) {
  const api = useApi();
  const [open, setOpen] = useState(false);
  const [roleLabel, setRoleLabel] = useState("");
  const [ratePerHour, setRatePerHour] = useState("");
  const [effectiveFrom, setEffectiveFrom] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();
  const [editing, setEditing] = useState<SowRateCardOut | null>(null);

  function submit() {
    if (!roleLabel.trim() || !ratePerHour.trim() || Number.isNaN(Number(ratePerHour)) || !effectiveFrom) {
      setError("Role, rate, and effective-from date are all required.");
      return;
    }
    startTransition(async () => {
      try {
        const created = await addRateCard(api, agreementId, {
          role_label: roleLabel.trim(),
          rate_per_hour: Number(ratePerHour),
          effective_from: effectiveFrom,
        });
        onAdded(created);
        setOpen(false);
        setRoleLabel("");
        setRatePerHour("");
        setEffectiveFrom("");
        setError(null);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to add rate.");
      }
    });
  }

  return (
    <div className="card">
      <div className="card-head">
        <h3>Rate card</h3>
        <div className="spacer" />
        <RoleOnly roles={["ACCOUNT_EXEC", "ADMIN"]}>
          <button className="btn sm" onClick={() => setOpen(true)}>Add rate</button>
        </RoleOnly>
      </div>
      <table>
        <thead><tr><th>Role / tier</th><th>Rate / hour</th><th>Currency</th><th>Effective</th><th></th></tr></thead>
        <tbody>
          {rateCards.map((r) => (
            <tr key={r.id}>
              <td className="t-strong">{r.role_label}</td>
              <td className="num">${r.rate_per_hour.toFixed(2)}</td>
              <td>{r.currency}</td>
              <td className="t-muted">{formatDate(r.effective_from)}</td>
              <td style={{ textAlign: "right" }}>
                <RoleOnly roles={["ACCOUNT_EXEC", "ADMIN"]}>
                  <button className="btn sm" onClick={() => setEditing(r)}>Edit</button>
                </RoleOnly>
              </td>
            </tr>
          ))}
          {rateCards.length === 0 && (
            <tr><td colSpan={5} className="empty-hint" style={{ padding: "18px 22px" }}>No rate card lines yet.</td></tr>
          )}
        </tbody>
      </table>
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Add rate card line"
        footer={
          <>
            <button className="btn sm" onClick={() => setOpen(false)} disabled={isPending}>Cancel</button>
            <div className="spacer" />
            <button className="btn primary sm" onClick={submit} disabled={isPending}>{isPending ? "Saving…" : "Add"}</button>
          </>
        }
      >
        <div className="fields" style={{ gridTemplateColumns: "1fr" }}>
          <div className="field">
            <div className="lab">Role / tier <span className="req">*</span></div>
            <input className="inp" value={roleLabel} onChange={(e) => setRoleLabel(e.target.value)} placeholder="e.g. Senior Engineer" autoFocus />
          </div>
          <div className="field">
            <div className="lab">Rate per hour <span className="req">*</span></div>
            <input className="inp" type="number" value={ratePerHour} onChange={(e) => setRatePerHour(e.target.value)} />
          </div>
          <div className="field">
            <div className="lab">Effective from <span className="req">*</span></div>
            <input className="inp" type="date" value={effectiveFrom} onChange={(e) => setEffectiveFrom(e.target.value)} />
          </div>
          {error && <div className="help err">{error}</div>}
        </div>
      </Modal>
      <EditRateModal rateCard={editing} onClose={() => setEditing(null)} onSaved={onUpdated} />
    </div>
  );
}

function EditRateModal({
  rateCard,
  onClose,
  onSaved,
}: {
  rateCard: SowRateCardOut | null;
  onClose: () => void;
  onSaved: (rateCard: SowRateCardOut) => void;
}) {
  const api = useApi();
  const [ratePerHour, setRatePerHour] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    if (!rateCard) return;
    setRatePerHour(rateCard.rate_per_hour.toString());
    setCurrency(rateCard.currency);
    setNotes(rateCard.notes ?? "");
    setError(null);
  }, [rateCard]);

  function submit() {
    if (!rateCard) return;
    if (!ratePerHour.trim() || Number.isNaN(Number(ratePerHour))) {
      setError("A valid rate is required.");
      return;
    }
    startTransition(async () => {
      try {
        const updated = await updateRateCard(api, rateCard.id, {
          rate_per_hour: Number(ratePerHour),
          currency: currency.trim() || "USD",
          notes: notes.trim() || null,
        });
        onSaved(updated);
        onClose();
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to save rate.");
      }
    });
  }

  return (
    <Modal
      open={rateCard !== null}
      onClose={onClose}
      title={rateCard ? `Edit ${rateCard.role_label}` : "Edit rate"}
      footer={
        <>
          <button className="btn sm" onClick={onClose} disabled={isPending}>Cancel</button>
          <div className="spacer" />
          <button className="btn primary sm" onClick={submit} disabled={isPending}>{isPending ? "Saving…" : "Save"}</button>
        </>
      }
    >
      <div className="fields" style={{ gridTemplateColumns: "1fr" }}>
        <div className="field">
          <div className="lab">Rate per hour <span className="req">*</span></div>
          <input className="inp" type="number" value={ratePerHour} onChange={(e) => setRatePerHour(e.target.value)} autoFocus />
        </div>
        <div className="field">
          <div className="lab">Currency</div>
          <input className="inp" value={currency} maxLength={3} onChange={(e) => setCurrency(e.target.value.toUpperCase())} />
        </div>
        <div className="field">
          <div className="lab">Notes</div>
          <textarea className="inp" value={notes} onChange={(e) => setNotes(e.target.value)} />
        </div>
        {error && <div className="help err">{error}</div>}
      </div>
    </Modal>
  );
}

function Team({
  agreementId,
  team,
  rateCards,
  onAdded,
  onUpdated,
}: {
  agreementId: string;
  team: SowTeamMemberOut[];
  rateCards: SowRateCardOut[];
  onAdded: (member: SowTeamMemberOut) => void;
  onUpdated: (member: SowTeamMemberOut) => void;
}) {
  const api = useApi();
  const { label: employeeLabel } = useEmployeeDirectory();
  const [open, setOpen] = useState(false);
  const [externalName, setExternalName] = useState("");
  const [rateCardId, setRateCardId] = useState("");
  const [overrideRate, setOverrideRate] = useState("");
  const [assignedFrom, setAssignedFrom] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();
  const [editing, setEditing] = useState<SowTeamMemberOut | null>(null);

  function submit() {
    if (!externalName.trim() || !assignedFrom) {
      setError("Name and assigned-from date are required.");
      return;
    }
    startTransition(async () => {
      try {
        const created = await addTeamMember(api, agreementId, {
          external_name: externalName.trim(),
          rate_card_id: rateCardId || null,
          override_rate_per_hour: overrideRate.trim() ? Number(overrideRate) : null,
          assigned_from: assignedFrom,
        });
        onAdded(created);
        setOpen(false);
        setExternalName("");
        setRateCardId("");
        setOverrideRate("");
        setAssignedFrom("");
        setError(null);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to add team member.");
      }
    });
  }

  return (
    <div className="card">
      <div className="card-head">
        <h3>SOW team</h3>
        <div className="spacer" />
        <RoleOnly roles={["ACCOUNT_EXEC", "ADMIN"]}>
          <button className="btn sm" onClick={() => setOpen(true)}>Add member</button>
        </RoleOnly>
      </div>
      <table>
        <thead><tr><th>Member</th><th>Billed as</th><th>Effective rate</th><th>Since</th><th>Until</th><th></th></tr></thead>
        <tbody>
          {team.map((m) => {
            const rateCard = rateCards.find((r) => r.id === m.rate_card_id);
            const effectiveRate = m.override_rate_per_hour ?? rateCard?.rate_per_hour ?? 0;
            const name = m.external_name ?? employeeLabel(m.employee_id);
            return (
              <tr key={m.id}>
                <td className="person">
                  <span className="avatar-sm" style={{ background: "#2F5FA6" }}>{name.slice(0, 2).toUpperCase()}</span>
                  {name}{m.external_name && " (external)"}
                </td>
                <td>
                  {rateCard?.role_label ?? "—"}
                  {m.override_rate_per_hour !== null && <Badge variant="amber" style={{ marginLeft: 6 }}>override ${m.override_rate_per_hour}</Badge>}
                </td>
                <td className="num">${effectiveRate.toFixed(2)}</td>
                <td className="t-muted">{formatDate(m.assigned_from)}</td>
                <td className={m.assigned_until ? "t-muted" : "empty-hint"}>{m.assigned_until ? formatDate(m.assigned_until) : "—"}</td>
                <td style={{ textAlign: "right" }}>
                  <RoleOnly roles={["ACCOUNT_EXEC", "ADMIN"]}>
                    <button className="btn sm" onClick={() => setEditing(m)}>Edit</button>
                  </RoleOnly>
                </td>
              </tr>
            );
          })}
          {team.length === 0 && (
            <tr><td colSpan={6} className="empty-hint" style={{ padding: "18px 22px" }}>No team members assigned yet.</td></tr>
          )}
        </tbody>
      </table>
      <div className="card-pad" style={{ borderTop: "1px solid var(--border)" }}>
        <div className="help">Effective rate = person override if set, otherwise the rate-card rate.</div>
      </div>
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Add team member"
        footer={
          <>
            <button className="btn sm" onClick={() => setOpen(false)} disabled={isPending}>Cancel</button>
            <div className="spacer" />
            <button className="btn primary sm" onClick={submit} disabled={isPending}>{isPending ? "Saving…" : "Add"}</button>
          </>
        }
      >
        <div className="fields" style={{ gridTemplateColumns: "1fr" }}>
          <div className="field">
            <div className="lab">Name <span className="req">*</span></div>
            <input className="inp" value={externalName} onChange={(e) => setExternalName(e.target.value)} autoFocus />
            <div className="help">Recorded as an external team member — there&apos;s no internal employee picker available yet.</div>
          </div>
          <div className="field">
            <div className="lab">Rate card</div>
            <select className="inp" value={rateCardId} onChange={(e) => setRateCardId(e.target.value)}>
              <option value="">None</option>
              {rateCards.map((r) => (
                <option key={r.id} value={r.id}>{r.role_label} (${r.rate_per_hour}/hr)</option>
              ))}
            </select>
          </div>
          <div className="field">
            <div className="lab">Override rate / hour</div>
            <input className="inp" type="number" value={overrideRate} onChange={(e) => setOverrideRate(e.target.value)} />
          </div>
          <div className="field">
            <div className="lab">Assigned from <span className="req">*</span></div>
            <input className="inp" type="date" value={assignedFrom} onChange={(e) => setAssignedFrom(e.target.value)} />
          </div>
          {error && <div className="help err">{error}</div>}
        </div>
      </Modal>
      <EditTeamMemberModal
        member={editing}
        rateCards={rateCards}
        onClose={() => setEditing(null)}
        onSaved={onUpdated}
      />
    </div>
  );
}

function EditTeamMemberModal({
  member,
  rateCards,
  onClose,
  onSaved,
}: {
  member: SowTeamMemberOut | null;
  rateCards: SowRateCardOut[];
  onClose: () => void;
  onSaved: (member: SowTeamMemberOut) => void;
}) {
  const api = useApi();
  const { label: employeeLabel } = useEmployeeDirectory();
  const [rateCardId, setRateCardId] = useState("");
  const [overrideRate, setOverrideRate] = useState("");
  const [assignedUntil, setAssignedUntil] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    if (!member) return;
    setRateCardId(member.rate_card_id ?? "");
    setOverrideRate(member.override_rate_per_hour?.toString() ?? "");
    setAssignedUntil(member.assigned_until ?? "");
    setError(null);
  }, [member]);

  function submit() {
    if (!member) return;
    startTransition(async () => {
      try {
        const updated = await updateTeamMember(api, member.id, {
          rate_card_id: rateCardId || null,
          override_rate_per_hour: overrideRate.trim() ? Number(overrideRate) : null,
          assigned_until: assignedUntil || null,
        });
        onSaved(updated);
        onClose();
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to save team member.");
      }
    });
  }

  const name = member?.external_name ?? employeeLabel(member?.employee_id ?? null);

  return (
    <Modal
      open={member !== null}
      onClose={onClose}
      title={member ? `Edit ${name}` : "Edit team member"}
      footer={
        <>
          <button className="btn sm" onClick={onClose} disabled={isPending}>Cancel</button>
          <div className="spacer" />
          <button className="btn primary sm" onClick={submit} disabled={isPending}>{isPending ? "Saving…" : "Save"}</button>
        </>
      }
    >
      <div className="fields" style={{ gridTemplateColumns: "1fr" }}>
        <div className="field">
          <div className="lab">Rate card</div>
          <select className="inp" value={rateCardId} onChange={(e) => setRateCardId(e.target.value)}>
            <option value="">None</option>
            {rateCards.map((r) => (
              <option key={r.id} value={r.id}>{r.role_label} (${r.rate_per_hour}/hr)</option>
            ))}
          </select>
        </div>
        <div className="field">
          <div className="lab">Override rate / hour</div>
          <input className="inp" type="number" value={overrideRate} onChange={(e) => setOverrideRate(e.target.value)} />
        </div>
        <div className="field">
          <div className="lab">Assigned until</div>
          <input className="inp" type="date" value={assignedUntil} onChange={(e) => setAssignedUntil(e.target.value)} />
          <div className="help">Set this to roll the member off the project.</div>
        </div>
        {error && <div className="help err">{error}</div>}
      </div>
    </Modal>
  );
}

function Miles({
  agreementId,
  milestones,
  onAdded,
  onUpdated,
}: {
  agreementId: string;
  milestones: SowMilestoneOut[];
  onAdded: (milestone: SowMilestoneOut) => void;
  onUpdated: (milestone: SowMilestoneOut) => void;
}) {
  const api = useApi();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [plannedDate, setPlannedDate] = useState("");
  const [amount, setAmount] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();
  const [updatingId, setUpdatingId] = useState<string | null>(null);
  const [rowError, setRowError] = useState<{ id: string; message: string } | null>(null);
  const [invoicing, setInvoicing] = useState<SowMilestoneOut | null>(null);
  const [orders, setOrders] = useState<OrderOut[]>([]);
  const [revenue, setRevenue] = useState<RevenueRecognitionEntryOut[]>([]);

  // Refetches whenever the milestone list changes — in particular right
  // after a milestone is marked INVOICED, which is the one moment the
  // backend creates a new Order + Revenue Recognition row (see
  // delivery_service.update_milestone()'s side effect).
  useEffect(() => {
    let cancelled = false;
    Promise.all([listOrders(api, agreementId), listRevenueRecognition(api, agreementId)])
      .then(([o, r]) => {
        if (!cancelled) {
          setOrders(o);
          setRevenue(r);
        }
      })
      .catch(() => {
        /* revenue is a supplementary read here — a failed fetch shouldn't block the milestones tab */
      });
    return () => {
      cancelled = true;
    };
  }, [api, agreementId, milestones]);

  function submit() {
    if (!name.trim() || !plannedDate) {
      setError("Milestone name and planned date are required.");
      return;
    }
    startTransition(async () => {
      try {
        const created = await addMilestone(api, agreementId, {
          milestone_name: name.trim(),
          planned_date: plannedDate,
          amount: amount.trim() ? Number(amount) : null,
        });
        onAdded(created);
        setOpen(false);
        setName("");
        setPlannedDate("");
        setAmount("");
        setError(null);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to add milestone.");
      }
    });
  }

  async function changeStatus(milestone: SowMilestoneOut, status: string, invoiceRef?: string) {
    setUpdatingId(milestone.id);
    setRowError(null);
    try {
      const updated = await updateMilestone(api, milestone.id, {
        status,
        ...(invoiceRef ? { invoice_ref: invoiceRef } : {}),
      });
      onUpdated(updated);
    } catch (err) {
      setRowError({ id: milestone.id, message: err instanceof ApiError ? err.message : "Failed to update milestone." });
    } finally {
      setUpdatingId(null);
    }
  }

  function handleAction(milestone: SowMilestoneOut, nextStatus: string) {
    if (nextStatus === "INVOICED") {
      setInvoicing(milestone);
      return;
    }
    changeStatus(milestone, nextStatus);
  }

  return (
    <>
    <div className="card">
      <div className="card-head">
        <h3>Milestones</h3>
        <div className="spacer" />
        <RoleOnly roles={["ACCOUNT_EXEC", "ADMIN"]}>
          <button className="btn sm" onClick={() => setOpen(true)}>Add milestone</button>
        </RoleOnly>
      </div>
      <table>
        <thead><tr><th>Milestone</th><th>Planned</th><th>Delivered</th><th>Amount</th><th>Status</th><th>Invoice</th><th></th></tr></thead>
        <tbody>
          {milestones.map((m) => {
            const nextOptions = MILESTONE_TRANSITIONS[m.status ?? ""] ?? [];
            return (
              <tr key={m.id}>
                <td className="t-strong">{m.milestone_name}</td>
                <td className="t-muted">{formatDate(m.planned_date)}</td>
                <td className={m.actual_date ? "t-muted" : "empty-hint"}>{formatDate(m.actual_date)}</td>
                <td className="num">{m.amount != null ? `$${m.amount.toLocaleString()}` : "—"}</td>
                <td>{m.status && <Badge variant={MILESTONE_BADGE[m.status] ?? "gray"}>{m.status}</Badge>}</td>
                <td className={m.invoice_ref ? "t-muted" : "empty-hint"} style={{ whiteSpace: "nowrap" }}>
                  {m.invoice_ref || "—"}
                  {m.invoiced_at && <div className="t-muted" style={{ fontSize: 11 }}>{formatDate(m.invoiced_at)}</div>}
                </td>
                <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                  <RoleOnly roles={["ACCOUNT_EXEC", "ADMIN"]}>
                    {nextOptions.map((next) => (
                      <button
                        key={next}
                        className="btn sm"
                        style={{ marginLeft: 6 }}
                        disabled={updatingId === m.id}
                        onClick={() => handleAction(m, next)}
                      >
                        {MILESTONE_ACTION_LABEL[next] ?? next}
                      </button>
                    ))}
                  </RoleOnly>
                  {rowError?.id === m.id && <div className="help err">{rowError.message}</div>}
                </td>
              </tr>
            );
          })}
          {milestones.length === 0 && (
            <tr><td colSpan={7} className="empty-hint" style={{ padding: "18px 22px" }}>No milestones yet.</td></tr>
          )}
        </tbody>
      </table>
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Add milestone"
        footer={
          <>
            <button className="btn sm" onClick={() => setOpen(false)} disabled={isPending}>Cancel</button>
            <div className="spacer" />
            <button className="btn primary sm" onClick={submit} disabled={isPending}>{isPending ? "Saving…" : "Add"}</button>
          </>
        }
      >
        <div className="fields" style={{ gridTemplateColumns: "1fr" }}>
          <div className="field">
            <div className="lab">Milestone name <span className="req">*</span></div>
            <input className="inp" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          </div>
          <div className="field">
            <div className="lab">Planned date <span className="req">*</span></div>
            <input className="inp" type="date" value={plannedDate} onChange={(e) => setPlannedDate(e.target.value)} />
          </div>
          <div className="field">
            <div className="lab">Amount</div>
            <input className="inp" type="number" value={amount} onChange={(e) => setAmount(e.target.value)} />
          </div>
          {error && <div className="help err">{error}</div>}
        </div>
      </Modal>
      <InvoiceModal
        milestone={invoicing}
        onClose={() => setInvoicing(null)}
        onConfirm={(ref) => {
          if (!invoicing) return;
          const m = invoicing;
          setInvoicing(null);
          changeStatus(m, "INVOICED", ref);
        }}
      />
    </div>
    {revenue.length > 0 && (
      <div className="card">
        <div className="card-head">
          <h3>Revenue recognized</h3>
          <div className="spacer" />
          <span className="t-strong num">
            ${revenue.reduce((sum, r) => sum + r.recognized_amount, 0).toLocaleString()}
          </span>
        </div>
        <table>
          <thead><tr><th>Order</th><th>Amount</th><th>Recognized</th><th>Opportunity</th></tr></thead>
          <tbody>
            {revenue.map((r) => {
              const order = orders.find((o) => o.id === r.order_id);
              return (
                <tr key={r.id}>
                  <td className="mono t-muted">{order?.id.slice(0, 8) ?? r.order_id.slice(0, 8)}</td>
                  <td className="num">${r.recognized_amount.toLocaleString()}</td>
                  <td className="t-muted">{formatDate(r.recognized_at)}</td>
                  <td>
                    {r.opportunity_id ? (
                      <a className="mono" href={`/opportunities/${r.opportunity_id}`}>{r.opportunity_id}</a>
                    ) : (
                      <span className="empty-hint">Unattributed</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <div className="help" style={{ padding: "12px 22px" }}>
          Created automatically when a milestone is marked Invoiced — replaces a plain invoice reference with a real, traceable revenue number.
        </div>
      </div>
    )}
    </>
  );
}

function InvoiceModal({
  milestone,
  onClose,
  onConfirm,
}: {
  milestone: SowMilestoneOut | null;
  onClose: () => void;
  onConfirm: (invoiceRef: string) => void;
}) {
  const [invoiceRef, setInvoiceRef] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setInvoiceRef("");
    setError(null);
  }, [milestone]);

  function confirm() {
    if (!invoiceRef.trim()) {
      setError("An invoice reference is required.");
      return;
    }
    onConfirm(invoiceRef.trim());
  }

  return (
    <Modal
      open={milestone !== null}
      onClose={onClose}
      title={milestone ? `Mark "${milestone.milestone_name}" invoiced` : "Mark invoiced"}
      footer={
        <>
          <button className="btn sm" onClick={onClose}>Cancel</button>
          <div className="spacer" />
          <button className="btn primary sm" onClick={confirm}>Mark invoiced</button>
        </>
      }
    >
      <div className="field">
        <div className="lab">Invoice reference <span className="req">*</span></div>
        <input className="inp" value={invoiceRef} onChange={(e) => setInvoiceRef(e.target.value)} placeholder="INV-00123" autoFocus />
        {error && <div className="help err">{error}</div>}
      </div>
    </Modal>
  );
}

function Notes({
  agreementId,
  notes,
  onAdded,
}: {
  agreementId: string;
  notes: AgreementNoteOut[];
  onAdded: (note: AgreementNoteOut) => void;
}) {
  const api = useApi();
  const { label: employeeLabel } = useEmployeeDirectory();
  const [noteText, setNoteText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  function submit() {
    if (!noteText.trim()) {
      setError("Note text is required.");
      return;
    }
    startTransition(async () => {
      try {
        const created = await addNote(api, agreementId, { note_text: noteText.trim() });
        onAdded(created);
        setNoteText("");
        setError(null);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to add note.");
      }
    });
  }

  return (
    <div className="card card-pad">
      <div className="timeline">
        {notes.map((n) => (
          <div key={n.id} className="tl-item done">
            <div className="tl-t">{employeeLabel(n.created_by)}</div>
            <div className="tl-d">{n.note_text}</div>
            <div className="tl-d">{formatDate(n.created_at)}</div>
          </div>
        ))}
        {notes.length === 0 && <div className="t-muted" style={{ fontSize: 13 }}>No notes yet.</div>}
      </div>
      <RoleOnly roles={["ACCOUNT_EXEC", "ADMIN"]}>
        <div style={{ marginTop: 14, paddingTop: 14, borderTop: "1px solid var(--border)" }}>
          <div className="field">
            <textarea
              className="inp"
              rows={3}
              value={noteText}
              onChange={(e) => setNoteText(e.target.value)}
              placeholder="Add a note…"
            />
            {error && <div className="help err">{error}</div>}
          </div>
          <button className="btn primary sm" style={{ marginTop: 10 }} onClick={submit} disabled={isPending}>
            {isPending ? "Saving…" : "Add note"}
          </button>
        </div>
      </RoleOnly>
    </div>
  );
}
