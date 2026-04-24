const API_BASE = '/api'

interface RequestOptions {
  signal?: AbortSignal
}

async function request<T>(path: string, options?: RequestInit & RequestOptions): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

// All verbs accept an optional AbortSignal so callers can cancel in-flight
// requests (e.g. when navigating between frames on the Vision page) and avoid
// stale responses clobbering newer state.
export const api = {
  get: <T>(path: string, opts?: RequestOptions) =>
    request<T>(path, { signal: opts?.signal }),
  post: <T>(path: string, body: unknown, opts?: RequestOptions) =>
    request<T>(path, { method: 'POST', body: JSON.stringify(body), signal: opts?.signal }),
  put: <T>(path: string, body: unknown, opts?: RequestOptions) =>
    request<T>(path, { method: 'PUT', body: JSON.stringify(body), signal: opts?.signal }),
  patch: <T>(path: string, body: unknown, opts?: RequestOptions) =>
    request<T>(path, { method: 'PATCH', body: JSON.stringify(body), signal: opts?.signal }),
  delete: <T>(path: string, opts?: RequestOptions) =>
    request<T>(path, { method: 'DELETE', signal: opts?.signal }),
}
