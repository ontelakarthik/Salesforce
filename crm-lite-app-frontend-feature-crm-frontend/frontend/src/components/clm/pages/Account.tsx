"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Badge, { type BadgeVariant } from "../Badge";
import ClickableRow from "../ClickableRow";
import RoleOnly from "../RoleOnly";
import Spinner from "../Spinner";
import { Icon } from "../icons";
import AccountWorkspace from "./account/AccountWorkspace";
import NewAgreementModal from "./NewAgreementModal";
import AssignOwnerModal from "../AssignOwnerModal";
import { ApiError, useApi } from "@/lib/api/client";
import { useEmployeeDirectory } from "@/lib/api/identity";
import { useAppSelector } from "@/lib/hooks";
import {
  deleteAccount,
  getAccount,
  listContacts,
  listOpportunities,
  promoteAccount,
  updateAccount,
  type ContactOut,
  type AccountOut,
  type OpportunityOut,
} from "@/lib/api/crm";
import { listAgreements, type AgreementOut } from "@/lib/api/contracts";
import { listProjects, type ProjectOut } from "@/lib/api/project";
import { listAccountCommunications, type CommunicationOut } from "@/lib/api/activity";
import { listAssets, type AssetOut } from "@/lib/api/delivery";

const STAGE_BADGE: Record<string, BadgeVariant> = {
  NEW: "gray",
  QUALIFIED: "blue",
  PROPOSAL: "amber",
  NEGOTIATION: "blue",
  WON: "green",
  LOST: "gray",
};

const AGREEMENT_TYPE_BADGE: Record<string, BadgeVariant> = {
  SOW: "violet",
  MSA: "blue",
  NDA: "blue",
  VENDOR_MSA: "blue",
  PURCHASE_ORDER: "gray",
};

const AGREEMENT_STATUS_BADGE: Record<string, BadgeVariant> = {
  DRAFT: "gray",
  REVIEW: "amber",
  APPROVED: "blue",
  SENT: "amber",
  SIGNED: "green",
  EXPIRED: "red",
  SUPERSEDED: "gray",
};

const PROJECT_STATUS_BADGE: Record<string, BadgeVariant> = {
  PLANNING: "blue",
  ACTIVE: "green",
  CLOSED: "gray",
};

