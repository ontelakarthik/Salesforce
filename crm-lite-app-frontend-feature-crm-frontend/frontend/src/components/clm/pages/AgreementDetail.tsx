"use client";

import { useEffect, useState } from "react";
import { ApiError, useApi } from "@/lib/api/client";
import { getAgreement, type AgreementOut } from "@/lib/api/contracts";
import { getAccount, type AccountOut } from "@/lib/api/crm";
import Spinner from "../Spinner";
import Nda from "./Nda";
import Sow from "./Sow";

/**
 * Fetches the agreement once and dispatches to the right detail layout by
 * its real `agreement_type` — real agreement ids (e.g. "AGR-00001") don't
 * embed the type the way the old mock ids did ("AGR-2026-SOW-00113"), so
 * this can't be determined from the id string alone.
 */
export default function AgreementDetail({ id }: { id: string }) {
  const api = useApi();
  const [agreement, setAgreement] = useState<AgreementOut | null>(null);
  const [account, setAccount] = useState<AccountOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional: fetch/reset state when inputs change
    setAgreement(null);
    setError(null);
    getAgreement(api, id)
      .then((a) => {
        if (cancelled) return;
        setAgreement(a);
        return getAccount(api, a.account_id).then((c) => {
          if (!cancelled) setAccount(c);
        });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Failed to load agreement.");
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

  if (!agreement || !account) {
    return (
      <section className="page active">
        <div className="card card-pad loading-inline"><Spinner /> Loading agreement…</div>
      </section>
    );
  }

  return agreement.agreement_type === "SOW" ? (
    <Sow agreement={agreement} account={account} onAgreementChange={setAgreement} />
  ) : (
    <Nda agreement={agreement} account={account} onAgreementChange={setAgreement} />
  );
}
