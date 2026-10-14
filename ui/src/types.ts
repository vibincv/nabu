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
  template_key?: string | null; // the template field this was read for (M3)
  name_suggestion?: string | null; // a similar template's name, one click to accept (FR-5.6)
}

export interface TemplateInfo {
  template_id: string;
  document_type: string;
  region: string | null;
  format: string;
  version: number;
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
    candidates: (TemplateInfo & { score: number })[];
    template?: TemplateInfo | null; // linked, or the most similar one
    missing_pages?: number[];
    chosen?: boolean;
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
  suggested?: "new" | "update";
  update_targets?: TemplateInfo[];
  document_types?: string[];
  format_suggestion?: string;
  changes?: Changes;
  labels?: string[]; // printed labels that would be written to disk (FR-7.1)
}

export interface Changes {
  renamed: [string | null, string][];
  added: string[];
  removed: string[];
  type_changed: string[];
  reordered: boolean;
}

export interface SaveBody {
  choice: "new" | "update" | "document_only";
  document_type?: string;
  region?: string;
  format?: string;
  template_id?: string;
}

export interface TemplateSummary extends TemplateInfo {
  fields: number;
  updated_at: string | null;
  field_names: string[];
}

export interface TemplateGroup {
  document_type: string;
  regions: { region: string | null; formats: TemplateSummary[] }[];
}

export interface Anchor {
  printed_label: string | null;
  page: number | null;
  box: number[] | null;
  value_offset: number[] | null;
  tolerance: number;
}

// DD-2: never holds a value.
export interface Template {
  template: {
    id: string;
    document_type: string;
    region: string | null;
    format: { id: string; name: string };
    version: number;
    updated_at?: string;
  };
  fields: { order: number; name: string; key: string; value_type: ValueType; anchor: Anchor }[];
  removed_labels: string[];
}

export interface HistoryEntry {
  version: number;
  updated_at: string | null;
  change: (Partial<Changes> & { kind?: string; to_version?: number; format?: string[]; document_type?: string[] }) | null;
  current: boolean;
}

export interface ReadEvent {
  type: "progress" | "done" | "error" | "cancelled";
  stage?: string;
  done?: number;
  total?: number;
  message?: string;
}
