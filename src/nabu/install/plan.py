"""What the installer will do, decided from detections alone (§7.6). Pure: no I/O.

The same facts give the same plan, word for word, so `--dry-run` twice prints the same text
(FR-1.8 acceptance). Numbers that drift between runs (free RAM, exact free disk) are rounded or
left out of the printed plan.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from nabu.install.pins import MODELS, Artefact, runtime_artefact
from nabu.model.runtime import same_model
from nabu.model.tiers import Tier, recommend

GB = 10**9
DISK_MARGIN = 2 * GB  # MH-4
TARGET_LANGS = ("en", "ko")  # Q4


@dataclass(frozen=True)
class Facts:
    system: str  # platform.system()
    arch: str
    cpu_cores: int | None
    ram_gb: float | None
    vram_gb: float | None  # largest NVIDIA GPU, None when none is detected
    disk_free_bytes: int
    runtime_answers: bool
    runtime_program: str | None  # path of an installed runtime that is not answering
    models: dict[str, str]  # installed model -> digest
    configured_model: str | None
    ocr_present: bool
    ocr_langs: tuple[str, ...]  # installed packs
    pack_sizes_mb: dict[str, float]
    shortcut: Path | None  # where the shortcut goes; None when the platform has no menu
    shortcut_exists: bool
    model_store: str  # where the runtime keeps model weights
    download_dir: Path


@dataclass(frozen=True)
class Choices:
    model: str | None = "auto"  # "auto", a model name, or None for no-model mode
    langs: tuple[str, ...] | None = None  # None: offer the target languages
    shortcut: bool = True


@dataclass
class Step:
    kind: str
    text: str
    command: list[str] | None = None  # printed in full before it runs (FR-1.6)
    download_bytes: int = 0
    consent: str | None = None  # the question asked before this step runs


@dataclass
class Plan:
    tier: Tier
    model: str | None  # the model Nabu will use; None = no-model mode
    reuse_model: bool
    runtime: Artefact | None  # runtime to download, if any
    lang_packs: list[str]
    steps: list[Step] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def gb(n: int | float) -> str:
    return f"{n / GB:.1f} GB"


def _installed(facts: Facts, name: str) -> str | None:
    return next((m for m in facts.models if same_model(m, name)), None)


def _pick_model(facts: Facts, choices: Choices, tier: Tier) -> str | None:
    if choices.model is None:
        return None
    if choices.model != "auto":
        return choices.model
    # A re-run keeps the model the user already set up (FR-1.2, FR-1.3).
    if facts.configured_model and _installed(facts, facts.configured_model):
        return facts.configured_model
    return tier.model


def make_plan(facts: Facts, choices: Choices) -> Plan:
    tier = recommend(facts.ram_gb, facts.vram_gb)
    model = _pick_model(facts, choices, tier)
    reuse = bool(model) and _installed(facts, model or "") is not None
    plan = Plan(tier=tier, model=model, reuse_model=reuse, runtime=None, lang_packs=[])
    steps, notes = plan.steps, plan.notes

    # Runtime
    if model is None:
        steps.append(Step("no-model", "No model: Nabu installs in no-model mode. Digital files and "
                          "saved templates still work; scans without a template and translation "
                          "need a model (FR-3.4). Add one later with: nabu models pull <name>"))
        if tier.offered and choices.model == "auto":
            notes.append(f"This machine is below the smallest tier; {tier.offered} can be added later.")
    elif facts.runtime_answers:
        steps.append(Step("runtime", "Model runtime (Ollama) is running: reused, not changed."))
    elif facts.runtime_program:
        steps.append(Step("runtime-start", "Ollama is installed but not running: start it.",
                          command=[facts.runtime_program, "serve"]))
    else:
        art = runtime_artefact(facts.system, facts.arch)
        if art is None:
            steps.append(Step("runtime-manual", f"No pinned Ollama build for {facts.system} "
                              f"{facts.arch}. Install Ollama yourself from ollama.com, then run "
                              "this installer again."))
            plan.model = None
            return _finish(plan, facts, choices)
        plan.runtime = art
        dest = facts.download_dir / art.url.rsplit("/", 1)[-1]
        steps.append(Step("runtime-download",
                          f"Download Ollama {art.url.rsplit('/', 1)[-1]} ({gb(art.size_bytes)}) and "
                          "check its sha256 against the value shipped with Nabu.",
                          download_bytes=art.size_bytes))
        steps.append(Step("runtime-install", "Install Ollama for this user (no admin rights).",
                          command=runtime_install_command(facts.system, dest)))
        steps.append(Step("runtime-health", "Check that the runtime answers a request (FR-1.7)."))

    # Model
    if model is not None:
        pin = MODELS.get(model)
        if reuse:
            have = facts.models[_installed(facts, model) or model]
            match = pin is None or have == pin.digest
            steps.append(Step("model-reuse", f"Model {model} is already installed: no download."
                              + ("" if match else " Its digest differs from the one pinned for "
                                 "Nabu (a newer or older build); it is kept as it is.")))
        elif pin is None:
            steps.append(Step("model-unpinned", f"{model} has no pinned digest in this Nabu "
                              "version, so it cannot be checked. Pull it yourself with "
                              f"`nabu models pull {model}` if you trust it."))
            plan.model = None
        else:
            need = pin.size_bytes + (plan.runtime.size_bytes if plan.runtime else 0) + DISK_MARGIN
            if facts.disk_free_bytes < need:
                steps.append(Step("disk-low", f"Not enough free disk for {model}: needs "
                                  f"{gb(need)} (download plus 2 GB), {gb(facts.disk_free_bytes)} "
                                  "free. Installing in no-model mode instead (MH-4)."))
                plan.model = None
                plan.runtime = None
                steps[:] = [s for s in steps if not s.kind.startswith("runtime")]
            else:
                steps.append(Step(
                    "model-pull", f"Download model {model} ({gb(pin.size_bytes)}) into "
                    f"{facts.model_store}, then check its digest and that it reads an image.",
                    download_bytes=pin.size_bytes))
        if plan.model and tier.model and not same_model(plan.model, tier.model) \
                and choices.model == "auto":
            notes.append(f"Recommended for this machine: {tier.model} ({tier.hardware}).")
    return _finish(plan, facts, choices)


def _finish(plan: Plan, facts: Facts, choices: Choices) -> Plan:
    steps = plan.steps
    downloads = sum(s.download_bytes for s in steps)
    if downloads:
        steps[0:0] = [Step("consent", "", consent=(
            f"Download {gb(downloads)} in total"
            + (f" ({plan.model}: {gb(MODELS[plan.model].size_bytes)} on disk, "
               f"stored in {facts.model_store})" if plan.model in MODELS else "")
            + f". Free disk: {gb(facts.disk_free_bytes)}. Continue?"))]

    # OCR
    if not facts.ocr_present:
        steps.append(Step("ocr-missing", "The OCR engine is not installed; scans cannot be read. "
                          "Reinstall Nabu with the reading extra (nabu[read])."))
    else:
        wanted = TARGET_LANGS if choices.langs is None else choices.langs
        missing = [x for x in wanted if x in facts.pack_sizes_mb and x not in facts.ocr_langs]
        have = [x for x in wanted if x in facts.ocr_langs or x not in facts.pack_sizes_mb]
        if have:
            steps.append(Step("ocr", f"OCR engine present; reads {', '.join(have)} already."))
        for lang in missing:
            plan.lang_packs.append(lang)
            steps.append(Step("lang-pack", f"Download the OCR pack for {lang} "
                              f"({facts.pack_sizes_mb[lang]} MB, checksum checked).",
                              command=["nabu", "langs", "pull", lang],
                              consent=f"Download the {lang} OCR pack ({facts.pack_sizes_mb[lang]} "
                                      "MB)?"))

    # Config, shortcut, sample
    steps.append(Step("config", "Write config: model = "
                      + (plan.model or "none (no-model mode)") + "."))
    if choices.shortcut and facts.shortcut is not None:
        steps.append(Step("shortcut", ("Shortcut already in place: " if facts.shortcut_exists
                                       else "Add the Nabu shortcut: ") + str(facts.shortcut)))
    steps.append(Step("sample", "Read the bundled synthetic sample and show the result (FR-1.10)."))
    return plan


def runtime_install_command(system: str, dest: Path) -> list[str]:
    if system == "Windows":
        # Inno Setup, PrivilegesRequired=lowest: installs under %LOCALAPPDATA%\Programs\Ollama.
        return [str(dest), "/VERYSILENT", "/NORESTART", "/SUPPRESSMSGBOXES"]
    if system == "Darwin":
        return ["tar", "-xzf", str(dest), "-C", str(Path.home() / "Applications")]
    return ["tar", "--zstd", "-xf", str(dest), "-C", str(Path.home() / ".local")]


def render(facts: Facts, plan: Plan) -> list[str]:
    """The detections and the plan, as printed by --dry-run and before a real run."""
    gpu = f"{facts.vram_gb} GB VRAM" if facts.vram_gb else "none detected"
    runtime = ("Ollama answering" if facts.runtime_answers
               else "installed, not running" if facts.runtime_program else "not found")
    lines = [
        "Detected:",
        f"  system      {facts.system} {facts.arch}, {facts.cpu_cores or '?'} cores",
        f"  memory      {facts.ram_gb or '?'} GB RAM; GPU {gpu}",
        f"  disk free   {facts.disk_free_bytes // GB} GB",
        f"  runtime     {runtime}",
        f"  models      {', '.join(sorted(facts.models)) or 'none'}",
        f"  OCR         {'present' if facts.ocr_present else 'missing'}"
        + (f"; packs {', '.join(facts.ocr_langs)}" if facts.ocr_langs else ""),
        f"  tier        {plan.tier.hardware} -> {plan.tier.model or 'no model'}",
        "",
        "Plan:",
    ]
    n = 0
    for s in plan.steps:
        if s.kind == "consent":
            lines.append(f"  ? {s.consent}")
            continue
        n += 1
        lines.append(f"  {n}. {s.text}")
        if s.command:
            lines.append("     $ " + " ".join(f'"{c}"' if " " in c else c for c in s.command))
    lines += [f"  note: {x}" for x in plan.notes]
    return lines
