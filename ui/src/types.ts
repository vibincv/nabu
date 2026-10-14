// Working result (DD-1) as the local API serves it. Mirrors nabu.fields.types and
// nabu.server.documents.ReviewDocument.to_dict.

export type ValueType = "name" | "id" | "number" | "date" | "amount" | "address" | "text";
export const VALUE_TYPES: ValueType[] = ["name", "id", "number", "date", "amount", "address", "text"];

export type Status =
  | "from_template"
  | "suggested"
  | "needs_review"
  | "not_found"
  | "not_translated"
  | "edited_by_user";

export type TStatus = "not_needed" | "memory" | "translated" | "low_confidence" | "untranslated" | "user";

export interface Field {
  id: string;
  name: string;
  printed_label: string | null;
  value: string | null;
  value_en: string | null;
  value_type: ValueType;
  lang: string | null;
  page: number;
  box: [number, number, number, number] | null; // 0-1000 grid, top-left origin
  box_source: "ocr" | "model" | "text_layer" | null;
  confidence: number;
  source: "template" | "model" | "model_reread" | "discovery_rules" | "user";
  status: Status[];
  translation: Partial<Record<"name" | "value", TStatus>>;
  removed: boolean;
}

export interface PageInfo {
  n: number;
  width_px: number | null;
  height_px: number | null;
  lang: string | null;
  text: string;
  messages: string[];
}

export interface Header {
  document_type: string | null;
  region: string | null;
  format: string | null;
}

export interface WorkingResult {
  id: string;
  state: "reading" | "ready" | "error" | "cancelled";
  error: string | null;
  schema_version: string;
  verified: boolean;
  document: { source_file: string; route: string; model_used: boolean; pages: PageInfo[] };
  header: Header;
  link: {
    outcome: "linked" | "ambiguous" | "similar" | "none";
    template_id: string | null;
    template_version: number | null;
    score: number;
    candidates: { template_id: string; score: number }[];
  };
  type_guess: string | null;
  country_guess: string | null;
  messages: string[];
  fields: Field[];
}

export interface VerifySummary {
  fields: number;
  not_found: number;
  needs_review: number;
  not_translated: number;
  duplicates: string[];
  can_confirm: boolean;
  save_dialog_needed: boolean;
  save_choices: { document_only: boolean; new: boolean; update: boolean };
}

export interface ReadEvent {
  type: "progress" | "done" | "error" | "cancelled";
  stage?: string;
  done?: number;
  total?: number;
  message?: string;
}
