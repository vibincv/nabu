// Review window (FR-6, UX-1, UX-2). Live against the local API, or on the bundled synthetic
// fixture when the page carries no token (development and the M5 demo). All state is in
// memory; nothing is written to browser storage.

import { ApiError, fixtureMode } from "./api";
import { fixtureBackend, liveBackend, type Backend } from "./backend";
import { REGION_CODES } from "./regions";
import {
  VALUE_TYPES,
  type Field,
  type HistoryEntry,
  type ReadEvent,
  type SaveBody,
  type Status,
  type TemplateGroup,
  type TemplateInfo,
  type TemplateSummary,
  type VerifySummary,
  type WorkingResult,
} from "./types";

const SVG = "http://www.w3.org/2000/svg";
const backend: Backend = fixtureMode ? fixtureBackend() : liveBackend;

const state = {
  docId: null as string | null,
  wr: null as WorkingResult | null,
  page: 1,
  selected: null as string | null,
  documentOrder: false,
  showOriginals: false,
  drawing: false,
  chosen: [] as File[],
  images: new Map<number, string>(), // page -> object URL of the in-memory image
  groups: [] as TemplateGroup[], // saved templates: names only, never values
  summary: null as VerifySummary | null,
};

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;

const STATUS_TEXT: Record<Status, string> = {
  from_template: "from your template",
  suggested: "suggested",
  needs_review: "needs review",
  not_found: "not found",
  not_translated: "not translated",
  edited_by_user: "edited",
};
const NO_MODEL_NOTE = "Finding fields on scans needs a local AI model";

function el<K extends keyof HTMLElementTagNameMap>(tag: K, cls?: string, text?: string) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function svgEl(tag: string, attrs: Record<string, string | number>): SVGElement {
  const e = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
  return e;
}

function noLeakInput<T extends HTMLInputElement | HTMLSelectElement>(input: T): T {
  // FR-6.18: spell-check and autofill must not see document text.
  if (input instanceof HTMLInputElement) {
    input.spellcheck = false;
    input.autocomplete = "off";
  }
  input.setAttribute("autocorrect", "off");
  input.setAttribute("autocapitalize", "off");
  input.setAttribute("data-gramm", "false"); // ask Grammarly-type extensions to stay out
  return input;
}

function notice(message: string | null): void {
  const n = $("notice");
  n.hidden = !message;
  n.textContent = message ?? "";
}

async function attempt(fn: () => Promise<void>): Promise<void> {
  try {
    notice(null);
    await fn();
  } catch (e) {
    if (!(e instanceof ApiError)) console.error(e); // a bug in this page; shown in DevTools only
    notice(e instanceof ApiError ? e.message : "Something went wrong. Try again.");
  }
}

function show(view: "upload" | "reading" | "review"): void {
  $("upload-view").hidden = view !== "upload";
  $("reading-view").hidden = view !== "reading";
  $("review-view").hidden = view !== "review";
  const review = view === "review";
  for (const id of ["doc-type-field", "region-field", "verify", "close-doc", "banner"]) $(id).hidden = !review;
}

// ---- upload (FR-6.2) ----------------------------------------------------------------------
function renderChosen(): void {
  const list = $("chosen");
  list.replaceChildren();
  state.chosen.forEach((f, i) => {
    const li = el("li", "chosen-row");
    li.append(el("span", "", `${i + 1}. ${f.name}`), el("span", "muted", `${Math.ceil(f.size / 1024)} KB`));
    const move = (to: number, label: string, text: string) => {
      const b = el("button", "icon", text);
      b.type = "button";
      b.setAttribute("aria-label", `${label} ${f.name}`);
      b.disabled = to < 0 || to >= state.chosen.length;
      b.addEventListener("click", () => {
        const [x] = state.chosen.splice(i, 1);
        state.chosen.splice(to, 0, x);
        renderChosen();
      });
      return b;
    };
    const remove = el("button", "icon", "✕");
    remove.type = "button";
    remove.setAttribute("aria-label", `Remove ${f.name}`);
    remove.addEventListener("click", () => {
      state.chosen.splice(i, 1);
      renderChosen();
    });
    li.append(move(i - 1, "Move earlier", "↑"), move(i + 1, "Move later", "↓"), remove);
    list.append(li);
  });
  $("chosen-actions").hidden = state.chosen.length === 0;
}

function choose(files: FileList | null): void {
  if (!files) return;
  state.chosen.push(...Array.from(files));
  renderChosen();
}

async function startReading(): Promise<void> {
  const files = state.chosen;
  if (!files.length) return;
  await attempt(async () => {
    const id = await backend.upload(files);
    state.chosen = [];
    renderChosen();
    await follow(id);
  });
}

/** Shows progress until the reading job ends, then the review (or the reason it stopped). */
async function follow(id: string): Promise<void> {
  state.docId = id;
  await attempt(async () => {
    show("reading");
    $<HTMLProgressElement>("reading-bar").value = 0;
    $("reading-stage").textContent = "";
    let last: ReadEvent | null = null;
    await backend.events(id, (e) => {
      last = e;
      if (e.type === "progress" && e.total) {
        $<HTMLProgressElement>("reading-bar").value = (e.done ?? 0) / e.total;
        $("reading-stage").textContent =
          e.stage === "translating"
            ? "Translating to English"
            : e.stage === "reading fields"
              ? "Reading the fields of your template"
              : `${e.stage === "reading" ? "Reading" : "Finding fields"}: page ${e.done} of ${e.total}`;
      }
    });
    const end = last as ReadEvent | null;
    if (end?.type === "done") {
      await loadResult();
    } else {
      await closeDocument();
      notice(end?.type === "error" ? end.message ?? "Reading failed." : end?.type === "cancelled" ? "Reading cancelled." : "Reading stopped.");
    }
  });
}

async function loadResult(): Promise<void> {
  if (!state.docId) return;
  state.wr = await backend.result(state.docId);
  await loadTemplates();
  state.page = state.wr.document.pages[0]?.n ?? 1;
  for (const url of state.images.values()) URL.revokeObjectURL(url);
  state.images.clear();
  for (const p of state.wr.document.pages) {
    const blob = await backend.pageImage(state.docId, p.n);
    if (blob) state.images.set(p.n, URL.createObjectURL(blob));
  }
  show("review");
  render();
}

