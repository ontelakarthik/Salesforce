"use client";

import { useState, useTransition } from "react";
import RoleOnly from "../../RoleOnly";
import Badge from "../../Badge";
import { ApiError, useApi } from "@/lib/api/client";
import {
  addContact,
  deleteContact,
  updateContact,
  type ContactCreatePayload,
  type ContactOut,
} from "@/lib/api/crm";
import { CONTACT_TYPES, EMAIL_RE, initialsFor } from "./mock";

const BLANK_CONTACT: ContactCreatePayload = {
  full_name: "",
  contact_type: "",
  salutation: "",
  email: "",
  phone: "",
  mobile_phone: "",
  home_phone: "",
  other_phone: "",
  title: "",
  department: "",
  birthdate: "",
  assistant_name: "",
  assistant_phone: "",
  lead_source: "",
  address: "",
  other_address: "",
  description: "",
  is_primary: false,
  is_distribution_list: false,
};

const SALUTATIONS = ["", "Mr.", "Ms.", "Mrs.", "Dr.", "Prof."];

const AVATAR_COLORS = ["#2F5FA6", "#6D45B8", "#B45309", "#0E8A7D", "#64748B"];

function avatarColor(contactId: string): string {
  let hash = 0;
  for (let i = 0; i < contactId.length; i++) hash = (hash * 31 + contactId.charCodeAt(i)) | 0;
  return AVATAR_COLORS[Math.abs(hash) % AVATAR_COLORS.length];
}

function validate(d: ContactCreatePayload): Record<string, string> {
  const e: Record<string, string> = {};
  if (!d.full_name.trim()) e.full_name = "Full name is required.";
  if (!d.contact_type) e.contact_type = "Contact type is required.";
  if (!d.email?.trim()) e.email = "Email is required.";
  else if (!EMAIL_RE.test(d.email.trim())) e.email = "Enter a valid email address.";
  return e;
}

