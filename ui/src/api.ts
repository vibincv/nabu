// Local API client. The token goes only in a header, never in a URL (API-6).

const token = document.querySelector<HTMLMetaElement>('meta[name="nabu-token"]')?.content ?? "";

export const fixtureMode = token === "";

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    ...init,
    credentials: "same-origin",
    cache: "no-store",
    referrerPolicy: "no-referrer",
    headers: { ...(init.headers ?? {}), "x-nabu-token": token, "content-type": "application/json" },
  });
  if (!res.ok) throw new Error(`request failed: ${res.status}`);
  return (await res.json()) as T;
}
