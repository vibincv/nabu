// Review window shell (FR-6, UX-1, UX-2). Runs on the bundled synthetic fixture until the
// M2 API exists. All state is in memory; nothing is written to browser storage.

import fixture from "@fixtures/working_result.sample.json";
import { api, fixtureMode } from "./api";
import { VALUE_TYPES, type Field, type Status, type WorkingResult } from "./types";

const SVG = "http://www.w3.org/2000/svg";
const wr = structuredClone(fixture) as unknown as WorkingResult;

const state = {
  selected: null as string | null,
  documentOrder: false,
  showOriginals: false,
};

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

const STATUS_TEXT: Record<Status, string> = {
  from_template: "from your template",
  suggested: "suggested",
  needs_review: "needs review",
  not_found: "not found",
  not_translated: "not translated",
  edited_by_user: "edited",
};

function noLeakInput(input: HTMLInputElement): HTMLInputElement {
  // FR-6.18: spell-check and autofill must not see document text.
  input.spellcheck = false;
  input.autocomplete = "off";
  input.setAttribute("autocorrect", "off");
  input.setAttribute("autocapitalize", "off");
  input.setAttribute("data-gramm", "false"); // ask Grammarly-type extensions to stay out
  return input;
}

function el<K extends keyof HTMLElementTagNameMap>(tag: K, cls?: string, text?: string) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function confidenceWord(c: number): string {
  if (c >= 0.85) return "high";
  if (c >= 0.6) return "medium";
  return "low";
}

function sortedFields(): Field[] {
  const kept = wr.fields.filter((f) => !f.removed);
  if (state.documentOrder) return kept;
  const rank = (f: Field) => (f.status.includes("needs_review") || f.status.includes("not_found") ? 0 : 1);
  return [...kept].sort((a, b) => rank(a) - rank(b));
}

// ---- page with highlights -----------------------------------------------------------------
function renderPage(): void {
  const page = wr.document.pages[0];
  const svg = $("page") as unknown as SVGSVGElement;
  svg.replaceChildren();
  const h = Math.round(1000 * (page.height_px / page.width_px));
  svg.setAttribute("viewBox", `0 0 1000 ${h}`);

  const paper = document.createElementNS(SVG, "rect");
  Object.entries({ x: 0, y: 0, width: 1000, height: h, class: "paper" }).forEach(([k, v]) =>
    paper.setAttribute(k, String(v)),
  );
  svg.append(paper);

  // Synthetic page: grey text lines so the shell looks like a document without a real image.
  for (let y = 420; y < h - 160; y += 34) {
    const line = document.createElementNS(SVG, "rect");
    const w = 380 + ((y * 37) % 420);
    Object.entries({ x: 80, y, width: w, height: 10, class: "ghost-line" }).forEach(([k, v]) =>
      line.setAttribute(k, String(v)),
    );
    svg.append(line);
  }

  for (const f of wr.fields) {
    if (!f.box || f.removed) continue;
    const [x0, y0, x1, y1] = f.box;
    const yScale = h / 1000;
    const g = document.createElementNS(SVG, "g");
    g.setAttribute("class", `hl ${f.status.join(" ")} ${state.selected === f.id ? "selected" : ""}`);
    g.setAttribute("tabindex", "-1");
    g.dataset.id = f.id;

    const r = document.createElementNS(SVG, "rect");
    Object.entries({ x: x0, y: y0 * yScale, width: x1 - x0, height: (y1 - y0) * yScale }).forEach(
      ([k, v]) => r.setAttribute(k, String(v)),
    );
    const label = document.createElementNS(SVG, "text");
    label.setAttribute("x", String(x0));
    label.setAttribute("y", String(y0 * yScale - 6));
    label.setAttribute("class", "hl-label");
    label.textContent = f.name;

    const val = document.createElementNS(SVG, "text");
    val.setAttribute("x", String(x0 + 6));
    val.setAttribute("y", String(y1 * yScale - 7));
    val.setAttribute("class", "hl-value");
    val.textContent = f.value ?? "";

    g.append(r, val, label);
    g.addEventListener("click", () => select(f.id, true));
    g.addEventListener("mouseenter", () => hover(f.id, true));
    g.addEventListener("mouseleave", () => hover(f.id, false));
    svg.append(g);
  }
}

