"""Content-addressed SQLite cache for LLM exit decisions.

Keyed by (model identity, prompt version, canonical prompt), so a decision is
reused only when the exact same question was asked of the exact same model. A
changed model or prompt version yields a new key rather than a stale answer.

`backend/app/services/cache.py` is not reused: its in-memory LRU (128 entries,
300 s TTL) is sized for API responses, not for a multi-hour decision sweep.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

FLOAT_PRECISION = 6


def _round_floats(obj: Any) -> Any:
    if isinstance(obj, float):
        if not math.isfinite(obj):
            return str(obj)
        r = round(obj, FLOAT_PRECISION)
        # 1.0 and 1 describe the same quantity; normalise so the key does not
        # depend on whether a feature happened to be an int or a float.
        return int(r) if r == int(r) and abs(r) < 1e15 else r
    if isinstance(obj, dict):
        return {str(k): _round_floats(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_round_floats(v) for v in obj]
    return obj


def canonicalize(obj: Any) -> str:
    """Stable string form: sorted keys, rounded floats, separators fixed."""
    return json.dumps(_round_floats(obj), sort_keys=True,
                      separators=(",", ":"), default=str)


class DecisionCache:
    """Persistent, deterministic store of gate decisions."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS decisions (
                   key TEXT PRIMARY KEY,
                   model TEXT,
                   prompt_version TEXT,
                   prompt TEXT,
                   response TEXT,
                   decision_json TEXT,
                   latency_s REAL,
                   created_at REAL
               )""")
        self._conn.commit()
        self._hits = 0
        self._misses = 0

    def key(self, model: str, prompt_version: str, canonical_prompt: str) -> str:
        h = hashlib.sha256()
        h.update(model.encode("utf-8"))
        h.update(b"\x00")
        h.update(prompt_version.encode("utf-8"))
        h.update(b"\x00")
        h.update(canonical_prompt.encode("utf-8"))
        return h.hexdigest()

    def get(self, key: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT decision_json FROM decisions WHERE key=?", (key,)).fetchone()
        if row is None:
            self._misses += 1
            return None
        try:
            decision = json.loads(row[0])
        except (TypeError, ValueError):
            # A corrupted row is a miss, never a silent wrong answer.
            self._misses += 1
            return None
        self._hits += 1
        return decision

    def put(self, key: str, request: dict, response: dict, decision: dict,
            latency_s: float) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO decisions "
            "(key, model, prompt_version, prompt, response, decision_json, "
            " latency_s, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (key,
             str(request.get("model", "")),
             str(request.get("prompt_version", "")),
             str(request.get("prompt", "")),
             json.dumps(response, default=str),
             json.dumps(decision, default=str),
             float(latency_s),
             time.time()))
        self._conn.commit()

    def stats(self) -> dict:
        n = self._hits + self._misses
        return {"hits": self._hits, "misses": self._misses,
                "hit_rate": round(self._hits / n, 4) if n else 0.0,
                "rows": self._conn.execute(
                    "SELECT COUNT(*) FROM decisions").fetchone()[0]}

    def close(self) -> None:
        self._conn.close()
