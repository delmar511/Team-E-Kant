"""질문 -> (캐시) -> (리라이트) -> 검색 -> 근거 판정 -> 생성 -> 인용 검사 -> schemas.AgentResponse.  [김선규]

status (schemas.Status, problem.md 9절):
  answered         정상 답변
  no_evidence      정상적인 근거 없음 (검색 0건, 점수 게이트, 모델 자기 판단)
  retrieval_error  검색 실패
  model_error      모델 오류 (거절·잘림·재시도 후에도 형식 오류)
  timeout          모델 호출 timeout
오류도 응답으로 돌려 평가 분모에 포함한다 (검색·생성 예외를 밖으로 던지지 않음).
설정 오류(검색기 미연결, evidence_gate params 누락 등)는 실행 전에 예외로 드러난다.

schemas.AgentResponse 에 칸이 없는 분석용 정보(근거 없음 사유, 모델에 넣은 청크, 리라이트 fallback)는
AgentResult.trace 로 따로 돌려준다.
"""
import time
from dataclasses import dataclass, field

from answer.citation_check import check_citations, mark_invalid
from answer.evidence_gate import NO_EVIDENCE_MESSAGE, gate_modes, model_gate, score_gate
from answer.generator import CallUsage, dummy_llm, generate
from answer.prompt import build_prompt, select_context
from config import OptimizationKind
from optimize.cache import make_key
from optimize.rewrite import REWRITE_PROMPT_VERSION, rewrite_query
from schemas import AgentResponse, LatencyBreakdown, Status, Usage


@dataclass
class AgentResult:
    response: AgentResponse
    candidates: list = field(default_factory=list)  # list[RetrievedCandidate], 최종 순위
    trace: dict = field(default_factory=dict)


def _ms(t0):
    return round((time.perf_counter() - t0) * 1000, 2)


def _err(e):
    return f"{type(e).__name__}: {e}"


def _is_timeout(e):
    return isinstance(e, TimeoutError) or "timeout" in type(e).__name__.lower()


def run_agent(question, cfg, retriever, llm_fn=dummy_llm, rewrite_fn=None, cache=None, versions=None,
              user_scope="public") -> AgentResult:
    """cfg: config.AppConfig, retriever: retrieve(query) -> list[RetrievedCandidate].
    cache 는 [optimization] kind=cache 일 때만 쓴다 (versions 필요: config.build_versions(cfg))."""
    if retriever is None:
        raise ValueError("retriever 가 필요합니다 (색인: search_adapter.make_retriever, 더미: answer.dev_stub)")
    use_score, use_model, min_score, min_chunks = gate_modes(cfg.evidence_gate)
    opt = cfg.optimization.kind
    use_cache = opt is OptimizationKind.CACHE and cache is not None
    use_rewrite = opt is OptimizationKind.REWRITE
    if use_cache and versions is None:
        raise ValueError("캐시를 쓰려면 versions(config.build_versions) 가 필요합니다")

    start = time.perf_counter()
    lat, usage = {}, CallUsage()
    trace = {"no_evidence_reason": "", "context_chunk_ids": [], "rewrite_fallback": False, "rewrite_error": "",
             "rewrite_prompt_version": REWRITE_PROMPT_VERSION if use_rewrite else "",
             "llm": getattr(llm_fn, "model_id", getattr(llm_fn, "__name__", "unknown"))}

    def finish(status, answer=None, cited=(), invalid=(), error=None, candidates=(), query=None):
        resp = AgentResponse(
            status=status, answer=answer, cited_chunk_ids=list(cited), invalid_citation_ids=list(invalid),
            error_message=error, latency=LatencyBreakdown(**lat, total_ms=_ms(start)),
            usage=Usage(model_calls=usage.model_calls, input_tokens=usage.input_tokens,
                        output_tokens=usage.output_tokens),
            rewritten_query=query if use_rewrite else None, cache_hit=False if use_cache else None)
        return AgentResult(resp, list(candidates), trace)

    key = None
    if use_cache:
        t0 = time.perf_counter()
        key = make_key(question, versions, user_scope)
        cached = cache.get(key)
        lat["cache_lookup_ms"] = _ms(t0)
        if cached is not None:
            resp = cached.response.model_copy(update={
                "cache_hit": True, "usage": Usage(),
                "latency": LatencyBreakdown(cache_lookup_ms=lat["cache_lookup_ms"], total_ms=_ms(start))})
            return AgentResult(resp, cached.candidates, {**cached.trace, "cached_from_key": key[:12]})

    query = question
    if use_rewrite:
        t0 = time.perf_counter()
        try:
            query = rewrite_query(question, rewrite_fn, usage)
        except Exception as e:  # 리라이트 실패는 원질문으로 계속 (오류로 끝내지 않음)
            query = question
            trace["rewrite_fallback"], trace["rewrite_error"] = True, _err(e)
        lat["rewrite_ms"] = _ms(t0)

    t0 = time.perf_counter()
    try:
        candidates = list(retriever(query))
    except Exception as e:
        lat["retrieval_ms"] = _ms(t0)
        return finish(Status.RETRIEVAL_ERROR, error=_err(e), query=query)
    lat["retrieval_ms"] = _ms(t0)
    rerank_ms = getattr(retriever, "last_rerank_ms", None)  # 구성 C: 재정렬 시간을 검색 시간에서 분리
    if rerank_ms is not None:
        lat["rerank_ms"] = rerank_ms
        lat["retrieval_ms"] = round(max(0.0, lat["retrieval_ms"] - rerank_ms), 2)

    lacking, reason = (True, "검색 결과 0건") if not candidates else (False, "")
    if not lacking and use_score:
        lacking, reason = score_gate(candidates, min_score, min_chunks)
    if lacking:
        trace["no_evidence_reason"] = reason
        result = finish(Status.NO_EVIDENCE, NO_EVIDENCE_MESSAGE, candidates=candidates, query=query)
    else:
        context = select_context(candidates, cfg.prompt.max_context_chunks, cfg.prompt.max_context_chars)
        context_ids = [c.chunk.chunk_id for c in context]
        trace["context_chunk_ids"] = context_ids
        prompt = build_prompt(question, context, cfg.path(cfg.prompt.template_path))
        t0 = time.perf_counter()
        try:
            out = generate(prompt, llm_fn, usage)
        except Exception as e:
            lat["generation_ms"] = _ms(t0)
            status = Status.TIMEOUT if _is_timeout(e) else Status.MODEL_ERROR
            return finish(status, error=_err(e), candidates=candidates, query=query)
        lat["generation_ms"] = _ms(t0)

        valid, invalid = check_citations(out.cited_chunk_ids, context_ids)
        lacking, reason = model_gate(out) if use_model else (False, "")
        if lacking:  # 부분 답변(문서에 있는 부분 + 나머지는 없다고 명시)도 no_evidence 로 둔다 (problem.md 11.3)
            trace["no_evidence_reason"] = reason
            result = finish(Status.NO_EVIDENCE, mark_invalid(out.answer.strip(), invalid) or NO_EVIDENCE_MESSAGE,
                            valid, invalid, candidates=candidates, query=query)
        else:
            result = finish(Status.ANSWERED, mark_invalid(out.answer, invalid), valid, invalid,
                            candidates=candidates, query=query)

    if use_cache and not trace["rewrite_fallback"]:
        cache.set(key, result)
    return result
