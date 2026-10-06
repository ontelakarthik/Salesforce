"use client";

import { useEffect, useState, useTransition } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import RoleOnly from "../RoleOnly";
import Badge from "../Badge";
import Spinner from "../Spinner";
import { CountrySelect, StateProvinceSelect } from "../CountryStateFields";
import { Icon } from "../icons";
import { useEmployeeDirectory } from "@/lib/api/identity";
import { ApiError, useApi } from "@/lib/api/client";
import { useAppSelector } from "@/lib/hooks";
import {
  deleteLead,
  getCampaign,
  getLead,
  getLeadScoreBreakdown,
  listAccounts,
  listCampaigns,
  updateLead,
  type AccountOut,
  type CampaignOut,
  type LeadOut,
  type LeadScoreBreakdownEntry,
  type LeadUpdatePayload,
} from "@/lib/api/crm";
import Tabs from "../Tabs";
import AssignOwnerModal from "../AssignOwnerModal";
import ConvertLeadModal from "./ConvertLeadModal";
import NewAccountModal from "./NewAccountModal";
import LeadActivityPanel from "./LeadActivityPanel";
import LeadCadencePanel from "./LeadCadencePanel";
import LeadSignalsPanel from "./LeadSignalsPanel";
import {
  ACTION_LABEL,
  LEAD_PATH_STAGES,
  LEAD_SIDE_STATES,
  LEAD_TRANSITIONS,
  STATUS_BADGE,
  STATUS_DESCRIPTION,
  STATUS_LABEL,
  leadFieldsFromAccount,
  leadFullName,
} from "./leadShared";
import { URL_RE } from "./account/mock";
import { useFieldPermissions } from "@/lib/api/fieldPermissions";

const SALUTATIONS = ["", "Mr.", "Ms.", "Mrs.", "Dr.", "Prof."];
const RATINGS = ["", "HOT", "WARM", "COLD"];
// Mirrored on the backend (LeadCreate/LeadUpdate in crm_models.py) so the
// requirement can't be bypassed via a direct API call.
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
/** Sentinel select value for "+ New account…" — never a real account id
 * (account ids are "ACC-00042"-shaped, see crm_models.Account.id), so it
 * can't collide with one. */
const NEW_ACCOUNT_OPTION = "__new__";

interface Draft {
  account_id: string;
  salutation: string;
  first_name: string;
  last_name: string;
  company_name: string;
  title: string;
  contact_email: string;
  contact_phone: string;
  mobile_phone: string;
  website: string;
  linkedin_url: string;
  industry: string;
  rating: string;
  annual_revenue: string;
  num_employees: string;
  source: string;
  address: string;
  country: string;
  state_province: string;
  description: string;
  do_not_call: boolean;
  email_opt_out: boolean;
  campaign_id: string;
}

function toDraft(lead: LeadOut): Draft {
  return {
    account_id: lead.account_id ?? "",
    salutation: lead.salutation ?? "",
    first_name: lead.first_name ?? "",
    last_name: lead.last_name ?? "",
    company_name: lead.company_name ?? "",
    title: lead.title ?? "",
    contact_email: lead.contact_email ?? "",
    contact_phone: lead.contact_phone ?? "",
    mobile_phone: lead.mobile_phone ?? "",
    website: lead.website ?? "",
    linkedin_url: lead.linkedin_url ?? "",
    industry: lead.industry ?? "",
    rating: lead.rating ?? "",
    annual_revenue: lead.annual_revenue != null ? String(lead.annual_revenue) : "",
    num_employees: lead.num_employees != null ? String(lead.num_employees) : "",
    source: lead.source ?? "",
    address: lead.address ?? "",
    country: lead.country ?? "",
    state_province: lead.state_province ?? "",
    description: lead.description ?? "",
    do_not_call: lead.do_not_call ?? false,
    email_opt_out: lead.email_opt_out ?? false,
    campaign_id: lead.campaign_id ?? "",
  };
}

