"use client";

import { useEffect, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import RoleOnly from "../RoleOnly";
import Badge, { type BadgeVariant } from "../Badge";
import Modal from "../Modal";
import Tabs from "../Tabs";
import { Icon } from "../icons";
import { ApiError, useApi } from "@/lib/api/client";
import { useEmployeeDirectory } from "@/lib/api/identity";
import { listContacts, type AccountOut, type ContactOut } from "@/lib/api/crm";
import {
  addAgreementDocument,
  addClause,
  addNote,
  addReview,
  listAgreementDocuments,
  listClauses,
  listNotes,
  listReviews,
  sendAgreementForSignature,
  signAgreement,
  supersedeAgreement,
  updateAgreement,
  type AgreementClauseOut,
  type AgreementDocumentOut,
  type AgreementNoteOut,
  type AgreementOut,
  type AgreementReviewOut,
} from "@/lib/api/contracts";
import {
  addAgreementCommunication,
  listAgreementCommunications,
  type CommunicationCreatePayload,
  type CommunicationOut,
} from "@/lib/api/activity";

const STATUS_BADGE: Record<string, BadgeVariant> = {
  DRAFT: "amber",
  REVIEW: "amber",
  APPROVED: "blue",
  SENT: "amber",
  SIGNED: "green",
  EXPIRED: "gray",
  SUPERSEDED: "gray",
};

const RESOLUTION_BADGE: Record<string, BadgeVariant> = {
  OPEN: "amber",
  AMENDED: "blue",
  ACCEPTED: "green",
  WAIVED: "gray",
};

const REVIEW_OUTCOME_BADGE: Record<string, BadgeVariant> = {
  APPROVED: "green",
  NEEDS_AMENDMENT: "amber",
  REJECTED: "red",
};

function formatDate(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

function hoursUntil(dueDate: string | null): number | null {
  if (!dueDate) return null;
  return Math.max(0, Math.round((new Date(dueDate).getTime() - Date.now()) / (60 * 60 * 1000)));
}

export default function Nda({
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
  const [clauses, setClauses] = useState<AgreementClauseOut[]>([]);
  const [documents, setDocuments] = useState<AgreementDocumentOut[]>([]);
  const [reviews, setReviews] = useState<AgreementReviewOut[]>([]);
  const [comms, setComms] = useState<CommunicationOut[]>([]);
  const [notes, setNotes] = useState<AgreementNoteOut[]>([]);
  const [actionError, setActionError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      listClauses(api, agreement.id),
      listAgreementDocuments(api, agreement.id),
      listReviews(api, agreement.id),
      listAgreementCommunications(api, agreement.id),
      listNotes(api, agreement.id),
    ])
      .then(([c, d, r, m, n]) => {
        if (cancelled) return;
        setClauses(c);
        setDocuments(d);
        setReviews(r);
        setComms(m);
        setNotes(n);
      })
      .catch(() => {
        // Sub-resource fetch failures aren't fatal to the page — tabs just show empty.
      });
    return () => {
      cancelled = true;
    };
  }, [api, agreement.id]);

  const accountName = account.legal_name?.replace(/ Pvt\. Ltd\.$/, "") ?? "—";
  const flaggedOpenCount = clauses.filter((c) => c.is_flagged && c.resolution_status === "OPEN").length;
  const slaHoursLeft = hoursUntil(agreement.sla_due_at);
  const isSigned = agreement.status === "SIGNED";

  function markSigned() {
    setActionError(null);
    startTransition(async () => {
      try {
        onAgreementChange(await signAgreement(api, agreement.id));
      } catch (err) {
        setActionError(err instanceof ApiError ? err.message : "Failed to mark signed.");
      }
    });
  }

  function sendForSignature() {
    setActionError(null);
    startTransition(async () => {
      try {
        onAgreementChange(await sendAgreementForSignature(api, agreement.id));
      } catch (err) {
        setActionError(err instanceof ApiError ? err.message : "Failed to send for signature.");
      }
    });
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
        <Badge variant={STATUS_BADGE[agreement.status] ?? "gray"} dot>
          {agreement.status}
        </Badge>
      </div>
      {agreement.sla_breached_at ? (
        <div className="alert-strip red">
          <Icon name="clock" />
          SLA breached — this agreement passed its window on {formatDate(agreement.sla_breached_at)}.
        </div>
      ) : slaHoursLeft !== null && slaHoursLeft <= 24 ? (
        <div className="alert-strip">
          <Icon name="clock" />
          SLA due in {slaHoursLeft} hours — window closes {formatDate(agreement.sla_due_at)}.
        </div>
      ) : null}
      {actionError && <div className="help err" style={{ margin: "12px 0" }}>{actionError}</div>}
      <Tabs
        tabs={[
          {
            id: "n-details",
            label: "Details",
            content: (
              <Details
                agreement={agreement}
                accountName={accountName}
                canMarkSigned={flaggedOpenCount === 0}
                isSigned={isSigned}
                isPending={isPending}
                onMarkSigned={markSigned}
                onSendForSignature={sendForSignature}
                onAgreementChange={onAgreementChange}
              />
            ),
          },
          {
            id: "n-clauses",
            label: (
              <>
                Clauses {flaggedOpenCount > 0 && <Badge variant="red" style={{ marginLeft: 4 }}>{flaggedOpenCount}</Badge>}
              </>
            ),
            content: <Clauses agreementId={agreement.id} clauses={clauses} onAdded={(c) => setClauses((prev) => [...prev, c])} />,
          },
          {
            id: "n-docs",
            label: "Documents",
            content: <Docs agreementId={agreement.id} documents={documents} onAdded={(d) => setDocuments((prev) => [d, ...prev])} />,
          },
          {
            id: "n-reviews",
            label: "Reviews",
            content: <Reviews agreementId={agreement.id} reviews={reviews} onAdded={(r) => setReviews((prev) => [r, ...prev])} />,
          },
          {
            id: "n-comms",
            label: "Communications",
            content: <Comms agreementId={agreement.id} comms={comms} onAdded={(m) => setComms((prev) => [m, ...prev])} />,
          },
          {
            id: "n-notes",
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
  accountName,
  canMarkSigned,
  isSigned,
  isPending,
  onMarkSigned,
  onSendForSignature,
  onAgreementChange,
}: {
  agreement: AgreementOut;
  accountName: string;
  canMarkSigned: boolean;
  isSigned: boolean;
  isPending: boolean;
  onMarkSigned: () => void;
  onSendForSignature: () => void;
  onAgreementChange: (agreement: AgreementOut) => void;
}) {
  const api = useApi();
  const { label: employeeLabel } = useEmployeeDirectory();
  const router = useRouter();
  const [renewOpen, setRenewOpen] = useState(false);
  const [renewTitle, setRenewTitle] = useState("");
  const [renewEffectiveDate, setRenewEffectiveDate] = useState("");
  const [renewExpiryDate, setRenewExpiryDate] = useState("");
  const [renewError, setRenewError] = useState<string | null>(null);
  const [isRenewing, startRenewing] = useTransition();
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
    listContacts(api, agreement.account_id)
      .then((c) => {
        if (!cancelled) setContacts(c);
      })
      .catch(() => {
        /* the picker just shows no options if this fails */
      });
    return () => {
      cancelled = true;
    };
  }, [api, agreement.account_id]);

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
        const updated = await updateAgreement(api, agreement.id, {
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
        const created = await supersedeAgreement(api, agreement.id, {
          title: renewTitle.trim() || undefined,
          effective_date: renewEffectiveDate || null,
          expiry_date: renewExpiryDate || null,
        });
        router.push(`/agreements/${created.id}`);
      } catch (err) {
        setRenewError(err instanceof ApiError ? err.message : "Failed to renew agreement.");
      }
    });
  }

  const canRenew = isSigned || agreement.status === "EXPIRED";
  const canSign = !isSigned && agreement.status !== "SUPERSEDED" && agreement.status !== "EXPIRED";

  return (
    <div className="card card-pad">
      <div className="fields">
        <div className="field"><div className="lab">Account <span className="req">*</span></div><div className="val">{accountName}</div></div>
        <div className="field"><div className="lab">Type <span className="req">*</span></div><div className="val"><Badge variant="blue">{agreement.agreement_type}</Badge></div></div>
        <div className="field"><div className="lab">Initiated by</div><div className="val">{employeeLabel(agreement.initiated_by_employee_id)}</div></div>
        <div className="field"><div className="lab">Effective date</div><div className="val">{formatDate(agreement.effective_date)}</div></div>
        <div className="field"><div className="lab">Expiry date</div><div className="val">{formatDate(agreement.expiry_date)}</div></div>
        <div className="field"><div className="lab">SLA due</div><div className="val">{agreement.sla_due_at ? <Badge variant="amber">{formatDate(agreement.sla_due_at)}</Badge> : "—"} <span className="t-muted">(auto)</span></div></div>
        <div className="field"><div className="lab">Signer</div><div className="val">{employeeLabel(agreement.signed_by_employee_id)}</div></div>
        <div className="field"><div className="lab">Status <span className="req">*</span></div><div className="val"><Badge variant={STATUS_BADGE[agreement.status] ?? "gray"}>{agreement.status}</Badge></div></div>
        <div className="field"><div className="lab">SharePoint folder</div><div className="val" style={{ color: "var(--primary)" }}>{agreement.sharepoint_folder_url || "—"}</div></div>
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
        <div style={{ marginTop: 18, paddingTop: 18, borderTop: "1px solid var(--border)" }}>
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
      <div style={{ display: "flex", gap: 10, marginTop: 22, paddingTop: 20, borderTop: "1px solid var(--border)" }}>
        <RoleOnly roles={["ACCOUNT_EXEC", "ADMIN", "LEADERSHIP"]}>
          {canSign && (
            <button
              className="btn primary sm"
              disabled={!canMarkSigned || isPending}
              title={canMarkSigned ? undefined : "Resolve all flagged clauses first."}
              onClick={onMarkSigned}
            >
              Mark signed
            </button>
          )}
        </RoleOnly>
        <RoleOnly roles={["ACCOUNT_EXEC", "ADMIN"]}>
          {canSign && (
            <button className="btn sm" disabled={isPending} onClick={onSendForSignature}>Send for signature</button>
          )}
          {canRenew && (
            <button className="btn sm" disabled={isRenewing} onClick={openRenew}>Renew / amend</button>
          )}
          {!editingContract && (
            <button className="btn sm" disabled={isPending} onClick={openEditContract}>Edit contract details</button>
          )}
        </RoleOnly>
        <RoleOnly roles={["SALES"]}>
          <span className="ro-chip" style={{ alignSelf: "center" }}>Read-only for your role</span>
        </RoleOnly>
      </div>

      <Modal
        open={renewOpen}
        onClose={() => setRenewOpen(false)}
        title="Renew / amend agreement"
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
            <input className="inp" value={renewTitle} onChange={(e) => setRenewTitle(e.target.value)} placeholder={agreement.title} autoFocus />
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
          Creates a new DRAFT agreement linked to this one; this agreement moves to SUPERSEDED.
        </div>
      </Modal>
    </div>
  );
}