/** Ends the session on the server (also after an error or cancel, to free the one slot). */
async function closeDocument(): Promise<void> {
  const id = state.docId;
  state.docId = null;
  state.wr = null;
  state.selected = null;
  for (const url of state.images.values()) URL.revokeObjectURL(url);
  state.images.clear();
  // FR-11.3: the window keeps no document text once the document is closed.
  for (const list of ["fields", "removed-list", "page-messages", "page", "summary-issues"]) $(list).replaceChildren();
  for (const list of ["save-changes", "save-landmarks", "link-choices", "name-options", "save-target"])
    $(list).replaceChildren();
  saveSummary = null;
  for (const id of ["page-text", "summary-text", "banner-text", "tr-term"]) $(id).textContent = "";
  for (const id of ["doc-type", "name-input", "tr-input", "save-type", "save-format"]) {
    $<HTMLInputElement>(id).value = "";
  }
  state.summary = null;
  $<HTMLSelectElement>("region").value = "";
  if (id) await backend.close(id).catch(() => undefined);
  show("upload");
  $("mode").textContent = "Local · nothing leaves this machine";
  $("quit").hidden = false;
  void showFirstRun();
}

/** Any edit means the server needs a new Verify before it serves the output (API-4). */
function changed(): void {
  if (state.wr) state.wr.verified = false;
}

// ---- page with highlights (FR-6.3, FR-6.9) ---------------------------------------------------
function currentPage() {
  return state.wr!.document.pages.find((p) => p.n === state.page) ?? state.wr!.document.pages[0];
}

function renderPage(): void {
  const wr = state.wr!;
  const pages = wr.document.pages;
  const page = currentPage();
  const idx = pages.indexOf(page);
  $("page-label").textContent = `Page ${page.n} of ${pages.length}`;
  $<HTMLButtonElement>("page-prev").disabled = idx <= 0;
  $<HTMLButtonElement>("page-next").disabled = idx >= pages.length - 1;
  const reorderable = wr.document.route === "raster" && pages.length > 1;
  $("order-tools").hidden = !reorderable;
  $<HTMLButtonElement>("page-earlier").disabled = idx <= 0;
  $<HTMLButtonElement>("page-later").disabled = idx >= pages.length - 1;

  const msgs = $("page-messages");
  msgs.replaceChildren(...[...wr.messages, ...page.messages].map((m) => el("li", "", m)));

  const image = state.images.get(page.n);
  const svg = $("page") as unknown as SVGSVGElement;
  const text = $("page-text");
  ($("draw") as HTMLButtonElement).disabled = !image;
  svg.replaceChildren();
  if (!image) {
    // Office and text files have no page positions (AD-15): show the text instead.
    svg.setAttribute("hidden", "");
    text.hidden = false;
    text.textContent = page.text || "(no text on this page)";
    return;
  }
  svg.removeAttribute("hidden");
  text.hidden = true;
  const h = page.width_px && page.height_px ? Math.round((1000 * page.height_px) / page.width_px) : 1414;
  const yScale = h / 1000;
  svg.setAttribute("viewBox", `0 0 1000 ${h}`);
  svg.setAttribute("aria-label", `Page ${page.n} with highlighted fields`);
  svg.append(svgEl("image", { href: image, x: 0, y: 0, width: 1000, height: h }));

  for (const f of wr.fields) {
    if (!f.box || f.removed || f.page !== page.n) continue;
    const [x0, y0, x1, y1] = f.box;
    const g = svgEl("g", { class: `hl ${f.status.join(" ")} ${state.selected === f.id ? "selected" : ""}` });
    g.dataset.id = f.id;
    const r = svgEl("rect", { x: x0, y: y0 * yScale, width: x1 - x0, height: (y1 - y0) * yScale });
    const label = svgEl("text", { x: x0, y: Math.max(14, y0 * yScale - 6), class: "hl-label" });
    label.textContent = f.name;
    g.append(r, label);
    g.addEventListener("click", () => !state.drawing && select(f.id, true));
    g.addEventListener("mouseenter", () => hover(f.id, true));
    g.addEventListener("mouseleave", () => hover(f.id, false));
    svg.append(g);
  }
}

function svgPoint(svg: SVGSVGElement, e: PointerEvent): { x: number; y: number } {
  const m = svg.getScreenCTM();
  const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(m ? m.inverse() : undefined);
  return { x: p.x, y: p.y };
}

function wireDrawing(): void {
  const svg = $("page") as unknown as SVGSVGElement;
  let start: { x: number; y: number } | null = null;
  let rect: SVGElement | null = null;
  svg.addEventListener("pointerdown", (e) => {
    if (!state.drawing) return;
    start = svgPoint(svg, e);
    rect = svgEl("rect", { class: "drawing", x: start.x, y: start.y, width: 0, height: 0 });
    svg.append(rect);
    svg.setPointerCapture(e.pointerId);
  });
  svg.addEventListener("pointermove", (e) => {
    if (!start || !rect) return;
    const p = svgPoint(svg, e);
    rect.setAttribute("x", String(Math.min(p.x, start.x)));
    rect.setAttribute("y", String(Math.min(p.y, start.y)));
    rect.setAttribute("width", String(Math.abs(p.x - start.x)));
    rect.setAttribute("height", String(Math.abs(p.y - start.y)));
  });
  svg.addEventListener("pointerup", (e) => {
    if (!start || !rect) return;
    const p = svgPoint(svg, e);
    const page = currentPage();
    const yScale = page.width_px && page.height_px ? page.height_px / page.width_px : 1.414;
    const box = [Math.min(p.x, start.x), Math.min(p.y, start.y) / yScale, Math.max(p.x, start.x), Math.max(p.y, start.y) / yScale];
    start = null;
    if (box[2] - box[0] < 4 || box[3] - box[1] < 4) {
      rect.remove();
      rect = null;
      return;
    }
    askName(box.map(Math.round));
  });
}