// ---- field list --------------------------------------------------------------------------
function renderFields(): void {
  const list = $("fields");
  list.replaceChildren();
  for (const f of sortedFields()) list.append(fieldRow(f));

  const removed = wr.fields.filter((f) => f.removed);
  $("removed-count").textContent = String(removed.length);
  const rl = $("removed-list");
  rl.replaceChildren();
  for (const f of removed) {
    const li = el("li", "removed-row");
    li.append(el("span", "", f.name));
    const restore = el("button", "link", "Restore");
    restore.type = "button";
    restore.addEventListener("click", () => {
      f.removed = false;
      render();
    });
    li.append(restore);
    rl.append(li);
  }
}

function fieldRow(f: Field): HTMLLIElement {
  const li = el("li", `field ${state.selected === f.id ? "selected" : ""}`);
  li.tabIndex = 0;
  li.dataset.id = f.id;

  const top = el("div", "row-top");
  const name = noLeakInput(el("input", "name"));
  name.value = f.name;
  name.setAttribute("aria-label", "Field name");
  name.addEventListener("change", () => {
    f.name = name.value.trim();
    mark(f);
    renderPage();
  });
  const remove = el("button", "icon", "✕");
  remove.type = "button";
  remove.title = "Not required";
  remove.setAttribute("aria-label", `Remove ${f.name}`);
  remove.addEventListener("click", () => {
    f.removed = true;
    render();
  });
  top.append(name, remove);

  const label = el("div", "printed", f.printed_label ? `printed: ${f.printed_label}` : "no printed label");

  const mid = el("div", "row-mid");
  const value = noLeakInput(el("input", "value"));
  const shown = state.showOriginals ? f.value : f.value_en ?? f.value;
  value.value = shown ?? "";
  value.placeholder = f.status.includes("not_found") ? "not found" : "";
  value.setAttribute("aria-label", `Value of ${f.name}`);
  value.addEventListener("change", () => {
    f.value_en = value.value;
    mark(f);
  });
  const vt = el("select", "vtype");
  vt.setAttribute("aria-label", "Value type");
  for (const t of VALUE_TYPES) {
    const o = el("option", "", t);
    o.value = t;
    o.selected = t === f.value_type;
    vt.append(o);
  }
  vt.addEventListener("change", () => {
    f.value_type = vt.value as Field["value_type"];
    mark(f);
  });
  mid.append(value, vt);

  const meta = el("div", "row-meta");
  const conf = el("span", "conf");
  const bar = el("span", "bar");
  const fill = el("span", "fill");
  fill.style.width = `${Math.round(f.confidence * 100)}%`; // CSSOM, allowed by CSP
  bar.append(fill);
  conf.append(el("span", "", `${confidenceWord(f.confidence)} confidence`), bar);
  meta.append(conf);
  if (f.lang !== "en") meta.append(el("span", "badge", f.lang.toUpperCase()));
  for (const s of f.status) meta.append(el("span", `marker ${s}`, STATUS_TEXT[s]));
  if (!f.box) meta.append(el("span", "marker", "no location"));
  if (f.value_en && f.value && f.value_en !== f.value && !state.showOriginals) {
    meta.append(el("span", "original", `original: ${f.value}`));
  }

  li.append(top, label, mid, meta);
  li.addEventListener("mouseenter", () => hover(f.id, true));
  li.addEventListener("mouseleave", () => hover(f.id, false));
  li.addEventListener("focusin", () => select(f.id, false));
  return li;
}

function mark(f: Field): void {
  if (!f.status.includes("edited_by_user")) f.status.push("edited_by_user");
}

function hover(id: string, on: boolean): void {
  document.querySelectorAll(`[data-id="${CSS.escape(id)}"]`).forEach((n) => n.classList.toggle("hover", on));
}

