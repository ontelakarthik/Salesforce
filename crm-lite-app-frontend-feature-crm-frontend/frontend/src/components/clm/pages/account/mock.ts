import type { BadgeVariant } from "../../Badge";

export type AccountType = "PROSPECT" | "CLIENT" | "PARTNER" | "VENDOR";

export const ACCOUNT_TYPE_LABEL: Record<AccountType, string> = {
  PROSPECT: "Prospect",
  CLIENT: "Client",
  PARTNER: "Partner",
  VENDOR: "Vendor",
};

export const ACCOUNT_TYPE_BADGE: Record<AccountType, BadgeVariant> = {
  PROSPECT: "blue",
  CLIENT: "green",
  PARTNER: "teal",
  VENDOR: "gray",
};

export const CONTACT_TYPES = ["Business", "Legal", "Procurement", "Finance", "Technical"];
export const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
export const URL_RE = /^(https?:\/\/)?[\w-]+(\.[\w-]+)+([/?#].*)?$/i;

export function formatDate(value: string | null): string {
  if (!value) return "—";
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return new Date(value).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
  }
  return value;
}

export function initialsFor(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  return (parts[0][0] + (parts[1]?.[0] ?? "")).toUpperCase();
}