function askName(box: number[]): void {
  const dialog = $<HTMLDialogElement>("name-dialog");
  const input = noLeakInput($<HTMLInputElement>("name-input"));
  input.value = "";
  dialog.showModal();
  input.focus();
  const form = $<HTMLFormElement>("name-form");
  const done = (ok: boolean) => {
    form.onsubmit = null;
    $("name-cancel").onclick = null;
    dialog.close();
    setDrawing(false);
    if (ok && input.value.trim() && state.docId) {
      void attempt(async () => {
        const f = await backend.addField(state.docId!, { name: input.value.trim(), page: state.page, box });
        state.wr!.fields.push(f);
        state.selected = f.id;
        changed();
        render();
      });
    } else {
      renderPage();
    }
  };
  form.onsubmit = (e) => {
    e.preventDefault();
    done(true);
  };
  $("name-cancel").onclick = () => done(false);
}

function setDrawing(on: boolean): void {
  state.drawing = on;
  const b = $("draw");
  b.setAttribute("aria-pressed", String(on));
  b.textContent = on ? "Drawing: drag a box around the value (Esc to stop)" : "Add field";
  $("page").classList.toggle("drawing-mode", on);
}

// ---- field list (FR-6.4 to FR-6.10) ---------------------------------------------------------
function confidenceWord(c: number): string {
  if (c >= 0.85) return "high";
  if (c >= 0.6) return "medium";
  return "low";
}

function sortedFields(): Field[] {
  const kept = state.wr!.fields.filter((f) => !f.removed);
  if (state.documentOrder) return kept;
  const rank = (f: Field) => (f.status.includes("needs_review") || f.status.includes("not_found") ? 0 : 1);
  return [...kept].sort((a, b) => rank(a) - rank(b));
}

function replaceField(f: Field): void {
  const wr = state.wr!;
  wr.fields = wr.fields.map((x) => (x.id === f.id ? f : x));
}

function edit(f: Field, body: Record<string, unknown>, rerender: "all" | "page" | "none" = "all"): void {
  void attempt(async () => {
    replaceField(await backend.editField(state.docId!, f.id, body));
    changed();
    if (rerender !== "all") renderHeader(); // the banner drops "Verified"
    if (rerender === "all") render();
    else if (rerender === "page") renderPage();
  });
}

function renderFields(): void {
  const wr = state.wr!;
  const list = $("fields");
  list.replaceChildren(...sortedFields().map(fieldRow));

  const empty = $("empty-state");
  const scanNoModel = wr.document.pages.some((p) => p.messages.some((m) => m.startsWith(NO_MODEL_NOTE)));
  empty.hidden = wr.fields.length > 0;
  empty.textContent = scanNoModel
    ? "No local AI model installed. Digital files and saved templates still work. The page text is shown on the left."
    : "Nothing found. Try a clearer scan, or draw a box around a value to add a field.";

  const removed = wr.fields.filter((f) => f.removed);
  $("removed-count").textContent = String(removed.length);
  $("removed-list").replaceChildren(
    ...removed.map((f) => {
      const li = el("li", "removed-row");
      const restore = el("button", "link", "Restore");
      restore.type = "button";
      restore.setAttribute("aria-label", `Restore ${f.name}`);
      restore.addEventListener("click", () => edit(f, { removed: false }));
      li.append(el("span", "", f.name), restore);
      return li;
    }),
  );
}

function fieldRow(f: Field): HTMLLIElement {
  const li = el("li", `field ${state.selected === f.id ? "selected" : ""}`);
  li.tabIndex = 0;
  li.dataset.id = f.id;

  const top = el("div", "row-top");
  const name = noLeakInput(el("input", "name"));
  name.value = f.name;
  name.setAttribute("list", "name-options"); // FR-6.5: names from this document type's templates
  name.setAttribute("aria-label", "Field name");
  name.addEventListener("change", () => {
    const v = name.value.trim();
    if (v && v !== f.name) edit(f, { name: v }, "page");
    else name.value = f.name;
  });
  const remove = el("button", "icon", "✕");
  remove.type = "button";
  remove.title = "Not required";
  remove.setAttribute("aria-label", `Remove ${f.name} (not required)`);
  remove.addEventListener("click", () => edit(f, { removed: true }));
  top.append(name, remove);

  const printed = el("div", "printed", f.printed_label ? `printed: ${f.printed_label}` : "no printed label");

  const mid = el("div", "row-mid");
  const value = noLeakInput(el("input", "value"));
  const shown = state.showOriginals ? f.value : f.value_en ?? f.value;
  value.value = shown ?? "";
  value.placeholder = f.status.includes("not_found") ? "not found" : "";
  value.readOnly = state.showOriginals; // originals are shown as printed; edits apply to the English value
  value.setAttribute("aria-label", `Value of ${f.name}`);
  value.addEventListener("change", () => edit(f, { value: value.value }, "none"));
  const vt = noLeakInput(el("select", "vtype"));
  vt.setAttribute("aria-label", `Value type of ${f.name}`);
  for (const t of VALUE_TYPES) {
    const o = el("option", "", t);
    o.value = t;
    o.selected = t === f.value_type;
    vt.append(o);
  }
  vt.addEventListener("change", () => edit(f, { value_type: vt.value }, "none"));
  mid.append(value, vt);

  const meta = el("div", "row-meta");
  const conf = el("span", "conf");
  const bar = el("span", "bar");
  const fill = el("span", "fill");
  fill.style.width = `${Math.round(f.confidence * 100)}%`; // CSSOM, allowed by CSP
  bar.append(fill);
  conf.append(el("span", "", `${confidenceWord(f.confidence)} confidence`), bar);
  meta.append(conf);
  if (f.lang && f.lang !== "en") meta.append(el("span", "badge", f.lang.toUpperCase()));
  for (const s of f.status) {
    if (s === "suggested") {
      const label = f.name_suggestion ? `use "${f.name_suggestion}"` : "suggested · accept";
      const b = el("button", "marker suggested", label);
      b.type = "button";
      b.setAttribute(
        "aria-label",
        f.name_suggestion ? `Rename ${f.name} to ${f.name_suggestion}` : `Accept suggested field ${f.name}`,
      );
      b.addEventListener("click", () => edit(f, { accept: true }));
      meta.append(b);
    } else if (s === "not_translated") {
      const b = el("button", "marker not_translated", "not translated · type English");
      b.type = "button";
      b.addEventListener("click", () => askTranslation(f));
      meta.append(b);
    } else {
      meta.append(el("span", `marker ${s}`, STATUS_TEXT[s]));
    }
  }
  if (!f.box && state.images.size) meta.append(el("span", "marker", "no location"));
  if (f.value_en && f.value && f.value_en !== f.value && !state.showOriginals) {
    meta.append(el("span", "original", `original: ${f.value}`));
  }

  li.append(top, printed, mid, meta);
  li.addEventListener("mouseenter", () => hover(f.id, true));
  li.addEventListener("mouseleave", () => hover(f.id, false));
  li.addEventListener("focusin", () => select(f.id, false));
  return li;
}

