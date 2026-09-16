// Thin fetch wrapper around the FastAPI sidecar (Section 10). The backend binds to a fixed
// localhost port (see apps/backend/app/config.py:BACKEND_PORT) — kept in sync here since the
// frontend has no way to read the Python file directly.
const BACKEND_PORT = 8756;
const BASE_URL = `http://127.0.0.1:${BACKEND_PORT}`;

export type TimeRange = "1D" | "7D" | "30D" | "6M" | "1Y";
export type SortKey = "change_pct" | "change_abs" | "volume";

export interface Top100Entry {
  rank: number;
  card_id: string;
  grade_id: string;
  start_price_eur: number;
  end_price_eur: number;
  change_pct: number;
  change_abs_eur: number;
  observation_count: number;
  name: string;
  name_en: string | null;
  number: string;
  language: string;
  image_local_path: string | null;
  grade_label: string;
  grading_company: string;
}

export interface SourceStatus {
  id: string;
  name: string;
  kind: string;
  is_free: number;
  last_status: string | null;
  last_started_at: string | null;
  last_finished_at: string | null;
  last_error: string | null;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`);
  if (!res.ok) {
    throw new Error(`${path} failed: ${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export function fetchTop100(params: {
  timeRange: TimeRange;
  sortKey?: SortKey;
  language?: string;
  minPriceEur?: number;
}): Promise<Top100Entry[]> {
  const query = new URLSearchParams({
    time_range: params.timeRange,
    sort_key: params.sortKey ?? "change_pct",
  });
  if (params.language) query.set("language", params.language);
  if (params.minPriceEur !== undefined) query.set("min_price_eur", String(params.minPriceEur));
  return get<Top100Entry[]>(`/top100?${query.toString()}`);
}

export function fetchSourceStatus(): Promise<SourceStatus[]> {
  return get<SourceStatus[]>("/sources/status");
}

export function fetchHealth(): Promise<{ status: string; time: string }> {
  return get("/health");
}

export function backendWsUrl(): string {
  return `ws://127.0.0.1:${BACKEND_PORT}/ws`;
}

export interface CardSearchResult {
  id: string;
  name: string;
  name_en: string | null;
  name_original: string | null;
  number: string;
  language: string;
  rarity: string | null;
  variant: string | null;
  image_source_url: string | null;
  set_name: string;
  set_language: string;
}

export function searchCards(q: string, limit = 60): Promise<CardSearchResult[]> {
  const query = new URLSearchParams({ q, limit: String(limit) });
  return get<CardSearchResult[]>(`/cards/search?${query.toString()}`);
}

export interface ReviewQueueItem {
  id: number;
  raw_title: string;
  confidence: number;
  status: string;
  created_at: string;
  candidate_card_id: string | null;
  candidate_grade_id: string | null;
  source_name: string;
}

export function fetchReviewQueue(): Promise<ReviewQueueItem[]> {
  return get<ReviewQueueItem[]>("/review-queue");
}

async function post<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, { method: "POST" });
  if (!res.ok) {
    throw new Error(`${path} failed: ${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export function confirmMatch(id: number): Promise<{ id: number; status: string }> {
  return post(`/review-queue/${id}/confirm`);
}

export function rejectMatch(id: number): Promise<{ id: number; status: string }> {
  return post(`/review-queue/${id}/reject`);
}

// GET never returns a stored secret's value (only whether one is set) — it lives in the macOS
// Keychain, not the plaintext settings file, and the backend doesn't echo it back over local
// HTTP on every read. PUT is write-only for it: send a new value to store one, an empty string
// to clear it, or omit the field entirely to leave it untouched.
export interface LocalSettings {
  scheduler_enabled?: boolean;
  pokemontcg_io_api_key_set?: boolean;
  top100_min_observations?: number;
  top100_min_price_eur?: number;
  [key: string]: unknown;
}

export interface LocalSettingsPatch extends Omit<LocalSettings, "pokemontcg_io_api_key_set"> {
  pokemontcg_io_api_key?: string;
}

export function fetchSettings(): Promise<LocalSettings> {
  return get<LocalSettings>("/settings");
}

export async function putSettings(payload: LocalSettingsPatch): Promise<LocalSettings> {
  const res = await fetch(`${BASE_URL}/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(`PUT /settings failed: ${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<LocalSettings>;
}
