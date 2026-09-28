"use client";

import { useEffect, useState, useTransition } from "react";
import Badge from "../Badge";
import DataTable, { TableLink, type DataTableColumn } from "../DataTable";
import Modal from "../Modal";
import RoleOnly from "../RoleOnly";
import Spinner from "../Spinner";
import { ApiError, useApi } from "@/lib/api/client";
import { createCadenceTemplate, listCadenceTemplates, type CadenceTemplateOut } from "@/lib/api/cadence";

function templateHref(template: CadenceTemplateOut): string {
  return `/admin/cadence-templates/${template.id}`;
}

const COLUMNS: DataTableColumn<CadenceTemplateOut>[] = [
  {
    key: "name",
    label: "Name",
    sortable: true,
    sortValue: (t) => t.name,
    render: (t) => <TableLink href={templateHref(t)}>{t.name}</TableLink>,
  },
  {
    key: "description",
    label: "Description",
    className: "t-muted",
    render: (t) => t.description ?? "—",
  },
  {
    key: "steps",
    label: "Steps",
    className: "num",
    sortable: true,
    sortValue: (t) => t.steps.length,
    render: (t) => t.steps.length,
  },
  {
    key: "status",
    label: "Status",
    render: (t) => <Badge variant={t.is_active ? "green" : "gray"}>{t.is_active ? "Active" : "Inactive"}</Badge>,
  },
];

export default function CadenceTemplates() {
  const api = useApi();
  const [templates, setTemplates] = useState<CadenceTemplateOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setTemplates(null);
    setError(null);
    listCadenceTemplates(api)
      .then((data) => {
        if (!cancelled) setTemplates(data);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Failed to load sales cadences.");
      });
    return () => {
      cancelled = true;
    };
  }, [api]);

  return (
    <section className="page active">
      <div className="pagehead">
        <div>
          <h1>Sales Cadences</h1>
          <div className="sub">Configured outreach sequences leads get enrolled into</div>
        </div>
        <div className="spacer" />
        <RoleOnly roles={["ADMIN"]}>
          <button className="btn primary" onClick={() => setShowNew(true)}>New cadence</button>
        </RoleOnly>
      </div>
      {error && <div className="help err" style={{ margin: "12px 0" }}>{error}</div>}
      {templates === null && !error ? (
        <div className="card card-pad loading-inline"><Spinner /> Loading…</div>
      ) : (
        <DataTable
          columns={COLUMNS}
          rows={templates ?? []}
          rowKey={(t) => t.id}
          rowHref={templateHref}
          searchPlaceholder="Search cadence name..."
          searchValue={(t) => `${t.name} ${t.description ?? ""}`}
        />
      )}
      <NewTemplateModal
        open={showNew}
        onClose={() => setShowNew(false)}
        onCreated={(created) => setTemplates((prev) => (prev ? [...prev, created] : [created]))}
      />
    </section>
  );
}

function NewTemplateModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (template: CadenceTemplateOut) => void;
}) {
  const api = useApi();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  function reset() {
    setName("");
    setDescription("");
    setError(null);
  }

  function close() {
    reset();
    onClose();
  }

  function submit() {
    if (!name.trim()) {
      setError("Name is required.");
      return;
    }
    startTransition(async () => {
      try {
        const created = await createCadenceTemplate(api, {
          name: name.trim(),
          description: description.trim() || undefined,
        });
        onCreated(created);
        close();
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to create cadence.");
      }
    });
  }

  return (
    <Modal
      open={open}
      onClose={close}
      title="New cadence"
      footer={
        <>
          <button className="btn sm" onClick={close} disabled={isPending}>Cancel</button>
          <div className="spacer" />
          <button className="btn primary sm" onClick={submit} disabled={isPending}>{isPending ? "Saving…" : "Save"}</button>
        </>
      }
    >
      <div className="fields" style={{ gridTemplateColumns: "1fr" }}>
        <div className="field">
          <div className="lab">Name <span className="req">*</span></div>
          <input className="inp" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
        </div>
        <div className="field">
          <div className="lab">Description</div>
          <textarea className="inp" rows={3} value={description} onChange={(e) => setDescription(e.target.value)} />
        </div>
        {error && <div className="help err">{error}</div>}
      </div>
    </Modal>
  );
}
