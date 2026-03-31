"""
LocalVectorDB - Local semantic search without cloud dependencies.

Wraps ChromaDB for local vector storage and similarity search.
All data stays on the user's machine.

Key features:
- No cloud API calls for embeddings (uses local models)
- Persistent storage in user directory
- Collections for different document types
- Metadata filtering support

Usage:
    # Initialize
    db = LocalVectorDB()
    
    # Add documents
    await db.add_documents(
        collection="emails",
        documents=["Meeting tomorrow at 3pm", "Invoice attached"],
        metadatas=[{"from": "boss@co.com"}, {"from": "billing@co.com"}],
        ids=["email_1", "email_2"]
    )
    
    # Search
    results = await db.search("meetings", collection="emails", n_results=5)
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import logging
import hashlib

logger = logging.getLogger(__name__)

# ChromaDB is optional - graceful degradation
try:
    import chromadb
    from chromadb.config import Settings
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False
    logger.warning("ChromaDB not installed. LocalVectorDB will use fallback mode.")


@dataclass
class SearchResult:
    """A single search result."""
    id: str
    document: str
    distance: float  # Lower = more similar
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def similarity(self) -> float:
        """Convert distance to similarity score (0-1)."""
        # For cosine distance, similarity ~= 1 - distance
        return max(0, 1 - self.distance)


@dataclass
class SearchResults:
    """Collection of search results."""
    query: str
    collection: str
    results: List[SearchResult]
    total: int
    
    def __iter__(self):
        return iter(self.results)
    
    def __len__(self):
        return len(self.results)


class LocalVectorDB:
    """
    Local vector database for semantic search.
    
    Uses ChromaDB with local persistence.
    Falls back to keyword matching if ChromaDB unavailable.
    """
    
    # Default collections
    DEFAULT_COLLECTIONS = [
        "emails",      # Email content
        "files",       # File content
        "calendar",    # Calendar events
        "contacts",    # Contact info
        "tasks",       # Task descriptions
        "notes",       # User notes
        "history",     # Action history descriptions
    ]
    
    def __init__(
        self,
        persist_dir: Optional[str] = None,
        embedding_model: str = "all-MiniLM-L6-v2",
    ):
        """
        Initialize LocalVectorDB.
        
        Args:
            persist_dir: Directory for persistent storage
            embedding_model: Sentence transformer model to use
        """
        apex_dir = Path.home() / ".apex"
        apex_dir.mkdir(exist_ok=True)
        
        if persist_dir is None:
            persist_dir = str(apex_dir / "vector_db")
        
        self._persist_dir = Path(persist_dir)
        self._persist_dir.mkdir(exist_ok=True)
        
        self._embedding_model = embedding_model
        self._client = None
        self._collections: Dict[str, Any] = {}
        
        self._init_client()
    
    def _init_client(self):
        """Initialize ChromaDB client."""
        if not CHROMADB_AVAILABLE:
            logger.warning("ChromaDB not available, using fallback storage")
            self._use_fallback = True
            self._fallback_store: Dict[str, List[Dict]] = {}
            return
        
        self._use_fallback = False
        
        try:
            self._client = chromadb.Client(Settings(
                persist_directory=str(self._persist_dir),
                anonymized_telemetry=False,
                is_persistent=True,
            ))
            logger.info(f"ChromaDB initialized at {self._persist_dir}")
        except Exception as e:
            logger.error(f"ChromaDB init failed: {e}, using fallback")
            self._use_fallback = True
            self._fallback_store = {}
    
    def _get_collection(self, name: str):
        """Get or create a collection."""
        if self._use_fallback:
            if name not in self._fallback_store:
                self._fallback_store[name] = []
            return None
        
        if name not in self._collections:
            self._collections[name] = self._client.get_or_create_collection(
                name=name,
                metadata={"hnsw:space": "cosine"}  # Use cosine similarity
            )
        return self._collections[name]
    
    async def add_documents(
        self,
        collection: str,
        documents: List[str],
        ids: Optional[List[str]] = None,
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> int:
        """
        Add documents to a collection.
        
        Args:
            collection: Collection name
            documents: List of document texts
            ids: Optional list of IDs (generated if not provided)
            metadatas: Optional list of metadata dicts
            
        Returns:
            Number of documents added
        """
        if not documents:
            return 0
        
        # Generate IDs if not provided
        if ids is None:
            ids = [
                hashlib.sha256(doc.encode()).hexdigest()[:16]
                for doc in documents
            ]
        
        if metadatas is None:
            metadatas = [{} for _ in documents]
        
        # Add timestamp to metadata
        for meta in metadatas:
            if "added_at" not in meta:
                meta["added_at"] = datetime.now().isoformat()
        
        if self._use_fallback:
            self._add_fallback(collection, documents, ids, metadatas)
            return len(documents)
        
        try:
            coll = self._get_collection(collection)
            coll.add(
                documents=documents,
                ids=ids,
                metadatas=metadatas,
            )
            return len(documents)
        except Exception as e:
            logger.error(f"Failed to add documents: {e}")
            return 0
    
    def _add_fallback(
        self,
        collection: str,
        documents: List[str],
        ids: List[str],
        metadatas: List[Dict],
    ):
        """Add documents to fallback store."""
        if collection not in self._fallback_store:
            self._fallback_store[collection] = []
        
        for doc, doc_id, meta in zip(documents, ids, metadatas):
            # Remove existing with same ID
            self._fallback_store[collection] = [
                d for d in self._fallback_store[collection]
                if d["id"] != doc_id
            ]
            self._fallback_store[collection].append({
                "id": doc_id,
                "document": doc,
                "metadata": meta,
            })
    
    async def search(
        self,
        query: str,
        collection: str,
        n_results: int = 10,
        where: Optional[Dict[str, Any]] = None,
    ) -> SearchResults:
        """
        Search for similar documents.
        
        Args:
            query: Search query
            collection: Collection to search
            n_results: Maximum results to return
            where: Metadata filter
            
        Returns:
            SearchResults with matching documents
        """
        if self._use_fallback:
            return self._search_fallback(query, collection, n_results, where)
        
        try:
            coll = self._get_collection(collection)
            
            kwargs = {
                "query_texts": [query],
                "n_results": n_results,
            }
            if where:
                kwargs["where"] = where
            
            results = coll.query(**kwargs)
            
            search_results = []
            if results["ids"] and results["ids"][0]:
                for i, doc_id in enumerate(results["ids"][0]):
                    search_results.append(SearchResult(
                        id=doc_id,
                        document=results["documents"][0][i] if results["documents"] else "",
                        distance=results["distances"][0][i] if results["distances"] else 0,
                        metadata=results["metadatas"][0][i] if results["metadatas"] else {},
                    ))
            
            return SearchResults(
                query=query,
                collection=collection,
                results=search_results,
                total=len(search_results),
            )
        
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return SearchResults(
                query=query,
                collection=collection,
                results=[],
                total=0,
            )
    
    def _search_fallback(
        self,
        query: str,
        collection: str,
        n_results: int,
        where: Optional[Dict],
    ) -> SearchResults:
        """Fallback keyword search."""
        if collection not in self._fallback_store:
            return SearchResults(query=query, collection=collection, results=[], total=0)
        
        docs = self._fallback_store[collection]
        query_lower = query.lower()
        query_words = set(query_lower.split())
        
        scored = []
        for doc in docs:
            # Apply where filter
            if where:
                match = True
                for key, value in where.items():
                    if doc["metadata"].get(key) != value:
                        match = False
                        break
                if not match:
                    continue
            
            # Simple keyword scoring
            doc_lower = doc["document"].lower()
            doc_words = set(doc_lower.split())
            
            # Count matching words
            matches = len(query_words & doc_words)
            if matches > 0:
                # Score based on word overlap
                score = matches / max(len(query_words), len(doc_words))
                scored.append((doc, 1 - score))  # Convert to distance
            elif query_lower in doc_lower:
                scored.append((doc, 0.3))  # Substring match
        
        # Sort by distance (lower = better)
        scored.sort(key=lambda x: x[1])
        
        results = [
            SearchResult(
                id=doc["id"],
                document=doc["document"],
                distance=dist,
                metadata=doc["metadata"],
            )
            for doc, dist in scored[:n_results]
        ]
        
        return SearchResults(
            query=query,
            collection=collection,
            results=results,
            total=len(results),
        )
    
    async def update_document(
        self,
        collection: str,
        doc_id: str,
        document: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Update a document.
        
        Args:
            collection: Collection name
            doc_id: Document ID
            document: New document text (optional)
            metadata: New metadata (optional)
            
        Returns:
            True if updated
        """
        if self._use_fallback:
            return self._update_fallback(collection, doc_id, document, metadata)
        
        try:
            coll = self._get_collection(collection)
            
            kwargs = {"ids": [doc_id]}
            if document:
                kwargs["documents"] = [document]
            if metadata:
                kwargs["metadatas"] = [metadata]
            
            coll.update(**kwargs)
            return True
        except Exception as e:
            logger.error(f"Update failed: {e}")
            return False
    
    def _update_fallback(
        self,
        collection: str,
        doc_id: str,
        document: Optional[str],
        metadata: Optional[Dict],
    ) -> bool:
        """Update document in fallback store."""
        if collection not in self._fallback_store:
            return False
        
        for doc in self._fallback_store[collection]:
            if doc["id"] == doc_id:
                if document:
                    doc["document"] = document
                if metadata:
                    doc["metadata"].update(metadata)
                return True
        return False
    
    async def delete_document(
        self,
        collection: str,
        doc_id: str,
    ) -> bool:
        """
        Delete a document.
        
        Args:
            collection: Collection name
            doc_id: Document ID
            
        Returns:
            True if deleted
        """
        if self._use_fallback:
            return self._delete_fallback(collection, doc_id)
        
        try:
            coll = self._get_collection(collection)
            coll.delete(ids=[doc_id])
            return True
        except Exception as e:
            logger.error(f"Delete failed: {e}")
            return False
    
    def _delete_fallback(self, collection: str, doc_id: str) -> bool:
        """Delete from fallback store."""
        if collection not in self._fallback_store:
            return False
        
        original_len = len(self._fallback_store[collection])
        self._fallback_store[collection] = [
            d for d in self._fallback_store[collection]
            if d["id"] != doc_id
        ]
        return len(self._fallback_store[collection]) < original_len
    
    async def delete_by_metadata(
        self,
        collection: str,
        where: Dict[str, Any],
    ) -> int:
        """
        Delete documents matching metadata filter.
        
        Args:
            collection: Collection name
            where: Metadata filter
            
        Returns:
            Number of documents deleted
        """
        if self._use_fallback:
            return self._delete_by_metadata_fallback(collection, where)
        
        try:
            coll = self._get_collection(collection)
            
            # Get matching IDs first
            results = coll.get(where=where)
            if not results["ids"]:
                return 0
            
            coll.delete(ids=results["ids"])
            return len(results["ids"])
        except Exception as e:
            logger.error(f"Delete by metadata failed: {e}")
            return 0
    
    def _delete_by_metadata_fallback(
        self,
        collection: str,
        where: Dict[str, Any],
    ) -> int:
        """Delete by metadata from fallback store."""
        if collection not in self._fallback_store:
            return 0
        
        original_len = len(self._fallback_store[collection])
        
        def matches_where(doc):
            for key, value in where.items():
                if doc["metadata"].get(key) != value:
                    return False
            return True
        
        self._fallback_store[collection] = [
            d for d in self._fallback_store[collection]
            if not matches_where(d)
        ]
        
        return original_len - len(self._fallback_store[collection])
    
    def get_collection_stats(self, collection: str) -> Dict[str, Any]:
        """Get statistics for a collection."""
        if self._use_fallback:
            docs = self._fallback_store.get(collection, [])
            return {
                "name": collection,
                "count": len(docs),
                "backend": "fallback",
            }
        
        try:
            coll = self._get_collection(collection)
            return {
                "name": collection,
                "count": coll.count(),
                "backend": "chromadb",
            }
        except Exception as e:
            return {
                "name": collection,
                "count": 0,
                "error": str(e),
            }
    
    def list_collections(self) -> List[str]:
        """List all collections."""
        if self._use_fallback:
            return list(self._fallback_store.keys())
        
        try:
            collections = self._client.list_collections()
            return [c.name for c in collections]
        except Exception:
            return []
    
    def delete_collection(self, collection: str) -> bool:
        """Delete an entire collection."""
        if self._use_fallback:
            if collection in self._fallback_store:
                del self._fallback_store[collection]
                return True
            return False
        
        try:
            self._client.delete_collection(collection)
            if collection in self._collections:
                del self._collections[collection]
            return True
        except Exception as e:
            logger.error(f"Delete collection failed: {e}")
            return False
    
    @property
    def backend(self) -> str:
        """Get current backend name."""
        return "fallback" if self._use_fallback else "chromadb"
    
    @property
    def is_available(self) -> bool:
        """Check if vector DB is available."""
        return CHROMADB_AVAILABLE and not self._use_fallback


# Global instance
local_vector_db = LocalVectorDB()
