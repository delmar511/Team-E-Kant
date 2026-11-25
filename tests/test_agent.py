"""src/agent.py: 상태 6가지 구분, 인용 검사, 근거 판정, 캐시, 리라이트 fallback. API 호출 없음."""
import json
from pathlib import Path

import pytest

from agent import run_agent
from answer.dev_stub import StubRetriever
from config import build_versions, load_config
from optimize.cache import AnswerCache
from schemas import AgentResponse, Status

ROOT = Path(__file__).resolve().parents[1]
Q = "유학 체류기간 연장 제출서류는"


def cfg(name="A", **gate):
    c = load_config(ROOT / "configs" / f"{name}.toml")
    if gate:
        c = c.model_copy(update={"evidence_gate": c.evidence_gate.model_copy(update=gate)})
        c._repo_root, c._source = ROOT, ROOT / "configs" / f"{name}.toml"
    return c


def _llm(answer, cited, insufficient=False):
    return lambda prompt: json.dumps({"answer": answer, "cited_chunk_ids": cited,
                                      "insufficient_evidence": insufficient}, ensure_ascii=False)


def test_answered_with_valid_citation_and_schema():
    r = run_agent(Q, cfg(), StubRetriever())
    assert isinstance(r.response, AgentResponse) and r.response.status is Status.ANSWERED
    assert r.response.cited_chunk_ids == ["DOC-D2#00000000a1"] and not r.response.invalid_citation_ids
    assert r.candidates[0].chunk.chunk_id == "DOC-D2#00000000a1"
    lat = r.response.latency
    assert lat.retrieval_ms is not None and lat.generation_ms is not None and lat.total_ms > 0
    assert r.response.usage.model_calls == 1
    assert r.response.cache_hit is None and r.response.rewritten_query is None  # 최적화 꺼짐


def test_retrieval_error_is_distinguished_from_no_evidence():
    def broken(query):
        raise TimeoutError("search timeout")

    r = run_agent(Q, cfg(), broken)
    assert r.response.status is Status.RETRIEVAL_ERROR and "search timeout" in r.response.error_message
    assert r.response.answer is None and not r.candidates


def test_model_error_keeps_candidates_for_hit_at_5():
    def bad_llm(prompt):
        raise RuntimeError("model down")

    r = run_agent(Q, cfg(), StubRetriever(), llm_fn=bad_llm)
    assert r.response.status is Status.MODEL_ERROR and r.candidates


def test_model_timeout():
    class APITimeoutError(Exception):
        pass

    def slow_llm(prompt):
        raise APITimeoutError("Request timed out.")

    assert run_agent(Q, cfg(), StubRetriever(), llm_fn=slow_llm).response.status is Status.TIMEOUT


def test_format_error_after_retry_is_model_error():
    r = run_agent(Q, cfg(), StubRetriever(), llm_fn=lambda p: "not json")
    assert r.response.status is Status.MODEL_ERROR and "OutputFormatError" in r.response.error_message
    assert r.response.usage.model_calls == 2  # 형식 오류 1회 재요청


def test_missing_retriever_is_a_setup_bug_not_a_status():
    with pytest.raises(ValueError):
        run_agent(Q, cfg(), None)


def test_no_evidence_by_model_self_judgment():
    r = run_agent(Q, cfg(), StubRetriever(), llm_fn=_llm("제공된 문서에서 근거를 찾을 수 없습니다.", [], True))
    assert r.response.status is Status.NO_EVIDENCE and not r.response.status.is_error
    assert "모델" in r.trace["no_evidence_reason"]


def test_partial_answer_keeps_citations_under_no_evidence():
    r = run_agent(Q, cfg(), StubRetriever(), llm_fn=_llm(
        "허가 여부 판정은 문서에서 확인되지 않습니다. 참고 요건: 재학증명서 제출 [DOC-D2#00000000a1]",
        ["DOC-D2#00000000a1"], True))
    assert r.response.status is Status.NO_EVIDENCE
    assert r.response.cited_chunk_ids == ["DOC-D2#00000000a1"] and "참고 요건" in r.response.answer


def test_no_evidence_by_score_gate_skips_generation():
    def never(prompt):
        raise AssertionError("점수 게이트에 걸리면 생성하지 않아야 함")

    c = cfg(method="score_threshold", params={"min_score": 0.9})
    r = run_agent("이 신청자 허가해도 되나", c, StubRetriever(), llm_fn=never)
    assert r.response.status is Status.NO_EVIDENCE and "점수 게이트" in r.trace["no_evidence_reason"]
    assert r.response.usage.model_calls == 0


def test_score_gate_without_min_score_is_config_error():
    with pytest.raises(ValueError, match="min_score"):
        run_agent(Q, cfg(method="both", params={}), StubRetriever())


def test_zero_candidates_is_no_evidence():
    r = run_agent(Q, cfg(), lambda q: [])
    assert r.response.status is Status.NO_EVIDENCE and r.trace["no_evidence_reason"] == "검색 결과 0건"


def test_citation_outside_context_is_rejected_and_marked():
    c = cfg()
    c = c.model_copy(update={"prompt": c.prompt.model_copy(update={"max_context_chunks": 1})})
    c._repo_root, c._source = ROOT, ROOT / "configs/A.toml"
    r = run_agent(Q, c, StubRetriever(),
                  llm_fn=_llm("정답 [DOC-D2#00000000a1] [DOC-D9#deadbeef00]", ["DOC-D2#00000000a1", "DOC-D9#deadbeef00"]))
    assert r.trace["context_chunk_ids"] == ["DOC-D2#00000000a1"]
    assert r.response.cited_chunk_ids == ["DOC-D2#00000000a1"]
    assert r.response.invalid_citation_ids == ["DOC-D9#deadbeef00"]
    assert "[검증 실패: DOC-D9#deadbeef00]" in r.response.answer


def test_cache_hit_and_invalidation_by_version():
    c = cfg("C_cache")
    v1 = build_versions(c)
    v2 = v1.model_copy(update={"index_version": v1.index_version + "-rebuilt"})
    cache = AnswerCache()
    first = run_agent(Q, c, StubRetriever(), cache=cache, versions=v1).response
    second = run_agent(Q, c, StubRetriever(), cache=cache, versions=v1).response
    third = run_agent(Q, c, StubRetriever(), cache=cache, versions=v2).response
    assert (first.cache_hit, second.cache_hit, third.cache_hit) == (False, True, False)
    assert second.answer == first.answer and second.usage.model_calls == 0


def test_errors_are_not_cached():
    c, cache = cfg("C_cache"), AnswerCache()
    v = build_versions(c)

    def broken(query):
        raise RuntimeError("down")

    run_agent(Q, c, broken, cache=cache, versions=v)
    assert run_agent(Q, c, StubRetriever(), cache=cache, versions=v).response.cache_hit is False


def test_rewrite_used_for_retrieval_and_original_kept_for_generation():
    seen = {}

    def spy(query):
        seen["q"] = query
        return StubRetriever()(query)

    r = run_agent("유학생 알바 허가 대상은", cfg("C_rewrite"), spy)
    assert seen["q"] == "유학생 시간제취업 허가 대상은" == r.response.rewritten_query


def test_rewrite_failure_falls_back_to_original_question():
    def bad_rewriter(prompt):
        raise RuntimeError("rewrite failed")

    r = run_agent(Q, cfg("C_rewrite"), StubRetriever(), rewrite_fn=bad_rewriter)
    assert r.response.status is Status.ANSWERED and r.trace["rewrite_fallback"] is True
    assert r.response.rewritten_query == Q
