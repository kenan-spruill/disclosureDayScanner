# UFO Corpus Workbench

Local workflow for downloading, extracting, OCRing, and reviewing the `war.gov` UFO/UAP `Release 01` corpus.

## What this repo does

This project turns the public release into a local, LLM-ready research corpus:

1. Download the release manifest and linked assets.
2. Extract native text from PDFs when possible.
3. Run OCR on scanned PDFs and image assets.
4. Build a canonical merged corpus.
5. Produce page-based chunks for search, review, and model analysis.

## Current local dataset

Primary dataset root:

`/Volumes/KenanSSD/AI Agent Projects/alienFiles/data/war_gov_ufo_release_01`

High-level status:

- CSV-linked document/image download complete
- Corpus stored locally at about `2.5 GB`
- Page-based chunking enabled
- OCR pipeline in progress / resumable

## Repo layout

- [download_ufo_release.py](/Volumes/KenanSSD/AI%20Agent%20Projects/alienFiles/download_ufo_release.py)
  Downloads the `Release 01` CSV manifest and linked assets.
- [extract_ufo_text.py](/Volumes/KenanSSD/AI%20Agent%20Projects/alienFiles/extract_ufo_text.py)
  Runs native PDF text extraction and builds the OCR queue.
- [ocr_ufo_assets.py](/Volumes/KenanSSD/AI%20Agent%20Projects/alienFiles/ocr_ufo_assets.py)
  Runs resumable OCR over queued assets.
- [build_ufo_corpus.py](/Volumes/KenanSSD/AI%20Agent%20Projects/alienFiles/build_ufo_corpus.py)
  Merges native extraction and OCR into one canonical corpus and writes page-based chunks.
- [ufo_review_workbench.ipynb](/Volumes/KenanSSD/AI%20Agent%20Projects/alienFiles/ufo_review_workbench.ipynb)
  Main notebook for inspection and the next LLM review stage.
- [STATUS.md](/Volumes/KenanSSD/AI%20Agent%20Projects/alienFiles/STATUS.md)
  Short operational handoff with resume commands.

## Important output folders

- Raw download set:
  [data/war_gov_ufo_release_01/raw](/Volumes/KenanSSD/AI%20Agent%20Projects/alienFiles/data/war_gov_ufo_release_01/raw)
- Native extraction outputs:
  [data/war_gov_ufo_release_01/extracted](/Volumes/KenanSSD/AI%20Agent%20Projects/alienFiles/data/war_gov_ufo_release_01/extracted)
- OCR outputs:
  [data/war_gov_ufo_release_01/extracted/ocr](/Volumes/KenanSSD/AI%20Agent%20Projects/alienFiles/data/war_gov_ufo_release_01/extracted/ocr)
- Canonical merged corpus:
  [data/war_gov_ufo_release_01/corpus](/Volumes/KenanSSD/AI%20Agent%20Projects/alienFiles/data/war_gov_ufo_release_01/corpus)

## Canonical corpus outputs

The canonical corpus is the main thing downstream tools should read.

- [documents.json](/Volumes/KenanSSD/AI%20Agent%20Projects/alienFiles/data/war_gov_ufo_release_01/corpus/documents.json)
  One row per asset with metadata, source path, extraction method, and text availability.
- [chunks.jsonl](/Volumes/KenanSSD/AI%20Agent%20Projects/alienFiles/data/war_gov_ufo_release_01/corpus/chunks.jsonl)
  One row per page chunk.
- [summary.json](/Volumes/KenanSSD/AI%20Agent%20Projects/alienFiles/data/war_gov_ufo_release_01/corpus/summary.json)
  Corpus-level totals.

## Chunk semantics

Chunks are page-based.

That means:

- one chunk usually represents one page
- `chunk_id` looks like `asset_id::page::0001`
- each chunk carries metadata such as title, agency, record index, source URL, extraction method, and page number

This is a better fit for citation, retrieval, and human review than arbitrary sliding text windows.

## Basic workflow

## Setup

Create or activate a Python environment, then install the Python dependencies:

```bash
cd "/Volumes/KenanSSD/AI Agent Projects/alienFiles"
python3 -m pip install -r requirements.txt
```

For OCR you also need a system `tesseract` binary. On macOS:

```bash
brew install tesseract
```

### 1. Download assets

```bash
cd "/Volumes/KenanSSD/AI Agent Projects/alienFiles"
python3 download_ufo_release.py
```

### 2. Run native extraction

```bash
cd "/Volumes/KenanSSD/AI Agent Projects/alienFiles"
python3 extract_ufo_text.py
```

### 3. Run or resume OCR

```bash
cd "/Volumes/KenanSSD/AI Agent Projects/alienFiles"
python3 ocr_ufo_assets.py --workers 3 --dpi 120
```

### 4. Rebuild the canonical corpus

```bash
cd "/Volumes/KenanSSD/AI Agent Projects/alienFiles"
python3 build_ufo_corpus.py
```

## Notebook

Open [ufo_review_workbench.ipynb](/Volumes/KenanSSD/AI%20Agent%20Projects/alienFiles/ufo_review_workbench.ipynb) to:

- inspect records and documents
- preview page chunks
- identify weak OCR pages
- prepare the next LLM review stage

The notebook already includes a dry-run scaffold for model review payloads. It uses a placeholder for the exact OpenAI OSS 120B model ID so you can fill it in explicitly later.

## Notes on OCR

- OCR is resumable.
- The queue runs shortest-first to surface useful outputs earlier.
- Some scan-heavy FBI pages are noisy, which is expected.
- Native extraction is still preferred when it is clearly available and useful.

## Next recommended step

Use the notebook to define the first structured review pass over page chunks, then write model outputs to a separate review/results JSONL set rather than mutating the source corpus.
