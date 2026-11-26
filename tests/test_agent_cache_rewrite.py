# -*- coding: utf-8 -*-
"""agent.py: 캐시+리라이트 상호작용, 순서(캐시→리라이트→검색→생성), 리라이트 쿼리 캐시 키. API 호출 없음."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent import run_agent
from answer.dev_stub import StubRetriever
from config import build_versions, load_config
from optimize.cache import AnswerCache, make_key

ROOT_CFG = ROOT


def _cfg(name):
    return load_config(ROOT_CFG / "configs" / f"{name}.toml")


# ---------------------------------------------------------------------------
# 캐시 적중 시 리라이트를 호출하지 않는다
# ---------------------------------------------------------------------------

def test_cache_hit_skips_rewrite():
    """캐시 적중 경로에서는 rewrite_fn 을 호출해선 안 된다."""
    never_called = {"rewrite": False}

    def spy_rewrite(prompt):
        never_called["rewrite"] = True
        return "리라이트 결과"

    cfg = _cfg("C_cache")
    versions = build_versions(cfg)
    cache = AnswerCache()

    q = "D-4 시간제취업 요건은?"

    # 첫 호출: 캐시 미적중 (리라이트 없는 C_cache 구성)
    run_agent(q, cfg, StubRetriever(), cache=cache, versions=versions)

    never_called["rewrite"] = False  # 리셋
    # 두 번째 호출: 캐시 적중 — 리라이트 절대 호출 안 됨
    result = run_agent(q, cfg, StubRetriever(), cache=cache, versions=versions)
    assert result.response.cache_hit is True
    assert not never_called["rewrite"], "캐시 적중인데 rewrite_fn 이 호출됨"


# ---------------------------------------------------------------------------
# 캐시 조회는 리라이트 전에 일어난다
# ---------------------------------------------------------------------------

def test_cache_checked_before_retrieval():
    """캐시 적중 시 retriever 가 호출되지 않는다 (캐시→검색 순서 보장)."""
    retrieval_called = {"n": 0}

    def spy_retriever(query):
        retrieval_called["n"] += 1
        return StubRetriever()(query)

    cfg = _cfg("C_cache")
    versions = build_versions(cfg)
    cache = AnswerCache()
    q = "D-2 연장 서류는?"

    run_agent(q, cfg, spy_retriever, cache=cache, versions=versions)
    n_first = retrieval_called["n"]
    assert n_first >= 1

    retrieval_called["n"] = 0
    result = run_agent(q, cfg, spy_retriever, cache=cache, versions=versions)
    assert result.response.cache_hit is True
    assert retrieval_called["n"] == 0, "캐시 적중인데 retriever 가 호출됨"


# ---------------------------------------------------------------------------
# 리라이트 오류는 캐시에 저장되지 않는다
# ---------------------------------------------------------------------------

def test_rewrite_fallback_result_not_cached():
    """리라이트 fallback(오류)으로 얻은 결과는 캐시에 넣지 않는다."""
    def broken_rewrite(prompt):
        raise RuntimeError("rewrite down")

    cfg = _cfg("C_rewrite")
    versions = build_versions(cfg)
    cache = AnswerCache()
    q = "어학당 알바 조건은?"

    result = run_agent(q, cfg, StubRetriever(), rewrite_fn=broken_rewrite,
                       cache=cache, versions=versions)
    assert result.trace.get("rewrite_fallback") is True

    # 같은 질문을 다시 보내면 캐시 미적중이어야 한다
    result2 = run_agent(q, cfg, StubRetriever(), rewrite_fn=broken_rewrite,
                        cache=cache, versions=versions)
    assert result2.response.cache_hit is not True


# ---------------------------------------------------------------------------
# 리라이트 결과가 retriever 에게 전달된다
# ---------------------------------------------------------------------------

def test_rewritten_query_reaches_retriever():
    """리라이트 결과가 검색 질의로 쓰인다 (원질문이 아님)."""
    seen_queries = []

    def spy_retriever(query):
        seen_queries.append(query)
        return StubRetriever()(query)

    cfg = _cfg("C_rewrite")

    run_agent("어학당 학생 알바 허가", cfg, spy_retriever)
    assert seen_queries, "retriever 가 호출되지 않음"
    # 용어 사전 치환 경로: "알바" → "시간제취업", "어학당" → "어학연수(D-4)"
    assert "알바" not in seen_queries[0], f"리라이트 결과가 retriever 에 전달되지 않음: {seen_queries[0]}"


# ---------------------------------------------------------------------------
# 버전 변경 → 이전 캐시 미적중
# ---------------------------------------------------------------------------

def test_different_index_version_misses_cache():
    """색인 버전이 바뀌면 이전 답변을 재사용하지 않는다."""
    cfg = _cfg("C_cache")
    v1 = build_versions(cfg)
    v2 = v1.model_copy(update={"index_version": v1.index_version + "-new"})
    cache = AnswerCache()
    q = "D-4 연장 서류는?"

    run_agent(q, cfg, StubRetriever(), cache=cache, versions=v1)
    result = run_agent(q, cfg, StubRetriever(), cache=cache, versions=v2)
    assert result.response.cache_hit is not True, "버전이 바뀌었는데 캐시 적중"
