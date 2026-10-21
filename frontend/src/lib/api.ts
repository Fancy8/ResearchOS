export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
  ) {
    super(message);
  }
}

export type Envelope<T> = {
  data: T;
  meta?: { has_more: boolean; next_cursor: string | null };
};

export function csrfToken() {
  if (typeof document === "undefined") return "";
  const cookie = document.cookie
    .split("; ")
    .find((entry) => entry.startsWith("researchos_csrf="));
  return cookie ? decodeURIComponent(cookie.split("=").slice(1).join("=")) : "";
}

export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<Envelope<T>> {
  const method = options.method ?? "GET";
  const response = await fetch(`/api/v1${path}`, {
    ...options,
    credentials: "same-origin",
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      ...(method !== "GET" ? { "X-CSRF-Token": csrfToken() } : {}),
      ...options.headers,
    },
  });
  const payload = await response.json();
  if (!response.ok)
    throw new ApiError(
      response.status,
      payload.error?.code ?? "REQUEST_FAILED",
      payload.error?.message ?? "操作失败，请重试",
      payload.error?.details,
    );
  return payload;
}

export function write<T>(
  path: string,
  method: string,
  body: unknown,
  key?: string,
) {
  return api<T>(path, {
    method,
    body: JSON.stringify(body),
    headers: key ? { "Idempotency-Key": key } : {},
  });
}