function askTranslation(f: Field): void {
  const part = f.translation.name === "untranslated" ? "name" : "value";
  const term = part === "name" ? f.printed_label ?? f.name : f.value ?? "";
  const dialog = $<HTMLDialogElement>("tr-dialog");
  const input = noLeakInput($<HTMLInputElement>("tr-input"));
  $("tr-term").textContent = `${term}${f.lang ? ` (${f.lang.toUpperCase()})` : ""}`;
  input.value = "";
  // FR-9.8: printed labels can be remembered, values never
  const remember = $<HTMLInputElement>("tr-remember");
  remember.checked = false;
  $("tr-remember-row").hidden = !backend.live || part !== "name" || !f.printed_label || !f.lang;
  dialog.showModal();
  input.focus();
  const form = $<HTMLFormElement>("tr-form");
  const done = (ok: boolean) => {
    form.onsubmit = null;
    $("tr-cancel").onclick = null;
    dialog.close();
    if (!ok || !input.value.trim()) return;
    void attempt(async () => {
      replaceField(
        await backend.setTranslation(state.docId!, `${f.id}.${part}`, input.value.trim(), remember.checked),
      );
      changed();
      render();
    });
  };
  form.onsubmit = (e) => {
    e.preventDefault();
    done(true);
  };
  $("tr-cancel").onclick = () => done(false);
}

function hover(id: string, on: boolean): void {
  document.querySelectorAll(`[data-id="${CSS.escape(id)}"]`).forEach((n) => n.classList.toggle("hover", on));
}

function select(id: string, focusRow: boolean): void {
  state.selected = id;
  const f = state.wr?.fields.find((x) => x.id === id);
  if (f && f.page !== state.page && f.box) {
    state.page = f.page;
    renderPage();
  }
  document.querySelectorAll(".selected").forEach((n) => n.classList.remove("selected"));
  document.querySelectorAll(`[data-id="${CSS.escape(id)}"]`).forEach((n) => n.classList.add("selected"));
  if (focusRow) document.querySelector<HTMLElement>(`li.field[data-id="${CSS.escape(id)}"]`)?.focus();
  document.querySelector(`.hl[data-id="${CSS.escape(id)}"]`)?.scrollIntoView({ block: "nearest", inline: "nearest" });
}

// ---- header (FR-6.17, UX-2.15) and banner (UX-2.1) ------------------------------------------
const regionNames = (() => {
  try {
    return new Intl.DisplayNames(["en"], { type: "region" });
  } catch {
    return null;
  }
})();

function fillRegions(): void {
  const sel = noLeakInput($<HTMLSelectElement>("region"));
  const none = el("option", "", "No region / not set");
  none.value = "";
  const countries = REGION_CODES.map((code) => {
    const o = el("option", "", `${regionNames?.of(code) ?? code} (${code})`);
    o.value = code;
    return o;
  }).sort((a, b) => a.text.localeCompare(b.text));
  sel.replaceChildren(none, ...countries);
}

function renderHeader(): void {
  const wr = state.wr!;
  const dt = noLeakInput($<HTMLInputElement>("doc-type"));
  dt.value = wr.header.document_type ?? "";
  dt.placeholder = "Not recognised — please choose";
  const rg = $<HTMLSelectElement>("region");
  rg.value = wr.header.region ?? "";

  const dtGuess = $<HTMLButtonElement>("doc-type-guess");
  dtGuess.hidden = !wr.type_guess || wr.type_guess === wr.header.document_type;
  dtGuess.textContent = `Use "${wr.type_guess}"`;
  const rgGuess = $<HTMLButtonElement>("region-guess");
  const guess = wr.country_guess && REGION_CODES.includes(wr.country_guess) ? wr.country_guess : null;
  rgGuess.hidden = !guess || guess === wr.header.region;
  rgGuess.textContent = `Use ${guess}`;

  // FR-5.7: the link result is always shown
  const b = $("banner");
  const t = wr.link.template;
  const about = t ? `${t.document_type} · ${t.region ?? "No region"} · ${t.format}` : "";
  const text: Record<WorkingResult["link"]["outcome"], string> = {
    linked: `Linked to template: ${about}`,
    ambiguous: "Several templates match — choose one",
    similar: `Similar to template: ${about}. Check the suggested names.`,
    none: "No matching template. Verify the fields, then save as a new template.",
  };
  $("banner-text").textContent = wr.verified
    ? "Verified. The output is ready to download; any change needs a new Verify."
    : text[wr.link.outcome];
  b.className = `banner ${wr.link.outcome}`;
  const change = $<HTMLButtonElement>("link-change");
  change.hidden = !backend.live || (wr.link.outcome === "none" && templateCount() === 0);
  change.textContent = wr.link.outcome === "ambiguous" ? "Choose template" : "Change template";
  $("mode").textContent = `${wr.document.source_file}${backend.live ? "" : " · fixture mode, synthetic sample"}`;
  fillNameOptions();
}

// ---- templates known to the window: names only (FR-6.5) --------------------------------------
async function loadTemplates(): Promise<void> {
  state.groups = await backend.templates().catch(() => []);
}

function allTemplates(): TemplateSummary[] {
  return state.groups.flatMap((g) => g.regions.flatMap((r) => r.formats));
}

function templateCount(): number {
  return allTemplates().length;
}

function fillNameOptions(): void {
  // FR-6.5: names used in other templates of the same document type
  const type = state.wr?.header.document_type?.toLowerCase();
  const names = new Set<string>();
  for (const t of allTemplates()) {
    if (type && t.document_type.toLowerCase() === type) t.field_names.forEach((n) => names.add(n));
  }
  $("name-options").replaceChildren(
    ...[...names].sort().map((n) => {
      const o = el("option");
      o.value = n;
      return o;
    }),
  );
}

