import base64
import io
import json

import pytest
from PIL import Image
from stub_ollama import StubOllama

from nabu.config import Config
from nabu.errors import ConfigError, ModelNotFound, ModelOutputInvalid, ModelUnavailable, NabuError
from nabu.model import images
from nabu.model.client import ModelClient, build_client
from nabu.model.evaluate import evaluate
from nabu.model.http import LoopbackHttp
from nabu.model.profiles import GENERIC, ModelProfile, resolve_profile
from nabu.model.runtime import same_model
from nabu.model.tiers import recommend
from nabu.model.types import CropField, PageImage, TranslateItem

SECRET = "RE-2026-0412"


def png(w=400, h=600) -> PageImage:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(buf, format="PNG")
    return PageImage(data=buf.getvalue(), width_px=w, height_px=h)


def discovery(**over) -> str:
    body = {"type_guess": "Invoice", "country_guess": "de", "fields": [
        {"label": "Rechnungsnr.", "value": SECRET, "value_type": "id",
         "bbox": [100, 50, 300, 70], "confidence": 0.9}]}
    body.update(over)
    return json.dumps(body)


def client(stub, model="stub-vl:test", runtime="ollama", **cfg) -> ModelClient:
    return ModelClient(Config(model=model, model_endpoint=stub.url, model_runtime=runtime, **cfg))


def posts(stub):
    return [c for c in stub.calls if c[0] == "POST"]


# ---- profiles ---------------------------------------------------------------------------
@pytest.mark.parametrize("model,profile", [
    ("qwen3.5:4b", "qwen3.5"), ("Qwen/Qwen3.5-4B", "qwen3.5"), ("qwen3-vl:8b", "qwen3-vl"),
    ("gemma4:e4b", "gemma4"), ("granite3.2-vision", "granite-vision"), ("brand-new-vlm:7b", "generic"),
])
def test_profile_picked_by_model_name(model, profile):
    assert resolve_profile(model).name == profile


def test_user_profile_wins_and_plugs_in_a_new_model():
    mine = ModelProfile(name="my-vlm", match=("brand-new-vlm",), coords="grid_1000")
    assert resolve_profile("brand-new-vlm:7b", custom=[mine]) == mine
    override = ModelProfile(name="qwen3.5-measured", match=("qwen3.5",), coords="pixels")
    assert resolve_profile("qwen3.5:4b", custom=[override]).coords == "pixels"


def test_unknown_profile_name_refused():
    with pytest.raises(ConfigError, match="unknown model_profile"):
        resolve_profile("qwen3.5:4b", "nope")


def test_profiles_from_config_file_shape():
    cfg = Config(model="brand-new-vlm:7b", model_profiles=[
        {"name": "my-vlm", "match": ["brand-new-vlm"], "coords": "unit"}])
    assert resolve_profile(cfg.model, cfg.model_profile, cfg.model_profiles).coords == "unit"


def test_same_model_handles_latest_tag():
    assert same_model("qwen3.5", "qwen3.5:latest")
    assert not same_model("qwen3.5:4b", "qwen3.5:2b")


# ---- coordinates and images ---------------------------------------------------------------
def test_to_grid_per_convention():
    assert images.to_grid((100, 60, 300, 120), "pixels", 400, 600) == (250, 100, 750, 200)
    assert images.to_grid((250, 100, 750, 200), "grid_1000", 400, 600) == (250, 100, 750, 200)
    assert images.to_grid((0.25, 0.1, 0.75, 0.2), "unit", 400, 600) == (250, 100, 750, 200)
    assert images.to_grid((100, 60, 300, 120), "none", 400, 600) is None


def test_to_grid_repairs_or_drops_bad_boxes():
    assert images.to_grid((300, 120, 100, 60), "pixels", 400, 600) == (250, 100, 750, 200)
    assert images.to_grid((-50, 0, 5000, 600), "pixels", 400, 600) == (0, 0, 1000, 1000)
    assert images.to_grid((10, 10, 10, 20), "grid_1000", 400, 600) is None
    assert images.raw_box([1, 2, 3]) is None and images.raw_box("1,2,3,4") is None


def test_crop_box_maps_back_to_page():
    assert images.crop_to_page((0, 0, 1000, 1000), (100, 200, 300, 400)) == (100, 200, 300, 400)
    assert images.crop_to_page((500, 500, 1000, 1000), (100, 200, 300, 400)) == (200, 300, 300, 400)


def test_fit_limits_the_long_edge():
    small = images.fit(png(3000, 2000), 1500)
    assert (small.width_px, small.height_px) == (1500, 1000)
    assert images.image_size(small.data) == (1500, 1000)