function Clauses({
  agreementId,
  clauses,
  onAdded,
}: {
  agreementId: string;
  clauses: AgreementClauseOut[];
  onAdded: (clause: AgreementClauseOut) => void;
}) {
  const api = useApi();
  const [open, setOpen] = useState(false);
  const [sectionRef, setSectionRef] = useState("");
  const [clauseText, setClauseText] = useState("");
  const [policyRef, setPolicyRef] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  function submit() {
    if (!clauseText.trim()) {
      setError("Clause text is required.");
      return;
    }
    startTransition(async () => {
      try {
        const created = await addClause(api, agreementId, {
          section_ref: sectionRef || null,
          clause_text: clauseText.trim(),
          policy_ref: policyRef || null,
        });
        onAdded(created);
        setOpen(false);
        setSectionRef("");
        setClauseText("");
        setPolicyRef("");
        setError(null);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to add clause.");
      }
    });
  }

  return (
    <div className="card">
      <div className="card-head">
        <h3>Clause review</h3>
        <div className="spacer" />
        <RoleOnly roles={["ACCOUNT_EXEC", "ADMIN"]}>
          <button className="btn sm" onClick={() => setOpen(true)}>Add clause</button>
        </RoleOnly>
      </div>
      <table>
        <thead><tr><th>Section</th><th>Concern</th><th>Policy</th><th>Resolution</th></tr></thead>
        <tbody>
          {clauses.map((c) => (
            <tr key={c.id}>
              <td className="t-strong">{c.section_ref || "—"}</td>
              <td className="flag-cell">
                {c.is_flagged ? <Badge variant="red" dot>Flagged</Badge> : <Badge variant="gray">Recorded</Badge>}
                {c.clause_text}
              </td>
              <td className="t-muted">{c.policy_ref || "—"}</td>
              <td>{c.resolution_status && <Badge variant={RESOLUTION_BADGE[c.resolution_status] ?? "gray"}>{c.resolution_status.charAt(0) + c.resolution_status.slice(1).toLowerCase()}</Badge>}</td>
            </tr>
          ))}
          {clauses.length === 0 && (
            <tr><td colSpan={4} className="empty-hint" style={{ padding: "18px 22px" }}>No clauses recorded yet.</td></tr>
          )}
        </tbody>
      </table>
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Add clause"
        footer={
          <>
            <button className="btn sm" onClick={() => setOpen(false)} disabled={isPending}>Cancel</button>
            <div className="spacer" />
            <button className="btn primary sm" onClick={submit} disabled={isPending}>{isPending ? "Saving…" : "Add clause"}</button>
          </>
        }
      >
        <div className="fields" style={{ gridTemplateColumns: "1fr" }}>
          <div className="field">
            <div className="lab">Section reference</div>
            <input className="inp" value={sectionRef} onChange={(e) => setSectionRef(e.target.value)} placeholder="e.g. 4.2" />
          </div>
          <div className="field">
            <div className="lab">Clause text <span className="req">*</span></div>
            <textarea className="inp" rows={4} value={clauseText} onChange={(e) => setClauseText(e.target.value)} autoFocus />
            {error && <div className="help err">{error}</div>}
          </div>
          <div className="field">
            <div className="lab">Policy reference</div>
            <input className="inp" value={policyRef} onChange={(e) => setPolicyRef(e.target.value)} />
          </div>
        </div>
      </Modal>
    </div>
  );
}

