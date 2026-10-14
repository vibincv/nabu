// Local API client. The token goes only in a header, never in a URL (API-6), which is also why
// server-sent events are read with fetch: EventSource cannot send headers.

import type { ReadEvent } from "./types";

const token = document.querySelector<HTMLMetaElement>('meta[name="nabu-token"]')?.content ?? "";

export const fixtureMode = token === "";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function send(path: string, init: RequestInit = {}): Promise<Response> {
  const res = await fetch(path, {
    ...init,
    credentials: "same-origin",
    cache: "no-store",
    referrerPolicy: "no-referrer",
    headers: { ...(init.headers ?? {}), "x-nabu-token": token },
  });
  if (!res.ok) {
    let message = `request failed (${res.status})`;
    try {
      message = ((await res.json()) as { error?: string }).error ?? message;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, message);
  }
  return res;
}

export async function api<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const init: RequestInit = { method };
  if (body !== undefined) {
    init.body = JSON.stringify(body);
    init.headers = { "content-type": "application/json" };
  }
  return (await (await send(path, init)).json()) as T;
}

export async function apiBlob(path: string): Promise<Blob> {
  return (await send(path)).blob();
}

/** Files are sent back to back with their names and sizes in a header (no multipart: the
 * server must never spool an upload to disk, FR-11.3). */
export async function uploadFiles(files: File[]): Promise<string> {
  const meta = files.map((f) => ({ name: f.name, size: f.size }));
  const res = await send("/api/documents", {
    method: "POST",
    body: new Blob(files),
    headers: { "x-nabu-files": JSON.stringify(meta), "content-type": "application/octet-stream" },
  });
  return ((await res.json()) as { document_id: string }).document_id;
}

export async function readEvents(docId: string, onEvent: (e: ReadEvent) => void): Promise<void> {
  const res = await send(`/api/documents/${encodeURIComponent(docId)}/events`);
  const reader = res.body?.getReader();
  if (!reader) return;
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    buffer += decoder.decode(value, { stream: true });
    let cut: number;
    while ((cut = buffer.indexOf("\n\n")) >= 0) {
      const chunk = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      for (const line of chunk.split("\n")) {
        if (line.startsWith("data: ")) onEvent(JSON.parse(line.slice(6)) as ReadEvent);
      }
    }
  }
}
