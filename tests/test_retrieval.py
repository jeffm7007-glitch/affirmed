"""Lexical retrieval tests (criteria #22, #23, #57)."""

from __future__ import annotations

from affirmed_mcp.retrieval import IndexCache, LexicalIndex, evidence_set_digest, retrieval_metadata, tokenize
from affirmed_mcp.source import open_source, load_all_records


def _records(demo_db_path):
    conn = open_source(demo_db_path)
    try:
        return load_all_records(conn)[0]
    finally:
        conn.close()


def test_tokenize_normalizes():
    assert tokenize("Towing, towing! TOWING") == ["towing", "towing", "towing"]


def test_search_returns_ranked_records_with_scores(demo_db_path):
    records = _records(demo_db_path)
    index = LexicalIndex(records)
    hits, scores, diag = index.search("towing price", 3)
    assert len(hits) <= 3
    assert [h["id"] for h in hits][0] == "r_towing_price"
    assert len(scores) == len(hits)
    assert diag["corpus_size"] == len(records)


def test_evidence_set_digest_identifies_ordered_records(demo_db_path):
    records = _records(demo_db_path)
    index = LexicalIndex(records)
    hits, _, _ = index.search("towing", 2)
    assert evidence_set_digest(hits) == evidence_set_digest(list(hits))
    assert evidence_set_digest(list(reversed(hits))) != evidence_set_digest(hits)
    assert evidence_set_digest(hits) != evidence_set_digest(hits[:1])


def test_retrieval_metadata_documents_score_meaning():
    meta = retrieval_metadata("q", 5, {"x": 1})
    assert meta["score_meaning"] == "retrieval_ranking_signal_not_probability"


def test_index_cache_keyed_by_snapshot_and_never_mutates_source(demo_db_path):
    """#57: cold and warm cache runs return identical records/digests; source untouched."""
    records = _records(demo_db_path)
    index = LexicalIndex(records)
    cache = IndexCache()
    cache.put("snap-1", index)
    assert cache.get("snap-1") is index
    assert cache.get("snap-other") is None
    hits_cold, _, _ = index.search("fuel delivery costs", 2)
    warm = LexicalIndex(records)
    hits_warm, _, _ = warm.search("fuel delivery costs", 2)
    assert [h["id"] for h in hits_cold] == [h["id"] for h in hits_warm]
    assert evidence_set_digest(hits_cold) == evidence_set_digest(hits_warm)
    # Source is opened read-only; nothing writes.
    conn = open_source(demo_db_path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM evidence_records").fetchone()[0]
        assert count == 8
    finally:
        conn.close()
