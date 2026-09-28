import { Icon } from "./icons";

/** Shown in place of a list page's entire body when the backend rejects the
 * load with FORBIDDEN (no Object Permissions "Read" grant for this profile)
 * — replaces the page shell + a raw "Profile not permitted for 'x.read'"
 * error line with a clean, actionable message. The nav item for this page
 * is also hidden for such a profile (see data.ts's NavItem.capability /
 * Panel.tsx) — this is the fallback for a stale link, bookmark, or direct
 * URL visit that gets here anyway. */
export default function AccessDenied({ what }: { what: string }) {
  return (
    <section className="page active">
      <div className="card card-pad" style={{ marginTop: 20, display: "flex", gap: 14, alignItems: "flex-start" }}>
        <div style={{ color: "var(--t-muted, #6b7280)" }}>
          <Icon name="alertTriangle" />
        </div>
        <div>
          <div style={{ fontWeight: 600, marginBottom: 6 }}>No access to {what}</div>
          <div className="t-muted">
            Your profile doesn&apos;t have permission to view {what.toLowerCase()}. Ask an administrator to grant
            Read access in Object Permissions.
          </div>
        </div>
      </div>
    </section>
  );
}
