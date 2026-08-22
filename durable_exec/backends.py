"""Storage backends for DurableStore.

Both implement the same tiny primitive interface the state machine needs:

    ping()                                          -> bool
    ensure_indexes()                                -> None
    upsert_run(run_id, request, meta, ts_iso)       -> None
    read_step(step_id)                              -> dict | None
    claim_step(step_id, run_id, key, meta, iso, ms) -> dict   # atomic RUNNING claim
    write_step(step_id, fields)                     -> None
    list_steps(run_id)                              -> list[dict]

MongoBackend targets a local standalone mongod (Community Edition): the only
atomicity requirement — the `begin` claim — is a single-document find_one_and_update,
which is atomic on standalone mongod, so NO replica set and NO transactions are needed.

Neither backend reads inside `result` or `meta`. They are dumb persistence.
"""

from __future__ import annotations

from typing import Optional

DONE = "DONE"
RUNNING = "RUNNING"


class MongoBackend:
    def __init__(self, uri: str = "mongodb://localhost:27017", db: str = "durable_exec"):
        from pymongo import MongoClient, ReturnDocument

        self._ReturnDocument = ReturnDocument
        self._client = MongoClient(uri)
        self._db = self._client[db]
        self.runs = self._db["runs"]
        self.steps = self._db["steps"]
        self.ensure_indexes()

    def ping(self) -> bool:
        self._client.admin.command("ping")
        return True

    def ensure_indexes(self) -> None:
        # _id is indexed by default (begin/get point lookups).
        self.steps.create_index([("runId", 1), ("state", 1)])  # context()/resume queries

    def upsert_run(self, run_id, request, meta, ts_iso) -> None:
        self.runs.update_one(
            {"_id": run_id},
            {
                "$set": {"updatedAt": ts_iso},
                "$setOnInsert": {"request": request, "meta": meta, "status": "open", "createdAt": ts_iso},
            },
            upsert=True,
        )

    def read_step(self, step_id) -> Optional[dict]:
        return self.steps.find_one({"_id": step_id})

    def claim_step(self, step_id, run_id, key, meta, ts_iso, ts_ms) -> dict:
        from pymongo.errors import DuplicateKeyError

        try:
            return self.steps.find_one_and_update(
                {"_id": step_id, "state": {"$ne": DONE}},  # never clobber a DONE step
                {
                    "$set": {
                        "state": RUNNING,
                        "startedAt": ts_iso,
                        "startedMs": ts_ms,
                        "error": None,
                        "endedAt": None,
                        "elapsedMs": None,
                        "meta": meta,
                    },
                    "$inc": {"attempt": 1},
                    "$setOnInsert": {"runId": run_id, "key": key, "createdAt": ts_iso},
                },
                upsert=True,
                return_document=self._ReturnDocument.AFTER,
            )
        except DuplicateKeyError:
            # A concurrent worker inserted a DONE doc between our read and this claim.
            return self.steps.find_one({"_id": step_id})

    def write_step(self, step_id, fields) -> None:
        self.steps.update_one({"_id": step_id}, {"$set": fields})

    def list_steps(self, run_id) -> list:
        return list(self.steps.find({"runId": run_id}))


class MemoryBackend:
    """In-process dict backend — same semantics, no server. For tests / offline demos.

    Resume across process restarts obviously requires a persistent backend (Mongo);
    within a single process this behaves identically to MongoBackend.
    """

    def __init__(self):
        self._runs: dict = {}
        self._steps: dict = {}

    def ping(self) -> bool:
        return True

    def ensure_indexes(self) -> None:
        pass

    def upsert_run(self, run_id, request, meta, ts_iso) -> None:
        run = self._runs.get(run_id)
        if run is None:
            self._runs[run_id] = {
                "_id": run_id,
                "request": request,
                "meta": meta,
                "status": "open",
                "createdAt": ts_iso,
                "updatedAt": ts_iso,
            }
        else:
            run["updatedAt"] = ts_iso

    def read_step(self, step_id) -> Optional[dict]:
        doc = self._steps.get(step_id)
        return dict(doc) if doc else None

    def claim_step(self, step_id, run_id, key, meta, ts_iso, ts_ms) -> dict:
        doc = self._steps.get(step_id)
        if doc is None:
            doc = {"_id": step_id, "runId": run_id, "key": key, "createdAt": ts_iso, "attempt": 0}
            self._steps[step_id] = doc
        if doc.get("state") == DONE:  # never clobber a DONE step
            return dict(doc)
        doc.update(
            {
                "state": RUNNING,
                "startedAt": ts_iso,
                "startedMs": ts_ms,
                "error": None,
                "endedAt": None,
                "elapsedMs": None,
                "meta": meta,
                "attempt": doc.get("attempt", 0) + 1,
            }
        )
        return dict(doc)

    def write_step(self, step_id, fields) -> None:
        self._steps[step_id].update(fields)

    def list_steps(self, run_id) -> list:
        return [dict(d) for d in self._steps.values() if d["runId"] == run_id]
