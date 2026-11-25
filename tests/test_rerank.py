"""src/rerank.py 와 구성 C 기록 형식. 모델 없이 가짜 점수 함수로 검사한다."""
from pathlib import Path

import pytest

from agent import run_agent
from config import load_config
from rerank import rerank, rerank_text
from schemas import CandidateSource, Chunk, Location, RetrievedCandidate

ROOT = Path(__file__).resolve().parents[1]
CHUNKS = {
    "DOC-D2#a": {"chunk_id": "DOC-D2#a", "location": "유학(D-2) > 시간제취업", "text": "주당 25시간"},
    "DOC-D4#b": {"chunk_id": "DOC-D4#b", "location": "일반연수(D-4) > 시간제취업", "text": "주당 20시간"},
    "DOC-E7#c": {"chunk_id": "DOC-E7#c", "location": "", "text": "무관한 내용"},
}
FUSED = [("DOC-E7#c", 0.033), ("DOC-D2#a", 0.032), ("DOC-D4#b", 0.031)]


def fake_scores(table):
    seen = []

    def fn(query, texts):
        seen.extend(texts)
        return [table[t.split("\n")[-1]] for t in texts]
    fn.seen = seen
    return fn


def test_reorders_by_new_relevance_not_rrf():
    fn = fake_scores({"무관한 내용": -5.0, "주당 25시간": 3.0, "주당 20시간": 1.0})
    rows = rerank("D-2 시간제취업", FUSED, CHUNKS, fn, input_k=3)
    assert [r[0] for r in rows] == ["DOC-D2#a", "DOC-D4#b", "DOC-E7#c"]
    assert [r[2] for r in rows] == [2, 3, 1]  # 재정렬 전 순위 보존
    assert fn.seen[0] == "무관한 내용"          # 절 경로 없으면 본문만
    assert fn.seen[1].startswith("유학(D-2) > 시간제취업\n")


def test_input_k_limits_and_ties_keep_prior_order():
    fn = fake_scores({"무관한 내용": 1.0, "주당 25시간": 1.0, "주당 20시간": 9.0})
    rows = rerank("q", FUSED, CHUNKS, fn, input_k=2)
    assert [r[0] for r in rows] == ["DOC-E7#c", "DOC-D2#a"]  # 3번째는 입력에서 빠짐, 동점은 원래 순서


def test_score_count_mismatch_is_error():
    with pytest.raises(RuntimeError):
        rerank("q", FUSED, CHUNKS, lambda q, t: [1.0], input_k=3)


def test_rerank_text():
    assert rerank_text(CHUNKS["DOC-E7#c"]) == "무관한 내용"


def test_config_c_valid_and_records_rerank_latency():
    cfg = load_config(ROOT / "configs" / "C.toml")
    assert cfg.retrieval.reranker.model and cfg.retrieval.reranker.model != "TBD"
    assert cfg.prompt.max_context_chunks == 5  # 재정렬 출력 k

    class FakeC:
        last_rerank_ms = 7.0

        def __call__(self, q):
            return [RetrievedCandidate(
                chunk=Chunk(chunk_id="DOC-D2#00000000a1", doc_id="DOC-D2", text="t",
                            location=Location(page_start=1, page_end=1)),
                score=2.0, rank=1, source=CandidateSource.RERANKED, rank_before_rerank=4, rank_after_rerank=1)]

    r = run_agent("유학 체류기간 연장 제출서류는", cfg, FakeC())
    assert r.response.latency.rerank_ms == 7.0
    assert r.candidates[0].rank_before_rerank == 4
