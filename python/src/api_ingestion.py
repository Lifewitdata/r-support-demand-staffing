"""Configurable REST ingestion; credentials never leave the configured HTTPS origin."""
import argparse
import json
import math
import os
from pathlib import Path
import tempfile
from urllib.parse import parse_qsl, urljoin, urlsplit

import pandas as pd
import requests


def _origin(url):
    if not isinstance(url, str) or not url or any(c.isspace() or ord(c) < 32 for c in url):
        raise ValueError("API URL must be a nonempty HTTPS URL without whitespace")
    parsed = urlsplit(url)
    if (parsed.scheme.lower() != "https" or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.fragment or "\\" in url):
        raise ValueError("API URL must use HTTPS without embedded credentials or fragments")
    return ("https", parsed.hostname.lower(), 443 if parsed.port is None else parsed.port)


def fetch_records(base_url, token, records_path="data", next_path="next",
                  page_size=500, timeout=30, max_pages=1000):
    origin = _origin(base_url)
    for name, value in (("page_size", page_size), ("max_pages", max_pages)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} must be a positive integer")
    if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout) or timeout <= 0):
        raise ValueError("timeout must be a finite positive number")
    for name, value in (("records_path", records_path), ("next_path", next_path)):
        if not isinstance(value, str) or not value or any(not p for p in value.split(".")):
            raise ValueError(f"{name} must be a nonempty dotted path")
    session = requests.Session()
    records = []
    try:
        session.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/json"})
        url = base_url
        params = None if "limit" in dict(parse_qsl(urlsplit(url).query)) else {"limit": page_size}
        for _ in range(max_pages):
            response = session.get(url, params=params, timeout=timeout, allow_redirects=False)
            if 300 <= response.status_code < 400:
                raise ValueError("API redirects are forbidden; refusing partial extract")
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, list):
                batch, next_url = payload, None
            elif isinstance(payload, dict):
                batch = payload
                for part in records_path.split("."):
                    if not isinstance(batch, dict) or part not in batch:
                        raise ValueError("Configured records_path is missing from API payload")
                    batch = batch[part]
                next_url = payload
                for part in next_path.split("."):
                    if next_url is None:
                        break
                    if not isinstance(next_url, dict):
                        raise ValueError("Configured next_path has an invalid pagination payload")
                    next_url = next_url.get(part)
            else:
                raise ValueError("API response must be a JSON object or array")
            if not isinstance(batch, list) or any(not isinstance(row, dict) for row in batch):
                raise ValueError("Configured records_path must resolve to a list of JSON objects")
            records.extend(batch)
            if next_url is None or next_url == "":
                break
            if not isinstance(next_url, str):
                raise ValueError("API next page must be a URL string or null")
            # Validate the reference as well as the resolved URL (urljoin strips controls).
            if any(c.isspace() or ord(c) < 32 for c in next_url) or "\\" in next_url:
                raise ValueError("Invalid pagination URL")
            url = urljoin(url, next_url)
            if _origin(url) != origin:
                raise ValueError("Cross-origin pagination is forbidden; refusing partial extract")
            params = None  # Server cursors and query strings must remain untouched.
        else:
            raise RuntimeError(f"Pagination exceeded max_pages={max_pages}; refusing partial extract")
        if not records:
            raise ValueError("API returned zero records; refusing to overwrite the last valid extract")
        return pd.json_normalize(records)
    finally:
        session.close()


def map_fields(raw, mapping):
    if not isinstance(mapping, dict) or not mapping:
        raise ValueError("API field mapping must be a nonempty JSON object")
    if any(not isinstance(v, str) or not v.strip() for v in (*mapping.keys(), *mapping.values())):
        raise ValueError("API mapping names and sources must be nonempty strings")
    sources = list(mapping.values())
    if len(set(sources)) != len(sources):
        raise ValueError("API field mapping contains duplicate source fields")
    if not raw.columns.is_unique:
        raise ValueError("API source columns must be unique")
    missing = [source for source in sources if source not in raw.columns]
    if missing:
        raise ValueError(f"API field mapping references missing source fields: {missing}")
    selected = raw.loc[:, sources].copy()
    selected.columns = list(mapping)
    return selected


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mapping", required=True, help="JSON object mapping canonical names to API fields")
    p.add_argument("--output", default="data/raw/api_conversations.csv")
    p.add_argument("--records-path", default=os.getenv("API_RECORDS_PATH", "data"))
    p.add_argument("--next-path", default=os.getenv("API_NEXT_PATH", "next"))
    a = p.parse_args()
    url, token = os.getenv("SUPPORT_API_URL"), os.getenv("SUPPORT_API_TOKEN")
    if not url or not token:
        raise SystemExit("Set SUPPORT_API_URL and SUPPORT_API_TOKEN as environment variables")
    mapping = json.loads(Path(a.mapping).read_text(encoding="utf-8"))
    canonical = map_fields(fetch_records(url, token, a.records_path, a.next_path), mapping)
    from commerce_analytics import _with_local_hour, validate_chats
    canonical = _with_local_hour(canonical)
    validate_chats(canonical)
    output = Path(a.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="",
                                         dir=output.parent, suffix=".tmp", delete=False) as handle:
            temp = Path(handle.name)
            canonical.to_csv(handle, index=False)
        temp.replace(output)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
    print(json.dumps({"rows": len(canonical), "output": str(output), "source": "configured_rest_api"}))


if __name__ == "__main__":
    main()
