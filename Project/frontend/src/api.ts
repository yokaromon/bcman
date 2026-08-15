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
  image_revision: string;
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
  card_owner_user_id?: string | null;
  exchanged_at?: string | null;
};

export type OrgMember = { id: string; name: string };

export type CardDetail = {
  id: string;
  status: CardStatus;
  image_url: string;
  image_revision: string;
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
export function cardImageUrl(cardId: string, revision: string): string {
  return `${API_BASE}/cards/${cardId}/image?v=${encodeURIComponent(revision)}`;
}

export function cardThumbnailUrl(cardId: string, revision: string): string {
  return `${API_BASE}/cards/${cardId}/thumbnail?v=${encodeURIComponent(revision)}`;
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
/** Card Owner（登録者）選択肢用。自分のOrganizationのUserを、管理者以外でも取得できる。 */
export function fetchMembers(): Promise<OrgMember[]> {
  return request<OrgMember[]>('/members');
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

/** 登録者(Card Owner)・名刺交換日(Exchanged At)の修正。確認(confirm)済みの名刺にのみ使える。 */
export function updateCardRegistration(
  cardId: string,
  body: { card_owner_user_id: string; exchanged_at: string },
): Promise<{ card_owner_user_id: string; exchanged_at: string }> {
  return request(`/cards/${cardId}/registration`, jsonInit('PUT', body));
}

export function reprocessCard(cardId: string): Promise<{ status: CardStatus }> {
  return request<{ status: CardStatus }>(`/cards/${cardId}/reprocess`, jsonInit('POST', { ocr: true, llm: true }));
}
export function setCardOrientation(cardId: string, rotation: number, reread = true): Promise<{ status: CardStatus; orientation: number }> {
  return request(`/cards/${cardId}/orientation`, jsonInit('POST', { rotation, reread }));
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

// --- 台帳（登録済み名刺の検索） ---

/** 1ページの件数。増やすほど初回表示は重くなる。 */
export const LEDGER_PAGE_SIZE = 50;
/** 入力が止まってから検索するまでの待ち時間(ms)。 */
export const LEDGER_SEARCH_DEBOUNCE_MS = 300;

export type LedgerEntry = {
  contact_id: string;
  card_id: string;
  status: CardStatus;
  image_revision: string;
  person_name: string | null;
  company_name: string | null;
  department: string | null;
  position: string | null;
  exchanged_at: string | null;
  card_owner: { id: string; name: string | null } | null;
};

export type LedgerPage = { total: number; items: LedgerEntry[] };

export function searchContacts(query: string, offset = 0, limit = LEDGER_PAGE_SIZE): Promise<LedgerPage> {
  const params = new URLSearchParams({ q: query, offset: String(offset), limit: String(limit) });
  return request<LedgerPage>(`/contacts?${params}`);
}

/** 検索結果を CardPager が扱う形にする。位置情報は台帳では使わないので持たない。 */
export function ledgerEntryToCard(entry: LedgerEntry): CardSummary {
  return {
    id: entry.card_id,
    status: entry.status,
    confidence: 0,
    image_revision: entry.image_revision,
    bounding_box: { x: 0, y: 0, width: 0, height: 0 },
  };
}

// --- 名刺画像の撮り直し。採用するまで既存の画像は変わらない ---

export type ReplacementDraft = { token: string; detected: boolean };

export async function startCardReplacement(cardId: string, file: File): Promise<ReplacementDraft> {
  const body = new FormData();
  body.append('file', file);
  return request<ReplacementDraft>(`/cards/${cardId}/replacement`, { method: 'POST', body });
}

export function cardReplacementPreviewUrl(cardId: string, token: string): string {
  return `${API_BASE}/cards/${cardId}/replacement/${token}`;
}

export function cancelCardReplacement(cardId: string, token: string): Promise<{ discarded: boolean }> {
  return request(`/cards/${cardId}/replacement/${token}`, { method: 'DELETE' });
}

export function applyCardReplacement(
  cardId: string,
  token: string,
  reread: boolean,
): Promise<{ status: CardStatus; image_revision: string }> {
  return request(`/cards/${cardId}/replacement/${token}/apply`, jsonInit('POST', { reread }));
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

// --- 名鑑（Person/Company/接点履歴） ---

export type TouchHistoryEntry = {
  contact_id: string;
  person_name: string | null;
  company_name: string | null;
  department: string | null;
  position: string | null;
  exchanged_at: string | null;
  card_owner: { id: string; name: string | null } | null;
};

export type PersonSummary = {
  id: string;
  display_name: string | null;
  display_company: string | null;
  contact_count: number;
  latest_exchanged_at: string | null;
};

export type PersonDetail = {
  id: string;
  display_name: string | null;
  display_company: string | null;
  touch_history: TouchHistoryEntry[];
};

export type CompanySummary = {
  id: string;
  display_name: string | null;
  person_count: number;
  latest_exchanged_at: string | null;
};

export type CompanyDetail = {
  id: string;
  display_name: string | null;
  touch_history: TouchHistoryEntry[];
};

export type MergeCandidate = {
  id: string;
  kind: 'person' | 'company';
  signal: string;
  signal_label: string;
  contact_id: string;
  contact_person_name: string | null;
  contact_company_name: string | null;
  target_id: string;
  target_display_name: string | null;
};

export function fetchPersons(): Promise<PersonSummary[]> {
  return request<PersonSummary[]>('/directory/persons');
}
export function fetchPerson(personId: string): Promise<PersonDetail> {
  return request<PersonDetail>(`/directory/persons/${personId}`);
}
export function splitPersonContact(personId: string, contactId: string): Promise<{ new_person_id: string }> {
  return request(`/directory/persons/${personId}/contacts/${contactId}/split`, { method: 'POST' });
}
export function fetchCompanies(): Promise<CompanySummary[]> {
  return request<CompanySummary[]>('/directory/companies');
}
export function fetchCompany(companyId: string): Promise<CompanyDetail> {
  return request<CompanyDetail>(`/directory/companies/${companyId}`);
}
export function splitCompanyContact(companyId: string, contactId: string): Promise<{ new_company_id: string }> {
  return request(`/directory/companies/${companyId}/contacts/${contactId}/split`, { method: 'POST' });
}
export function fetchMergeCandidates(): Promise<MergeCandidate[]> {
  return request<MergeCandidate[]>('/directory/merge-candidates');
}
export function acceptMergeCandidate(candidateId: string): Promise<{ status: string }> {
  return request(`/directory/merge-candidates/${candidateId}/accept`, { method: 'POST' });
}
export function dismissMergeCandidate(candidateId: string): Promise<{ status: string }> {
  return request(`/directory/merge-candidates/${candidateId}/dismiss`, { method: 'POST' });
}
