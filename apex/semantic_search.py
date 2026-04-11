"""
Semantic Search

Vector embedding layer on top of the local data index. Enables natural
language search across all indexed objects:

  "that budget spreadsheet John sent last week"
  → finds the email, the attached file, and the related calendar event

Architecture:
  Embedder        — Generates vector embeddings (local or API)
  VectorStore     — SQLite blob storage for embeddings + numpy cosine search
  SemanticSearch  — High-level API combining vector search with FTS5 fallback

Embedding strategy:
  - Primary: sentence-transformers (local, no API call, ~5ms per embed)
  - Fallback: OpenAI text-embedding-3-small (if local model unavailable)
  - Vectors stored as numpy float32 blobs in SQLite
  - Cosine similarity search — brute force is fast enough for <100k objects

Usage:
    from apex.semantic_search import SemanticSearch

    ss = SemanticSearch(index)
    results = await ss.search("budget spreadsheet from John", limit=10)
    # Returns [(DataObject, score), ...] sorted by relevance
"""

import asyncio
import logging
import os
import struct
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Embedder — generates vector embeddings
# ---------------------------------------------------------------------------

class Embedder:
    """Generates text embeddings using local model or API fallback.

    Uses sentence-transformers 'all-MiniLM-L6-v2' by default:
      - 384 dimensions
      - ~5ms per single text, ~50ms per batch of 64
      - 80MB model download on first use
      - No API key needed
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self._model_name = model_name
        self._model = None
        self._dimension: int = 0
        self._backend = "none"
        self._openai_client = None

    @property
    def dimension(self) -> int:
        """Embedding vector dimension."""
        return self._dimension

    @property
    def backend(self) -> str:
        """Which backend is active: 'local', 'openai', 'hash', or 'none'."""
        return self._backend

    def initialize(self) -> bool:
        """Load the embedding model. Returns True if ready."""
        # Try local sentence-transformers first
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_name)
            # Get dimension from a test embedding
            test = self._model.encode(["test"], convert_to_numpy=True)
            self._dimension = test.shape[1]
            self._backend = "local"
            logger.info(f"Embedder: local model '{self._model_name}' loaded ({self._dimension}d)")
            return True
        except Exception as e:
            logger.warning(f"Local embedding model failed: {e}")

        # Fallback to OpenAI
        api_key = os.environ.get("OPENAI_API_KEY")
        if api_key:
            try:
                import openai
                self._openai_client = openai.OpenAI(api_key=api_key)
                self._dimension = 1536  # text-embedding-3-small default
                self._backend = "openai"
                logger.info("Embedder: using OpenAI text-embedding-3-small (1536d)")
                return True
            except Exception as e:
                logger.warning(f"OpenAI embedding fallback failed: {e}")

        # Last resort: deterministic local hash embeddings (lower quality but always available)
        self._dimension = 384
        self._backend = "hash"
        logger.info("Embedder: using built-in hash embeddings (384d)")
        return True

    def embed(self, texts: List[str]) -> np.ndarray:
        """Embed a list of texts. Returns (N, dimension) float32 array."""
        if not texts:
            return np.array([], dtype=np.float32).reshape(0, self._dimension)

        if self._backend == "local":
            return self._embed_local(texts)
        elif self._backend == "openai":
            return self._embed_openai(texts)
        elif self._backend == "hash":
            return self._embed_hash(texts)
        else:
            raise RuntimeError("Embedder not initialized — call initialize() first")

    def embed_one(self, text: str) -> np.ndarray:
        """Embed a single text. Returns (dimension,) float32 array."""
        result = self.embed([text])
        return result[0]

    def _embed_local(self, texts: List[str]) -> np.ndarray:
        """Embed using local sentence-transformers model."""
        # Truncate very long texts (model has max token limit)
        truncated = [t[:2000] for t in texts]
        vectors = self._model.encode(
            truncated,
            convert_to_numpy=True,
            show_progress_bar=False,
            normalize_embeddings=True,  # Pre-normalize for cosine sim
        )
        return vectors.astype(np.float32)

    def _embed_openai(self, texts: List[str]) -> np.ndarray:
        """Embed using OpenAI API."""
        # Truncate and batch (API limit: 8191 tokens per text)
        truncated = [t[:6000] for t in texts]
        response = self._openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=truncated,
        )
        vectors = np.array(
            [d.embedding for d in response.data],
            dtype=np.float32,
        )
        # Normalize for cosine similarity
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        vectors = vectors / norms
        return vectors

    def _embed_hash(self, texts: List[str]) -> np.ndarray:
        """Embed using token hashing for offline, dependency-free semantic matching."""
        import hashlib
        import re

        vectors = np.zeros((len(texts), self._dimension), dtype=np.float32)
        for row, text in enumerate(texts):
            tokens = re.findall(r"\w+", (text or "").lower())[:512]
            if not tokens:
                tokens = [""]

            for token in tokens:
                digest = hashlib.sha256(token.encode("utf-8", errors="ignore")).digest()
                idx = int.from_bytes(digest[:4], "little") % self._dimension
                sign = 1.0 if (digest[4] & 1) == 0 else -1.0
                vectors[row, idx] += sign

        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        return vectors / norms


# ---------------------------------------------------------------------------
# VectorStore — SQLite storage for embeddings
# ---------------------------------------------------------------------------

_VECTOR_SCHEMA = """
CREATE TABLE IF NOT EXISTS embeddings (
    object_id    TEXT PRIMARY KEY,     -- matches data_objects.id
    vector       BLOB NOT NULL,        -- numpy float32 array
    text_hash    TEXT NOT NULL,         -- hash of embedded text (for re-embed detection)
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_emb_object
    ON embeddings(object_id);
"""


def _vector_to_blob(v: np.ndarray) -> bytes:
    """Serialize a numpy vector to bytes for SQLite BLOB storage."""
    return v.astype(np.float32).tobytes()


def _blob_to_vector(blob: bytes, dim: int) -> np.ndarray:
    """Deserialize bytes from SQLite BLOB to numpy vector."""
    return np.frombuffer(blob, dtype=np.float32).copy()


def _text_hash(text: str) -> str:
    """Quick hash to detect when text changes and re-embedding is needed."""
    import hashlib
    return hashlib.md5(text.encode(errors="replace")).hexdigest()[:12]


class VectorStore:
    """SQLite-backed vector storage with numpy cosine search.

    For <100k objects, brute-force cosine similarity is fast:
      - 10k vectors: ~2ms search
      - 50k vectors: ~8ms search
      - 100k vectors: ~15ms search
    """

    def __init__(self, db_path: Optional[str] = None, dimension: int = 384):
        if db_path is None:
            db_path = str(Path(__file__).parent / "sqlite" / "vectors.db")
        self._db_path = db_path
        self._dimension = dimension
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_VECTOR_SCHEMA)
        self._conn.commit()

        # In-memory cache for fast search (loaded once, updated incrementally)
        self._ids: List[str] = []
        self._matrix: Optional[np.ndarray] = None  # (N, dim) normalized vectors
        self._dirty = True

        logger.info(f"VectorStore opened: {db_path} ({dimension}d)")

    def close(self):
        self._conn.close()

    @property
    def count(self) -> int:
        """Number of stored embeddings."""
        row = self._conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()
        return row[0]

    def upsert(self, object_id: str, vector: np.ndarray, text_hash_val: str) -> None:
        """Store or update a single embedding."""
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        self._conn.execute("""
            INSERT INTO embeddings (object_id, vector, text_hash, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(object_id) DO UPDATE SET
                vector=excluded.vector, text_hash=excluded.text_hash, created_at=excluded.created_at
        """, (object_id, _vector_to_blob(vector), text_hash_val, now))
        self._conn.commit()
        self._dirty = True

    def upsert_batch(self, items: List[Tuple[str, np.ndarray, str]]) -> int:
        """Batch upsert. Items: [(object_id, vector, text_hash), ...]. Returns count."""
        if not items:
            return 0
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        rows = [
            (oid, _vector_to_blob(vec), th, now)
            for oid, vec, th in items
        ]
        self._conn.executemany("""
            INSERT INTO embeddings (object_id, vector, text_hash, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(object_id) DO UPDATE SET
                vector=excluded.vector, text_hash=excluded.text_hash, created_at=excluded.created_at
        """, rows)
        self._conn.commit()
        self._dirty = True
        return len(rows)

    def delete(self, object_id: str) -> None:
        """Remove an embedding."""
        self._conn.execute("DELETE FROM embeddings WHERE object_id = ?", (object_id,))
        self._conn.commit()
        self._dirty = True

    def get_text_hash(self, object_id: str) -> Optional[str]:
        """Get the text hash for an object (to check if re-embedding needed)."""
        row = self._conn.execute(
            "SELECT text_hash FROM embeddings WHERE object_id = ?", (object_id,)
        ).fetchone()
        return row[0] if row else None

    def get_text_hashes(self, object_ids: List[str]) -> Dict[str, str]:
        """Batch get text hashes. Returns {object_id: text_hash}."""
        if not object_ids:
            return {}
        placeholders = ",".join("?" for _ in object_ids)
        rows = self._conn.execute(
            f"SELECT object_id, text_hash FROM embeddings WHERE object_id IN ({placeholders})",
            object_ids
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def search(
        self,
        query_vector: np.ndarray,
        limit: int = 20,
        min_score: float = 0.0,
    ) -> List[Tuple[str, float]]:
        """Find the most similar vectors by cosine similarity.

        Returns [(object_id, score), ...] sorted by descending similarity.
        """
        self._ensure_loaded()
        if self._matrix is None or len(self._ids) == 0:
            return []

        # Cosine similarity = dot product of normalized vectors
        query_norm = query_vector / (np.linalg.norm(query_vector) or 1.0)
        scores = self._matrix @ query_norm

        # Get top-k indices
        if limit < len(scores):
            top_indices = np.argpartition(scores, -limit)[-limit:]
            top_indices = top_indices[np.argsort(scores[top_indices])[::-1]]
        else:
            top_indices = np.argsort(scores)[::-1]

        results = []
        for idx in top_indices:
            score = float(scores[idx])
            if score >= min_score:
                results.append((self._ids[idx], score))
            if len(results) >= limit:
                break

        return results

    def _ensure_loaded(self):
        """Load all vectors into memory for fast search."""
        if not self._dirty and self._matrix is not None:
            return

        rows = self._conn.execute(
            "SELECT object_id, vector FROM embeddings"
        ).fetchall()

        if not rows:
            self._ids = []
            self._matrix = None
            self._dirty = False
            return

        self._ids = [r[0] for r in rows]
        vectors = [_blob_to_vector(r[1], self._dimension) for r in rows]
        self._matrix = np.stack(vectors)
        self._dirty = False
        logger.info(f"VectorStore: loaded {len(self._ids)} embeddings into memory")


# ---------------------------------------------------------------------------
# SemanticSearch — high-level API
# ---------------------------------------------------------------------------

class SemanticSearch:
    """Cross-service semantic search over the local data index.

    Combines vector similarity with FTS5 text search for best results.

    Usage:
        ss = SemanticSearch(index)
        await ss.initialize()
        results = await ss.search("budget spreadsheet from John")
    """

    def __init__(self, index, db_path: Optional[str] = None):
        """
        Args:
            index: The Index instance (from apex/index.py)
            db_path: Path for vectors.db (defaults to apex/sqlite/vectors.db)
        """
        self._index = index
        self._embedder = Embedder()
        self._store: Optional[VectorStore] = None
        self._db_path = db_path
        self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "ready": self._ready,
            "backend": self._embedder.backend,
            "dimension": self._embedder.dimension,
            "embedded_count": self._store.count if self._store else 0,
            "index_count": self._index.count() if self._index else 0,
        }

    async def initialize(self) -> bool:
        """Initialize the embedder and vector store.

        This loads the embedding model (may download on first run).
        Call once at startup.
        """
        # Run model loading in thread to not block the event loop
        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(None, self._embedder.initialize)
        if not success:
            logger.error("Semantic search: no embedding backend available")
            return False

        self._store = VectorStore(
            db_path=self._db_path,
            dimension=self._embedder.dimension,
        )
        self._ready = True
        logger.info(f"Semantic search ready: {self._embedder.backend} ({self._embedder.dimension}d), {self._store.count} vectors cached")
        return True

    async def search(
        self,
        query: str,
        kind: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 20,
        min_score: float = 0.25,
    ) -> List[Tuple[Any, float]]:
        """Semantic search across all indexed objects.

        Args:
            query: Natural language search query
            kind: Filter by ObjectKind (event, email, contact, etc.)
            limit: Max results to return
            min_score: Minimum cosine similarity threshold

        Returns:
            List of (DataObject, score) tuples sorted by relevance
        """
        if not self._ready:
            logger.warning("Semantic search not ready, falling back to FTS")
            return self._fts_fallback(query, kind, limit)

        try:
            # Generate query embedding
            loop = asyncio.get_event_loop()
            query_vector = await loop.run_in_executor(
                None, self._embedder.embed_one, query
            )

            # Vector search — get more candidates than needed for post-filtering
            fetch_limit = limit * 3 if (kind or source) else limit
            candidates = self._store.search(
                query_vector, limit=fetch_limit, min_score=min_score
            )

            if not candidates:
                # Fall back to FTS5 text search
                return self._fts_fallback(query, kind, limit)

            # Resolve object_ids to DataObjects and apply filters
            results = []
            for object_id, score in candidates:
                # Look up the actual object
                obj = self._get_object(object_id)
                if not obj:
                    continue
                # Apply kind/source filters
                if kind and obj.kind.value != kind:
                    continue
                if source and obj.source != source:
                    continue
                results.append((obj, score))
                if len(results) >= limit:
                    break

            # If all vector candidates were stale/filtered, fall back to FTS
            if not results:
                return self._fts_fallback(query, kind, limit)

            return results

        except Exception as e:
            logger.warning(f"Vector search failed, falling back to FTS: {e}")
            return self._fts_fallback(query, kind, limit)

    def _fts_fallback(
        self, query: str, kind: Optional[str], limit: int
    ) -> List[Tuple[Any, float]]:
        """Fall back to FTS5 text search when vectors aren't available."""
        try:
            results = self._index.search(query, kind=kind, limit=limit)
            # Assign synthetic scores based on FTS rank position
            return [(obj, 1.0 - i * 0.05) for i, obj in enumerate(results)]
        except Exception:
            return []

    def _get_object(self, object_id: str) -> Optional[Any]:
        """Look up a DataObject by its composite ID.
        
        IDs use format 'source:source_id'. We handle Windows paths
        (e.g. 'local_file:C:\\Users\\...') by finding the first colon
        that follows a known source prefix rather than blindly splitting.
        """
        try:
            # Handle Windows drive letters: if the part after first colon
            # starts with \\ or /, it's likely a path — try splitting at
            # the second colon instead.  Fall back to the raw split.
            colon_pos = object_id.find(":")
            if colon_pos == -1:
                return None
            # Check if this looks like source:X:\path (drive letter after source:)
            remainder = object_id[colon_pos + 1:]
            if len(remainder) >= 2 and remainder[1] == ":" and remainder[0].isalpha():
                # Windows path — source is everything before the first colon
                pass  # colon_pos is already correct
            results = self._index._conn.execute(
                "SELECT * FROM data_objects WHERE id = ?", (object_id,)
            ).fetchone()
            if results:
                return self._index._row_to_obj(results)
        except Exception:
            pass
        return None

    # -------------------------------------------------------------------
    # Embedding pipeline — builds/updates embeddings for indexed objects
    # -------------------------------------------------------------------

    async def embed_all(self, batch_size: int = 64) -> Dict[str, int]:
        """Embed all objects in the index that don't have embeddings yet.

        Returns stats: {embedded, skipped, errors, time_ms}
        """
        if not self._ready:
            return {"error": "not initialized"}

        start = time.time()
        stats = {"embedded": 0, "skipped": 0, "errors": 0}

        # Get all objects from the index
        all_objects = self._index._conn.execute(
            "SELECT id, title, body, participants FROM data_objects"
        ).fetchall()

        if not all_objects:
            return {**stats, "time_ms": 0}

        # Check which already have up-to-date embeddings
        object_ids = [r[0] for r in all_objects]
        existing_hashes = self._store.get_text_hashes(object_ids)

        # Build list of objects that need (re-)embedding
        to_embed: List[Tuple[str, str]] = []  # (object_id, text)
        for row in all_objects:
            obj_id = row[0]
            text = self._make_embed_text(row[1], row[2], row[3])
            current_hash = _text_hash(text)

            if existing_hashes.get(obj_id) == current_hash:
                stats["skipped"] += 1
                continue

            to_embed.append((obj_id, text, current_hash))

        if not to_embed:
            elapsed = (time.time() - start) * 1000
            return {**stats, "time_ms": round(elapsed, 1)}

        # Embed in batches
        loop = asyncio.get_event_loop()
        for i in range(0, len(to_embed), batch_size):
            batch = to_embed[i:i + batch_size]
            texts = [t[1] for t in batch]

            try:
                vectors = await loop.run_in_executor(
                    None, self._embedder.embed, texts
                )
                items = [
                    (batch[j][0], vectors[j], batch[j][2])
                    for j in range(len(batch))
                ]
                self._store.upsert_batch(items)
                stats["embedded"] += len(batch)
            except Exception as e:
                logger.error(f"Embedding batch failed: {e}")
                stats["errors"] += len(batch)

        elapsed = (time.time() - start) * 1000
        logger.info(
            f"Embedding complete: {stats['embedded']} new, "
            f"{stats['skipped']} skipped, {stats['errors']} errors "
            f"in {elapsed:.0f}ms"
        )
        return {**stats, "time_ms": round(elapsed, 1)}

    async def embed_objects(self, objects: List[Any]) -> int:
        """Embed a specific list of DataObjects (used during sync).

        Returns count of objects embedded.
        """
        if not self._ready or not objects:
            return 0

        to_embed = []
        texts_for_hash = []
        for obj in objects:
            text = self._make_embed_text(
                obj.title, obj.body,
                json.dumps(obj.participants) if isinstance(obj.participants, list) else str(obj.participants)
            )
            h = _text_hash(text)
            existing = self._store.get_text_hash(obj.id)
            if existing == h:
                continue
            to_embed.append((obj.id, text, h))

        if not to_embed:
            return 0

        texts = [t[1] for t in to_embed]
        loop = asyncio.get_event_loop()
        try:
            vectors = await loop.run_in_executor(
                None, self._embedder.embed, texts
            )
            items = [
                (to_embed[j][0], vectors[j], to_embed[j][2])
                for j in range(len(to_embed))
            ]
            self._store.upsert_batch(items)
            return len(items)
        except Exception as e:
            logger.error(f"Failed to embed {len(to_embed)} objects: {e}")
            return 0

    @staticmethod
    def _make_embed_text(title: str, body: str, participants_json: str) -> str:
        """Combine fields into a single text for embedding.

        We include title (most important), first ~500 chars of body,
        and participant names — this captures the semantic essence.
        """
        parts = []
        if title:
            parts.append(title)
        if body:
            parts.append(body[:500])
        try:
            participants = json.loads(participants_json) if isinstance(participants_json, str) else participants_json
            if participants:
                parts.append("with " + ", ".join(str(p) for p in participants[:5]))
        except (json.JSONDecodeError, TypeError):
            pass
        return " | ".join(parts) if parts else ""


# Need json for _make_embed_text
import json
