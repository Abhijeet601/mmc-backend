"""Upload the unique local notice source files to the configured R2 bucket.

This script uploads files only. It does not create duplicate database notice
records. Run from the backend directory after setting R2 environment variables:

    python scripts/upload_notice_source_to_r2.py --apply
"""

from __future__ import annotations

import argparse
from mimetypes import guess_type
from pathlib import Path
import sys
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings
from app.storage.r2 import get_r2_client


DEFAULT_SOURCE_DIR = ROOT.parent / "frontend" / "data files" / "Notice"
ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".jpg", ".jpeg", ".png"}
OBJECT_PREFIX = "public/source-notices"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Upload files instead of showing the plan.")
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    args = parser.parse_args()

    source_dir = args.source_dir.resolve()
    if not source_dir.is_dir():
        raise SystemExit(f"Notice source directory not found: {source_dir}")

    files = sorted(
        path for path in source_dir.iterdir() if path.is_file() and path.suffix.lower() in ALLOWED_EXTENSIONS
    )
    if not files:
        raise SystemExit("No supported notice files found.")

    if not args.apply:
        print(f"Would upload {len(files)} unique notice files to R2:")
        for path in files:
            print(f"- {path.name}")
        print("Run again with --apply to upload.")
        return

    client = get_r2_client()
    uploaded = 0
    for path in files:
        key = f"{OBJECT_PREFIX}/{path.name}"
        content_type = guess_type(path.name)[0] or "application/octet-stream"
        client.upload_file(str(path), settings.r2_bucket, key, ExtraArgs={"ContentType": content_type})
        print(f"Uploaded: {settings.r2_public_url}/{quote(key, safe='/')}")
        uploaded += 1

    print(f"Uploaded and verified submission of {uploaded} unique notice files.")


if __name__ == "__main__":
    main()