function formatDate(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

export default function Account({ id }: { id: string }) {
  const api = useApi();
  const { label: employeeLabel } = useEmployeeDirectory();
  const role = useAppSelector((state) => state.role.value);
  const canEditAccount = (["SALES", "ACCOUNT_EXEC", "ADMIN"] as string[]).includes(role);
  const router = useRouter();
  const [account, setAccount] = useState<AccountOut | null>(null);
  const [showAssignOwner, setShowAssignOwner] = useState(false);
  const [contacts, setContacts] = useState<ContactOut[]>([]);
  const [agreements, setAgreements] = useState<AgreementOut[]>([]);
  const [projects, setProjects] = useState<ProjectOut[]>([]);
  const [opportunities, setOpportunities] = useState<OpportunityOut[]>([]);
  const [comms, setComms] = useState<CommunicationOut[]>([]);
  const [assets, setAssets] = useState<AssetOut[]>([]);
  const [renewingAsset, setRenewingAsset] = useState<AssetOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setAccount(null);
    setError(null);
    Promise.all([
      getAccount(api, id),
      listContacts(api, id),
      listAgreements(api),
      listProjects(api),
      listOpportunities(api),
      listAccountCommunications(api, id),
      listAssets(api, id),
    ])
      .then(([accountData, contactsData, allAgreements, allProjects, allOpportunities, commsData, assetsData]) => {
        if (cancelled) return;
        setAccount(accountData);
        setContacts(contactsData);
        setAgreements(allAgreements.filter((a) => a.account_id === id));
        setProjects(allProjects.filter((p) => p.account_id === id));
        setOpportunities(allOpportunities.filter((o) => o.account_id === id));
        setComms(commsData);
        setAssets(assetsData);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Failed to load account.");
      });
    return () => {
      cancelled = true;
    };
  }, [api, id]);

  if (error) {
    return (
      <section className="page active">
        <div className="help err">{error}</div>
      </section>
    );
  }

  if (!account) {
    return (
      <section className="page active">
        <div className="card card-pad loading-inline"><Spinner /> Loading account…</div>
      </section>
    );
  }

  const hasSignedSow = agreements.some((a) => a.agreement_type === "SOW" && a.status === "SIGNED");
  const isProspect = account.account_type === "PROSPECT";
  const canPromote = isProspect && hasSignedSow;

  function goBack() {
    if (typeof window !== "undefined" && window.history.length > 1) router.back();
    else router.push("/accounts");
  }

  async function assignOwner(ownerId: string | null) {
    const updated = await updateAccount(api, id, { owner_employee_id: ownerId });
    setAccount(updated);
  }

  function remove() {
    if (!account) return;
    if (!window.confirm(`Delete the account "${account.legal_name}"? This can't be undone.`)) return;
    setIsDeleting(true);
    setDeleteError(null);
    deleteAccount(api, account.id)
      .then(() => router.push("/accounts"))
      .catch((err: unknown) => {
        setDeleteError(err instanceof ApiError ? err.message : "Failed to delete account.");
        setIsDeleting(false);
      });
  }

  return (
    <section className="page active">
      <div className="banner">
        <button type="button" onClick={goBack} className="banner-back" aria-label="Go back" title="Go back">
          <Icon name="chevronLeft" />
        </button>
        <div>
          <div className="id">{id}</div>
          <h1>{account.legal_name ? account.legal_name.replace(/ Pvt\. Ltd\.$/, "") : "—"}</h1>
        </div>
        <div className="spacer" />
        {account.account_type === "CLIENT" && account.promoted_to_client_at && (
          <span className="badge">
            Client since{" "}
            {new Date(account.promoted_to_client_at).toLocaleDateString("en-US", { month: "short", year: "numeric" })}
          </span>
        )}
        {account.industry && (
          <span className="badge">
            <span className="dot" />
            {account.industry}
          </span>
        )}
        <RoleOnly roles={["SALES", "ACCOUNT_EXEC", "ADMIN"]}>
          <button
            className="badge"
            style={{ cursor: "pointer", border: "none", marginLeft: 10 }}
            onClick={() => setShowAssignOwner(true)}
          >
            Owner · {employeeLabel(account.owner_employee_id)} · Change
          </button>
        </RoleOnly>
        {!canEditAccount && <span className="badge">Owner · {employeeLabel(account.owner_employee_id)}</span>}
        {account.can_delete && (
          <RoleOnly roles={["ADMIN"]}>
            <button className="btn sm" style={{ marginLeft: 10 }} disabled={isDeleting} onClick={remove}>
              {isDeleting ? "Deleting…" : "Delete"}
            </button>
          </RoleOnly>
        )}
      </div>
      {deleteError && <div className="help err" style={{ margin: "0 0 14px" }}>{deleteError}</div>}

      <AccountWorkspace
        accountId={id}
        account={account}
        canPromote={canPromote}
        onPromoted={setAccount}
        agreements={agreements}
        projectsCount={projects.length}
        opportunitiesCount={opportunities.length}
        contactsInitial={contacts}
        commsInitial={comms}
        agreementsTabContent={
          <AgreementsTab
            agreements={agreements}
            accountId={id}
            onCreated={(a) => setAgreements((prev) => [a, ...prev])}
          />
        }
        projectsTabContent={<ProjectsTab projects={projects} />}
        opportunitiesTabContent={<OpportunitiesTab opportunities={opportunities} />}
        assetsTabContent={<AssetsTab assets={assets} onStartRenewal={setRenewingAsset} />}
        renewingAsset={renewingAsset}
        onRenewalHandled={() => setRenewingAsset(null)}
        onOpportunityCreated={(o) => {
          setOpportunities((prev) => [o, ...prev]);
          if (o.originating_asset_id) {
            setAssets((prev) => prev.map((a) => (a.id === o.originating_asset_id
              ? { ...a, renewed_by_opportunity_id: o.id } : a)));
          }
        }}
      />
      <AssignOwnerModal
        open={showAssignOwner}
        currentOwnerId={account.owner_employee_id}
        onClose={() => setShowAssignOwner(false)}
        onAssign={assignOwner}
      />
    </section>
  );
}

