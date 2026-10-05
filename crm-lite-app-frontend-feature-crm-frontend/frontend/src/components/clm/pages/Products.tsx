"use client";

import { useEffect, useState, useTransition } from "react";
import Badge from "../Badge";
import Modal from "../Modal";
import RoleOnly from "../RoleOnly";
import Spinner from "../Spinner";
import { ApiError, useApi } from "@/lib/api/client";
import {
  createProduct,
  deleteProduct,
  listProducts,
  updateProduct,
  type ProductOut,
} from "@/lib/api/crm";

export default function Products() {
  const api = useApi();
  const [rows, setRows] = useState<ProductOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [editing, setEditing] = useState<ProductOut | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  function load() {
    setRows(null);
    setError(null);
    listProducts(api)
      .then(setRows)
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : "Failed to load the product catalog.");
      });
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional: fetch/reset state when inputs change
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api]);

  function remove(product: ProductOut) {
    if (!window.confirm(`Delete "${product.name}"? This can't be undone.`)) return;
    setDeletingId(product.id);
    deleteProduct(api, product.id)
      .then(() => setRows((prev) => (prev ?? []).filter((p) => p.id !== product.id)))
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : "Failed to delete product.");
      })
      .finally(() => setDeletingId(null));
  }

  return (
    <section className="page active">
      <div className="pagehead">
        <div>
          <h1>Product Catalog</h1>
          <div className="sub">What we sell — AI-drafted emails and call prep match a lead against this</div>
        </div>
        <RoleOnly roles={["ADMIN"]}>
          <button className="btn primary" onClick={() => setShowNew(true)}>New product</button>
        </RoleOnly>
      </div>
      {error && <div className="help err" style={{ margin: "12px 0" }}>{error}</div>}
      {rows === null && !error ? (
        <div className="card card-pad loading-inline"><Spinner /> Loading…</div>
      ) : (
        <div className="card">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Description</th>
                <th>Target industry</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {(rows ?? []).map((product) => (
                <tr key={product.id}>
                  <td>{product.name}</td>
                  <td className="t-muted">{product.description}</td>
                  <td className="mono">{product.target_industry ?? "Any"}</td>
                  <td><Badge variant={product.is_active ? "green" : "gray"}>{product.is_active ? "Active" : "Inactive"}</Badge></td>
                  <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                    <RoleOnly roles={["ADMIN"]}>
                      <button className="btn sm" onClick={() => setEditing(product)}>Edit</button>{" "}
                      <button
                        className="btn sm"
                        disabled={deletingId === product.id}
                        onClick={() => remove(product)}
                      >
                        {deletingId === product.id ? "Deleting…" : "Delete"}
                      </button>
                    </RoleOnly>
                  </td>
                </tr>
              ))}
              {rows?.length === 0 && (
                <tr>
                  <td colSpan={5} className="empty-hint">No products configured yet.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      <ProductModal
        mode="new"
        open={showNew}
        product={null}
        onClose={() => setShowNew(false)}
        onSaved={(created) => setRows((prev) => (prev ? [...prev, created] : [created]))}
      />
      <ProductModal
        mode="edit"
        open={editing !== null}
        product={editing}
        onClose={() => setEditing(null)}
        onSaved={(updated) => setRows((prev) => (prev ?? []).map((p) => (p.id === updated.id ? updated : p)))}
      />
    </section>
  );
}

function ProductModal({
  mode,
  open,
  product,
  onClose,
  onSaved,
}: {
  mode: "new" | "edit";
  open: boolean;
  product: ProductOut | null;
  onClose: () => void;
  onSaved: (product: ProductOut) => void;
}) {
  const api = useApi();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [targetIndustry, setTargetIndustry] = useState("");
  const [isActive, setIsActive] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    if (!open) return;
    if (mode === "edit" && product) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional: fetch/reset state when inputs change
      setName(product.name);
      setDescription(product.description);
      setTargetIndustry(product.target_industry ?? "");
      setIsActive(product.is_active);
    } else {
      setName("");
      setDescription("");
      setTargetIndustry("");
      setIsActive(true);
    }
    setError(null);
  }, [open, mode, product]);

  function submit() {
    if (!name.trim()) {
      setError("Name is required.");
      return;
    }
    if (!description.trim()) {
      setError("Description is required — this is what the AI matches leads against.");
      return;
    }
    startTransition(async () => {
      try {
        const payload = {
          name: name.trim(),
          description: description.trim(),
          target_industry: targetIndustry.trim() || null,
        };
        const saved =
          mode === "edit" && product
            ? await updateProduct(api, product.id, { ...payload, is_active: isActive })
            : await createProduct(api, payload);
        onSaved(saved);
        onClose();
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to save product.");
      }
    });
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={mode === "edit" ? `Edit ${product?.name ?? "product"}` : "New product"}
      footer={
        <>
          <button className="btn sm" onClick={onClose} disabled={isPending}>Cancel</button>
          <div className="spacer" />
          <button className="btn primary sm" onClick={submit} disabled={isPending}>{isPending ? "Saving…" : "Save"}</button>
        </>
      }
    >
      <div className="fields" style={{ gridTemplateColumns: "1fr 1fr" }}>
        <div className="field" style={{ gridColumn: "1 / -1" }}>
          <div className="lab">Name <span className="req">*</span></div>
          <input className="inp" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
        </div>
        <div className="field" style={{ gridColumn: "1 / -1" }}>
          <div className="lab">Description <span className="req">*</span></div>
          <textarea
            className="inp"
            rows={3}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="What it does and who it's for — this is what AI drafting reads to match a lead."
          />
        </div>
        <div className="field">
          <div className="lab">Target industry</div>
          <input
            className="inp"
            value={targetIndustry}
            onChange={(e) => setTargetIndustry(e.target.value)}
            placeholder="Leave blank for any industry"
          />
        </div>
        {mode === "edit" && (
          <div className="field">
            <label className="val" style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} />
              Active
            </label>
          </div>
        )}
        {error && <div className="help err" style={{ gridColumn: "1 / -1" }}>{error}</div>}
      </div>
    </Modal>
  );
}
