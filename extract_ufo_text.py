#!/usr/bin/env python3
import argparse
import json
import mimetypes
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import fitz
from pypdf import PdfReader


PDF_SUFFIXES = {".pdf"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".gif"}


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[Dict]) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def normalized_suffix(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in PDF_SUFFIXES or suffix in IMAGE_SUFFIXES:
        return suffix
    try:
        with path.open("rb") as handle:
            header = handle.read(16)
    except OSError:
        header = b""
    if header.startswith(b"%PDF-"):
        return ".pdf"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if header.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed == "application/pdf":
        return ".pdf"
    if guessed and guessed.startswith("image/"):
        return "." + guessed.split("/", 1)[1]
    return suffix


def extract_pdf_pages(path: Path) -> Tuple[List[Dict], str]:
    doc = fitz.open(path)
    page_rows: List[Dict] = []

    for page_index, page in enumerate(doc, start=1):
        text = page.get_text("text") or ""
        text = text.replace("\x00", "").strip()
        page_rows.append(
            {
                "page_number": page_index,
                "char_count": len(text),
                "word_count": len(text.split()) if text else 0,
                "text": text,
            }
        )

    if not any(row["char_count"] for row in page_rows):
        reader = PdfReader(str(path))
        page_rows = []
        for page_index, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").replace("\x00", "").strip()
            page_rows.append(
                {
                    "page_number": page_index,
                    "char_count": len(text),
                    "word_count": len(text.split()) if text else 0,
                    "text": text,
                }
            )

    combined_text = "\n\n".join(row["text"] for row in page_rows if row["text"]).strip()
    return page_rows, combined_text


def classify_pdf(page_rows: List[Dict], combined_text: str) -> Dict[str, object]:
    total_pages = len(page_rows)
    pages_with_text = sum(1 for row in page_rows if row["char_count"] > 0)
    low_text_pages = sum(1 for row in page_rows if row["char_count"] < 50)
    total_chars = len(combined_text)

    needs_ocr = False
    reason = None
    if total_pages == 0:
        needs_ocr = True
        reason = "empty_pdf"
    elif total_chars < max(100, total_pages * 40):
        needs_ocr = True
        reason = "low_total_text"
    elif pages_with_text / total_pages < 0.5:
        needs_ocr = True
        reason = "too_many_textless_pages"
    elif low_text_pages / total_pages > 0.7:
        needs_ocr = True
        reason = "mostly_low_text_pages"

    return {
        "page_count": total_pages,
        "pages_with_text": pages_with_text,
        "low_text_pages": low_text_pages,
        "total_text_chars": total_chars,
        "needs_ocr": needs_ocr,
        "ocr_reason": reason,
    }


def build_record_lookup(records: List[Dict], downloads: List[Dict]) -> Dict[str, Dict]:
    by_path: Dict[str, Dict] = {}
    record_by_index = {record["record_index"]: record for record in records}
    for item in downloads:
        record = record_by_index.get(item["record_index"])
        if not record:
            continue
        by_path[str(Path(item["path"]).resolve())] = record
    return by_path


def process_asset(
    path: Path,
    record: Dict,
    text_dir: Path,
    pages_dir: Path,
) -> Tuple[Dict, Dict]:
    resolved = path.resolve()
    suffix = normalized_suffix(path)
    asset_id = path.stem
    manifest = {
        "asset_id": asset_id,
        "path": str(resolved),
        "filename": path.name,
        "suffix": suffix,
        "record_index": record["record_index"],
        "title": record["title"],
        "agency": record["agency"],
        "release_date": record["release_date"],
        "incident_date": record["incident_date"],
        "incident_location": record["incident_location"],
    }
    ocr_entry = {
        "asset_id": asset_id,
        "path": str(resolved),
        "filename": path.name,
        "record_index": record["record_index"],
        "title": record["title"],
    }

    if suffix == ".pdf":
        page_rows, combined_text = extract_pdf_pages(path)
        stats = classify_pdf(page_rows, combined_text)
        manifest.update(
            {
                "kind": "pdf",
                **stats,
                "text_output": str((text_dir / f"{asset_id}.txt").resolve()),
                "pages_output": str((pages_dir / f"{asset_id}.json").resolve()),
            }
        )
        ensure_dir(text_dir)
        (text_dir / f"{asset_id}.txt").write_text(combined_text + ("\n" if combined_text else ""), encoding="utf-8")
        write_json(pages_dir / f"{asset_id}.json", page_rows)
        if stats["needs_ocr"]:
            ocr_entry.update(
                {
                    "kind": "pdf",
                    "page_count": stats["page_count"],
                    "ocr_reason": stats["ocr_reason"],
                    "existing_text_chars": stats["total_text_chars"],
                }
            )
        else:
            ocr_entry = {}
    elif suffix in IMAGE_SUFFIXES:
        manifest.update(
            {
                "kind": "image",
                "page_count": 1,
                "pages_with_text": 0,
                "low_text_pages": 1,
                "total_text_chars": 0,
                "needs_ocr": True,
                "ocr_reason": "image_file",
            }
        )
        ocr_entry.update({"kind": "image", "page_count": 1, "ocr_reason": "image_file"})
    else:
        manifest.update(
            {
                "kind": "unknown",
                "page_count": None,
                "pages_with_text": None,
                "low_text_pages": None,
                "total_text_chars": 0,
                "needs_ocr": True,
                "ocr_reason": "unknown_file_type",
            }
        )
        ocr_entry.update({"kind": "unknown", "page_count": None, "ocr_reason": "unknown_file_type"})

    return manifest, ocr_entry


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract text from the local UFO release corpus.")
    parser.add_argument(
        "--dataset-root",
        default="data/war_gov_ufo_release_01",
        help="Root directory for the downloaded dataset.",
    )
    args = parser.parse_args()

    dataset_root = Path(args.dataset_root).resolve()
    raw_documents_dir = dataset_root / "raw" / "documents"
    output_root = dataset_root / "extracted"
    text_dir = output_root / "text"
    pages_dir = output_root / "pages"

    records = load_json(dataset_root / "records.json")
    downloads = load_json(dataset_root / "downloads.json")
    record_lookup = build_record_lookup(records, downloads)

    manifests: List[Dict] = []
    ocr_queue: List[Dict] = []

    for path in sorted(raw_documents_dir.iterdir()):
        if not path.is_file():
            continue
        record = record_lookup.get(str(path.resolve()))
        if not record:
            continue
        manifest, ocr_entry = process_asset(path, record, text_dir, pages_dir)
        manifests.append(manifest)
        if ocr_entry:
            ocr_queue.append(ocr_entry)

    summary = {
        "assets_processed": len(manifests),
        "pdf_assets": sum(1 for item in manifests if item["kind"] == "pdf"),
        "image_assets": sum(1 for item in manifests if item["kind"] == "image"),
        "unknown_assets": sum(1 for item in manifests if item["kind"] == "unknown"),
        "assets_needing_ocr": sum(1 for item in manifests if item["needs_ocr"]),
        "assets_with_usable_native_text": sum(1 for item in manifests if item["kind"] == "pdf" and not item["needs_ocr"]),
        "total_native_text_chars": sum(item["total_text_chars"] for item in manifests if isinstance(item["total_text_chars"], int)),
    }

    write_json(output_root / "summary.json", summary)
    write_json(output_root / "manifest.json", manifests)
    write_jsonl(output_root / "manifest.jsonl", manifests)
    write_json(output_root / "ocr_queue.json", ocr_queue)
    write_jsonl(output_root / "ocr_queue.jsonl", ocr_queue)

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
