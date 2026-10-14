// What the review window talks to: the local API (live), or the bundled synthetic fixture
// (fixture mode, used for development and the M5 demo; no network at all).

import fixture from "@fixtures/working_result.sample.json";
import { api, apiBlob, readEvents, uploadFiles } from "./api";
import type { Field, Header, PageInfo, ReadEvent, VerifySummary, WorkingResult } from "./types";

export interface Backend {
  readonly live: boolean;
  current(): Promise<{ document_id: string | null; state: string | null }>;
  upload(files: File[]): Promise<string>;
  events(id: string, onEvent: (e: ReadEvent) => void): Promise<void>;
  result(id: string): Promise<WorkingResult>;
  pageImage(id: string, n: number): Promise<Blob | null>;
  editField(id: string, fieldId: string, body: Record<string, unknown>): Promise<Field>;
  addField(id: string, body: { name: string; page: number; box: number[] }): Promise<Field>;
  setTranslation(id: string, termId: string, english: string): Promise<Field>;
  setHeader(id: string, body: Partial<Header>): Promise<Header>;
  reorder(id: string, order: number[]): Promise<WorkingResult>;
  verify(id: string): Promise<VerifySummary>;
  save(id: string): Promise<void>;
  output(id: string): Promise<Blob>;
  close(id: string): Promise<void>;
}

const doc = (id: string) => `/api/documents/${encodeURIComponent(id)}`;

export const liveBackend: Backend = {
  live: true,
  current: () => api(`/api/documents`),
  upload: uploadFiles,
  events: readEvents,
  result: (id) => api<WorkingResult>(doc(id)),
  pageImage: async (id, n) => {
    try {
      return await apiBlob(`${doc(id)}/pages/${n}.png`);
    } catch {
      return null; // office and text files have no page image (AD-15)
    }
  },
  editField: (id, fieldId, body) => api<Field>(`${doc(id)}/fields/${encodeURIComponent(fieldId)}`, "PATCH", body),
  addField: (id, body) => api<Field>(`${doc(id)}/fields`, "POST", body),
  setTranslation: (id, termId, english) =>
    api<Field>(`${doc(id)}/translations/${encodeURIComponent(termId)}`, "PATCH", { english }),
  setHeader: (id, body) => api<Header>(`${doc(id)}/header`, "PATCH", body),
  reorder: (id, order) => api<WorkingResult>(`${doc(id)}/pages/order`, "PUT", { order }),
  verify: (id) => api<VerifySummary>(`${doc(id)}/verify`, "POST"),
  save: async (id) => {
    await api(`${doc(id)}/save`, "POST", { choice: "document_only" });
  },
  output: (id) => apiBlob(`${doc(id)}/output`),
  close: async (id) => {
    await api(doc(id), "DELETE");
  },
};

/** Fixture mode mirrors the server's rules closely enough to demo the window. */
export function fixtureBackend(): Backend {
  // The fixture predates some DD-1 additions; missing keys get their defaults.
  const wr = structuredClone(fixture) as unknown as WorkingResult;
  wr.id = "fixture";
  wr.state = "ready";
  wr.error = null;
  wr.messages ??= [];
  wr.document.route ??= "digital_pdf";
  wr.document.model_used ??= false;
  wr.document.pages.forEach((p: PageInfo) => {
    p.text ??= "";
    p.messages ??= [];
  });
  wr.fields.forEach((f: Field) => {
    f.translation ??= {};
    f.removed ??= false;
  });
  const find = (fieldId: string) => wr.fields.find((f) => f.id === fieldId)!;
  const mark = (f: Field) => {
    if (!f.status.includes("edited_by_user")) f.status.push("edited_by_user");
  };

  return {
    live: false,
    current: async () => ({ document_id: null, state: null }),
    upload: async () => "fixture",
    events: async (_id, onEvent) => onEvent({ type: "done" }),
    result: async () => structuredClone(wr),
    pageImage: async () => null,
    editField: async (_id, fieldId, body) => {
      const f = find(fieldId);
      if (typeof body.name === "string") (f.name = body.name), mark(f);
      if ("value" in body) (f.value_en = (body.value as string) || null), mark(f);
      if (typeof body.value_type === "string") (f.value_type = body.value_type as Field["value_type"]), mark(f);
      if (typeof body.removed === "boolean") f.removed = body.removed;
      if (body.accept) f.status = f.status.filter((s) => s !== "suggested" && s !== "needs_review");
      return structuredClone(f);
    },
    addField: async (_id, body) => {
      const f: Field = {
        id: `f${wr.fields.length + 1}`, name: body.name, printed_label: null, value: null, value_en: null,
        value_type: "text", lang: null, page: body.page, box: body.box as Field["box"], box_source: null,
        confidence: 1, source: "user", status: ["edited_by_user", "not_found"], translation: {}, removed: false,
      };
      wr.fields.push(f);
      return structuredClone(f);
    },
    setTranslation: async (_id, termId, english) => {
      const [fieldId, part] = termId.split(".");
      const f = find(fieldId);
      if (part === "name") f.name = english;
      else f.value_en = english;
      f.translation[part as "name" | "value"] = "user";
      f.status = f.status.filter((s) => s !== "not_translated");
      return structuredClone(f);
    },
    setHeader: async (_id, body) => Object.assign(wr.header, body),
    reorder: async () => structuredClone(wr),
    verify: async () => {
      const kept = wr.fields.filter((f) => !f.removed);
      const count = new Map<string, number>();
      kept.forEach((f) => count.set(f.name.toLowerCase(), (count.get(f.name.toLowerCase()) ?? 0) + 1));
      const duplicates = [...new Set(kept.filter((f) => count.get(f.name.toLowerCase())! > 1).map((f) => f.name))];
      return {
        fields: kept.length,
        not_found: kept.filter((f) => (f.value_en ?? f.value) === null).length,
        needs_review: kept.filter((f) => f.status.includes("needs_review")).length,
        not_translated: kept.filter((f) => f.status.includes("not_translated")).length,
        duplicates,
        can_confirm: duplicates.length === 0,
        save_dialog_needed: true,
        save_choices: { document_only: true, new: false, update: false },
      };
    },
    save: async () => {
      wr.verified = true;
    },
    output: async () =>
      new Blob([JSON.stringify({ note: "fixture mode: no output is produced" }, null, 2)], {
        type: "application/json",
      }),
    close: async () => {},
  };
}