function AgreementsTab({
  agreements,
  accountId,
  onCreated,
}: {
  agreements: AgreementOut[];
  accountId: string;
  onCreated: (agreement: AgreementOut) => void;
}) {
  const [showNew, setShowNew] = useState(false);
  return (
    <div className="card">
      <div className="card-head">
        <h3>Agreements</h3>
        <div className="spacer" />
        <RoleOnly roles={["ACCOUNT_EXEC", "ADMIN"]}>
          <button className="btn sm" onClick={() => setShowNew(true)}>
            <Icon name="plus" />
            New agreement
          </button>
        </RoleOnly>
      </div>
      <table>
        <thead>
          <tr><th>Reference</th><th>Type</th><th>Status</th><th>Effective</th><th>Expiry</th></tr>
        </thead>
        <tbody>
          {agreements.map((a) => (
            <ClickableRow key={a.id} href={`/agreements/${a.id}`}>
              <td className="t-strong">{a.id}</td>
              <td><Badge variant={AGREEMENT_TYPE_BADGE[a.agreement_type] ?? "gray"}>{a.agreement_type}</Badge></td>
              <td><Badge variant={AGREEMENT_STATUS_BADGE[a.status] ?? "gray"}>{a.status}</Badge></td>
              <td className={!a.effective_date ? "empty-hint" : undefined}>{formatDate(a.effective_date)}</td>
              <td className={!a.expiry_date ? "empty-hint" : undefined}>{formatDate(a.expiry_date)}</td>
            </ClickableRow>
          ))}
          {agreements.length === 0 && (
            <tr>
              <td colSpan={5} className="empty-hint" style={{ padding: "18px 22px" }}>No agreements yet.</td>
            </tr>
          )}
        </tbody>
      </table>
      <NewAgreementModal
        open={showNew}
        onClose={() => setShowNew(false)}
        accountId={accountId}
        onCreated={onCreated}
      />
    </div>
  );
}

function OpportunitiesTab({ opportunities }: { opportunities: OpportunityOut[] }) {
  return (
    <div className="card">
      <div className="card-head"><h3>Opportunities</h3></div>
      <table>
        <thead>
          <tr><th>Reference</th><th>Name</th><th>Stage</th><th>Value</th></tr>
        </thead>
        <tbody>
          {opportunities.map((o) => (
            <ClickableRow key={o.id} href={`/opportunities/${o.id}`}>
              <td className="t-strong">{o.id}</td>
              <td>{o.name}</td>
              <td><Badge variant={STAGE_BADGE[o.stage] ?? "gray"}>{o.stage}</Badge></td>
              <td className="num">{o.estimated_value != null ? `${o.currency ?? "USD"} ${o.estimated_value.toLocaleString()}` : "—"}</td>
            </ClickableRow>
          ))}
          {opportunities.length === 0 && (
            <tr>
              <td colSpan={4} className="empty-hint" style={{ padding: "18px 22px" }}>No opportunities yet.</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function AssetsTab({ assets, onStartRenewal }: { assets: AssetOut[]; onStartRenewal: (asset: AssetOut) => void }) {
  return (
    <div className="card">
      <div className="card-head">
        <h3>Assets</h3>
        <div className="spacer" />
        <span className="help" style={{ margin: 0 }}>What this account owns as a result of delivery</span>
      </div>
      <table>
        <thead>
          <tr><th>Name</th><th>Status</th><th></th></tr>
        </thead>
        <tbody>
          {assets.map((a) => (
            <tr key={a.id}>
              <td className="t-strong">{a.name}</td>
              <td><Badge variant={a.status === "ACTIVE" ? "green" : "gray"}>{a.status}</Badge></td>
              <td style={{ textAlign: "right" }}>
                <RoleOnly roles={["SALES", "ACCOUNT_EXEC", "ADMIN"]}>
                  {a.renewed_by_opportunity_id ? (
                    <a className="btn sm" href={`/opportunities/${a.renewed_by_opportunity_id}`}>
                      View renewal
                    </a>
                  ) : (
                    <button className="btn sm" onClick={() => onStartRenewal(a)}>Start renewal</button>
                  )}
                </RoleOnly>
              </td>
            </tr>
          ))}
          {assets.length === 0 && (
            <tr>
              <td colSpan={3} className="empty-hint" style={{ padding: "18px 22px" }}>
                No assets yet — created automatically the first time a SOW milestone is invoiced.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function ProjectsTab({ projects }: { projects: ProjectOut[] }) {
  return (
    <div className="card">
      <div className="card-head"><h3>Projects</h3></div>
      <table>
        <thead>
          <tr><th>Reference</th><th>Name</th><th>Status</th></tr>
        </thead>
        <tbody>
          {projects.map((p) => (
            <ClickableRow key={p.id} href={`/projects/${p.id}`}>
              <td className="t-strong">{p.id}</td>
              <td>{p.name}</td>
              <td><Badge variant={PROJECT_STATUS_BADGE[p.status] ?? "gray"}>{p.status}</Badge></td>
            </ClickableRow>
          ))}
          {projects.length === 0 && (
            <tr>
              <td colSpan={3} className="empty-hint" style={{ padding: "18px 22px" }}>No projects yet.</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