function nextFormat(type: string, region: string | null): string {
  const used = new Set(
    allTemplates()
      .filter((t) => t.document_type.toLowerCase() === type.toLowerCase() && t.region === region)
      .map((t) => t.format.toLowerCase()),
  );
  for (const letter of "ABCDEFGHIJKLMNOPQRSTUVWXYZ") {
    if (!used.has(`format ${letter.toLowerCase()}`)) return `Format ${letter}`;
  }
  return `Format ${used.size + 1}`;
}

function describeTemplate(t: TemplateInfo): string {
  return `${t.document_type} · ${t.region ?? "No region"} · ${t.format} (v${t.version})`;
}

function setHeader(body: Record<string, string>): void {
  void attempt(async () => {
    state.wr!.header = await backend.setHeader(state.docId!, body);
    changed();
    renderHeader();
  });
}

// ---- verify, save, output (FR-6.11, FR-6.12, FR-8.5) -----------------------------------------
async function openSummary(): Promise<void> {
  await attempt(async () => {
    const s = await backend.verify(state.docId!);
    $("summary-text").textContent =
      `${s.fields} fields · ${s.not_found} not found · ${s.needs_review} needs review · ${s.not_translated} not translated`;
    const issues = $("summary-issues");
    issues.replaceChildren(
      ...s.duplicates.map((d) => el("li", "blocking", `More than one field is named "${d}". Rename or remove one.`)),
    );
    $<HTMLButtonElement>("summary-confirm").disabled = !s.can_confirm; // FR-6.16
    state.summary = s;
    $<HTMLDialogElement>("summary").showModal();
  });
}

async function confirmSummary(): Promise<void> {
  $<HTMLDialogElement>("summary").close();
  const s = state.summary;
  if (!s) return;
  if (!s.save_dialog_needed) {
    // FR-6.12: the linked template was used as it is; the server already confirmed it.
    await attempt(async () => {
      state.wr = await backend.result(state.docId!);
      renderHeader();
      $<HTMLDialogElement>("done").showModal();
    });
    return;
  }
  openSave(s);
}

// ---- save dialog (FR-7.1 to FR-7.6, UX-3) ------------------------------------------------------
function saveChoice(): SaveBody["choice"] | null {
  const checked = document.querySelector<HTMLInputElement>('input[name="save-choice"]:checked');
  return (checked?.value as SaveBody["choice"] | undefined) ?? null;
}

function openSave(s: VerifySummary): void {
  const wr = state.wr!;
  const choices = s.save_choices;
  for (const value of ["new", "update", "document_only"] as const) {
    const radio = document.querySelector<HTMLInputElement>(`input[name="save-choice"][value="${value}"]`)!;
    radio.disabled = !choices[value];
    radio.checked = value === (choices[s.suggested ?? "new"] ? s.suggested : "document_only");
    radio.closest("label")?.classList.toggle("disabled", radio.disabled);
  }
  // FR-7.2: the suggested choice is labelled
  $("choice-new").querySelector<HTMLElement>(".marker")!.hidden = s.suggested !== "new";
  $("choice-update").querySelector<HTMLElement>(".marker")!.hidden = s.suggested !== "update";

  const type = noLeakInput($<HTMLInputElement>("save-type"));
  type.value = wr.header.document_type ?? "";
  $("type-options").replaceChildren(
    ...(s.document_types ?? []).map((n) => {
      const o = el("option");
      o.value = n;
      return o;
    }),
  );
  const region = noLeakInput($<HTMLSelectElement>("save-region"));
  region.replaceChildren(...[...$<HTMLSelectElement>("region").options].map((o) => o.cloneNode(true)));
  region.value = wr.header.region ?? "";
  const fmt = noLeakInput($<HTMLInputElement>("save-format"));
  fmt.value = s.format_suggestion ?? nextFormat(type.value, region.value || null);
  fmt.dataset.auto = "1"; // follows type and region until the user types a name

  const target = noLeakInput($<HTMLSelectElement>("save-target"));
  target.replaceChildren(
    ...(s.update_targets ?? []).map((t) => {
      const o = el("option", "", describeTemplate(t));
      o.value = t.template_id;
      return o;
    }),
  );
  saveSummary = s;
  renderChanges(s);
  syncSave();
  $<HTMLDialogElement>("save").showModal();
}

let saveSummary: VerifySummary | null = null;

/** Fixed printed lines that help recognise the form (M3 fix). They are written to disk, so each
 * is listed with a box to leave it out: a line that was never a field could still be personal. */
function renderLandmarks(): void {
  const choice = saveChoice();
  const lines = choice === "new" || choice === "update" ? (saveSummary?.landmarks?.[choice] ?? []) : [];
  const box = $("save-landmarks");
  const before = new Set(uncheckedLandmarks());
  box.replaceChildren();
  if (lines.length) {
    box.append(el("h3", "", "Fixed text stored to recognise this form (untick anything personal)"));
    for (const text of lines) {
      const label = el("label", "choice");
      const cb = el("input");
      cb.type = "checkbox";
      cb.checked = !before.has(text);
      cb.dataset.landmark = text;
      cb.addEventListener("change", syncUnlinkable);
      label.append(cb, ` ${text}`);
      box.append(label);
    }
  }
  syncUnlinkable();
}

function uncheckedLandmarks(): string[] {
  return [...document.querySelectorAll<HTMLInputElement>("#save-landmarks input[data-landmark]")]
    .filter((cb) => !cb.checked)
    .map((cb) => cb.dataset.landmark!);
}

function syncUnlinkable(): void {
  const choice = saveChoice();
  const kept = document.querySelectorAll("#save-landmarks input[data-landmark]:checked").length;
  $("save-unlinkable").hidden =
    !(choice === "new" || choice === "update") || (saveSummary?.labels ?? []).length > 0 || kept > 0;
}

function renderChanges(s: VerifySummary): void {
  const c = s.changes;
  const box = $("save-changes");
  box.replaceChildren();
  const list = (title: string, items: string[]) => {
    if (!items.length) return;
    const ul = el("ul");
    ul.append(...items.map((i) => el("li", "", i)));
    box.append(el("h3", "", title), ul);
  };
  if (c) {
    list("Renamed", c.renamed.map(([a, b]) => `${a ?? "(no label)"} → ${b}`));
    list("Added", c.added);
    list("Removed", c.removed);
    list("Value type changed", c.type_changed);
  }
  // FR-7.1: every printed label that will be stored, since these are written to disk
  list("Printed labels stored as anchors", s.labels ?? []);
}