function select(id: string, focusRow: boolean): void {
  state.selected = id;
  document.querySelectorAll(".selected").forEach((n) => n.classList.remove("selected"));
  document.querySelectorAll(`[data-id="${CSS.escape(id)}"]`).forEach((n) => n.classList.add("selected"));
  if (focusRow) document.querySelector<HTMLElement>(`li.field[data-id="${CSS.escape(id)}"]`)?.focus();
}

// ---- header, banner, verify --------------------------------------------------------------
function renderHeader(): void {
  const dt = noLeakInput($("doc-type") as HTMLInputElement);
  const rg = noLeakInput($("region") as HTMLInputElement);
  dt.value = wr.header.document_type ?? "";
  rg.value = wr.header.region ?? "";
  dt.placeholder = wr.type_guess ? `Suggested: ${wr.type_guess}` : "Not recognised — please choose";
  rg.placeholder = wr.country_guess ?? "No region";

  const b = $("banner");
  const l = wr.link;
  const text: Record<typeof l.outcome, string> = {
    linked: `Linked to template: ${wr.header.document_type} · ${wr.header.region ?? "No region"} · ${wr.header.format}`,
    ambiguous: "Several templates match — choose one",
    similar: "Similar to a saved template. Check the suggested names.",
    none: "No matching template. Verify the fields, then save as a new template.",
  };
  b.textContent = text[l.outcome];
  b.className = `banner ${l.outcome}`;
}

function openSummary(): void {
  const kept = wr.fields.filter((f) => !f.removed);
  const notFound = kept.filter((f) => f.status.includes("not_found")).length;
  const review = kept.filter((f) => f.status.includes("needs_review")).length;
  const untranslated = kept.filter((f) => f.status.includes("not_translated")).length;
  $("summary-text").textContent =
    `${kept.length} fields · ${notFound} not found · ${review} needs review · ${untranslated} not translated`;

  const issues = $("summary-issues");
  issues.replaceChildren();
  const names = new Map<string, number>();
  kept.forEach((f) => names.set(f.name.toLowerCase(), (names.get(f.name.toLowerCase()) ?? 0) + 1));
  const dups = [...names.entries()].filter(([, n]) => n > 1).map(([k]) => k);
  for (const d of dups) issues.append(el("li", "blocking", `Two fields are named "${d}". Rename or remove one.`));
  ($("summary-confirm") as HTMLButtonElement).disabled = dups.length > 0; // FR-6.16
  ($("summary") as HTMLDialogElement).showModal();
}

function wire(): void {
  $("verify").addEventListener("click", openSummary);
  $("summary-back").addEventListener("click", () => ($("summary") as HTMLDialogElement).close());
  $("summary-confirm").addEventListener("click", () => {
    ($("summary") as HTMLDialogElement).close();
    $("banner").textContent = fixtureMode
      ? "Verified (fixture mode). The save dialog and output arrive in M2/M3."
      : "Verified. The save dialog and output arrive in M2/M3.";
  });
  ($("order-toggle") as HTMLInputElement).addEventListener("change", (e) => {
    state.documentOrder = (e.target as HTMLInputElement).checked;
    renderFields();
  });
  ($("lang-toggle") as HTMLInputElement).addEventListener("change", (e) => {
    state.showOriginals = (e.target as HTMLInputElement).checked;
    renderFields();
  });
  // Arrow keys move between rows (UX-2.2).
  $("fields").addEventListener("keydown", (e) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    if ((e.target as HTMLElement).tagName !== "LI") return;
    const rows = [...document.querySelectorAll<HTMLElement>("li.field")];
    const i = rows.indexOf(e.target as HTMLElement);
    const next = rows[e.key === "ArrowDown" ? i + 1 : i - 1];
    if (next) {
      e.preventDefault();
      next.focus();
    }
  });
}

async function connect(): Promise<void> {
  const mode = $("mode");
  if (fixtureMode) {
    mode.textContent = "Fixture mode · synthetic sample";
    return;
  }
  try {
    const h = await api<{ ok: boolean; version: string }>("/api/health");
    mode.textContent = `Local · v${h.version} · synthetic sample`;
  } catch {
    mode.textContent = "Not connected to local Nabu";
  }
}

function render(): void {
  renderHeader();
  renderPage();
  renderFields();
}

wire();
render();
void connect();
