// Working result (DD-1). Mirrors fixtures/working_result.sample.json.

export type ValueType = "name" | "id" | "number" | "date" | "amount" | "address" | "text";
export const VALUE_TYPES: ValueType[] = ["name", "id", "number", "date", "amount", "address", "text"];

export type Status =
  | "from_template"
  | "suggested"
  | "needs_review"
  | "not_found"
  | "not_translated"
  | "edited_by_user";

export interface Field {
  id: string;
  name: string;
  printed_label: string | null;
  value: string | null;
  value_en: string | null;
  value_type: ValueType;
  lang: string;
  page: number;
  box: [number, number, number, number] | null; // 0-1000 grid, top-left origin
  box_source: "ocr" | "model" | "text_layer" | null;
  confidence: number;
  source: "template" | "model" | "model_reread" | "discovery_rules" | "user";
  status: Status[];
  removed?: boolean;
}

export interface WorkingResult {
  schema_version: string;
  verified: boolean;
  document: { source_file: string; pages: { n: number; width_px: number; height_px: number; lang: string }[] };
  header: { document_type: string | null; region: string | null; format: string | null };
  link: {
    outcome: "linked" | "ambiguous" | "similar" | "none";
    template_id: string | null;
    template_version: number | null;
    score: number;
    candidates: { template_id: string; score: number }[];
  };
  type_guess: string | null;
  country_guess: string | null;
  fields: Field[];
}
