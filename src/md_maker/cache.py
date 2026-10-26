"""On-disk cache of AI results, so reruns and interrupted runs are free."""

import hashlib
import json
import os
from pathlib import Path


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def key(*parts) -> str:
    return hashlib.sha256("\x1f".join(map(str, parts)).encode()).hexdigest()


class Cache:
    """JSON files under root; root=None disables caching."""

    def __init__(self, root: Path | None):
        self.root = root

    def _path(self, k: str) -> Path:
        return self.root / k[:2] / f"{k}.json"

    def get(self, k: str) -> dict | None:
        if not self.root:
            return None
        try:
            return json.loads(self._path(k).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def put(self, k: str, value: dict):
        if not self.root:
            return
        path = self._path(k)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            pass  # a cache that can't be written only costs a rerun
