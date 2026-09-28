"use client";

import { useEffect, useState, useTransition } from "react";
import Modal from "./Modal";
import { ApiError } from "@/lib/api/client";
import { useEmployeeDirectory } from "@/lib/api/identity";

/** Generic "who owns this record" reassignment modal — used by Lead,
 * Account, and Opportunity detail pages. `onAssign` does the actual
 * updateX(api, id, {owner_employee_id}) call for whichever entity is
 * open, so this component stays entity-agnostic. */
export default function AssignOwnerModal({
  open,
  currentOwnerId,
  onClose,
  onAssign,
}: {
  open: boolean;
  currentOwnerId: string | null;
  onClose: () => void;
  onAssign: (ownerId: string | null) => Promise<void>;
}) {
  const { entries } = useEmployeeDirectory();
  const [selected, setSelected] = useState(currentOwnerId ?? "");
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    if (open) {
      setSelected(currentOwnerId ?? "");
      setError(null);
    }
  }, [open, currentOwnerId]);

  function submit() {
    startTransition(async () => {
      try {
        await onAssign(selected || null);
        onClose();
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to assign owner.");
      }
    });
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Assign owner"
      footer={
        <>
          <button className="btn sm" onClick={onClose} disabled={isPending}>Cancel</button>
          <div className="spacer" />
          <button className="btn primary sm" onClick={submit} disabled={isPending}>
            {isPending ? "Saving…" : "Save"}
          </button>
        </>
      }
    >
      <div className="fields" style={{ gridTemplateColumns: "1fr" }}>
        <div className="field">
          <div className="lab">Owner</div>
          <select className="inp" value={selected} onChange={(e) => setSelected(e.target.value)} autoFocus>
            <option value="">Unassigned</option>
            {entries.map((e) => (
              <option key={e.id} value={e.id}>{e.full_name}</option>
            ))}
          </select>
        </div>
        {error && <div className="help err">{error}</div>}
      </div>
    </Modal>
  );
}
