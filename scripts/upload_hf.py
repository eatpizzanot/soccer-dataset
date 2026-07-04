"""Upload the curated parquet dataset to Hugging Face Datasets.

Requires a Hugging Face token (label ``huggingface`` in the secrets file, or HF_TOKEN env).
Never prints the token. Idempotent: re-running re-uploads changed files.

    python scripts/upload_hf.py --repo eatpizzanot/soccer-dataset
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import config as c


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="eatpizzanot/soccer-dataset")
    ap.add_argument("--private", action="store_true")
    args = ap.parse_args()

    try:
        from huggingface_hub import HfApi
    except ImportError:
        raise SystemExit("pip install huggingface_hub to upload")

    token = None
    try:
        token = c.huggingface_token()
    except Exception:
        import os
        token = os.environ.get("HF_TOKEN")
    if not token:
        raise SystemExit("no Hugging Face token found (secrets file label 'huggingface' or HF_TOKEN env)")

    api = HfApi(token=token)
    api.create_repo(args.repo, repo_type="dataset", exist_ok=True, private=args.private)

    # upload curated parquet + metadata + quality report + docs
    files = list(c.CURATED_DIR.glob("*.parquet"))
    for f in files:
        api.upload_file(path_or_fileobj=str(f), path_in_repo=f.name,
                        repo_id=args.repo, repo_type="dataset")
        print(f"  uploaded {f.name}")
    for extra, dest in [
        (c.METADATA_DIR / "datapackage.json", "datapackage.json"),
        (c.METADATA_DIR / "croissant.json", "croissant.json"),
        (c.REPO_ROOT / "QUALITY_REPORT.md", "QUALITY_REPORT.md"),
        (c.REPO_ROOT / "docs" / "data_dictionary.md", "data_dictionary.md"),
        (c.REPO_ROOT / "README_HF.md", "README.md"),
    ]:
        if extra.exists():
            api.upload_file(path_or_fileobj=str(extra), path_in_repo=dest,
                            repo_id=args.repo, repo_type="dataset")
            print(f"  uploaded {dest}")
    print(f"done -> https://huggingface.co/datasets/{args.repo}")


if __name__ == "__main__":
    main()
