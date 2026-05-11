# UFO Corpus Status

## Current state

- `Release 01` download is complete for CSV-linked documents and images.
- Local dataset root: `/Volumes/KenanSSD/AI Agent Projects/alienFiles/data/war_gov_ufo_release_01`
- Raw corpus size: about `2.5 GB`
- Video IDs captured in metadata: `41`

## Extraction pipeline

- Native extraction script: `/Volumes/KenanSSD/AI Agent Projects/alienFiles/extract_ufo_text.py`
- OCR script: `/Volumes/KenanSSD/AI Agent Projects/alienFiles/ocr_ufo_assets.py`
- Corpus builder: `/Volumes/KenanSSD/AI Agent Projects/alienFiles/build_ufo_corpus.py`

## Important output directories

- Native extraction summary:
  `/Volumes/KenanSSD/AI Agent Projects/alienFiles/data/war_gov_ufo_release_01/extracted/summary.json`
- OCR outputs:
  `/Volumes/KenanSSD/AI Agent Projects/alienFiles/data/war_gov_ufo_release_01/extracted/ocr`
- Canonical merged corpus:
  `/Volumes/KenanSSD/AI Agent Projects/alienFiles/data/war_gov_ufo_release_01/corpus`

## Resume commands

Run OCR or resume it:

```bash
cd "/Volumes/KenanSSD/AI Agent Projects/alienFiles"
python3 ocr_ufo_assets.py --workers 3 --dpi 120
```

Rebuild canonical corpus after OCR advances:

```bash
cd "/Volumes/KenanSSD/AI Agent Projects/alienFiles"
python3 build_ufo_corpus.py
```

## Notes

- OCR is resumable and skips assets that already have OCR text and page JSON.
- The OCR queue is processed shortest-first so progress is visible earlier.
- The canonical corpus currently prefers OCR text when present, otherwise native extracted text.
- Final LLM-ready chunks are written to:
  `/Volumes/KenanSSD/AI Agent Projects/alienFiles/data/war_gov_ufo_release_01/corpus/chunks.jsonl`
