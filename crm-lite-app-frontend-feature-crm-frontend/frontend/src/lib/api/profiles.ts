import type { Api } from "./client";

/** Wire types for Profiles — admin-configurable RBAC bundles (see
 * admin_models.Profile on the backend). Replaces the old fixed 4-role
 * CAPABILITIES dict: which capability keys a profile grants now lives in
 * the role_capability table, edited via the endpoints below. */
export interface ProfileOut {
  id: number;
  code: string;
  display_name: string;
  is_system: boolean;
  /** Role Hierarchy: the profile this one reports to, or null if it's
   * top-level. Holding a profile grants visibility into records owned by
   * anyone holding a profile strictly beneath it in this tree. */
  parent_role_id: number | null;
}

export interface ProfileCreatePayload {
  code: string;
  display_name: string;
}

export interface ProfileUpdatePayload {
  display_name?: string;
  parent_role_id?: number | null;
}

export interface CapabilityEntry {
  key: string;
  description: string;
}

export interface ProfileCapabilities {
  capability_keys: string[];
}

export function listProfiles(api: Api): Promise<ProfileOut[]> {
  return api.get<ProfileOut[]>("/admin/profiles");
}

export function createProfile(api: Api, payload: ProfileCreatePayload): Promise<ProfileOut> {
  return api.post<ProfileOut>("/admin/profiles", payload);
}

export function updateProfile(api: Api, profileId: number, payload: ProfileUpdatePayload): Promise<ProfileOut> {
  return api.patch<ProfileOut>(`/admin/profiles/${profileId}`, payload);
}

export function deleteProfile(api: Api, profileId: number): Promise<void> {
  return api.del(`/admin/profiles/${profileId}`);
}

export function listCapabilities(api: Api): Promise<CapabilityEntry[]> {
  return api.get<CapabilityEntry[]>("/admin/capabilities");
}

export function getProfileCapabilities(api: Api, profileId: number): Promise<ProfileCapabilities> {
  return api.get<ProfileCapabilities>(`/admin/profiles/${profileId}/capabilities`);
}

export function saveProfileCapabilities(
  api: Api,
  profileId: number,
  capabilityKeys: string[]
): Promise<ProfileCapabilities> {
  return api.put<ProfileCapabilities>(`/admin/profiles/${profileId}/capabilities`, {
    capability_keys: capabilityKeys,
  });
}
