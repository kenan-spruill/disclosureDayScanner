#!/usr/bin/env python3
import argparse
import csv
import io
import json
import re
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

import requests


BASE_URL = "https://www.war.gov"
PAGE_URL = f"{BASE_URL}/ufo/"
CSV_URL = f"{BASE_URL}/Portals/1/Interactive/2026/UFO/uap-csv.csv"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)
REQUEST_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "en-US,en;q=0.9",
}
CSV_HEADERS = {
    **REQUEST_HEADERS,
    "Accept": "text/csv,text/plain;q=0.9,*/*;q=0.8",
    "Referer": PAGE_URL,
    "Sec-Ch-Ua": '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}
FILE_HEADERS = {
    **REQUEST_HEADERS,
    "Accept": "*/*",
    "Referer": PAGE_URL,
}
PAGE_HEADERS = {
    **REQUEST_HEADERS,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Ch-Ua": '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}
ASSET_HEADERS = {
    **REQUEST_HEADERS,
    "Accept": "application/pdf,application/octet-stream;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Referer": PAGE_URL,
    "Sec-Ch-Ua": '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}
RETRY_STATUS_CODES = {403, 404}


def slugify(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9._-]+", "_", value)
    value = re.sub(r"_+", "_", value)
    return value.strip("._") or "untitled"


def ensure_suffix(name: str, url: str) -> str:
    if Path(name).suffix:
        return name
    path = requests.utils.urlparse(url).path
    suffix = Path(path).suffix
    return f"{name}{suffix}" if suffix else name


def split_multi(value: str) -> List[str]:
    return [part.strip() for part in (value or "").split("|") if part.strip()]


def fetch_csv(session: requests.Session) -> str:
    response = session.get(CSV_URL, headers=CSV_HEADERS, timeout=120)
    response.raise_for_status()
    return response.text


def prime_session(session: requests.Session) -> None:
    response = session.get(PAGE_URL, headers=PAGE_HEADERS, timeout=120)
    response.raise_for_status()


def parse_records(csv_text: str) -> List[Dict[str, str]]:
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    records: List[Dict[str, str]] = []
    for idx, row in enumerate(rows, start=1):
        title = (row.get("Title") or "").replace("\n", " ").strip()
        record = {
            "record_index": idx,
            "release_date": (row.get("Release Date") or "").strip(),
            "title": title,
            "type": (row.get("Type") or "").strip(),
            "agency": (row.get("Agency") or "").strip(),
            "incident_date": (row.get("Incident Date") or "").strip(),
            "incident_location": (row.get("Incident Location") or "").strip(),
            "description": (row.get("Description Blurb") or "").strip(),
            "redaction": (row.get("Redaction") or "").strip(),
            "video_pairing": (row.get("Video Pairing") or "").strip(),
            "pdf_pairing": (row.get("PDF Pairing") or row.get("PDF PAiring") or "").strip(),
            "document_url": (row.get("PDF | Image Link") or "").strip(),
            "modal_images": split_multi(row.get("Modal Image") or ""),
            "video_ids": split_multi(row.get("DVIDS Video ID") or ""),
            "video_title": (row.get("Video Title") or "").strip(),
        }
        records.append(record)
    return records


def iter_assets(record: Dict[str, str]) -> Iterable[Dict[str, str]]:
    title_slug = slugify(record["title"])
    if record["document_url"]:
        filename = ensure_suffix(
            f"{record['record_index']:03d}_{title_slug}",
            record["document_url"],
        )
        yield {
            "kind": "document",
            "url": record["document_url"],
            "filename": filename,
        }
    for image_index, image_url in enumerate(record["modal_images"], start=1):
        filename = ensure_suffix(
            f"{record['record_index']:03d}_{title_slug}_modal_{image_index}",
            image_url,
        )
        yield {
            "kind": "modal_image",
            "url": image_url,
            "filename": filename,
        }


def download_file(
    session: requests.Session,
    url: str,
    destination: Path,
    overwrite: bool = False,
) -> Dict[str, object]:
    if destination.exists() and not overwrite:
        return {"status": "skipped", "bytes": destination.stat().st_size}

    destination.parent.mkdir(parents=True, exist_ok=True)
    plans = [
        (FILE_HEADERS, False),
        (ASSET_HEADERS, True),
        (ASSET_HEADERS, True),
    ]

    last_error: Optional[Exception] = None
    for headers, should_prime in plans:
        if should_prime:
            prime_session(session)

        response = session.get(url, headers=headers, stream=True, timeout=300)
        with response:
            if response.status_code in RETRY_STATUS_CODES:
                last_error = requests.HTTPError(
                    f"{response.status_code} for url: {url}",
                    response=response,
                )
                continue

            response.raise_for_status()
            with destination.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        handle.write(chunk)
            return {"status": "downloaded", "bytes": destination.stat().st_size}

    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Failed to download asset: {url}")


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def build_summary(records: List[Dict[str, str]], download_results: List[Dict[str, object]]) -> Dict[str, object]:
    summary = {
        "records": len(records),
        "documents_or_images_listed": sum(1 for record in records if record["document_url"]),
        "modal_images_listed": sum(len(record["modal_images"]) for record in records),
        "video_ids_listed": sum(len(record["video_ids"]) for record in records),
        "downloaded_files": sum(1 for item in download_results if item["status"] == "downloaded"),
        "skipped_existing_files": sum(1 for item in download_results if item["status"] == "skipped"),
        "failed_files": sum(1 for item in download_results if item["status"] == "failed"),
        "downloaded_bytes": sum(int(item.get("bytes", 0)) for item in download_results if item["status"] != "failed"),
    }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Download war.gov UFO release files.")
    parser.add_argument(
        "--output",
        default="data/war_gov_ufo_release_01",
        help="Output directory for CSV, manifests, and downloads.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only download the first N assets for a test run.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Redownload files even if they already exist.",
    )
    args = parser.parse_args()

    root = Path(args.output).resolve()
    raw_dir = root / "raw"
    docs_dir = raw_dir / "documents"
    images_dir = raw_dir / "modal_images"
    root.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)
    prime_session(session)

    print(f"Fetching CSV manifest from {CSV_URL}", file=sys.stderr)
    csv_text = fetch_csv(session)
    records = parse_records(csv_text)

    (root / "source_urls.json").write_text(
        json.dumps(
            {
                "page_url": PAGE_URL,
                "csv_url": CSV_URL,
                "fetched_at_epoch": int(time.time()),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "uap-csv.csv").write_text(csv_text, encoding="utf-8")

    download_results: List[Dict[str, object]] = []
    video_manifest: List[Dict[str, object]] = []
    seen_urls: Set[str] = set()
    asset_counter = 0

    for record in records:
        video_manifest.append(
            {
                "record_index": record["record_index"],
                "title": record["title"],
                "agency": record["agency"],
                "type": record["type"],
                "video_ids": record["video_ids"],
                "video_title": record["video_title"],
                "video_pairing": record["video_pairing"],
                "document_url": record["document_url"],
                "modal_images": record["modal_images"],
            }
        )

        for asset in iter_assets(record):
            url = asset["url"]
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            asset_counter += 1
            if args.limit is not None and asset_counter > args.limit:
                break

            target_dir = docs_dir if asset["kind"] == "document" else images_dir
            destination = target_dir / asset["filename"]
            result: Dict[str, object] = {
                "record_index": record["record_index"],
                "title": record["title"],
                "kind": asset["kind"],
                "url": url,
                "path": str(destination),
            }
            try:
                status = download_file(session, url, destination, overwrite=args.overwrite)
                result.update(status)
                print(f"{status['status']:>10}  {destination.name}", file=sys.stderr)
            except Exception as exc:
                result.update({"status": "failed", "error": str(exc)})
                print(f"    failed  {destination.name} :: {exc}", file=sys.stderr)
            download_results.append(result)

        if args.limit is not None and asset_counter >= args.limit:
            break

    write_json(root / "records.json", records)
    write_json(root / "videos.json", [item for item in video_manifest if item["video_ids"]])
    write_json(root / "downloads.json", download_results)
    write_json(root / "summary.json", build_summary(records, download_results))

    summary = build_summary(records, download_results)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
