"""Lexical BM25 retrieval (spec §3, §4B, §11).

Method is explicitly labeled ``lexical_bm25`` (k1=1.2, b=0.75, fixed and
versioned). Scores are retrieval-ranking signals, never calibrated
probabilities or evidence-confidence percentages.

The in-memory index cache is keyed by
``(source_snapshot_id, tokenizer_version, retrieval_version)``. Cache hits
return the same ordered records as a cold run; no cache may write to the
evidence source (the source is opened read-only regardless).
"""

from __future__ import annotations

import math
import re
import unicodedata
from typing import Any

from . import RETRIEVAL_VERSION, TOKENIZER_VERSION
from .schema import record_digest
from .canonical import digest

TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)
RETRIEVAL_METHOD = "lexical_bm25"
DETERMINISTIC_TIE_BREAK = "score_descending_then_id_ascending"


def tokenize(text: str) -> list[str]:
    """Tokenizer v1: Unicode-aware word tokens, NFC + lowercase."""
    normalized = unicodedata.normalize("NFC", text).lower()
    return TOKEN_RE.findall(normalized)


class LexicalIndex:
    """In-memory BM25 index over the ``text`` field of one snapshot."""

    def __init__(self, records: list[dict[str, Any]], k1: float = 1.2, b: float = 0.75):
        self.records = records
        self.k1 = k1
        self.b = b
        self.doc_tokens: list[list[str]] = [tokenize(r.get("text", "")) for r in records]
        self.doc_lengths = [len(toks) for toks in self.doc_tokens]
        self.avgdl = (sum(self.doc_lengths) / len(self.doc_lengths)) if self.doc_lengths else 0.0
        self.doc_freqs: dict[str, int] = {}
        for toks in self.doc_tokens:
            for tok in set(toks):
                self.doc_freqs[tok] = self.doc_freqs.get(tok, 0) + 1
        self.N = len(records)

    def _idf(self, term: str) -> float:
        df = self.doc_freqs.get(term, 0)
        # BM25 idf (Robertson variant, floored at 0 for stability on tiny corpora)
        return max(0.0, math.log(1.0 + (self.N - df + 0.5) / (df + 0.5)))

    def score(self, query_tokens: list[str], doc_idx: int) -> float:
        toks = self.doc_tokens[doc_idx]
        if not toks:
            return 0.0
        freq: dict[str, int] = {}
        for tok in toks:
            freq[tok] = freq.get(tok, 0) + 1
        dl = self.doc_lengths[doc_idx]
        total = 0.0
        for term in set(query_tokens):
            f = freq.get(term, 0)
            if f == 0:
                continue
            idf = self._idf(term)
            denom = f + self.k1 * (1.0 - self.b + self.b * (dl / self.avgdl if self.avgdl else 0.0))
            total += idf * (f * (self.k1 + 1.0)) / denom
        return total

    def search(self, query: str, limit: int) -> tuple[list[dict[str, Any]], list[float], dict[str, Any]]:
        query_tokens = tokenize(query)
        scored = [
            (self.score(query_tokens, idx), self.records[idx].get("id", ""), idx)
            for idx in range(self.N)
        ]
        # Deterministic ordering: score desc, then id asc (documented tie-break).
        scored.sort(key=lambda item: (-item[0], str(item[1])))
        top = scored[:limit]
        records = [self.records[idx] for _, _, idx in top]
        scores = [s for s, _, _ in top]
        diagnostics = {
            "query_token_count": len(query_tokens),
            "query_tokens": query_tokens,
            "corpus_size": self.N,
            "tie_break": DETERMINISTIC_TIE_BREAK,
        }
        return records, scores, diagnostics


class IndexCache:
    """In-memory cache keyed by (snapshot_id, tokenizer_version, retrieval_version)."""

    def __init__(self):
        self._store: dict[tuple[str, str, str], LexicalIndex] = {}

    def get(self, snapshot_id: str) -> LexicalIndex | None:
        key = (snapshot_id, TOKENIZER_VERSION, RETRIEVAL_VERSION)
        return self._store.get(key)

    def put(self, snapshot_id: str, index: LexicalIndex) -> None:
        key = (snapshot_id, TOKENIZER_VERSION, RETRIEVAL_VERSION)
        self._store[key] = index


GLOBAL_INDEX_CACHE = IndexCache()


def evidence_set_digest(records: list[dict[str, Any]]) -> str:
    """Digest over the exact ordered canonical records of one retrieval/claim."""
    return digest([record_digest(r) for r in records])


def retrieval_metadata(query: str, limit: int, diagnostics: dict[str, Any]) -> dict[str, Any]:
    return {
        "method": RETRIEVAL_METHOD,
        "parameters": {"query": query, "limit": limit, "k1": 1.2, "b": 0.75},
        "tokenizer_version": TOKENIZER_VERSION,
        "retrieval_version": RETRIEVAL_VERSION,
        "score_meaning": "retrieval_ranking_signal_not_probability",
        "tie_break": DETERMINISTIC_TIE_BREAK,
        **diagnostics,
    }