function syncSave(): void {
  const choice = saveChoice();
  const isNew = choice === "new";
  $("new-inputs").classList.toggle("off", !isNew);
  $("update-inputs").classList.toggle("off", choice !== "update");
  // UX-3: type and region are editable only for a new template
  for (const id of ["save-type", "save-region", "save-format"]) $<HTMLInputElement>(id).disabled = !isNew;
  $<HTMLSelectElement>("save-target").disabled = choice !== "update";
  const fmt = $<HTMLInputElement>("save-format");
  if (isNew && fmt.dataset.auto) {
    fmt.value = nextFormat($<HTMLInputElement>("save-type").value.trim(), $<HTMLSelectElement>("save-region").value || null);
  }
  const ready =
    choice === "document_only" ||
    (choice === "update" && !!$<HTMLSelectElement>("save-target").value) ||
    (isNew && !!$<HTMLInputElement>("save-type").value.trim() && !!fmt.value.trim());
  $<HTMLButtonElement>("save-confirm").disabled = !ready;
  renderLandmarks();
}

async function confirmSave(): Promise<void> {
  const choice = saveChoice();
  if (!choice) return;
  const body: SaveBody = { choice, landmarks_excluded: uncheckedLandmarks() };
  if (choice === "new") {
    body.document_type = $<HTMLInputElement>("save-type").value.trim();
    body.region = $<HTMLSelectElement>("save-region").value;
    body.format = $<HTMLInputElement>("save-format").value.trim();
  } else if (choice === "update") {
    body.template_id = $<HTMLSelectElement>("save-target").value;
  }
  await attempt(async () => {
    await backend.save(state.docId!, body);
    $<HTMLDialogElement>("save").close();
    if (backend.live) {
      state.wr = await backend.result(state.docId!); // header now names the saved template
      await loadTemplates();
    } else {
      state.wr!.verified = true;
    }
    render();
    $<HTMLDialogElement>("done").showModal();
  });
}

// ---- change the link (FR-5.8) ------------------------------------------------------------------
function openLink(): void {
  const wr = state.wr!;
  const offered: TemplateInfo[] = wr.link.candidates.length ? wr.link.candidates : allTemplates();
  const box = $("link-choices");
  const option = (value: string, text: string, checked: boolean) => {
    const label = el("label", "choice");
    const radio = el("input");
    radio.type = "radio";
    radio.name = "link-choice";
    radio.value = value;
    radio.checked = checked;
    label.append(radio, ` ${text}`);
    return label;
  };
  const score = (t: TemplateInfo) => {
    const c = wr.link.candidates.find((x) => x.template_id === t.template_id);
    return c ? ` — match ${Math.round(c.score * 100)}%` : "";
  };
  box.replaceChildren(
    el("legend", "", "Template"),
    ...offered.map((t, i) =>
      option(t.template_id, `${describeTemplate(t)}${score(t)}`, wr.link.template_id ? t.template_id === wr.link.template_id : i === 0),
    ),
    option("", "No template: find the fields again", offered.length === 0),
  );
  $<HTMLDialogElement>("link-dialog").showModal();
}

async function confirmLink(): Promise<void> {
  const picked = document.querySelector<HTMLInputElement>('input[name="link-choice"]:checked');
  if (!picked) return;
  $<HTMLDialogElement>("link-dialog").close();
  const id = state.docId!;
  await attempt(async () => {
    await backend.relink(id, picked.value || null);
    await follow(id);
  });
}

// ---- template manager (FR-7.9 to FR-7.12, UX-4) ------------------------------------------------
function askConfirm(text: string, action: string): Promise<boolean> {
  const dialog = $<HTMLDialogElement>("confirm-dialog");
  $("confirm-text").textContent = text;
  $("confirm-yes").textContent = action;
  dialog.showModal();
  return new Promise((resolve) => {
    const done = (ok: boolean) => {
      $("confirm-yes").onclick = null;
      $("confirm-no").onclick = null;
      dialog.close();
      resolve(ok);
    };
    $("confirm-yes").onclick = () => done(true);
    $("confirm-no").onclick = () => done(false);
  });
}

async function showFirstRun(): Promise<void> {
  const info = await backend.firstRun().catch(() => null);
  if (!info?.show) return;
  const model = info.model
    ? `Model ${info.model}` +
      (info.model_size_gb ? `: ${info.model_size_gb} GB on disk` : "") +
      (info.seconds_per_page ? `, about ${Math.round(info.seconds_per_page)} s per page on this machine` : "") +
      ". Saved templates make repeat documents fast."
    : "No local AI model installed. Digital files and saved templates still work.";
  $("fr-model").textContent = model;
  $("fr-store").textContent = info.store;
  const dialog = $<HTMLDialogElement>("first-run-dialog");
  dialog.showModal();
  $("fr-ok").onclick = () => {
    dialog.close();
    void backend.firstRunSeen();
  };
}

async function quitNabu(): Promise<void> {
  if (state.docId && !(await askConfirm("Quit Nabu? The open document is closed and not kept.", "Quit"))) return;
  await backend.quit().catch(() => undefined);
  document.body.replaceChildren();
  const p = document.createElement("p");
  p.className = "stopped";
  p.textContent = "Nabu has stopped. You can close this tab. Open Nabu again from its shortcut.";
  document.body.append(p);
}

function askRename(what: string, current: string): Promise<string | null> {
  const dialog = $<HTMLDialogElement>("rename-dialog");
  const input = noLeakInput($<HTMLInputElement>("rename-input"));
  $("rename-what").textContent = what;
  $("rename-title").textContent = `Rename ${what.toLowerCase()}`;
  input.value = current;
  dialog.showModal();
  input.select();
  return new Promise((resolve) => {
    const form = $<HTMLFormElement>("rename-form");
    const done = (value: string | null) => {
      form.onsubmit = null;
      $("rename-cancel").onclick = null;
      dialog.close();
      resolve(value && value.trim() && value.trim() !== current ? value.trim() : null);
    };
    form.onsubmit = (e) => {
      e.preventDefault();
      done(input.value);
    };
    $("rename-cancel").onclick = () => done(null);
  });
}

