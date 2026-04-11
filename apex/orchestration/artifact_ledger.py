"""Indexed artifact ledger for orchestration handoffs.

The ledger stores all generated artifacts in SQLite with indexes so downstream
steps (e.g., message/send tools) can find outputs quickly and reliably.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ArtifactRecord:
    artifact_id: str
    workflow_id: str
    step_id: str
    tool_name: str
    artifact_type: str
    uri: str
    checksum: str
    metadata: Dict[str, Any]
    created_at: str


class ArtifactLedger:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    step_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    uri TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    metadata_json TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_artifacts_workflow
                ON artifacts (workflow_id, created_at DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_artifacts_tool
                ON artifacts (tool_name, created_at DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_artifacts_uri
                ON artifacts (uri)
                """
            )

    def record_artifact(
        self,
        workflow_id: str,
        step_id: str,
        tool_name: str,
        artifact_type: str,
        uri: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[ArtifactRecord]:
        if not uri:
            return None
        metadata = metadata or {}
        created_at = datetime.now(timezone.utc).isoformat()
        fingerprint = f"{workflow_id}|{step_id}|{tool_name}|{artifact_type}|{uri}"
        artifact_id = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:24]
        checksum = hashlib.sha256(uri.encode("utf-8")).hexdigest()[:16]

        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO artifacts
                (artifact_id, workflow_id, step_id, tool_name, artifact_type, uri, checksum, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id,
                    workflow_id,
                    step_id,
                    tool_name,
                    artifact_type,
                    uri,
                    checksum,
                    json.dumps(metadata, default=str),
                    created_at,
                ),
            )

        return ArtifactRecord(
            artifact_id=artifact_id,
            workflow_id=workflow_id,
            step_id=step_id,
            tool_name=tool_name,
            artifact_type=artifact_type,
            uri=uri,
            checksum=checksum,
            metadata=metadata,
            created_at=created_at,
        )

    def list_artifacts(self, workflow_id: str, limit: int = 50) -> List[ArtifactRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT artifact_id, workflow_id, step_id, tool_name, artifact_type, uri, checksum, metadata_json, created_at
                FROM artifacts
                WHERE workflow_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (workflow_id, limit),
            ).fetchall()

        records: List[ArtifactRecord] = []
        for r in rows:
            records.append(
                ArtifactRecord(
                    artifact_id=r["artifact_id"],
                    workflow_id=r["workflow_id"],
                    step_id=r["step_id"],
                    tool_name=r["tool_name"],
                    artifact_type=r["artifact_type"],
                    uri=r["uri"],
                    checksum=r["checksum"],
                    metadata=json.loads(r["metadata_json"] or "{}"),
                    created_at=r["created_at"],
                )
            )
        return records


def extract_artifact_candidates(tool_name: str, result: Any) -> List[Dict[str, Any]]:
    """Extract artifact candidates from generic tool results.

    This is schema-agnostic and supports new primitives/connectors automatically.
    """

    candidates: List[Dict[str, Any]] = []

    def _visit(node: Any, depth: int = 0) -> None:
        if depth > 4:
            return
        if isinstance(node, dict):
            path_val = node.get("path") or node.get("file") or node.get("filepath")
            url_val = node.get("url") or node.get("uri")
            if isinstance(path_val, str) and path_val.strip():
                candidates.append(
                    {
                        "artifact_type": "file",
                        "uri": path_val.strip(),
                        "metadata": {"source": tool_name},
                    }
                )
            if isinstance(url_val, str) and url_val.strip():
                candidates.append(
                    {
                        "artifact_type": "url",
                        "uri": url_val.strip(),
                        "metadata": {"source": tool_name},
                    }
                )
            attachments = node.get("attachments")
            if isinstance(attachments, list):
                for a in attachments:
                    if isinstance(a, str) and a.strip():
                        candidates.append(
                            {
                                "artifact_type": "attachment",
                                "uri": a.strip(),
                                "metadata": {"source": tool_name},
                            }
                        )
                    elif isinstance(a, dict):
                        a_uri = a.get("path") or a.get("url") or a.get("uri")
                        if isinstance(a_uri, str) and a_uri.strip():
                            candidates.append(
                                {
                                    "artifact_type": "attachment",
                                    "uri": a_uri.strip(),
                                    "metadata": {"source": tool_name, "raw": a},
                                }
                            )
            for v in node.values():
                _visit(v, depth + 1)
        elif isinstance(node, list):
            for item in node:
                _visit(item, depth + 1)

    _visit(result)

    unique: Dict[str, Dict[str, Any]] = {}
    for c in candidates:
        key = f"{c['artifact_type']}|{c['uri']}"
        unique[key] = c
    return list(unique.values())
