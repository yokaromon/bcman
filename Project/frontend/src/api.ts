// CT101 が /bcman/ プレフィックスを剥がして CT113 へ渡すため、
// ブラウザから見た API のパスは常に /bcman/api で始まる。
const API_BASE = '/bcman/api';

export type Role = 'system_admin' | 'org_admin' | 'member';

export type User = {
  id: string;
  name: string;
  role: Role;
  organization_id: string | null;
  group_id: string | null;
};

export type Organization = {
  id: string;
  name: string;
  sharing_mode: string;
};

export type Group = {
  id: string;
  organization_id: string;
  name: string;
};

export type BootstrapData = {
  users: User[];
  organizations: Organization[];
  groups: Group[];
};

export type PhotoSummary = {
  id: string;
  filename: string;
  status: PhotoStatus;
  created_at: string;
  card_count: number;
  confirmed_count: number;
};

export type PhotoStatus = 'uploaded' | 'detecting' | 'detected' | 'completed' | 'failed';

export type CardStatus =
  | 'detected'
  | 'corrected'
  | 'ocr_processing'
  | 'ocr_completed'
  | 'llm_processing'
  | 'review_required'
  | 'confirmed';

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

async function request<T>(path: string, userId: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { ...((init.headers as Record<string, string>) ?? {}) };
  if (userId) {
    headers['X-User-Id'] = userId;
  }

  const response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!response.ok) {
    throw new ApiError(await readErrorMessage(response), response.status);
  }
  return (await response.json()) as T;
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

export function fetchBootstrap(): Promise<BootstrapData> {
  return request<BootstrapData>('/bootstrap', '');
}

export function fetchPhotos(userId: string): Promise<PhotoSummary[]> {
  return request<PhotoSummary[]>('/photos', userId);
}

export async function uploadPhoto(userId: string, file: File): Promise<string> {
  const body = new FormData();
  body.append('file', file);
  const result = await request<{ photo_id: string }>('/photos', userId, { method: 'POST', body });
  return result.photo_id;
}

export function startProcessing(userId: string, photoId: string): Promise<{ status: string }> {
  return request<{ status: string }>(`/photos/${photoId}/process`, userId, { method: 'POST' });
}

export function fetchCards(userId: string, photoId: string): Promise<CardSummary[]> {
  return request<CardSummary[]>(`/photos/${photoId}/cards`, userId);
}

export function fetchCard(userId: string, cardId: string): Promise<CardDetail> {
  return request<CardDetail>(`/cards/${cardId}`, userId);
}

export function saveContact(userId: string, cardId: string, contact: ContactInput): Promise<Contact> {
  return request<Contact>(`/cards/${cardId}/contact`, userId, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(contact),
  });
}

export function confirmCard(userId: string, cardId: string): Promise<{ status: string }> {
  return request<{ status: string }>(`/cards/${cardId}/confirm`, userId, { method: 'POST' });
}

export function reprocessCard(userId: string, cardId: string): Promise<{ status: CardStatus }> {
  return request<{ status: CardStatus }>(`/cards/${cardId}/reprocess`, userId, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ocr: true, llm: true }),
  });
}

export function deletePhoto(userId: string, photoId: string): Promise<{ deleted: boolean }> {
  return request<{ deleted: boolean }>(`/photos/${photoId}`, userId, { method: 'DELETE' });
}

export function deleteCard(userId: string, cardId: string): Promise<{ deleted: boolean }> {
  return request<{ deleted: boolean }>(`/cards/${cardId}`, userId, { method: 'DELETE' });
}

/** 確認画面に出せる状態か。これ以外は解析途中か失敗のいずれか。 */
export function isCardReady(status: CardStatus): boolean {
  return status === 'review_required' || status === 'confirmed';
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
};

export function cardStatusLabel(status: CardStatus): string {
  return CARD_STATUS_LABELS[status] ?? status;
}