async function openTemplates(): Promise<void> {
  await attempt(async () => {
    state.groups = await backend.templates(); // errors shown, not read as "no templates"
    renderTree(null);
    await renderTranslations();
    $<HTMLDialogElement>("tm-dialog").showModal();
  });
}

function renderTree(selected: string | null): void {
  const tree = $("tm-tree");
  if (!state.groups.length) {
    tree.replaceChildren(
      el("p", "muted", backend.live ? "No templates yet. Verify a document and save it as a new template." : "Fixture mode has no templates."),
    );
    $("tm-detail").replaceChildren();
    return;
  }
  tree.replaceChildren(
    ...state.groups.map((g) => {
      const d = el("details");
      d.open = true;
      d.append(el("summary", "", g.document_type));
      for (const r of g.regions) {
        const region = el("div", "tm-region", r.region ? `${regionNames?.of(r.region) ?? r.region} (${r.region})` : "No region");
        const ul = el("ul");
        for (const t of r.formats) {
          const li = el("li");
          const b = el("button", `tm-format ${t.template_id === selected ? "selected" : ""}`, t.format);
          b.type = "button";
          b.append(el("span", "muted", ` v${t.version} · ${t.fields} fields · ${shortDate(t.updated_at)}`));
          b.addEventListener("click", () => void showTemplate(t.template_id));
          li.append(b);
          ul.append(li);
        }
        d.append(region, ul);
      }
      return d;
    }),
  );
}

function shortDate(iso: string | null): string {
  return iso ? iso.slice(0, 10) : "";
}

async function showTemplate(tid: string): Promise<void> {
  await attempt(async () => {
    const t = await backend.template(tid);
    renderTree(tid);
    const h = t.template;
    const detail = $("tm-detail");
    const title = el("h3", "", `${h.document_type} · ${h.region ?? "No region"} · ${h.format.name}`);
    const meta = el("p", "muted", `Version ${h.version}${h.updated_at ? ` · updated ${shortDate(h.updated_at)}` : ""}`);
    const table = el("table", "tm-fields");
    const head = el("tr");
    head.append(el("th", "", "Field name"), el("th", "", "Value type"), el("th", "", "Printed label"));
    table.append(head);
    for (const f of t.fields) {
      const row = el("tr");
      row.append(el("td", "", f.name), el("td", "", f.value_type), el("td", "", f.anchor.printed_label ?? "(drawn box)"));
      table.append(row);
    }
    const actions = el("div", "tm-actions");
    const button = (text: string, fn: () => Promise<void>, cls = "") => {
      const b = el("button", cls, text);
      b.type = "button";
      b.addEventListener("click", () => void attempt(fn));
      actions.append(b);
    };
    button("Rename format", async () => {
      const name = await askRename("Format", h.format.name);
      if (name) await afterChange(await backend.renameTemplate(tid, { format: name }), tid);
    });
    button("Rename document type", async () => {
      const name = await askRename("Document type", h.document_type);
      if (name) await afterChange(await backend.renameTemplate(tid, { document_type: name }), tid);
    });
    button("History", () => showHistory(tid));
    button(
      "Delete",
      async () => {
        // FR-7.10: the confirmation names the template
        const what = `${h.document_type} · ${h.region ?? "No region"} · ${h.format.name}`;
        if (!(await askConfirm(`Delete the template "${what}" and its earlier versions? This cannot be undone.`, "Delete"))) return;
        await backend.deleteTemplate(tid);
        await loadTemplates();
        renderTree(null);
        $("tm-detail").replaceChildren(el("p", "muted", `Deleted "${what}".`));
        if (state.wr) renderHeader();
      },
      "danger",
    );
    const removed = t.removed_labels.length
      ? el("p", "muted", `Hidden on future documents: ${t.removed_labels.join(", ")}`)
      : el("span");
    detail.replaceChildren(title, meta, table, removed, actions, el("div", "tm-history"));
  });
}

async function afterChange(_t: unknown, tid: string): Promise<void> {
  await loadTemplates();
  await showTemplate(tid);
  if (state.wr) renderHeader();
}

async function showHistory(tid: string): Promise<void> {
  const versions = await backend.history(tid);
  const box = $("tm-detail").querySelector(".tm-history")!;
  const ul = el("ul", "history");
  for (const v of [...versions].reverse()) {
    const li = el("li");
    li.append(el("span", "", `v${v.version} · ${shortDate(v.updated_at)} · ${describeChange(v)}${v.current ? " (current)" : ""}`));
    if (!v.current) {
      const b = el("button", "link", "Roll back to this version");
      b.type = "button";
      b.addEventListener("click", () =>
        void attempt(async () => {
          if (!(await askConfirm(`Restore the field names of version ${v.version}? This is saved as a new version.`, "Roll back"))) return;
          await afterChange(await backend.rollback(tid, v.version), tid);
          await showHistory(tid);
        }),
      );
      li.append(b);
    }
    ul.append(li);
  }
  box.replaceChildren(el("h3", "", "History"), ul);
}

function describeChange(v: HistoryEntry): string {
  const c = v.change;
  if (!c) return "";
  if (c.kind === "rolled_back") return `rolled back to v${c.to_version}`;
  if (c.kind === "renamed") {
    const [a, b] = c.format ?? c.document_type ?? ["?", "?"];
    return `renamed ${a} → ${b}`;
  }
  const parts = [c.kind ?? "changed"];
  for (const [a, b] of c.renamed ?? []) parts.push(`renamed ${a ?? "?"} → ${b}`);
  for (const n of c.added ?? []) parts.push(`added ${n}`);
  for (const n of c.removed ?? []) parts.push(`removed ${n}`);
  for (const n of c.type_changed ?? []) parts.push(`type of ${n}`);
  if (c.reordered) parts.push("reordered");
  return parts.join("; ");
}

async function renderTranslations(): Promise<void> {
  const entries = await backend.translations().catch(() => []);
  $("tr-count").textContent = String(entries.length);
  $("tr-list").replaceChildren(
    ...entries.map((e) => {
      const li = el("li");
      const b = el("button", "link", "Delete");
      b.type = "button";
      b.setAttribute("aria-label", `Delete the translation of ${e.term}`);
      b.addEventListener("click", () =>
        void attempt(async () => {
          await backend.deleteTranslation(e.id);
          await renderTranslations();
        }),
      );
      li.append(el("span", "", `${e.term} (${e.lang.toUpperCase()}) → ${e.english} `), b);
      return li;
    }),
  );
}

