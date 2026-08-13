// CT101 が /bcman/ プレフィックスを剥がして CT113 へ渡すため、
// ブラウザから見た API のパスは常に /bcman/api で始まる。
const API_BASE = '/bcman/api';

export type Role = 'admin' | 'member';

export type Group = {
  id: string;
  name: string;
};

export type Me = {
  id: string;
  username: string;
  name: string;
  role: Role;
  organization_id: string;
  sharing_mode: string;
  groups: Group[];
};

export type LoginResult = { status: 'ok' | 'totp_required' };

export type OrgUser = {
  id: string;
  username: string;
  name: string;
  role: Role;
  groups: string[];
};

export type TrustedDevice = {
  id: string;
  label: string;
  created_at: string;
  last_used_at: string;
  expires_at: string;
  revoked: boolean;
};

export type PhotoSummary = {
  id: string;
  filename: string;
  status: PhotoStatus;
  created_at: string;
  card_count: number;
  confirmed_count: number;
  source_retained: boolean;
};

export type PhotoStatus = 'uploaded' | 'detecting' | 'detected' | 'completed' | 'failed';

export type CardStatus =
  | 'detected'
  | 'corrected'
  | 'ocr_processing'
  | 'ocr_completed'
  | 'llm_processing'
  | 'review_required'
  | 'confirmed'
  | 'retry_required';

export type CardSummary = {
  id: string;
  status: CardStatus;
  confidence: number;
  bounding_box: { x: number; y: number; width: number; height: number };
};

export const CONTACT_FIELDS = [
  'company_name',
  'company_name_kana',
  'department',
  'position',
  'person_name',
  'person_name_kana',
  'postal_code',
  'address',
  'telephone',
  'fax',
  'mobile',
  'email',
  'website',
  'notes',
] as const;

export type ContactField = (typeof CONTACT_FIELDS)[number];

export type ContactInput = Record<ContactField, string>;

/** サーバーが返す Contact は編集対象の項目に加えて id や confirmed 等も含む。 */
export type Contact = Partial<Record<ContactField, string | null>> & {
  id?: string;
  card_id?: string;
  confirmed?: boolean;
};

export type CardDetail = {
  id: string;
  status: CardStatus;
  image_url: string;
  contact: Contact | null;
  ocr_text: string;
  review_flags: Partial<Record<ContactField, string>>;
  orientation: number;
};

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function readErrorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === 'string') {
      return body.detail;
    }
  } catch {
    // JSON でないエラー応答（nginx の 413/502 等）はステータス行で代替する
  }
  return `${response.status} ${response.statusText}`;
}

/** 認証は Cookie（セッション）で行うため、ここではトークン等を一切扱わない。 */
async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { ...init, credentials: 'include' });
  if (!response.ok) {
    throw new ApiError(await readErrorMessage(response), response.status);
  }
  return (await response.json()) as T;
}

function jsonInit(method: string, body: unknown): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
}

/**
 * サーバーの CardDetail.image_url は "/api/..." を返すため、そのまま API_BASE に
 * 連結すると /bcman/api/api/... になる。画像URLはここで組み立てる。
 */
export function cardImageUrl(cardId: string): string {
  return `${API_BASE}/cards/${cardId}/image`;
}

export function cardThumbnailUrl(cardId: string): string {
  return `${API_BASE}/cards/${cardId}/thumbnail`;
}

export function photoThumbnailUrl(photoId: string): string {
  return `${API_BASE}/photos/${photoId}/thumbnail`;
}

// --- 認証 ---

export function login(username: string, password: string): Promise<LoginResult> {
  return request<LoginResult>('/auth/login', jsonInit('POST', { username, password }));
}
export function verifyTotp(code: string): Promise<{ status: string }> {
  return request<{ status: string }>('/auth/verify-totp', jsonInit('POST', { code }));
}
export function logout(): Promise<{ status: string }> {
  return request<{ status: string }>('/auth/logout', { method: 'POST' });
}
export function fetchMe(): Promise<Me> {
  return request<Me>('/auth/me');
}

// --- ユーザ・グループ・端末管理（Organization管理者のみ呼び出せる） ---

