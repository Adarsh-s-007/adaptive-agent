/**
 * Typed API client. Owner: P1.
 * Adds the bearer token and turns the error envelope into ApiError.
 * The access token lives in memory only (blueprint 12.5), never in storage.
 */

export const API_BASE_URL: string =
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

let accessToken = "";
export function setAccessToken(token: string) {
  accessToken = token;
}
export function hasAccessToken() {
  return accessToken !== "";
}

export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
    public requestId?: string,
    public details?: Record<string, unknown>,
  ) {
    super(message);
  }
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        ...(init.headers || {}),
      },
    });
  } catch {
    throw new ApiError("NETWORK", "Cannot reach the ProjectPulse API.", 0);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const err = body?.error ?? {};
    throw new ApiError(
      err.code ?? "HTTP_" + response.status,
      err.message ?? `Request failed (HTTP ${response.status}).`,
      response.status,
      err.request_id ?? response.headers.get("x-request-id") ?? undefined,
      err.details,
    );
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

export const api = {
  get: <T>(path: string) => request<T>(`/api/v1${path}`),
  post: <T>(path: string, body?: unknown) =>
    request<T>(`/api/v1${path}`, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
  health: () => request<Health>("/health"),
};

export type DepStatus = "ok" | "degraded" | "down";
export type Health = { status: string; db: DepStatus; hindsight: DepStatus; groq: DepStatus };
