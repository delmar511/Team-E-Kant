# -*- coding: utf-8 -*-
"""src/search_adapter.py: to_chunk, to_candidates 컴포넌트 점수, rank_before/after_rerank. 색인 불필요."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from schemas import CandidateSource
from search_adapter import to_candidates, to_chunk


# ---------------------------------------------------------------------------
# to_chunk
# ---------------------------------------------------------------------------

_RAW = {
    "chunk_id": "DOC-D2#aaa",
    "doc_id": "DOC-D2",
    "doc_title": "유학(D-2)",
    "page": 44,
    "location": "유학(D-2) > 체류기간 연장허가 > 다. 제출서류",
    "visa_codes": ["D-2"],
    "text": "신청서, 여권, 외국인등록증, 수수료",
    "section_key": "sk-abc",
    "part": 1,
    "n_parts": 1,
}


def test_to_chunk_parses_location_string():
    ch = to_chunk(_RAW)
    assert ch.location.section_path == ["유학(D-2)", "체류기간 연장허가", "다. 제출서류"]
    assert ch.location.page_start == ch.location.page_end == 44


def test_to_chunk_copies_metadata_keys():
    ch = to_chunk(_RAW)
    assert ch.metadata["visa_codes"] == ["D-2"]
    assert ch.metadata["doc_title"] == "유학(D-2)"


def test_to_chunk_carries_section_key_and_parts():
    ch = to_chunk(_RAW)
    assert ch.section_key == "sk-abc"
    assert ch.part == 1 and ch.n_parts == 1


def test_to_chunk_missing_location_gives_empty_path():
    raw = dict(_RAW, location=None)
    ch = to_chunk(raw)
    assert ch.location.section_path == []


# ---------------------------------------------------------------------------
# to_candidates: 컴포넌트 점수
# ---------------------------------------------------------------------------

_CHUNKS = {
    "DOC-D2#aaa": _RAW,
    "DOC-D4#bbb": dict(_RAW, chunk_id="DOC-D4#bbb", doc_id="DOC-D4"),
}


def test_to_candidates_rank_starts_at_one():
    ranked = [("DOC-D2#aaa", 0.5), ("DOC-D4#bbb", 0.3)]
    cands = to_candidates(ranked, _CHUNKS, CandidateSource.VECTOR, "vector", top_k=5)
    assert cands[0].rank == 1 and cands[1].rank == 2


def test_to_candidates_component_scores_include_primary():
    ranked = [("DOC-D2#aaa", 0.42)]
    cands = to_candidates(ranked, _CHUNKS, CandidateSource.FUSED, "rrf", top_k=5)
    assert "rrf" in cands[0].component_scores
    assert abs(cands[0].component_scores["rrf"] - 0.42) < 1e-9


def test_to_candidates_extra_bm25_and_vector_scores_stored():
    """하이브리드(B 구성)에서 bm25·vector 단계 점수가 component_scores 에 들어간다."""
    ranked = [("DOC-D2#aaa", 0.03)]
    extra = {
        "bm25": {"DOC-D2#aaa": 12.5},
        "vector": {"DOC-D2#aaa": 0.88},
    }
    cands = to_candidates(ranked, _CHUNKS, CandidateSource.FUSED, "rrf", top_k=5, extra=extra)
    assert abs(cands[0].component_scores["bm25"] - 12.5) < 1e-9
    assert abs(cands[0].component_scores["vector"] - 0.88) < 1e-9


def test_to_candidates_extra_chunk_not_in_extra_dict_is_ok():
    """extra 에 없는 chunk 는 해당 단계 점수가 없어도 오류 없이 처리된다."""
    ranked = [("DOC-D2#aaa", 0.03), ("DOC-D4#bbb", 0.02)]
    extra = {"bm25": {"DOC-D2#aaa": 10.0}}   # DOC-D4#bbb 는 bm25 에 없음
    cands = to_candidates(ranked, _CHUNKS, CandidateSource.FUSED, "rrf", top_k=5, extra=extra)
    assert "bm25" in cands[0].component_scores
    assert "bm25" not in cands[1].component_scores


def test_to_candidates_top_k_limits_output():
    ranked = [("DOC-D2#aaa", 0.5), ("DOC-D4#bbb", 0.3)]
    cands = to_candidates(ranked, _CHUNKS, CandidateSource.VECTOR, "vector", top_k=1)
    assert len(cands) == 1


def test_to_candidates_rank_before_and_after_rerank_default_none():
    """재정렬 전에는 rank_before_rerank 와 rank_after_rerank 가 None 이어야 한다."""
    ranked = [("DOC-D2#aaa", 0.5)]
    cands = to_candidates(ranked, _CHUNKS, CandidateSource.VECTOR, "vector", top_k=5)
    assert cands[0].rank_before_rerank is None
    assert cands[0].rank_after_rerank is None


def test_to_candidates_source_is_set_correctly():
    for source in (CandidateSource.VECTOR, CandidateSource.FUSED):
        ranked = [("DOC-D2#aaa", 0.5)]
        cands = to_candidates(ranked, _CHUNKS, source, "score", top_k=5)
        assert cands[0].source is source