def test_damaged_image_is_a_named_error():
    with pytest.raises(NabuError):
        images.fit(PageImage(data=b"not an image", width_px=5000, height_px=5000), 1500)


# ---- tiers ------------------------------------------------------------------------------
@pytest.mark.parametrize("ram,vram,model", [
    (6, None, None), (12, None, "qwen3.5:2b"), (15.8, None, "qwen3.5:4b"), (None, None, "qwen3.5:4b"),
    (64, None, "qwen3.5:9b"), (16, 8, "qwen3.5:9b"), (16, 24, "qwen3.5:27b"),
])
def test_tier_recommendation(ram, vram, model):
    assert recommend(ram, vram).model == model


# ---- client against both runtimes -------------------------------------------------------
@pytest.mark.parametrize("runtime", ["ollama", "openai_compat"])
def test_discover_page_on_both_runtimes(runtime):
    with StubOllama() as stub:
        stub.responses.append(discovery())
        c = client(stub, runtime=runtime)
        d = c.discover_page(png(), "Rechnungsnr. RE-2026-0412")
        c.close()
    assert d.country_guess == "DE" and d.type_guess == "Invoice"
    f = d.fields[0]
    assert (f.label, f.value, f.value_type, f.confidence) == ("Rechnungsnr.", SECRET, "id", 0.9)
    assert f.box is None and f.raw_box == (100, 50, 300, 70)  # generic profile ignores model boxes
    path, body = posts(stub)[0][1:]
    assert path == ("/api/chat" if runtime == "ollama" else "/v1/chat/completions")
    if runtime == "ollama":
        assert body["format"]["required"] == ["type_guess", "country_guess", "fields"]
        assert base64.b64decode(body["messages"][1]["images"][0])[:4] == b"\x89PNG"
    else:
        assert body["response_format"]["type"] == "json_schema"
        assert body["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_answers_are_clamped_not_trusted():
    with StubOllama() as stub:
        stub.responses.append(discovery(country_guess="Germany", fields=[
            {"label": "A", "value": 12, "value_type": "weird", "bbox": "x", "confidence": 7},
            {"label": "", "value": "dropped", "value_type": "text", "bbox": None, "confidence": 1},
            {"label": "B", "value": None, "value_type": "date", "bbox": None}]))
        d = client(stub).discover_page(png(), "")
    assert d.country_guess is None
    assert [(f.label, f.value, f.value_type, f.confidence) for f in d.fields] == [
        ("A", "12", "text", 1.0), ("B", None, "date", 0.0)]


def test_one_repair_attempt_then_success():
    with StubOllama() as stub:
        stub.responses.extend(["Sure! Here are the fields: not json",
                               "```json\n" + discovery() + "\n```"])
        d = client(stub).discover_page(png(), "")
    assert len(d.fields) == 1
    assert "not valid JSON" in posts(stub)[1][2]["messages"][1]["content"]


def test_invalid_twice_is_model_output_invalid():
    with StubOllama() as stub:
        stub.responses.extend(["nope", "still nope", discovery()])
        with pytest.raises(ModelOutputInvalid):
            client(stub).discover_page(png(), "")
        assert len(posts(stub)) == 2  # exactly one repair (FR-3.5)


def test_thinking_turned_off_only_where_the_profile_says():
    with StubOllama(models=["qwen3.5:4b", "stub-vl:test"]) as stub:
        stub.responses.extend([discovery(), discovery()])
        client(stub, model="qwen3.5:4b").discover_page(png(), "")
        client(stub).discover_page(png(), "")
    qwen, generic = (c[2] for c in posts(stub))
    assert qwen["think"] is False and "think" not in generic


def test_structured_output_can_be_switched_off_per_profile():
    with StubOllama() as stub:
        stub.responses.append(discovery())
        client(stub, model_profiles=[{"name": "plain", "match": ["stub-vl"],
                                      "structured_output": False}]).discover_page(png(), "")
    assert "format" not in posts(stub)[0][2]


def test_large_page_is_resized_before_sending():
    with StubOllama() as stub:
        stub.responses.append(discovery())
        client(stub).discover_page(png(3000, 1500), "")
    sent = base64.b64decode(posts(stub)[0][2]["messages"][1]["images"][0])
    assert images.image_size(sent) == (1500, 750)


def test_profile_coords_convert_model_boxes():
    with StubOllama() as stub:
        stub.responses.append(discovery())
        c = client(stub, model_profiles=[{"name": "px", "match": ["stub-vl"], "coords": "pixels"}])
        d = c.discover_page(png(400, 600), "")
    assert d.fields[0].box == (250, 83, 750, 117)


def test_reread_crop_returns_a_page_box():
    with StubOllama() as stub:
        stub.responses.append(json.dumps({"value": SECRET, "bbox": [0, 0, 1000, 1000],
                                          "confidence": 0.8}))
        c = client(stub, model_profiles=[{"name": "g", "match": ["stub-vl"], "coords": "grid_1000"}])
        r = c.reread_crop(png(), (100, 100, 300, 200),
                          CropField(name="Invoice Number", printed_label="Rechnungsnr.", value_type="id"))
    assert r.value == SECRET and r.box == (70, 70, 330, 230)  # crop margin of 30 grid units


def test_translate_keeps_every_item_and_never_guesses():
    with StubOllama() as stub:
        stub.responses.append(json.dumps({"items": [
            {"id": "1", "english": "Invoice number", "status": "translated"},
            {"id": "2", "english": "???", "status": "untranslated"},
            {"id": "x", "english": "not asked", "status": "translated"}]}))
        out = client(stub).translate([TranslateItem("1", "Rechnungsnr."), TranslateItem("2", "Hinweis"),
                                      TranslateItem("3", "Fällig am")], "de", None)
    assert [(t.id, t.english, t.status) for t in out] == [
        ("1", "Invoice number", "translated"), ("2", "Hinweis", "untranslated"),
        ("3", "Fällig am", "untranslated")]


def test_model_not_installed_names_the_fix():
    with StubOllama() as stub:
        stub.fail_next(404, {"error": "model 'qwen3.5:4b' not found"})
        with pytest.raises(ModelNotFound, match="nabu models pull qwen3.5:4b"):
            client(stub, model="qwen3.5:4b").discover_page(png(), "")


def test_out_of_memory_has_its_own_message_and_hides_runtime_text():
    with StubOllama() as stub:
        stub.fail_next(500, {"error": f"model requires more system memory; prompt was {SECRET}"})
        with pytest.raises(ModelUnavailable) as e:
            client(stub).discover_page(png(), "")
    assert "ran out of memory" in e.value.message and SECRET not in e.value.message


def test_runtime_down_names_the_fix():
    c = ModelClient(Config(model="qwen3.5:4b", model_endpoint="http://127.0.0.1:1"))
    with pytest.raises(ModelUnavailable, match="not answering"):
        c.discover_page(png(), "")
    assert c.available() is False


def test_available_needs_the_model_installed():
    with StubOllama(models=["qwen3.5:latest"]) as stub:
        assert client(stub, model="qwen3.5").available()
        assert not client(stub, model="qwen3.5:4b").available()


def test_no_model_means_no_model_mode():
    assert build_client(Config()) is None
    with pytest.raises(ConfigError, match="nabu models use"):
        ModelClient(Config())


@pytest.mark.parametrize("path", ["http://evil.example/x", "//evil.example/x", "api/chat"])
def test_requests_take_relative_paths_only(path):
    http = LoopbackHttp(Config(), 1.0)
    with pytest.raises(NabuError, match="relative"):
        http.request("GET", path)


def test_openai_endpoint_with_v1_suffix():
    with StubOllama() as stub:
        stub.responses.append(discovery())
        c = ModelClient(Config(model="stub-vl:test", model_endpoint=stub.url + "/v1",
                               model_runtime="openai_compat"))
        assert c.available()
        c.discover_page(png(), "")
    assert posts(stub)[0][1] == "/v1/chat/completions"


def test_reprs_never_show_values():
    with StubOllama() as stub:
        stub.responses.append(discovery())
        d = client(stub).discover_page(png(), "")
    assert SECRET not in repr(d) and "Rechnungsnr" not in repr(d)


def test_generic_profile_ignores_boxes():
    assert GENERIC.coords == "none"


# ---- evaluation -------------------------------------------------------------------------
def test_evaluate_reports_metrics_only(tmp_path):
    page = png(400, 600)
    (tmp_path / "synthetic_1.png").write_bytes(page.data)
    (tmp_path / "synthetic_1.expected.json").write_text(json.dumps({"fields": [
        {"label": "Rechnungsnr.", "value": SECRET, "box": [250, 83, 750, 117]},
        {"label": "Datum", "value": "01.10.2026"}]}))
    with StubOllama() as stub:
        stub.responses.append(discovery())
        report = evaluate(Config(model="stub-vl:test", model_endpoint=stub.url), tmp_path)
    assert report["json_valid_rate"] == 1.0
    assert report["label_recall"] == 0.5 and report["value_accuracy"] == 1.0
    assert report["suggested_coords"] == "pixels"
    text = json.dumps(report)
    assert SECRET not in text and "Rechnungsnr" not in text
