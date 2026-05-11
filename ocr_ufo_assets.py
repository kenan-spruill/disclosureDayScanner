#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import fitz


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".gif"}


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: List[Dict]) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def run_tesseract(image_path: Path) -> str:
    result = subprocess.run(
        ["tesseract", str(image_path), "stdout", "-l", "eng", "--psm", "6"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise RuntimeError(stderr or f"tesseract failed for {image_path}")
    return result.stdout.replace("\x0c", "").strip()


def render_pdf_page(page: fitz.Page, output_path: Path, dpi: int) -> None:
    matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    pix.save(str(output_path))


def ocr_pdf(asset_path: Path, dpi: int) -> Tuple[List[Dict], str]:
    rows: List[Dict] = []
    texts: List[str] = []
    doc = fitz.open(asset_path)
    with tempfile.TemporaryDirectory(prefix="ufo_ocr_") as tmpdir:
        tmpdir_path = Path(tmpdir)
        for page_index, page in enumerate(doc, start=1):
            image_path = tmpdir_path / f"page_{page_index:04d}.png"
            render_pdf_page(page, image_path, dpi=dpi)
            text = run_tesseract(image_path)
            rows.append(
                {
                    "page_number": page_index,
                    "char_count": len(text),
                    "word_count": len(text.split()) if text else 0,
                    "text": text,
                }
            )
            if text:
                texts.append(text)
    return rows, "\n\n".join(texts).strip()


def ocr_image(asset_path: Path) -> Tuple[List[Dict], str]:
    text = run_tesseract(asset_path)
    row = {
        "page_number": 1,
        "char_count": len(text),
        "word_count": len(text.split()) if text else 0,
        "text": text,
    }
    return [row], text


def process_item(item: Dict, output_root: str, dpi: int) -> Dict:
    asset_path = Path(item["path"])
    asset_id = item["asset_id"]
    pages_dir = Path(output_root) / "pages"
    text_dir = Path(output_root) / "text"
    ensure_dir(pages_dir)
    ensure_dir(text_dir)
    pages_output = pages_dir / f"{asset_id}.json"
    text_output = text_dir / f"{asset_id}.txt"

    suffix = asset_path.suffix.lower()
    if text_output.exists() and pages_output.exists():
        existing_pages = load_json(pages_output)
        existing_text = text_output.read_text(encoding="utf-8")
        return {
            "asset_id": asset_id,
            "path": str(asset_path.resolve()),
            "filename": asset_path.name,
            "record_index": item["record_index"],
            "title": item["title"],
            "kind": item["kind"],
            "ocr_reason": item["ocr_reason"],
            "page_count": len(existing_pages),
            "total_text_chars": len(existing_text),
            "pages_output": str(pages_output.resolve()),
            "text_output": str(text_output.resolve()),
            "status": "cached",
        }

    if item["kind"] == "pdf" or suffix == ".pdf":
        page_rows, combined_text = ocr_pdf(asset_path, dpi=dpi)
    elif suffix in IMAGE_SUFFIXES or item["kind"] == "image":
        page_rows, combined_text = ocr_image(asset_path)
    else:
        raise RuntimeError(f"Unsupported OCR asset type: {asset_path.name}")

    write_json(pages_output, page_rows)
    text_output.write_text(combined_text + ("\n" if combined_text else ""), encoding="utf-8")

    return {
        "asset_id": asset_id,
        "path": str(asset_path.resolve()),
        "filename": asset_path.name,
        "record_index": item["record_index"],
        "title": item["title"],
        "kind": item["kind"],
        "ocr_reason": item["ocr_reason"],
        "page_count": len(page_rows),
        "total_text_chars": len(combined_text),
        "pages_output": str(pages_output.resolve()),
        "text_output": str(text_output.resolve()),
        "status": "done",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run OCR over queued UFO assets.")
    parser.add_argument(
        "--dataset-root",
        default="data/war_gov_ufo_release_01",
        help="Root directory for the downloaded dataset.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=max(1, min(4, (os.cpu_count() or 2) - 1)),
        help="Number of parallel OCR workers.",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=150,
        help="Render DPI for OCRing PDF pages.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only OCR the first N queued assets for testing.",
    )
    args = parser.parse_args()

    dataset_root = Path(args.dataset_root).resolve()
    extracted_root = dataset_root / "extracted"
    ocr_root = extracted_root / "ocr"
    queue: List[Dict] = load_json(extracted_root / "ocr_queue.json")
    queue.sort(key=lambda item: (item.get("page_count") or 0, item["filename"]))

    if args.limit is not None:
        queue = queue[: args.limit]

    completed: List[Dict] = []
    failed: List[Dict] = []

    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(process_item, item, str(ocr_root), args.dpi): item
            for item in queue
        }
        for future in as_completed(futures):
            item = futures[future]
            try:
                result = future.result()
                completed.append(result)
                print(f"done      {item['filename']}")
            except Exception as exc:
                failed.append(
                    {
                        **item,
                        "status": "failed",
                        "error": str(exc),
                    }
                )
                print(f"failed    {item['filename']} :: {exc}")

    completed.sort(key=lambda row: row["asset_id"])
    failed.sort(key=lambda row: row["asset_id"])

    summary = {
        "queued_assets": len(queue),
        "completed_assets": len(completed),
        "failed_assets": len(failed),
        "workers": args.workers,
        "dpi": args.dpi,
        "total_ocr_text_chars": sum(row["total_text_chars"] for row in completed),
    }

    write_json(ocr_root / "summary.json", summary)
    write_json(ocr_root / "results.json", completed)
    write_jsonl(ocr_root / "results.jsonl", completed)
    write_json(ocr_root / "failed.json", failed)
    write_jsonl(ocr_root / "failed.jsonl", failed)

    print(json.dumps(summary, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
