import type { Api } from "./client";

/** Wire types for user-based Record Sharing (src/models/crm_models.py
 * RecordShare* / src/services/record_access_service.py). READ|EDIT only —
 * never DELETE, and only ever ADDS access on top of OWD/ownership. */
export const SHAREABLE_OBJECTS = ["LEAD", "ACCOUNT", "CONTACT", "OPPORTUNITY", "CAMPAIGN"] as const;
export type ShareableObjectName = (typeof SHAREABLE_OBJECTS)[number];
export const RECORD_SHARE_ACCESS_LEVELS = ["READ", "EDIT"] as const;
export type RecordShareAccessLevel = (typeof RECORD_SHARE_ACCESS_LEVELS)[number];

export interface RecordShareOut {
  id: string;
  object_name: string;
  record_id: string;
  shared_with_employee_id: string;
  access_level: string;
  granted_by: string | null;
  granted_at: string;
}

export interface RecordShareCreatePayload {
  object_name: string;
  record_id: string;
  shared_with_employee_id: string;
  access_level: string;
}

export function listRecordShares(api: Api, objectName: string, recordId: string): Promise<RecordShareOut[]> {
  return api.get<RecordShareOut[]>("/record-shares", { object_name: objectName, record_id: recordId });
}

export function createRecordShare(api: Api, payload: RecordShareCreatePayload): Promise<RecordShareOut> {
  return api.post<RecordShareOut>("/record-shares", payload);
}

export function deleteRecordShare(api: Api, shareId: string): Promise<void> {
  return api.del(`/record-shares/${shareId}`);
}