export default function ContactsPanel({
  accountId,
  initialContacts,
}: {
  accountId: string;
  initialContacts: ContactOut[];
}) {
  const api = useApi();
  const [contacts, setContacts] = useState<ContactOut[]>(initialContacts);
  const [open, setOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<ContactCreatePayload>(BLANK_CONTACT);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [isPending, startTransition] = useTransition();
  const [rowError, setRowError] = useState<{ id: string; message: string } | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  function remove(c: ContactOut) {
    if (!window.confirm(`Delete the contact "${c.full_name}"? This can't be undone.`)) return;
    setDeletingId(c.id);
    setRowError(null);
    deleteContact(api, c.id)
      .then(() => setContacts((prev) => prev.filter((existing) => existing.id !== c.id)))
      .catch((err: unknown) => {
        setRowError({ id: c.id, message: err instanceof ApiError ? err.message : "Failed to delete contact." });
      })
      .finally(() => setDeletingId(null));
  }

  function openAdd() {
    setEditingId(null);
    setDraft(BLANK_CONTACT);
    setErrors({});
    setOpen(true);
  }

  function openEdit(c: ContactOut) {
    setEditingId(c.id);
    setDraft({
      full_name: c.full_name,
      contact_type: c.contact_type,
      salutation: c.salutation ?? "",
      email: c.email ?? "",
      phone: c.phone ?? "",
      mobile_phone: c.mobile_phone ?? "",
      home_phone: c.home_phone ?? "",
      other_phone: c.other_phone ?? "",
      title: c.title ?? "",
      department: c.department ?? "",
      birthdate: c.birthdate ?? "",
      assistant_name: c.assistant_name ?? "",
      assistant_phone: c.assistant_phone ?? "",
      lead_source: c.lead_source ?? "",
      address: c.address ?? "",
      other_address: c.other_address ?? "",
      description: c.description ?? "",
      is_primary: c.is_primary,
      is_distribution_list: c.is_distribution_list,
    });
    setErrors({});
    setOpen(true);
  }

  function save() {
    const e = validate(draft);
    setErrors(e);
    if (Object.keys(e).length > 0) return;

    startTransition(async () => {
      try {
        if (editingId) {
          const updated = await updateContact(api, editingId, draft);
          setContacts((prev) => prev.map((c) => (c.id === editingId ? updated : c)));
        } else {
          const created = await addContact(api, accountId, draft);
          setContacts((prev) => [...prev, created]);
        }
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
          setErrors({ full_name: err instanceof ApiError ? err.message : "Failed to save contact." });
        }
      }
    });
  }

  return (
    <div className="card">
      <div className="card-head">
        <h3>Contacts</h3>
        <div className="spacer" />
        <RoleOnly roles={["SALES", "ACCOUNT_EXEC", "ADMIN"]}>
          <button className="btn sm" onClick={openAdd}>Add contact</button>
        </RoleOnly>
      </div>

      {open && (
        <div className="card-pad" style={{ borderBottom: "1px solid var(--border)" }}>
          <div className="fields" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
            <div className="field">
              <div className="lab">Salutation</div>
              <select className="inp" value={draft.salutation ?? ""} onChange={(e) => setDraft({ ...draft, salutation: e.target.value })}>
                {SALUTATIONS.map((s) => <option key={s} value={s}>{s || "—"}</option>)}
              </select>
            </div>
            <div className="field" style={{ gridColumn: "span 2" }}>
              <div className="lab">Full name <span className="req">*</span></div>
              <input className="inp" value={draft.full_name} onChange={(e) => setDraft({ ...draft, full_name: e.target.value })} />
              {errors.full_name && <div className="help err">{errors.full_name}</div>}
            </div>
            <div className="field">
              <div className="lab">Contact type <span className="req">*</span></div>
              <select className="inp" value={draft.contact_type} onChange={(e) => setDraft({ ...draft, contact_type: e.target.value })}>
                <option value="">Select…</option>
                {CONTACT_TYPES.map((t) => (
                  <option key={t} value={t.toUpperCase()}>{t}</option>
                ))}
              </select>
              {errors.contact_type && <div className="help err">{errors.contact_type}</div>}
            </div>
            <div className="field">
              <div className="lab">Title</div>
              <input className="inp" value={draft.title ?? ""} onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
            </div>
            <div className="field">
              <div className="lab">Department</div>
              <input className="inp" value={draft.department ?? ""} onChange={(e) => setDraft({ ...draft, department: e.target.value })} />
            </div>
            <div className="field">
              <div className="lab">Email <span className="req">*</span></div>
              <input className="inp" value={draft.email ?? ""} onChange={(e) => setDraft({ ...draft, email: e.target.value })} />
              {errors.email && <div className="help err">{errors.email}</div>}
            </div>
            <div className="field">
              <div className="lab">Phone</div>
              <input className="inp" value={draft.phone ?? ""} onChange={(e) => setDraft({ ...draft, phone: e.target.value })} />
            </div>
            <div className="field">
              <div className="lab">Mobile</div>
              <input className="inp" value={draft.mobile_phone ?? ""} onChange={(e) => setDraft({ ...draft, mobile_phone: e.target.value })} />
            </div>
            <div className="field">
              <div className="lab">Home phone</div>
              <input className="inp" value={draft.home_phone ?? ""} onChange={(e) => setDraft({ ...draft, home_phone: e.target.value })} />
            </div>
            <div className="field">
              <div className="lab">Other phone</div>
              <input className="inp" value={draft.other_phone ?? ""} onChange={(e) => setDraft({ ...draft, other_phone: e.target.value })} />
            </div>
            <div className="field">
              <div className="lab">Birthdate</div>
              <input type="date" className="inp" value={draft.birthdate ?? ""} onChange={(e) => setDraft({ ...draft, birthdate: e.target.value })} />
            </div>
            <div className="field">
              <div className="lab">Lead source</div>
              <input className="inp" value={draft.lead_source ?? ""} onChange={(e) => setDraft({ ...draft, lead_source: e.target.value })} />
            </div>
            <div className="field">
              <div className="lab">Assistant name</div>
              <input className="inp" value={draft.assistant_name ?? ""} onChange={(e) => setDraft({ ...draft, assistant_name: e.target.value })} />
            </div>
            <div className="field">
              <div className="lab">Assistant phone</div>
              <input className="inp" value={draft.assistant_phone ?? ""} onChange={(e) => setDraft({ ...draft, assistant_phone: e.target.value })} />
            </div>
            <div className="field" style={{ gridColumn: "1 / -1" }}>
              <div className="lab">Mailing address</div>
              <input className="inp" value={draft.address ?? ""} onChange={(e) => setDraft({ ...draft, address: e.target.value })} />
            </div>
            <div className="field" style={{ gridColumn: "1 / -1" }}>
              <div className="lab">Other address</div>
              <input className="inp" value={draft.other_address ?? ""} onChange={(e) => setDraft({ ...draft, other_address: e.target.value })} />
            </div>
            <div className="field" style={{ gridColumn: "1 / -1" }}>
              <div className="lab">Description</div>
              <textarea className="inp" rows={2} value={draft.description ?? ""} onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
            </div>
            <div className="field">
              <div className="lab">Is distribution list</div>
              <select
                className="inp"
                value={draft.is_distribution_list ? "yes" : "no"}
                onChange={(e) => {
                  const isDl = e.target.value === "yes";
                  setDraft({ ...draft, is_distribution_list: isDl, is_primary: isDl ? false : draft.is_primary });
                }}
              >
                <option value="no">No</option>
                <option value="yes">Yes</option>
              </select>
              <div className="help">DLs can&apos;t be set as primary; phone is optional.</div>
            </div>
            <div className="field">
              <div className="lab">Is primary</div>
              <select
                className="inp"
                disabled={draft.is_distribution_list}
                value={draft.is_primary ? "yes" : "no"}
                onChange={(e) => setDraft({ ...draft, is_primary: e.target.value === "yes" })}
              >
                <option value="no">No</option>
                <option value="yes">Yes</option>
              </select>
              {draft.is_primary && <div className="help">This clears the primary flag on any existing primary contact.</div>}
            </div>
          </div>
          <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
            <button className="btn primary sm" onClick={save} disabled={isPending}>
              {isPending ? "Saving…" : "Save contact"}
            </button>
            <button className="btn sm" onClick={() => setOpen(false)} disabled={isPending}>Cancel</button>
          </div>
        </div>
      )}

      <table>
        <thead>
          <tr><th>Name</th><th>Type</th><th>Email</th><th>Phone</th><th>Primary</th><th></th></tr>
        </thead>
        <tbody>
          {contacts.map((c) => (
            <tr key={c.id}>
              <td
                className={c.can_edit ? "person clickable" : "person"}
                onClick={() => c.can_edit && openEdit(c)}
              >
                <span className="avatar-sm" style={{ background: avatarColor(c.id) }}>{initialsFor(c.full_name)}</span><span className="t-strong">{c.full_name}</span>
              </td>
              <td><Badge variant={c.is_distribution_list ? "teal" : "gray"}>{c.is_distribution_list ? "Distribution list" : c.contact_type}</Badge></td>
              <td>{c.email}</td>
              <td>{c.phone || <span className="empty-hint">— n/a</span>}</td>
              <td>{c.is_primary && <Badge variant="green">Primary</Badge>}</td>
              <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                {c.can_delete && (
                  <RoleOnly roles={["SALES", "ACCOUNT_EXEC", "ADMIN"]}>
                    <button className="btn sm" disabled={deletingId === c.id} onClick={() => remove(c)}>
                      {deletingId === c.id ? "Deleting…" : "Delete"}
                    </button>
                  </RoleOnly>
                )}
                {rowError?.id === c.id && <div className="help err">{rowError.message}</div>}
              </td>
            </tr>
          ))}
          {contacts.length === 0 && (
            <tr>
              <td colSpan={6} className="empty-hint" style={{ padding: "26px 22px" }}>No contacts yet.</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
