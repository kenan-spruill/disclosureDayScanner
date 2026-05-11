#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


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


def normalize_ws(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def build_download_lookup(downloads: List[Dict]) -> Tuple[Dict[str, Dict], Dict[str, List[Dict]]]:
    by_path: Dict[str, Dict] = {}
    by_record: Dict[str, List[Dict]] = {}
    for item in downloads:
        by_path[str(Path(item["path"]).resolve())] = item
        by_record.setdefault(str(item["record_index"]), []).append(item)
    return by_path, by_record


def build_records_lookup(records: List[Dict]) -> Dict[str, Dict]:
    return {str(record["record_index"]): record for record in records}


def load_ocr_result_maps(ocr_root: Path) -> Tuple[Dict[str, Path], Dict[str, Path]]:
    text_dir = ocr_root / "text"
    pages_dir = ocr_root / "pages"
    text_map = {path.stem: path for path in text_dir.glob("*.txt")} if text_dir.exists() else {}
    pages_map = {path.stem: path for path in pages_dir.glob("*.json")} if pages_dir.exists() else {}
    return text_map, pages_map


def collect_native_sources(manifest: List[Dict]) -> Dict[str, Dict]:
    return {item["asset_id"]: item for item in manifest}


def page_rows_from_text(text: str) -> List[Dict]:
    return [
        {
            "page_number": 1,
            "char_count": len(text),
            "word_count": len(text.split()) if text else 0,
            "text": text,
        }
    ]


def choose_text_source(
    asset_id: str,
    native_item: Dict,
    ocr_text_map: Dict[str, Path],
    ocr_pages_map: Dict[str, Path],
) -> Tuple[str, str, Optional[List[Dict]]]:
    if asset_id in ocr_text_map:
        text = normalize_ws(ocr_text_map[asset_id].read_text(encoding="utf-8"))
        pages = load_json(ocr_pages_map[asset_id]) if asset_id in ocr_pages_map else page_rows_from_text(text)
        return "ocr", text, pages

    if native_item.get("kind") == "pdf" and native_item.get("text_output"):
        text_path = Path(native_item["text_output"])
        pages_path = Path(native_item["pages_output"])
        if text_path.exists():
            text = normalize_ws(text_path.read_text(encoding="utf-8"))
            pages = load_json(pages_path) if pages_path.exists() else page_rows_from_text(text)
            return "native", text, pages

    return "none", "", None


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a canonical LLM-ready UFO corpus.")
    parser.add_argument(
        "--dataset-root",
        default="data/war_gov_ufo_release_01",
        help="Root directory for the downloaded dataset.",
    )
    args = parser.parse_args()

    dataset_root = Path(args.dataset_root).resolve()
    records = load_json(dataset_root / "records.json")
    downloads = load_json(dataset_root / "downloads.json")
    native_manifest = load_json(dataset_root / "extracted" / "manifest.json")
    ocr_root = dataset_root / "extracted" / "ocr"

    records_lookup = build_records_lookup(records)
    downloads_by_path, downloads_by_record = build_download_lookup(downloads)
    native_sources = collect_native_sources(native_manifest)
    ocr_text_map, ocr_pages_map = load_ocr_result_maps(ocr_root)

    corpus_root = dataset_root / "corpus"
    docs_out = corpus_root / "documents.json"
    chunks_out = corpus_root / "chunks.jsonl"

    documents: List[Dict] = []
    chunks: List[Dict] = []

    for asset_id, native_item in sorted(native_sources.items()):
        path = str(Path(native_item["path"]).resolve())
        download_item = downloads_by_path.get(path)
        if not download_item:
            continue
        record = records_lookup.get(str(download_item["record_index"]))
        if not record:
            continue

        extraction_method, text, page_rows = choose_text_source(
            asset_id=asset_id,
            native_item=native_item,
            ocr_text_map=ocr_text_map,
            ocr_pages_map=ocr_pages_map,
        )

        document = {
            "asset_id": asset_id,
            "record_index": record["record_index"],
            "title": record["title"],
            "agency": record["agency"],
            "release_date": record["release_date"],
            "incident_date": record["incident_date"],
            "incident_location": record["incident_location"],
            "description": record["description"],
            "asset_kind": download_item["kind"],
            "source_path": path,
            "url": download_item["url"],
            "extraction_method": extraction_method,
            "has_text": bool(text),
            "text_char_count": len(text),
            "page_count": len(page_rows) if page_rows else native_item.get("page_count"),
            "related_asset_count": len(downloads_by_record.get(str(record["record_index"]), [])),
        }

        if text:
            document["text_path"] = str((corpus_root / "text" / f"{asset_id}.txt").resolve())
            ensure_dir((corpus_root / "text"))
            (corpus_root / "text" / f"{asset_id}.txt").write_text(text + "\n", encoding="utf-8")

        if page_rows:
            pages_out = corpus_root / "pages" / f"{asset_id}.json"
            write_json(pages_out, page_rows)
            document["pages_path"] = str(pages_out.resolve())

        documents.append(document)

        if page_rows:
            for idx, page in enumerate(page_rows, start=1):
                page_text = normalize_ws(page.get("text", ""))
                if not page_text:
                    continue
                chunks.append(
                    {
                        "chunk_id": f"{asset_id}::page::{idx:04d}",
                        "asset_id": asset_id,
                        "record_index": record["record_index"],
                        "title": record["title"],
                        "agency": record["agency"],
                        "release_date": record["release_date"],
                        "incident_date": record["incident_date"],
                        "incident_location": record["incident_location"],
                        "asset_kind": download_item["kind"],
                        "extraction_method": extraction_method,
                        "source_path": path,
                        "url": download_item["url"],
                        "page_number": page.get("page_number", idx),
                        "chunk_index": idx,
                        "text": page_text,
                        "char_count": len(page_text),
                        "word_count": page.get("word_count"),
                    }
                )
        elif text:
            fallback_text = normalize_ws(text)
            if fallback_text:
                chunks.append(
                    {
                        "chunk_id": f"{asset_id}::page::0001",
                        "asset_id": asset_id,
                        "record_index": record["record_index"],
                        "title": record["title"],
                        "agency": record["agency"],
                        "release_date": record["release_date"],
                        "incident_date": record["incident_date"],
                        "incident_location": record["incident_location"],
                        "asset_kind": download_item["kind"],
                        "extraction_method": extraction_method,
                        "source_path": path,
                        "url": download_item["url"],
                        "page_number": 1,
                        "chunk_index": 1,
                        "text": fallback_text,
                        "char_count": len(fallback_text),
                        "word_count": len(fallback_text.split()),
                    }
                )

    summary = {
        "documents_total": len(documents),
        "documents_with_text": sum(1 for doc in documents if doc["has_text"]),
        "documents_using_ocr": sum(1 for doc in documents if doc["extraction_method"] == "ocr"),
        "documents_using_native_text": sum(1 for doc in documents if doc["extraction_method"] == "native"),
        "documents_without_text": sum(1 for doc in documents if not doc["has_text"]),
        "chunks_total": len(chunks),
        "total_text_chars": sum(doc["text_char_count"] for doc in documents),
    }

    write_json(corpus_root / "summary.json", summary)
    write_json(docs_out, documents)
    write_jsonl(chunks_out, chunks)

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