export function fetchOrgGroups(orgId: string): Promise<Group[]> {
  return request<Group[]>(`/organizations/${orgId}/groups`);
}
export function createOrgGroup(orgId: string, name: string): Promise<Group> {
  return request<Group>(`/organizations/${orgId}/groups`, jsonInit('POST', { name }));
}
export function fetchOrgUsers(orgId: string): Promise<OrgUser[]> {
  return request<OrgUser[]>(`/organizations/${orgId}/users`);
}
export function createOrgUser(
  orgId: string,
  body: { username: string; name: string; password: string; group_ids: string[]; role: Role },
): Promise<{ id: string; username: string; totp_provisioning_uri: string }> {
  return request(`/organizations/${orgId}/users`, jsonInit('POST', body));
}
export function resetUserPassword(orgId: string, userId: string, password: string): Promise<{ reset: boolean }> {
  return request(`/organizations/${orgId}/users/${userId}/password`, jsonInit('PUT', { password }));
}
export function resetUserTotp(orgId: string, userId: string): Promise<{ totp_provisioning_uri: string }> {
  return request(`/organizations/${orgId}/users/${userId}/reset-totp`, { method: 'POST' });
}
export function unlockUser(orgId: string, userId: string): Promise<{ unlocked: boolean }> {
  return request(`/organizations/${orgId}/users/${userId}/unlock`, { method: 'POST' });
}
export function fetchUserDevices(orgId: string, userId: string): Promise<TrustedDevice[]> {
  return request<TrustedDevice[]>(`/organizations/${orgId}/users/${userId}/devices`);
}
export function revokeDevice(orgId: string, deviceId: string): Promise<{ revoked: boolean }> {
  return request(`/organizations/${orgId}/devices/${deviceId}`, { method: 'DELETE' });
}

// --- 名刺 ---

export function fetchPhotos(): Promise<PhotoSummary[]> {
  return request<PhotoSummary[]>('/photos');
}

export async function uploadPhoto(groupId: string, file: File): Promise<string> {
  const body = new FormData();
  body.append('file', file);
  const result = await request<{ photo_id: string }>(`/photos?group_id=${encodeURIComponent(groupId)}`, {
    method: 'POST',
    body,
  });
  return result.photo_id;
}

export function startProcessing(photoId: string): Promise<{ status: string }> {
  return request<{ status: string }>(`/photos/${photoId}/process`, { method: 'POST' });
}

export function fetchCards(photoId: string): Promise<CardSummary[]> {
  return request<CardSummary[]>(`/photos/${photoId}/cards`);
}

export function fetchCard(cardId: string): Promise<CardDetail> {
  return request<CardDetail>(`/cards/${cardId}`);
}

export function saveContact(cardId: string, contact: ContactInput, resolvedFields: ContactField[] = []): Promise<Contact> {
  return request<Contact>(`/cards/${cardId}/contact`, jsonInit('PUT', { ...contact, resolved_fields: resolvedFields }));
}

export function confirmCard(cardId: string): Promise<{ status: string }> {
  return request<{ status: string }>(`/cards/${cardId}/confirm`, { method: 'POST' });
}

export function reprocessCard(cardId: string): Promise<{ status: CardStatus }> {
  return request<{ status: CardStatus }>(`/cards/${cardId}/reprocess`, jsonInit('POST', { ocr: true, llm: true }));
}
export function setCardOrientation(cardId: string, rotation: number): Promise<{ status: CardStatus; orientation: number }> {
  return request(`/cards/${cardId}/orientation`, jsonInit('POST', { rotation }));
}

export function deletePhoto(photoId: string): Promise<{ deleted: boolean }> {
  return request<{ deleted: boolean }>(`/photos/${photoId}`, { method: 'DELETE' });
}
export function completeReview(photoId: string, retainPhoto: boolean): Promise<{ source_retained: boolean }> {
  return request(`/photos/${photoId}/complete-review`, jsonInit('POST', { retain_photo: retainPhoto }));
}
export function addManualCard(photoId: string, corners: Array<[number, number]>): Promise<{ id: string; status: CardStatus }> {
  return request(`/photos/${photoId}/cards`, jsonInit('POST', { corners }));
}
export function confirmCards(photoId: string, cardIds: string[]): Promise<{ confirmed_count: number }> {
  return request(`/photos/${photoId}/confirm-cards`, jsonInit('POST', { card_ids: cardIds }));
}

export function deleteCard(cardId: string): Promise<{ deleted: boolean }> {
  return request<{ deleted: boolean }>(`/cards/${cardId}`, { method: 'DELETE' });
}

/** 確認画面に出せる状態か。これ以外は解析途中か失敗のいずれか。 */
export function isCardReady(status: CardStatus): boolean {
  return status === 'review_required' || status === 'confirmed' || status === 'retry_required';
}

export function emptyContactInput(): ContactInput {
  const values = {} as ContactInput;
  for (const field of CONTACT_FIELDS) {
    values[field] = '';
  }
  return values;
}

export function toContactInput(contact: Contact | null): ContactInput {
  const values = emptyContactInput();
  if (!contact) {
    return values;
  }
  for (const field of CONTACT_FIELDS) {
    values[field] = contact[field] ?? '';
  }
  return values;
}

const CARD_STATUS_LABELS: Record<CardStatus, string> = {
  detected: '検出済み',
  corrected: '解析待ち',
  ocr_processing: '文字を読み取り中',
  ocr_completed: '読み取り完了',
  llm_processing: '内容を整理中',
  review_required: '確認できます',
  confirmed: '登録済み',
  retry_required: '要再試行',
};

export function cardStatusLabel(status: CardStatus): string {
  return CARD_STATUS_LABELS[status] ?? status;
}
