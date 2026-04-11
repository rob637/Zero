import builtins

from semantic_search import Embedder


def _block_sentence_transformers_import(monkeypatch):
    real_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name.startswith("sentence_transformers"):
            raise ImportError("blocked for test")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _fake_import)


def test_embedder_prefers_charhash_before_hash(monkeypatch):
    _block_sentence_transformers_import(monkeypatch)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("TELIC_ENABLE_CHARHASH_EMBEDDINGS", "1")

    emb = Embedder()
    assert emb.initialize() is True
    assert emb.backend == "charhash"
    assert emb.dimension == 512

    vecs = emb.embed(["hello world", "hello there world"])
    assert vecs.shape == (2, 512)


def test_embedder_uses_hash_when_charhash_disabled(monkeypatch):
    _block_sentence_transformers_import(monkeypatch)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("TELIC_ENABLE_CHARHASH_EMBEDDINGS", "0")

    emb = Embedder()
    assert emb.initialize() is True
    assert emb.backend == "hash"
    assert emb.dimension == 384

    vec = emb.embed_one("fallback path")
    assert vec.shape == (384,)
