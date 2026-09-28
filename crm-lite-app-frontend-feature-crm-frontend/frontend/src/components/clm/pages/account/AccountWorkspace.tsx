"use client";

import { useState, useTransition, type ReactNode } from "react";
import RoleOnly from "../../RoleOnly";
import Tabs from "../../Tabs";
import OverviewPanel from "./OverviewPanel";
import AssignmentsPanel from "./AssignmentsPanel";
import ContactsPanel from "./ContactsPanel";
import CommsPanel from "./CommsPanel";
import NewOpportunityModal from "../NewOpportunityModal";
import { ApiError, useApi } from "@/lib/api/client";
import { promoteAccount, type ContactOut, type AccountOut, type OpportunityOut } from "@/lib/api/crm";
import type { AgreementOut } from "@/lib/api/contracts";
import type { CommunicationOut } from "@/lib/api/activity";
import type { AssetOut } from "@/lib/api/delivery";

export default function AccountWorkspace({
  accountId,
  account,
  canPromote,
  onPromoted,
  agreements,
  projectsCount,
  opportunitiesCount,
  contactsInitial,
  commsInitial,
  agreementsTabContent,
  projectsTabContent,
  opportunitiesTabContent,
  assetsTabContent,
  onOpportunityCreated,
  renewingAsset,
  onRenewalHandled,
}: {
  accountId: string;
  account: AccountOut;
  canPromote: boolean;
  onPromoted: (account: AccountOut) => void;
  agreements: AgreementOut[];
  projectsCount: number;
  opportunitiesCount: number;
  contactsInitial: ContactOut[];
  commsInitial: CommunicationOut[];
  agreementsTabContent: ReactNode;
  projectsTabContent: ReactNode;
  opportunitiesTabContent: ReactNode;
  assetsTabContent: ReactNode;
  onOpportunityCreated: (opportunity: OpportunityOut) => void;
  /** Set by the Assets tab's "Start renewal" button — opens the same
   * New Opportunity modal, pre-wired to that Asset. */
  renewingAsset: AssetOut | null;
  onRenewalHandled: () => void;
}) {
  const api = useApi();
  const [activeTab, setActiveTab] = useState("c-overview");
  const [editingOverview, setEditingOverview] = useState(false);
  const [showNewOpportunity, setShowNewOpportunity] = useState(false);
  const [promoteError, setPromoteError] = useState<string | null>(null);
  const [isPromoting, startPromoting] = useTransition();

  function openOverviewEdit() {
    setActiveTab("c-overview");
    setEditingOverview(true);
  }

  function handlePromote() {
    setPromoteError(null);
    startPromoting(async () => {
      try {
        onPromoted(await promoteAccount(api, accountId));
      } catch (err) {
        setPromoteError(err instanceof ApiError ? err.message : "Failed to promote account.");
      }
    });
  }

  return (
    <>
      <div className="card card-pad" style={{ marginBottom: 20 }}>
        <div className="kpi-row">
          <div className="kpi"><span className="l">Active projects:</span> <span className="n">{projectsCount}</span></div>
          <div className="kpi"><span className="l">Agreements:</span> <span className="n">{agreements.length}</span></div>
          <div className="kpi"><span className="l">Opportunities:</span> <span className="n">{opportunitiesCount}</span></div>
          {account.promoted_to_client_at && (
            <div className="kpi">
              <span className="l">Converted:</span>{" "}
              <span className="n">{new Date(account.promoted_to_client_at).toLocaleDateString("en-US", { month: "short", year: "numeric" })}</span>
            </div>
          )}
        </div>
        <RoleOnly roles={["SALES", "ACCOUNT_EXEC", "ADMIN"]}>
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 14 }}>
            <button className="btn sm" onClick={openOverviewEdit}>Edit</button>
            <button className="btn sm" onClick={() => setShowNewOpportunity(true)}>Start opportunity</button>
            <button
              className="btn sm"
              disabled={!canPromote || isPromoting}
              title={canPromote ? undefined : "Available once the first SOW is signed."}
              style={!canPromote ? { opacity: 0.5, cursor: "not-allowed" } : undefined}
              onClick={handlePromote}
            >
              {isPromoting ? "Promoting…" : "Promote to client"}
            </button>
            {promoteError && <span className="help err">{promoteError}</span>}
          </div>
        </RoleOnly>
      </div>

      <Tabs
        activeId={activeTab}
        onChange={setActiveTab}
        tabs={[
          {
            id: "c-overview",
            label: "Overview",
            content: (
              <>
                <OverviewPanel
                  accountId={accountId}
                  initialAccount={account}
                  editing={editingOverview}
                  onEditingChange={setEditingOverview}
                />
                <AssignmentsPanel accountId={accountId} />
              </>
            ),
          },
          { id: "c-contacts", label: "Contacts", content: <ContactsPanel accountId={accountId} initialContacts={contactsInitial} /> },
          { id: "c-opportunities", label: "Opportunities", content: opportunitiesTabContent },
          { id: "c-agreements", label: "Agreements", content: agreementsTabContent },
          { id: "c-projects", label: "Projects", content: projectsTabContent },
          { id: "c-assets", label: "Assets", content: assetsTabContent },
          { id: "c-comms", label: "Communications", content: <CommsPanel accountId={accountId} initialComms={commsInitial} /> },
        ]}
      />
      <NewOpportunityModal
        open={showNewOpportunity || renewingAsset !== null}
        onClose={() => {
          setShowNewOpportunity(false);
          onRenewalHandled();
        }}
        accountId={accountId}
        originatingAssetId={renewingAsset?.id}
        onCreated={(created, andNew) => {
          onOpportunityCreated(created);
          setActiveTab("c-opportunities");
          onRenewalHandled();
          if (!andNew) setShowNewOpportunity(false);
        }}
      />
    </>
  );
}
