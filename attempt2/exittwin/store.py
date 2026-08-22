"""Persistence for the three ExitTwin collections.

Two interchangeable backends behind one interface:
  * JsonStore  — zero-dependency, one JSON file per collection. The default so a
                 fresh `git pull && python run_demo.py` works with nothing else set.
  * MongoStore — used when EXITTWIN_MONGODB_URI is set and pymongo is importable;
                 writes to the real `building_evidence`, `observations`, and
                 `scenario_runs` collections on the GB10.

Raw RGB video never enters either store (issue #15 data contract).
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

from . import config

COLLECTIONS = ("building_evidence", "observations", "scenario_runs")


class JsonStore:
    def __init__(self, root: pathlib.Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, collection: str) -> pathlib.Path:
        return self.root / f"{collection}.json"

    def all(self, collection: str) -> list[dict[str, Any]]:
        path = self._path(collection)
        if not path.exists():
            return []
        return json.loads(path.read_text())

    def replace(self, collection: str, docs: list[dict[str, Any]]) -> None:
        self._path(collection).write_text(json.dumps(docs, indent=2))

    def upsert(self, collection: str, doc: dict[str, Any], key: str = "id") -> None:
        docs = self.all(collection)
        docs = [d for d in docs if d.get(key) != doc.get(key)]
        docs.append(doc)
        self.replace(collection, docs)

    def label(self) -> str:
        return f"json:{self.root}"


class MongoStore:  # pragma: no cover - requires a live MongoDB
    def __init__(self, uri: str, db_name: str) -> None:
        from pymongo import MongoClient  # imported lazily; optional dependency

        self._db = MongoClient(uri)[db_name]
        self._uri = uri

    def all(self, collection: str) -> list[dict[str, Any]]:
        return list(self._db[collection].find({}, {"_id": 0}))

    def replace(self, collection: str, docs: list[dict[str, Any]]) -> None:
        self._db[collection].delete_many({})
        if docs:
            self._db[collection].insert_many([dict(d) for d in docs])

    def upsert(self, collection: str, doc: dict[str, Any], key: str = "id") -> None:
        self._db[collection].replace_one({key: doc.get(key)}, doc, upsert=True)

    def label(self) -> str:
        return f"mongodb:{self._uri}"


def get_store() -> "JsonStore | MongoStore":
    if config.MONGODB_URI:
        try:
            return MongoStore(config.MONGODB_URI, config.MONGODB_DB)
        except Exception as exc:  # noqa: BLE001 - fall back rather than crash the demo
            print(f"[store] MongoDB unavailable ({exc}); using JSON store")
    return JsonStore(config.DATA_DIR / "store")
