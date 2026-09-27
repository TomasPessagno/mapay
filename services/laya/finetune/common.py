"""Shared by the fine-tune scripts. The data is news text and the repo is public, so it lives in
LAYA_DATA_DIR (default ~/mapay-laya-data), never in git."""
import os
import re
from pathlib import Path

DATA_DIR = Path(os.environ.get("LAYA_DATA_DIR", Path.home() / "mapay-laya-data"))


def title_key(title: str) -> str:
    """Normalised first ten words: the same story from several outlets gets the same key."""
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", title.lower()).split()[:10])
