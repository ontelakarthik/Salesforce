"use client";

import { useState, useTransition } from "react";
import Modal from "../Modal";
import { ApiError, useApi } from "@/lib/api/client";
import { createAccount, type AccountOut } from "@/lib/api/crm";
import { useFieldPermissions } from "@/lib/api/fieldPermissions";
import { useAppDispatch } from "@/lib/hooks";
import { showToast } from "@/lib/features/toastSlice";
import {
  AccountFormFields,
  BLANK_ACCOUNT_DRAFT,
  accountDraftToPayload,
  validateAccountDraft,
} from "./account/AccountFormFields";

export default function NewAccountModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  /** andNew=true means the modal stays open (Save & New) — don't navigate away on this call. */
  onCreated: (account: AccountOut, andNew: boolean) => void;
}) {
  const api = useApi();
  const dispatch = useAppDispatch();
  const { isVisible, isEditable } = useFieldPermissions("ACCOUNT");
  const [draft, setDraft] = useState(BLANK_ACCOUNT_DRAFT);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [isPending, startTransition] = useTransition();

  function reset() {
    setDraft(BLANK_ACCOUNT_DRAFT);
    setErrors({});
  }

  function close() {
    reset();
    onClose();
  }

  function submit(andNew: boolean) {
    const e = validateAccountDraft(draft);
    setErrors(e);
    if (Object.keys(e).length > 0) return;

    startTransition(async () => {
      try {
        const created = await createAccount(api, accountDraftToPayload(draft));
        dispatch(showToast("Account saved successfully."));
        onCreated(created, andNew);
        if (andNew) {
          reset();
        } else {
          close();
        }
      } catch (err) {
        if (err instanceof ApiError && err.fields) {
          const fieldErrors: Record<string, string> = {};
          for (const f of err.fields) {
            const key = String(f.loc[f.loc.length - 1]);
            fieldErrors[key] = f.msg;
          }
          setErrors(fieldErrors);
        } else {
          setErrors({ legal_name: err instanceof ApiError ? err.message : "Failed to create account." });
        }
      }
    });
  }

  return (
    <Modal
      open={open}
      onClose={close}
      title="New Account"
      footer={
        <>
          <button className="btn sm" onClick={close} disabled={isPending}>Cancel</button>
          <div className="spacer" />
          <button className="btn sm" onClick={() => submit(true)} disabled={isPending}>Save &amp; New</button>
          <button className="btn primary sm" onClick={() => submit(false)} disabled={isPending}>
            {isPending ? "Saving…" : "Save"}
          </button>
        </>
      }
    >
      <div className="fields" style={{ gridTemplateColumns: "repeat(2, 1fr)" }}>
        <AccountFormFields
          draft={draft}
          setDraft={setDraft}
          errors={errors}
          isVisible={isVisible}
          isEditable={isEditable}
          autoFocusLegalName
        />
        <div className="help" style={{ gridColumn: "1 / -1" }}>New accounts always start as Prospect — use &quot;Promote to client&quot; on the account page once a SOW is signed.</div>
      </div>
    </Modal>
  );
}