function downloadName(source: string): string {
  return source.replace(/ \(\+\d+ images?\)$/, "").replace(/[\\/:*?"<>|\u0000-\u001f]/g, "_") + ".nabu.json";
}

async function download(): Promise<void> {
  await attempt(async () => {
    const blob = await backend.output(state.docId!);
    const url = URL.createObjectURL(blob);
    const a = el("a");
    a.href = url;
    a.download = downloadName(state.wr!.document.source_file);
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
}

function wire(): void {
  $("quit").addEventListener("click", () => void quitNabu());
  // upload
  const input = $<HTMLInputElement>("file-input");
  $("choose").addEventListener("click", () => input.click());
  input.addEventListener("change", () => {
    choose(input.files);
    input.value = "";
  });
  const drop = $("drop");
  drop.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      input.click();
    }
  });
  drop.addEventListener("dragover", (e) => {
    e.preventDefault();
    drop.classList.add("over");
  });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => {
    e.preventDefault();
    drop.classList.remove("over");
    choose(e.dataTransfer?.files ?? null);
  });
  $("chosen-clear").addEventListener("click", () => {
    state.chosen = [];
    renderChosen();
  });
  $("read").addEventListener("click", () => void startReading());
  $("cancel").addEventListener("click", () => void attempt(() => closeDocument()));

  // page
  $("page-prev").addEventListener("click", () => movePage(-1));
  $("page-next").addEventListener("click", () => movePage(1));
  $("page-earlier").addEventListener("click", () => reorder(-1));
  $("page-later").addEventListener("click", () => reorder(1));
  $("draw").addEventListener("click", () => setDrawing(!state.drawing));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && state.drawing) setDrawing(false);
  });
  wireDrawing();

  // header
  const dt = $<HTMLInputElement>("doc-type");
  dt.addEventListener("change", () => setHeader({ document_type: dt.value.trim() }));
  const rg = $<HTMLSelectElement>("region");
  rg.addEventListener("change", () => setHeader({ region: rg.value }));
  $("doc-type-guess").addEventListener("click", () => setHeader({ document_type: state.wr?.type_guess ?? "" }));
  $("region-guess").addEventListener("click", () => setHeader({ region: state.wr?.country_guess ?? "" }));

  // list
  $<HTMLInputElement>("order-toggle").addEventListener("change", (e) => {
    state.documentOrder = (e.target as HTMLInputElement).checked;
    renderFields();
  });
  $<HTMLInputElement>("lang-toggle").addEventListener("change", (e) => {
    state.showOriginals = (e.target as HTMLInputElement).checked;
    renderFields();
  });
  $("fields").addEventListener("keydown", (e) => {
    // Arrow keys move between rows (UX-2.2).
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    if ((e.target as HTMLElement).tagName !== "LI") return;
    const rows = [...document.querySelectorAll<HTMLElement>("li.field")];
    const next = rows[rows.indexOf(e.target as HTMLElement) + (e.key === "ArrowDown" ? 1 : -1)];
    if (next) {
      e.preventDefault();
      next.focus();
    }
  });

  // verify -> save -> output
  $("verify").addEventListener("click", () => void openSummary());
  $("summary-back").addEventListener("click", () => $<HTMLDialogElement>("summary").close());
  $("summary-confirm").addEventListener("click", () => void confirmSummary());
  // FR-7.6: Cancel saves nothing
  $("save-cancel").addEventListener("click", () => $<HTMLDialogElement>("save").close());
  $("save-confirm").addEventListener("click", () => void confirmSave());
  document.querySelectorAll('input[name="save-choice"]').forEach((r) => r.addEventListener("change", syncSave));
  $("save-type").addEventListener("input", syncSave);
  $("save-region").addEventListener("change", syncSave);
  $("save-format").addEventListener("input", () => {
    delete $("save-format").dataset.auto;
    syncSave();
  });
  $("save-target").addEventListener("change", syncSave);

  // link and templates
  $("link-change").addEventListener("click", openLink);
  $("link-cancel").addEventListener("click", () => $<HTMLDialogElement>("link-dialog").close());
  $("link-confirm").addEventListener("click", () => void confirmLink());
  $("templates-open").addEventListener("click", () => void openTemplates());
  $("tm-close").addEventListener("click", () => $<HTMLDialogElement>("tm-dialog").close());
  $("download").addEventListener("click", () => void download());
  $("done-back").addEventListener("click", () => $<HTMLDialogElement>("done").close());
  $("done-close").addEventListener("click", () => {
    $<HTMLDialogElement>("done").close();
    void closeDocument();
  });
  $("close-doc").addEventListener("click", () => void closeDocument());
}

function movePage(step: number): void {
  const pages = state.wr!.document.pages;
  const i = pages.indexOf(currentPage()) + step;
  if (i < 0 || i >= pages.length) return;
  state.page = pages[i].n;
  renderPage();
}

function reorder(step: number): void {
  const pages = state.wr!.document.pages.map((p) => p.n);
  const i = pages.indexOf(state.page);
  const j = i + step;
  if (j < 0 || j >= pages.length) return;
  [pages[i], pages[j]] = [pages[j], pages[i]];
  void attempt(async () => {
    state.wr = await backend.reorder(state.docId!, pages);
    // Page numbers changed: reload the images under their new numbers.
    await loadResult();
    state.page = j + 1;
    renderPage();
  });
}

function render(): void {
  renderHeader();
  renderPage();
  renderFields();
}

async function start(): Promise<void> {
  fillRegions();
  wire();
  if (fixtureMode) {
    state.docId = "fixture";
    await loadResult();
    return;
  }
  $("mode").textContent = "Local · nothing leaves this machine";
  $("quit").hidden = false;
  void showFirstRun();
  // A reloaded window resumes the open document instead of being locked out of a new one.
  const open = await backend.current().catch(() => ({ document_id: null, state: null }));
  if (open.document_id && (open.state === "ready" || open.state === "reading")) {
    await follow(open.document_id);
    return;
  }
  if (open.document_id) {
    state.docId = open.document_id;
    await closeDocument();
    return;
  }
  show("upload");
}

void start();
