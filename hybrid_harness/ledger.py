import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _now():
    return datetime.now(timezone.utc).isoformat()


class Ledger:
    def __init__(self, database, blobs):
        self.database = Path(database)
        self.blobs = Path(blobs)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.blobs.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(self.database))
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, parent_id TEXT, tenant_id TEXT NOT NULL,
                product_id TEXT NOT NULL, stage TEXT NOT NULL, status TEXT NOT NULL,
                prompt TEXT NOT NULL, provider TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                checks TEXT, error TEXT,
                FOREIGN KEY(parent_id) REFERENCES runs(id)
            );
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY, run_id TEXT NOT NULL, kind TEXT NOT NULL,
                payload TEXT NOT NULL, created_at TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES runs(id)
            );
            CREATE TABLE IF NOT EXISTS artifacts (
                id TEXT PRIMARY KEY, run_id TEXT NOT NULL, tenant_id TEXT NOT NULL,
                product_id TEXT NOT NULL, name TEXT NOT NULL, hash TEXT NOT NULL,
                bytes INTEGER NOT NULL, created_at TEXT NOT NULL,
                UNIQUE(run_id,name), FOREIGN KEY(run_id) REFERENCES runs(id)
            );
            CREATE TABLE IF NOT EXISTS merge_events (
                delivery_id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
                commit_sha TEXT NOT NULL, continuation_id TEXT NOT NULL,
                created_at TEXT NOT NULL, UNIQUE(run_id,commit_sha),
                FOREIGN KEY(run_id) REFERENCES runs(id),
                FOREIGN KEY(continuation_id) REFERENCES runs(id)
            );
        """)

    def _one(self, query, args=()):
        row = self.connection.execute(query, args).fetchone()
        return dict(row) if row else None

    def create_run(self, stage, prompt, provider, tenant_id="demo", product_id="demo", parent_id=None):
        run_id = str(uuid.uuid4())
        time = _now()
        with self.connection:
            self.connection.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (run_id, parent_id, tenant_id, product_id, stage, "running", prompt, provider, time, time, None, None))
            self._event(run_id, "run.started", {"stage": stage, "parentId": parent_id})
        return self.get_run(run_id)

    def get_run(self, run_id):
        row = self._one("SELECT * FROM runs WHERE id=?", (run_id,))
        if row and row["checks"]:
            row["checks"] = json.loads(row["checks"])
        return row

    def list_runs(self, limit=30):
        ids = [row["id"] for row in self.connection.execute("SELECT id FROM runs ORDER BY created_at DESC LIMIT ?", (limit,))]
        return [self.get_run(run_id) for run_id in ids]

    def _event(self, run_id, kind, payload):
        self.connection.execute("INSERT INTO events VALUES (?,?,?,?,?)", (str(uuid.uuid4()), run_id, kind, json.dumps(payload), _now()))

    def event(self, run_id, kind, payload=None):
        with self.connection:
            self._event(run_id, kind, payload or {})

    def events(self, run_id):
        return [{**dict(row), "payload": json.loads(row["payload"])} for row in self.connection.execute("SELECT * FROM events WHERE run_id=? ORDER BY created_at,id", (run_id,))]

    def transition(self, run_id, expected, next_status, checks=None, error=None):
        with self.connection:
            row = self._one("SELECT status FROM runs WHERE id=?", (run_id,))
            if not row or row["status"] != expected:
                raise ValueError("Expected %s, found %s" % (expected, row["status"] if row else "missing"))
            self.connection.execute("UPDATE runs SET status=?,updated_at=?,checks=COALESCE(?,checks),error=? WHERE id=?", (next_status, _now(), json.dumps(checks) if checks is not None else None, error, run_id))
            self._event(run_id, "run." + next_status, {"from": expected, "error": error})
        return self.get_run(run_id)

    def put_artifact(self, run, name, content, write_set):
        if name not in write_set:
            raise ValueError("Artifact name denied")
        data = content.encode("utf-8")
        digest = hashlib.sha256(data).hexdigest()
        path = self.blobs / digest
        if not path.exists():
            path.write_bytes(data)
        artifact_id = str(uuid.uuid4())
        with self.connection:
            self.connection.execute("INSERT INTO artifacts VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(run_id,name) DO UPDATE SET id=excluded.id,hash=excluded.hash,bytes=excluded.bytes,created_at=excluded.created_at", (artifact_id, run["id"], run["tenant_id"], run["product_id"], name, digest, len(data), _now()))
            self._event(run["id"], "artifact.written", {"name": name, "hash": digest, "bytes": len(data)})
        return {"id": artifact_id, "hash": digest, "bytes": len(data)}

    def artifacts(self, run_id):
        return [dict(row) for row in self.connection.execute("SELECT * FROM artifacts WHERE run_id=? ORDER BY name", (run_id,))]

    def read_artifact(self, run_id, name):
        row = self._one("SELECT hash FROM artifacts WHERE run_id=? AND name=?", (run_id, name))
        if not row:
            return None
        data = (self.blobs / row["hash"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != row["hash"]:
            raise ValueError("Artifact hash mismatch")
        return data.decode("utf-8")

    def child(self, run_id, stage):
        row = self._one("SELECT id FROM runs WHERE parent_id=? AND stage=? ORDER BY created_at DESC LIMIT 1", (run_id, stage))
        return self.get_run(row["id"]) if row else None

    def merge_event(self, delivery_id, run_id, commit_sha):
        return self._one("SELECT * FROM merge_events WHERE delivery_id=? OR (run_id=? AND commit_sha=?)", (delivery_id, run_id, commit_sha))

    def record_merge(self, delivery_id, run_id, commit_sha, continuation_id):
        with self.connection:
            self.connection.execute("INSERT INTO merge_events VALUES (?,?,?,?,?)", (delivery_id, run_id, commit_sha, continuation_id, _now()))
            self._event(continuation_id, "pr.merged", {"deliveryId": delivery_id, "commitSha": commit_sha, "runId": run_id})

    def close(self):
        self.connection.close()