export default function Lead({ id }: { id: string }) {
  const api = useApi();
  const { label: employeeLabel } = useEmployeeDirectory();
  const { isVisible, isEditable } = useFieldPermissions("LEAD");
  const role = useAppSelector((state) => state.role.value);
  const canEditLead = (["SALES", "ACCOUNT_EXEC", "ADMIN"] as string[]).includes(role);
  const router = useRouter();
  const [lead, setLead] = useState<LeadOut | null>(null);
  const [sourceCampaign, setSourceCampaign] = useState<CampaignOut | null>(null);
  const [campaigns, setCampaigns] = useState<CampaignOut[]>([]);
  const [accounts, setAccounts] = useState<AccountOut[] | null>(null);
  const [scoreBreakdown, setScoreBreakdown] = useState<LeadScoreBreakdownEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [converting, setConverting] = useState<LeadOut | null>(null);
  const [editingDetails, setEditingDetails] = useState(false);
  const [detailsDraft, setDetailsDraft] = useState<Draft | null>(null);
  const [detailsError, setDetailsError] = useState<string | null>(null);
  const [websiteError, setWebsiteError] = useState<string | null>(null);
  const [isUpdating, startUpdate] = useTransition();
  const [isDeleting, setIsDeleting] = useState(false);
  const [showAssignOwner, setShowAssignOwner] = useState(false);
  const [showNewAccount, setShowNewAccount] = useState(false);

  async function assignOwner(ownerId: string | null) {
    const updated = await updateLead(api, id, { owner_employee_id: ownerId });
    setLead(updated);
  }

  function remove() {
    if (!lead) return;
    if (!window.confirm(`Delete the lead "${lead.company_name}"? This can't be undone.`)) return;
    setIsDeleting(true);
    setActionError(null);
    deleteLead(api, lead.id)
      .then(() => router.push("/leads"))
      .catch((err: unknown) => {
        setActionError(err instanceof ApiError ? err.message : "Failed to delete lead.");
        setIsDeleting(false);
      });
  }

  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional: fetch/reset state when inputs change
    setLead(null);
    setError(null);
    getLead(api, id)
      .then((l) => {
        if (cancelled) return;
        setLead(l);
        if (l.campaign_id) {
          getCampaign(api, l.campaign_id).then((c) => {
            if (!cancelled) setSourceCampaign(c);
          }).catch(() => {
            /* attribution is a nice-to-have — a missing/deleted campaign shouldn't break the page */
          });
        }
        getLeadScoreBreakdown(api, id).then((entries) => {
          if (!cancelled) setScoreBreakdown(entries);
        }).catch(() => {
          /* the breakdown is explanatory extra context — a failure here shouldn't break the page */
        });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Failed to load lead.");
      });
    return () => {
      cancelled = true;
    };
  }, [api, id]);

  useEffect(() => {
    let cancelled = false;
    listCampaigns(api).then((rows) => {
      if (!cancelled) setCampaigns(rows);
    }).catch(() => {
      /* the campaign picker just stays empty — editing the rest of the lead still works */
    });
    return () => {
      cancelled = true;
    };
  }, [api]);

  useEffect(() => {
    let cancelled = false;
    listAccounts(api, { page_size: 100 }).then((page) => {
      if (!cancelled) setAccounts(page.items);
    }).catch(() => {
      /* the account picker just stays empty — editing the rest of the lead still works */
    });
    return () => {
      cancelled = true;
    };
  }, [api]);

  function applyAccount(account: AccountOut | null) {
    setDetailsDraft((prev) => (prev ? {
      ...prev,
      account_id: account?.id ?? "",
      ...(account ? leadFieldsFromAccount(account) : {}),
    } : prev));
  }

  function selectAccount(value: string) {
    if (value === NEW_ACCOUNT_OPTION) {
      setShowNewAccount(true);
      return;
    }
    applyAccount(accounts?.find((a) => a.id === value) ?? null);
  }

  if (error) {
    return (
      <section className="page active">
        <div className="help err">{error}</div>
      </section>
    );
  }

  if (!lead) {
    return (
      <section className="page active">
        <div className="card card-pad loading-inline"><Spinner /> Loading lead…</div>
      </section>
    );
  }

  const stageIdx = LEAD_PATH_STAGES.indexOf(lead.status as (typeof LEAD_PATH_STAGES)[number]);
  const nextOptions = LEAD_TRANSITIONS[lead.status] ?? [];

  function advance(status: string) {
    setActionError(null);
    startUpdate(async () => {
      try {
        const updated = await updateLead(api, id, { status });
        setLead(updated);
      } catch (err) {
        setActionError(err instanceof ApiError ? err.message : "Failed to update lead.");
      }
    });
  }

  function openEditDetails() {
    if (!lead) return;
    setDetailsDraft(toDraft(lead));
    setDetailsError(null);
    setWebsiteError(null);
    setEditingDetails(true);
  }

  function saveDetails() {
    if (!detailsDraft) return;
    const email = detailsDraft.contact_email.trim();
    if (!email) {
      setDetailsError("Email is required.");
      return;
    }
    if (!EMAIL_RE.test(email)) {
      setDetailsError("Please enter a valid email address.");
      return;
    }
    const website = detailsDraft.website.trim();
    if (website && !URL_RE.test(website)) {
      setWebsiteError("Enter a valid URL.");
      return;
    }
    setWebsiteError(null);
    setActionError(null);
    startUpdate(async () => {
      try {
        const payload: LeadUpdatePayload = {
          account_id: detailsDraft.account_id || null,
          salutation: detailsDraft.salutation || null,
          first_name: detailsDraft.first_name.trim() || null,
          last_name: detailsDraft.last_name.trim(),
          company_name: detailsDraft.company_name.trim(),
          title: detailsDraft.title.trim() || null,
          contact_email: detailsDraft.contact_email.trim(),
          contact_phone: detailsDraft.contact_phone.trim() || null,
          mobile_phone: detailsDraft.mobile_phone.trim() || null,
          website: detailsDraft.website.trim() || null,
          linkedin_url: detailsDraft.linkedin_url.trim() || null,
          industry: detailsDraft.industry.trim() || null,
          rating: detailsDraft.rating || null,
          annual_revenue: detailsDraft.annual_revenue.trim() ? Number(detailsDraft.annual_revenue) : null,
          num_employees: detailsDraft.num_employees.trim() ? Number(detailsDraft.num_employees) : null,
          source: detailsDraft.source || null,
          address: detailsDraft.address.trim() || null,
          country: detailsDraft.country || null,
          state_province: detailsDraft.state_province || null,
          description: detailsDraft.description.trim() || null,
          do_not_call: detailsDraft.do_not_call,
          email_opt_out: detailsDraft.email_opt_out,
          campaign_id: detailsDraft.campaign_id || null,
        };
        const updated = await updateLead(api, id, payload);
        setLead(updated);
        setSourceCampaign(updated.campaign_id ? campaigns.find((c) => c.id === updated.campaign_id) ?? null : null);
        setEditingDetails(false);
      } catch (err) {
        setDetailsError(err instanceof ApiError ? err.message : "Failed to save changes.");
      }
    });
  }

  function goBack() {
    if (typeof window !== "undefined" && window.history.length > 1) router.back();
    else router.push("/leads");
  }

  return (
    <section className="page active">
      <div className="banner">
        <button type="button" onClick={goBack} className="banner-back" aria-label="Go back" title="Go back">
          <Icon name="chevronLeft" />
        </button>
        <div>
          <div className="id">{lead.company_name}</div>
          <h1>{leadFullName(lead)}</h1>
        </div>
        <div className="spacer" />
        {lead.can_delete && (
          <RoleOnly roles={["SALES", "ACCOUNT_EXEC", "ADMIN"]}>
            <button className="btn sm" style={{ marginRight: 10 }} disabled={isDeleting} onClick={remove}>
              {isDeleting ? "Deleting…" : "Delete"}
            </button>
          </RoleOnly>
        )}
        <RoleOnly roles={["SALES", "ACCOUNT_EXEC", "ADMIN"]}>
          <button
            className="badge"
            style={{ cursor: "pointer", border: "none" }}
            onClick={() => setShowAssignOwner(true)}
          >
            Owner · {employeeLabel(lead.owner_employee_id)} · Change
          </button>
        </RoleOnly>
        {!canEditLead && <span className="badge">Owner · {employeeLabel(lead.owner_employee_id)}</span>}
      </div>
      {actionError && <div className="help err" style={{ margin: "0 0 14px" }}>{actionError}</div>}
      <div className="stagebar">
        {LEAD_PATH_STAGES.map((stage, idx) => (
          <div
            key={stage}
            className={`st${idx < stageIdx ? " done" : ""}${idx === stageIdx ? " current" : ""}`}
            title={STATUS_DESCRIPTION[stage]}
          >
            {STATUS_LABEL[stage]}
          </div>
        ))}
        {LEAD_SIDE_STATES.map((stage) => (
          <div
            key={stage}
            className={`st${lead.status === stage ? " lost" : ""}`}
            title={STATUS_DESCRIPTION[stage]}
          >
            {STATUS_LABEL[stage]}
          </div>
        ))}
      </div>
      <Tabs
        defaultTab="lead-details"
        tabs={[
          {
            id: "lead-details",
            label: "Details",
            content: (
        <div className="card">
          <div className="card-head">
            <h3>Lead details</h3>
            <div className="spacer" />
            <RoleOnly roles={["SALES", "ACCOUNT_EXEC", "ADMIN"]}>
              {lead.status === "QUALIFIED" && (
                <button className="btn primary sm" onClick={() => setConverting(lead)} disabled={isUpdating}>
                  Convert
                </button>
              )}
              {nextOptions.map((next) => (
                <button
                  key={next}
                  className="btn sm"
                  style={{ marginLeft: 8 }}
                  disabled={isUpdating}
                  onClick={() => advance(next)}
                >
                  {ACTION_LABEL[next] ?? next}
                </button>
              ))}
            </RoleOnly>
          </div>
          <div className="card-pad">
            {actionError && <div className="help err" style={{ marginBottom: 14 }}>{actionError}</div>}
            {!editingDetails && (
              <>
                <div className="fields">
                  {isVisible("company_name") && (
                    <div className="field">
                      <div className="lab">Company <span className="req">*</span></div>
                      <div className="val">
                        {lead.account_id || lead.converted_account_id ? (
                          <Link href={`/accounts/${lead.account_id || lead.converted_account_id}`} className="tlink">
                            {lead.company_name}
                          </Link>
                        ) : (
                          lead.company_name
                        )}
                      </div>
                    </div>
                  )}
                  {isVisible("last_name") && (
                    <div className="field"><div className="lab">Contact</div><div className="val">{leadFullName(lead)}</div></div>
                  )}
                  {isVisible("title") && (
                    <div className="field"><div className="lab">Title</div><div className="val">{lead.title || "—"}</div></div>
                  )}
                  <div className="field">
                    <div className="lab">Status</div>
                    <div className="val" title={STATUS_DESCRIPTION[lead.status]}>
                      {lead.converted_opportunity_id ? (
                        <Link href={`/opportunities/${lead.converted_opportunity_id}`}>
                          <Badge variant={STATUS_BADGE[lead.status] ?? "gray"}>{STATUS_LABEL[lead.status] ?? lead.status}</Badge>
                        </Link>
                      ) : (
                        <Badge variant={STATUS_BADGE[lead.status] ?? "gray"}>{STATUS_LABEL[lead.status] ?? lead.status}</Badge>
                      )}
                    </div>
                  </div>
                  <div className="field">
                    <div className="lab">Lead score</div>
                    <div className="val num">{lead.lead_score}</div>
                    {scoreBreakdown.length > 0 && (
                      <div
                        style={{
                          marginTop: 6,
                          padding: "8px 10px",
                          background: "var(--surface-2)",
                          border: "1px solid var(--border)",
                          borderRadius: 8,
                          fontSize: 12.5,
                        }}
                      >
                        <div className="t-muted" style={{ marginBottom: 4 }}>Matched rules</div>
                        {scoreBreakdown.map((entry) => (
                          <div key={entry.rule_id} style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                            <span>{entry.name}</span>
                            <span className="num t-strong">+{entry.points}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                  {isVisible("rating") && (
                    <div className="field"><div className="lab">Rating</div><div className="val">{lead.rating || "—"}</div></div>
                  )}
                  {isVisible("contact_email") && (
                    <div className="field"><div className="lab">Email</div><div className="val">{lead.contact_email || "—"}</div></div>
                  )}
                  {isVisible("contact_phone") && (
                    <div className="field"><div className="lab">Phone</div><div className="val">{lead.contact_phone || "—"}</div></div>
                  )}
                  {isVisible("mobile_phone") && (
                    <div className="field"><div className="lab">Mobile</div><div className="val">{lead.mobile_phone || "—"}</div></div>
                  )}
                  {isVisible("website") && (
                    <div className="field"><div className="lab">Website</div><div className="val">{lead.website || "—"}</div></div>
                  )}
                  {isVisible("linkedin_url") && (
                    <div className="field">
                      <div className="lab">LinkedIn</div>
                      <div className="val">
                        {lead.linkedin_url ? (
                          <a href={lead.linkedin_url} target="_blank" rel="noopener noreferrer">Open LinkedIn ↗</a>
                        ) : "—"}
                      </div>
                    </div>
                  )}
                  {isVisible("industry") && (
                    <div className="field"><div className="lab">Industry</div><div className="val">{lead.industry || "—"}</div></div>
                  )}
                  {isVisible("annual_revenue") && (
                    <div className="field"><div className="lab">Annual revenue</div><div className="val num">{lead.annual_revenue != null ? lead.annual_revenue.toLocaleString() : "—"}</div></div>
                  )}
                  {isVisible("num_employees") && (
                    <div className="field"><div className="lab">No. of employees</div><div className="val num">{lead.num_employees ?? "—"}</div></div>
                  )}
                  {isVisible("source") && (
                    <div className="field"><div className="lab">Lead source</div><div className="val">{lead.source || "—"}</div></div>
                  )}
                  {isVisible("campaign_id") && (
                    <div className="field"><div className="lab">Campaign</div><div className="val">{sourceCampaign ? <Badge variant="teal">{sourceCampaign.name}</Badge> : "—"}</div></div>
                  )}
                  {isVisible("country") && (
                    <div className="field"><div className="lab">Country</div><div className="val">{lead.country || "—"}</div></div>
                  )}
                  {isVisible("state_province") && (
                    <div className="field"><div className="lab">State/Province</div><div className="val">{lead.state_province || "—"}</div></div>
                  )}
                  {/* Region is always derived server-side from Country + State/Province
                      (never user-entered) — shown read-only whenever a lead has one. */}
                  <div className="field"><div className="lab">Region</div><div className="val">{lead.region || "—"}</div></div>
                  {/* Sales Territory — deliberately separate from Country/State/Region
                      above; server-defaulted from the owner's employee territory at
                      create time (see backend crm_service.create_lead()). Read-only. */}
                  <div className="field"><div className="lab">Sales territory</div><div className="val">{lead.territory || "—"}</div></div>
                  {isVisible("address") && (
                    <div className="field"><div className="lab">Address</div><div className="val">{lead.address || "—"}</div></div>
                  )}
                  {isVisible("description") && (
                    <div className="field"><div className="lab">Description</div><div className="val">{lead.description || "—"}</div></div>
                  )}
                  {isVisible("do_not_call") && (
                    <div className="field"><div className="lab">Do not call</div><div className="val">{lead.do_not_call ? "Yes" : "No"}</div></div>
                  )}
                  {isVisible("email_opt_out") && (
                    <div className="field"><div className="lab">Email opt out</div><div className="val">{lead.email_opt_out ? "Yes" : "No"}</div></div>
                  )}
                </div>
                {lead.can_edit && (
                  <RoleOnly roles={["SALES", "ACCOUNT_EXEC", "ADMIN"]}>
                    <button className="btn sm" style={{ marginTop: 18 }} onClick={openEditDetails}>Edit details</button>
                  </RoleOnly>
                )}
              </>
            )}
            {editingDetails && detailsDraft && (
              <>
                <div className="fields" style={{ gridTemplateColumns: "repeat(2, 1fr)" }}>
                  {isVisible("salutation") && (
                    <div className="field">
                      <div className="lab">Salutation</div>
                      <select className="inp" disabled={!isEditable("salutation")} value={detailsDraft.salutation} onChange={(e) => setDetailsDraft({ ...detailsDraft, salutation: e.target.value })}>
                        {SALUTATIONS.map((s) => <option key={s} value={s}>{s || "—"}</option>)}
                      </select>
                    </div>
                  )}
                  {isVisible("first_name") && (
                    <div className="field">
                      <div className="lab">First name</div>
                      <input className="inp" disabled={!isEditable("first_name")} value={detailsDraft.first_name} onChange={(e) => setDetailsDraft({ ...detailsDraft, first_name: e.target.value })} />
                    </div>
                  )}
                  {isVisible("last_name") && (
                    <div className="field">
                      <div className="lab">Last name <span className="req">*</span></div>
                      <input className="inp" disabled={!isEditable("last_name")} value={detailsDraft.last_name} onChange={(e) => setDetailsDraft({ ...detailsDraft, last_name: e.target.value })} />
                    </div>
                  )}
                  {isVisible("company_name") && (
                    <div className="field">
                      <div className="lab">Company <span className="req">*</span></div>
                      <input className="inp" disabled={!isEditable("company_name")} value={detailsDraft.company_name} onChange={(e) => setDetailsDraft({ ...detailsDraft, company_name: e.target.value })} />
                    </div>
                  )}
                  {isVisible("title") && (
                    <div className="field">
                      <div className="lab">Title</div>
                      <input className="inp" disabled={!isEditable("title")} value={detailsDraft.title} onChange={(e) => setDetailsDraft({ ...detailsDraft, title: e.target.value })} />
                    </div>
                  )}
                  {isVisible("rating") && (
                    <div className="field">
                      <div className="lab">Rating</div>
                      <select className="inp" disabled={!isEditable("rating")} value={detailsDraft.rating} onChange={(e) => setDetailsDraft({ ...detailsDraft, rating: e.target.value })}>
                        {RATINGS.map((r) => <option key={r} value={r}>{r || "—"}</option>)}
                      </select>
                    </div>
                  )}
                  {isVisible("contact_email") && (
                    <div className="field">
                      <div className="lab">Email <span className="req">*</span></div>
                      <input className="inp" type="email" disabled={!isEditable("contact_email")} value={detailsDraft.contact_email} onChange={(e) => setDetailsDraft({ ...detailsDraft, contact_email: e.target.value })} />
                    </div>
                  )}
                  {isVisible("contact_phone") && (
                    <div className="field">
                      <div className="lab">Phone</div>
                      <input className="inp" disabled={!isEditable("contact_phone")} value={detailsDraft.contact_phone} onChange={(e) => setDetailsDraft({ ...detailsDraft, contact_phone: e.target.value })} />
                    </div>
                  )}
                  {isVisible("mobile_phone") && (
                    <div className="field">
                      <div className="lab">Mobile</div>
                      <input className="inp" disabled={!isEditable("mobile_phone")} value={detailsDraft.mobile_phone} onChange={(e) => setDetailsDraft({ ...detailsDraft, mobile_phone: e.target.value })} />
                    </div>
                  )}
                  {isVisible("website") && (
                    <div className="field">
                      <div className="lab">Website</div>
                      <input
                        className="inp"
                        disabled={!isEditable("website")}
                        value={detailsDraft.website}
                        onChange={(e) => setDetailsDraft({ ...detailsDraft, website: e.target.value })}
                        placeholder="example.com"
                      />
                      {websiteError && <div className="help err">{websiteError}</div>}
                    </div>
                  )}
                  {isVisible("linkedin_url") && (
                    <div className="field">
                      <div className="lab">LinkedIn URL</div>
                      <input
                        className="inp"
                        disabled={!isEditable("linkedin_url")}
                        value={detailsDraft.linkedin_url}
                        onChange={(e) => setDetailsDraft({ ...detailsDraft, linkedin_url: e.target.value })}
                        placeholder="https://www.linkedin.com/in/..."
                      />
                    </div>
                  )}
                  {isVisible("industry") && (
                    <div className="field">
                      <div className="lab">Industry</div>
                      <input className="inp" disabled={!isEditable("industry")} value={detailsDraft.industry} onChange={(e) => setDetailsDraft({ ...detailsDraft, industry: e.target.value })} />
                    </div>
                  )}
                  {isVisible("annual_revenue") && (
                    <div className="field">
                      <div className="lab">Annual revenue</div>
                      <input className="inp" type="number" disabled={!isEditable("annual_revenue")} value={detailsDraft.annual_revenue} onChange={(e) => setDetailsDraft({ ...detailsDraft, annual_revenue: e.target.value })} />
                    </div>
                  )}
                  {isVisible("num_employees") && (
                    <div className="field">
                      <div className="lab">No. of employees</div>
                      <input className="inp" type="number" disabled={!isEditable("num_employees")} value={detailsDraft.num_employees} onChange={(e) => setDetailsDraft({ ...detailsDraft, num_employees: e.target.value })} />
                    </div>
                  )}
                  {isVisible("source") && (
                    <div className="field">
                      <div className="lab">Lead source</div>
                      <input className="inp" disabled={!isEditable("source")} value={detailsDraft.source} onChange={(e) => setDetailsDraft({ ...detailsDraft, source: e.target.value })} />
                    </div>
                  )}
                  {isVisible("account_id") && (
                    <div className="field">
                      <div className="lab">Account</div>
                      <select
                        className="inp"
                        disabled={!isEditable("account_id") || accounts === null}
                        value={detailsDraft.account_id}
                        onChange={(e) => selectAccount(e.target.value)}
                      >
                        <option value="">{accounts === null ? "Loading…" : "None"}</option>
                        <option value={NEW_ACCOUNT_OPTION}>+ New account…</option>
                        {accounts?.map((a) => (
                          <option key={a.id} value={a.id}>{a.legal_name} ({a.id})</option>
                        ))}
                      </select>
                      <div className="help">Selecting an existing account fills in the company fields below.</div>
                    </div>
                  )}
                  {isVisible("campaign_id") && (
                    <div className="field">
                      <div className="lab">Campaign</div>
                      <select
                        className="inp"
                        disabled={!isEditable("campaign_id")}
                        value={detailsDraft.campaign_id}
                        onChange={(e) => setDetailsDraft({ ...detailsDraft, campaign_id: e.target.value })}
                      >
                        <option value="">—</option>
                        {campaigns.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                      </select>
                    </div>
                  )}
                  {isVisible("country") && (
                    <div className="field">
                      <div className="lab">Country</div>
                      <CountrySelect
                        disabled={!isEditable("country")}
                        value={detailsDraft.country}
                        onChange={(country) => setDetailsDraft({ ...detailsDraft, country, state_province: "" })}
                      />
                    </div>
                  )}
                  {isVisible("state_province") && (
                    <div className="field">
                      <div className="lab">State/Province</div>
                      <StateProvinceSelect
                        country={detailsDraft.country}
                        disabled={!isEditable("state_province")}
                        value={detailsDraft.state_province}
                        onChange={(state_province) => setDetailsDraft({ ...detailsDraft, state_province })}
                      />
                    </div>
                  )}
                  {isVisible("address") && (
                    <div className="field" style={{ gridColumn: "1 / -1" }}>
                      <div className="lab">Address</div>
                      <input className="inp" disabled={!isEditable("address")} value={detailsDraft.address} onChange={(e) => setDetailsDraft({ ...detailsDraft, address: e.target.value })} />
                    </div>
                  )}
                  {isVisible("description") && (
                    <div className="field" style={{ gridColumn: "1 / -1" }}>
                      <div className="lab">Description</div>
                      <textarea className="inp" rows={3} disabled={!isEditable("description")} value={detailsDraft.description} onChange={(e) => setDetailsDraft({ ...detailsDraft, description: e.target.value })} />
                    </div>
                  )}
                  {isVisible("do_not_call") && (
                    <div className="field" style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8 }}>
                      <input type="checkbox" disabled={!isEditable("do_not_call")} checked={detailsDraft.do_not_call} onChange={(e) => setDetailsDraft({ ...detailsDraft, do_not_call: e.target.checked })} id="lead-detail-dnc" />
                      <label htmlFor="lead-detail-dnc" className="lab" style={{ margin: 0 }}>Do not call</label>
                    </div>
                  )}
                  {isVisible("email_opt_out") && (
                    <div className="field" style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8 }}>
                      <input type="checkbox" disabled={!isEditable("email_opt_out")} checked={detailsDraft.email_opt_out} onChange={(e) => setDetailsDraft({ ...detailsDraft, email_opt_out: e.target.checked })} id="lead-detail-optout" />
                      <label htmlFor="lead-detail-optout" className="lab" style={{ margin: 0 }}>Email opt out</label>
                    </div>
                  )}
                </div>
                {detailsError && <div className="help err" style={{ marginTop: 10 }}>{detailsError}</div>}
                <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
                  <button className="btn primary sm" onClick={saveDetails} disabled={isUpdating}>
                    {isUpdating ? "Saving…" : "Save"}
                  </button>
                  <button className="btn sm" onClick={() => setEditingDetails(false)} disabled={isUpdating}>Cancel</button>
                </div>
              </>
            )}
          </div>
        </div>
            ),
          },
          {
            id: "lead-cadence",
            label: "Cadence",
            content: (
              <>
                <LeadCadencePanel leadId={id} />
                <div style={{ marginTop: 16 }}>
                  <LeadActivityPanel
                    lead={lead}
                    onActivity={() => getLead(api, id).then(setLead).catch(() => {})}
                  />
                </div>
              </>
            ),
          },
          {
            id: "lead-signals",
            label: "Signals & NBA",
            content: <LeadSignalsPanel leadId={id} />,
          },
        ]}
      />
      <ConvertLeadModal
        lead={converting}
        onClose={() => setConverting(null)}
        onConverted={(converted) => {
          setLead(converted);
          setConverting(null);
        }}
      />
      <AssignOwnerModal
        open={showAssignOwner}
        currentOwnerId={lead.owner_employee_id}
        onClose={() => setShowAssignOwner(false)}
        onAssign={assignOwner}
      />
      <NewAccountModal
        open={showNewAccount}
        onClose={() => setShowNewAccount(false)}
        onCreated={(created, andNew) => {
          setAccounts((prev) => (prev ? [created, ...prev] : [created]));
          applyAccount(created);
          if (!andNew) setShowNewAccount(false);
        }}
      />
    </section>
  );
}
