# M0 OCR spike (2026-10-13)

Machine: Windows 11, 28 logical cores, CPU only. 7 synthetic pages (scratchpad evalcases; same set as the
qwen3.5 eval): 3 clean (EN receipt, DE invoice, KO form), 1 dense small print, 1 phone-style photo, 2 bad photos
(DE, KO). Score = expected labels / values found anywhere in the OCR text (compact match). Single run each;
timings include per-line recognition without batching. Script: `tasks/m0_ocr_spike.py`.

## Results

| Setup | Clean EN/DE | Dense | Clean KO form | Bad KO photo | Bad DE photo | s/page |
|---|---|---|---|---|---|---|
| rapidocr-onnxruntime 1.4.4, bundled (ch/en) | 100% | 100% | labels 0/5, values 3/5, **0 Hangul** | 0/5, 3/5 | 0/5, 2/5 | 5-11 |
| + Korean PP-OCRv5 rec only | DE labels 5/6 (umlauts) | values 10/12 | 4/5, 5/5 | 3/5, 3/5 | 0/5, 0/5 | 2-8 |
| Pick by confidence, both models | 100% | 100% | 3/5, 3/5 | 2/5, 3/5 | - | 7-14 |
| **rapidocr 3.10 (Py 3.13), detect once, Korean re-read only where base output has CJK or score < 0.8, keep it if it has Hangul** | **100%** | **100%** | **5/5, 5/5** | **5/5, 4/5** | 0/5, 3/5 | **3-8** |

Bad DE photo: OCR cannot read it with any setup; qwen3.5:4b read it (labels 4/5, values 5/5). That page
needs the model path anyway.

## Findings
- [Certain] Bundled RapidOCR models read no Korean. Korean needs the PP-OCRv5 Korean rec model
  (13.5 MB onnx + 47 KB dict, Apache-2.0 PaddleOCR via RapidAI ModelScope).
  sha256 onnx `cd6e2ea50f6943ca7271eb8c56a877a5a90720b7047fe9c41a2e541a25773c9b`,
  dict `a88071c68c01707489baa79ebe0405b7beb5cca229f4fc94cc3ef992328802d7`.
- [Certain] `rapidocr-onnxruntime` (1.4.4, last release) requires Python < 3.13; CI runs 3.13. Use
  `rapidocr` 3.10 (Apache-2.0, py3-none-any, bundles PP-OCRv6 det/rec small, headless OpenCV) + `onnxruntime`.
- [Certain] With the egress guard installed and model paths given, rapidocr 3.10 made no network attempt.
  It contains download code (`requests`) used when a model path is missing: Nabu must always pass paths.
- [Certain] rapidocr 3.x keeps `use_det/use_cls/use_rec` from one call for the next calls. The adapter must
  pass all three on every call.
- [Certain] Picking a line by confidence fails: the base model reads Hangul as confident Chinese.
- Size on disk (Windows): opencv 113 MB, onnxruntime 43, numpy 43, rapidocr 32 (27 MB models), pillow 15,
  pdf/office libs ~25. Total read stack ~270 MB. NFR-2 budget (provisional) is 120 MB.
- Tesseract is not needed for EN/DE/KO (Q5).

## Decisions needed (owner)
1. NFR-2: 120 MB is not reachable with any ONNX OCR (OpenCV + onnxruntime alone are ~150 MB). Proposed: 300 MB.
2. NFR-3: "1-page scan filled from a template < 5 s" - OCR alone is 3-8 s/page on this CPU. Proposed: < 10 s,
   confirmed on the owner's reference laptop.
3. Korean pack download vs AR-3 (only loopback network): FR-1.9 says `nabu langs pull`, which needs the internet.
   Proposed: `langs pull` is a separate command that never runs while documents are loaded, downloads only
   pinned URLs, checks sha256, and is listed in AR-3 as the one exception; or packs install from a local file only.
4. Q5: close as "Tesseract not used".

## Owner decisions (2026-10-13)
1. NFR-2 budget raised to 300 MB.
2. Korean (and later) OCR packs: `nabu langs pull <lang>`, pinned URL + sha256, refused while a review
   session is open; AR-3 lists it as the one exception.
3. NFR-3 scan target < 10 s, to be confirmed on the owner's reference laptop.
4. Q5 closed: Tesseract not used.
FRD text for these is proposed to the owner, not written by Claude.