function Docs({
  agreementId,
  documents,
  onAdded,
}: {
  agreementId: string;
  documents: AgreementDocumentOut[];
  onAdded: (document: AgreementDocumentOut) => void;
}) {
  const api = useApi();
  const [open, setOpen] = useState(false);
  const [filename, setFilename] = useState("");
  const [sharepointUrl, setSharepointUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  function submit() {
    if (!filename.trim()) {
      setError("Filename is required.");
      return;
    }
    startTransition(async () => {
      try {
        const created = await addAgreementDocument(api, agreementId, {
          filename: filename.trim(),
          sharepoint_url: sharepointUrl || null,
        });
        onAdded(created);
        setOpen(false);
        setFilename("");
        setSharepointUrl("");
        setError(null);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to add document.");
      }
    });
  }

  return (
    <div className="card">
      <div className="card-head">
        <h3>Document versions</h3>
        <div className="spacer" />
        <RoleOnly roles={["ACCOUNT_EXEC", "ADMIN"]}>
          <button className="btn sm" onClick={() => setOpen(true)}>Upload version</button>
        </RoleOnly>
      </div>
      <table>
        <thead><tr><th>Version</th><th>File</th><th>Source</th><th>Uploaded</th></tr></thead>
        <tbody>
          {documents.map((d) => (
            <tr key={d.id}>
              <td className="t-strong">v{d.version_number}</td>
              <td>{d.filename || "—"}</td>
              <td><Badge variant="gray">{d.uploaded_by_source ? d.uploaded_by_source.charAt(0) + d.uploaded_by_source.slice(1).toLowerCase() : "—"}</Badge></td>
              <td className="t-muted">{formatDate(d.uploaded_at)}</td>
            </tr>
          ))}
          {documents.length === 0 && (
            <tr><td colSpan={4} className="empty-hint" style={{ padding: "18px 22px" }}>No documents yet.</td></tr>
          )}
        </tbody>
      </table>
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Upload document version"
        footer={
          <>
            <button className="btn sm" onClick={() => setOpen(false)} disabled={isPending}>Cancel</button>
            <div className="spacer" />
            <button className="btn primary sm" onClick={submit} disabled={isPending}>{isPending ? "Saving…" : "Upload"}</button>
          </>
        }
      >
        <div className="fields" style={{ gridTemplateColumns: "1fr" }}>
          <div className="field">
            <div className="lab">Filename <span className="req">*</span></div>
            <input className="inp" value={filename} onChange={(e) => setFilename(e.target.value)} autoFocus />
            {error && <div className="help err">{error}</div>}
          </div>
          <div className="field">
            <div className="lab">SharePoint URL</div>
            <input className="inp" value={sharepointUrl} onChange={(e) => setSharepointUrl(e.target.value)} />
          </div>
        </div>
      </Modal>
    </div>
  );
}

const REVIEW_OUTCOMES = ["APPROVED", "NEEDS_AMENDMENT", "REJECTED"];

function Reviews({
  agreementId,
  reviews,
  onAdded,
}: {
  agreementId: string;
  reviews: AgreementReviewOut[];
  onAdded: (review: AgreementReviewOut) => void;
}) {
  const api = useApi();
  const { label: employeeLabel } = useEmployeeDirectory();
  const [open, setOpen] = useState(false);
  const [outcome, setOutcome] = useState("");
  const [summary, setSummary] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  function submit() {
    if (!outcome) {
      setError("Outcome is required.");
      return;
    }
    startTransition(async () => {
      try {
        const created = await addReview(api, agreementId, { outcome, summary: summary || null });
        onAdded(created);
        setOpen(false);
        setOutcome("");
        setSummary("");
        setError(null);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to record review.");
      }
    });
  }

  return (
    <div className="card">
      <div className="card-head">
        <h3>Review passes</h3>
        <div className="spacer" />
        <RoleOnly roles={["ACCOUNT_EXEC", "ADMIN"]}>
          <button className="btn sm" onClick={() => setOpen(true)}>Record review</button>
        </RoleOnly>
      </div>
      <table>
        <thead><tr><th>Reviewer</th><th>Type</th><th>Outcome</th><th>Date</th></tr></thead>
        <tbody>
          {reviews.map((r) => (
            <tr key={r.id}>
              <td className="person">
                <span className="avatar-sm" style={{ background: "#6D45B8" }}>
                  {employeeLabel(r.reviewer_employee_id).split(" ").map((p) => p[0]).join("").slice(0, 2).toUpperCase()}
                </span>
                {employeeLabel(r.reviewer_employee_id)}
              </td>
              <td><Badge variant="gray">{r.reviewer_type === "HUMAN" ? "Human" : "Agent"}</Badge></td>
              <td>{r.outcome && <Badge variant={REVIEW_OUTCOME_BADGE[r.outcome] ?? "gray"}>{r.outcome.replace(/_/g, " ").toLowerCase()}</Badge>}</td>
              <td className="t-muted">{formatDate(r.reviewed_at)}</td>
            </tr>
          ))}
          {reviews.length === 0 && (
            <tr><td colSpan={4} className="empty-hint" style={{ padding: "18px 22px" }}>No reviews recorded yet.</td></tr>
          )}
        </tbody>
      </table>
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Record review"
        footer={
          <>
            <button className="btn sm" onClick={() => setOpen(false)} disabled={isPending}>Cancel</button>
            <div className="spacer" />
            <button className="btn primary sm" onClick={submit} disabled={isPending}>{isPending ? "Saving…" : "Record review"}</button>
          </>
        }
      >
        <div className="fields" style={{ gridTemplateColumns: "1fr" }}>
          <div className="field">
            <div className="lab">Outcome <span className="req">*</span></div>
            <select className="inp" value={outcome} onChange={(e) => setOutcome(e.target.value)}>
              <option value="">Select…</option>
              {REVIEW_OUTCOMES.map((o) => (
                <option key={o} value={o}>{o.replace(/_/g, " ")}</option>
              ))}
            </select>
            {error && <div className="help err">{error}</div>}
          </div>
          <div className="field">
            <div className="lab">Summary</div>
            <textarea className="inp" rows={4} value={summary} onChange={(e) => setSummary(e.target.value)} />
          </div>
        </div>
      </Modal>
    </div>
  );
}

interface CommDraft {
  direction: string;
  channel: string;
  subject: string;
  from_address: string;
  to_recipients: string;
  cc_recipients: string;
  occurred_at: string;
}

const BLANK_COMM: CommDraft = {
  direction: "OUTBOUND",
  channel: "",
  subject: "",
  from_address: "",
  to_recipients: "",
  cc_recipients: "",
  occurred_at: "",
};

function Comms({
  agreementId,
  comms,
  onAdded,
}: {
  agreementId: string;
  comms: CommunicationOut[];
  onAdded: (comm: CommunicationOut) => void;
}) {
  const api = useApi();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<CommDraft>(BLANK_COMM);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [isPending, startTransition] = useTransition();

  function openForm() {
    setDraft(BLANK_COMM);
    setErrors({});
    setOpen(true);
  }

  function validate(d: CommDraft): Record<string, string> {
    const e: Record<string, string> = {};
    if (!d.channel.trim()) e.channel = "Channel is required.";
    if (!d.subject.trim()) e.subject = "Subject is required.";
    if (!d.occurred_at.trim()) e.occurred_at = "Date is required.";
    return e;
  }

  function save() {
    const e = validate(draft);
    setErrors(e);
    if (Object.keys(e).length > 0) return;

    startTransition(async () => {
      try {
        const payload: CommunicationCreatePayload = {
          direction: draft.direction,
          channel: draft.channel.trim(),
          subject: draft.subject.trim() || null,
          from_address: draft.from_address.trim() || null,
          to_recipients: draft.to_recipients.trim() || null,
          cc_recipients: draft.cc_recipients.trim() || null,
          occurred_at: new Date(`${draft.occurred_at}T00:00:00`).toISOString(),
        };
        const created = await addAgreementCommunication(api, agreementId, payload);
        onAdded(created);
        setOpen(false);
      } catch (err) {
        if (err instanceof ApiError && err.fields) {
          const fieldErrors: Record<string, string> = {};
          for (const f of err.fields) {
            const key = String(f.loc[f.loc.length - 1]);
            fieldErrors[key] = f.msg;
          }
          setErrors(fieldErrors);
        } else {
          setErrors({ channel: err instanceof ApiError ? err.message : "Failed to log communication." });
        }
      }
    });
  }

  return (
    <div className="card card-pad">
      {open && (
        <div style={{ marginBottom: 18, paddingBottom: 18, borderBottom: "1px solid var(--border)" }}>
          <div className="fields" style={{ gridTemplateColumns: "repeat(2, 1fr)" }}>
            <div className="field">
              <div className="lab">Direction <span className="req">*</span></div>
              <select className="inp" value={draft.direction} onChange={(e) => setDraft({ ...draft, direction: e.target.value })}>
                <option value="INBOUND">Inbound</option>
                <option value="OUTBOUND">Outbound</option>
              </select>
            </div>
            <div className="field">
              <div className="lab">Channel <span className="req">*</span></div>
              <input className="inp" value={draft.channel} onChange={(e) => setDraft({ ...draft, channel: e.target.value })} placeholder="Email, Teams, Sales DL…" />
              {errors.channel && <div className="help err">{errors.channel}</div>}
            </div>
            <div className="field">
              <div className="lab">Subject <span className="req">*</span></div>
              <input className="inp" value={draft.subject} onChange={(e) => setDraft({ ...draft, subject: e.target.value })} />
              {errors.subject && <div className="help err">{errors.subject}</div>}
            </div>
            <div className="field">
              <div className="lab">Occurred at <span className="req">*</span></div>
              <input type="date" className="inp" value={draft.occurred_at} onChange={(e) => setDraft({ ...draft, occurred_at: e.target.value })} />
              {errors.occurred_at && <div className="help err">{errors.occurred_at}</div>}
            </div>
            <div className="field">
              <div className="lab">From</div>
              <input className="inp" value={draft.from_address} onChange={(e) => setDraft({ ...draft, from_address: e.target.value })} />
            </div>
            <div className="field">
              <div className="lab">To</div>
              <input className="inp" value={draft.to_recipients} onChange={(e) => setDraft({ ...draft, to_recipients: e.target.value })} />
            </div>
            <div className="field">
              <div className="lab">Cc</div>
              <input className="inp" value={draft.cc_recipients} onChange={(e) => setDraft({ ...draft, cc_recipients: e.target.value })} />
            </div>
          </div>
          <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
            <button className="btn primary sm" onClick={save} disabled={isPending}>
              {isPending ? "Logging…" : "Log communication"}
            </button>
            <button className="btn sm" onClick={() => setOpen(false)} disabled={isPending}>Cancel</button>
          </div>
        </div>
      )}

      <div className="timeline">
        {comms.map((c) => (
          <div key={c.id} className="tl-item done">
            <div className="tl-t">{c.direction === "INBOUND" ? "Inbound" : "Outbound"} · {c.subject || "—"}</div>
            <div className="tl-d">
              via {c.channel}{c.to_recipients ? ` · to ${c.to_recipients}` : ""} · {formatDate(c.occurred_at)}
            </div>
          </div>
        ))}
        {comms.length === 0 && <div className="t-muted" style={{ fontSize: 13 }}>No communications logged yet.</div>}
      </div>
      <RoleOnly roles={["SALES", "ACCOUNT_EXEC", "ADMIN"]}>
        <div style={{ marginTop: 14 }}>
          <button className="btn sm" onClick={openForm}>Log communication</button>
        </div>
      </RoleOnly>
    </div>
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
