import type { Api } from "./client";

/** Wire types for Organization-Wide Defaults (src/models/crm_models.py
 * OrgWideDefault*, src/services/record_access_service.py). One row per
 * OWD-eligible object — PRIVATE/PUBLIC_READ_ONLY/PUBLIC_READ_WRITE. */
export const OWD_OBJECTS = ["LEAD", "ACCOUNT", "CONTACT", "OPPORTUNITY", "CAMPAIGN"] as const;
export type OwdObjectName = (typeof OWD_OBJECTS)[number];
export const OWD_ACCESS_LEVELS = ["PRIVATE", "PUBLIC_READ_ONLY", "PUBLIC_READ_WRITE"] as const;
export type OwdAccessLevel = (typeof OWD_ACCESS_LEVELS)[number];

export interface OrgWideDefaultsOut {
  defaults: Record<string, string>;
}

export interface OrgWideDefaultsSaveRequest {
  entries: { object_name: string; access_level: string }[];
}

export function getOrgWideDefaults(api: Api): Promise<OrgWideDefaultsOut> {
  return api.get<OrgWideDefaultsOut>("/org-wide-defaults");
}

export function saveOrgWideDefaults(
  api: Api,
  defaults: Record<string, string>
): Promise<OrgWideDefaultsOut> {
  const entries = Object.entries(defaults).map(([object_name, access_level]) => ({ object_name, access_level }));
  return api.put<OrgWideDefaultsOut>("/org-wide-defaults", { entries });
}
