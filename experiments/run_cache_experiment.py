"""캐시 검증 15건 (발제 STEP 5, 평가표 7번): 답변 가능 5문항 x (미적중 -> 동일 질문 적중 -> 문서 버전 변경 후 재요청).

A/B/C 품질 비교와 분리해 run_kind=branch 로 기록한다 (configs/C_cache.toml).
단계별 기대값을 실제와 대조해 trace 의 ok 칸에 남기고, 하나라도 어긋나면 종료 코드 1.

  1단계 miss    : 빈 캐시. cache_hit=False, 검색·생성 수행
  2단계 hit     : 같은 질문·같은 버전. cache_hit=True, 모델 호출 0. 1단계가 오류였으면 캐시에 없으므로 miss 가 정답
  3단계 updated : 문서 버전 변경 후 같은 질문. cache_hit=False, 새로 생성 (이전 답변 재사용 금지)

3단계의 '문서 버전 변경'은 [docs] doc_version 레이블을 바꿔 흉내 낸다 (실제 매뉴얼 개정 시 바뀌는 값).
doc_version 은 index_version 에도 들어가므로 둘 다 바뀐다. 실제 재청킹 시에는 data/chunks.jsonl 해시가
index_version 에 들어가 같은 효과가 난다 (config.index_version). 색인 자체는 다시 만들지 않으므로
3단계 답변 내용이 1단계와 같을 수 있다 — 여기서 확인하는 것은 '재사용하지 않고 다시 만들었는가' 이다.

예) python experiments/run_cache_experiment.py --stub                                  # 무료 리허설
    python experiments/run_cache_experiment.py --eval eval/eval-test.json --llm claude   # 제출용 (비용 발생)
"""
import argparse
import sys
from datetime import datetime, timezone

from _common import ROOT, load_questions, make_record, out_paths, summarize, trace_row, write_jsonl

from agent import run_agent  # noqa: E402
from answer.generator import dummy_llm, make_answer_llm  # noqa: E402
from config import OptimizationKind, build_versions, load_config  # noqa: E402
from optimize.cache import AnswerCache  # noqa: E402
from schemas import RunKind  # noqa: E402
from search_adapter import make_retriever  # noqa: E402

UPDATE_SUFFIX = "+cachetest-rev"


def bumped(cfg):
    """doc_version 레이블만 바꾼 설정 (문서 개정 흉내)."""
    new = cfg.model_copy(update={"docs": cfg.docs.model_copy(
        update={"doc_version": cfg.docs.doc_version + UPDATE_SUFFIX})})
    new._repo_root, new._source = cfg._repo_root, cfg._source
    return new


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="C_cache", help="configs/ 아래 이름. [optimization] kind=cache 여야 함")
    p.add_argument("--eval", default=str(ROOT / "eval/eval-dev.json"))
    p.add_argument("--qids", nargs="*", help="고정할 답변 가능 문항 5개. 없으면 평가셋의 앞 5개 답변 가능 문항")
    p.add_argument("--llm", choices=["dummy", "claude"], default="dummy")
    p.add_argument("--stub", action="store_true", help="색인 없이 더미 검색기")
    p.add_argument("--user-scope", default="public")
    a = p.parse_args(argv)

    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")

    cfg = load_config(ROOT / "configs" / f"{a.config}.toml")
    if cfg.optimization.kind is not OptimizationKind.CACHE:
        sys.exit(f"{a.config} 는 캐시 구성이 아닙니다 ([optimization] kind=cache)")
    qs = [q for q in load_questions(a.eval) if q["answerable"]]
    if a.qids:
        by_id = {q["question_id"]: q for q in qs}
        missing = [i for i in a.qids if i not in by_id]
        if missing:
            sys.exit(f"답변 가능 문항이 아니거나 없음: {missing}")
        qs = [by_id[i] for i in a.qids]
    else:
        qs = qs[:5]
    if len(qs) != 5:
        print(f"[주의] 발제 기준은 5문항인데 {len(qs)}문항입니다")

    cfg2 = bumped(cfg)
    retriever = make_retriever(cfg, stub=a.stub)
    llm_fn = make_answer_llm(cfg) if a.llm == "claude" else dummy_llm
    # run_experiment.py 와 같게: effort 를 생성 모델 이름에 붙여 기록 (캐시 키에도 반영)
    tag = {"generation_model": llm_fn.model_id}
    actual = getattr(retriever, "model", None)
    if actual and cfg.index.embedding_model in ("", "TBD"):
        tag["embedding_model"] = actual
    v1, v2 = (build_versions(c).model_copy(update=tag) for c in (cfg, cfg2))
    assert v1.doc_version != v2.doc_version and v1.index_version != v2.index_version
    cache = AnswerCache(cfg.optimization.cache.ttl_s)

    stem = f"branch_cache_{a.config}" + ("_stub" if a.stub else "")
    run_stamp, rec_path, trace_path = out_paths(stem)
    records, traces, failures = [], [], []
    first_status = {}
    phases = [("miss", cfg, v1), ("hit", cfg, v1), ("updated", cfg2, v2)]
    n = 0
    for phase, c, v in phases:
        for q in qs:
            n += 1
            started = datetime.now(timezone.utc)
            result = run_agent(q["question"], c, retriever, llm_fn, None, cache, v, user_scope=a.user_scope)
            rec = make_record(q, c, v, result, f"{run_stamp}_{stem}_{n:03d}", RunKind.BRANCH, started, datetime.now(timezone.utc))
            resp = rec.response
            if phase == "miss":
                first_status[q["question_id"]] = resp.status
                expect_hit = False
            elif phase == "hit":
                expect_hit = not first_status[q["question_id"]].is_error  # 오류 결과는 캐시에 저장하지 않음
            else:
                expect_hit = False
            ok = resp.cache_hit is expect_hit
            if phase == "hit" and expect_hit:
                ok = ok and resp.usage.model_calls == 0
            if phase == "updated":
                ok = ok and rec.versions.doc_version == v2.doc_version and (
                    resp.status.is_error or resp.latency.retrieval_ms is not None)  # 새로 검색·생성함
            if not ok:
                failures.append(f"{q['question_id']} {phase}: cache_hit={resp.cache_hit} 기대 {expect_hit}")
            records.append(rec)
            traces.append(trace_row(q, rec, {**result.trace, "config_name": c.name, "phase": phase,
                                             "expected_cache_hit": expect_hit, "ok": ok,
                                             "doc_version": rec.versions.doc_version,
                                             "index_version": rec.versions.index_version,
                                             "user_scope": a.user_scope}))
            print(f"  {phase:8s} {q['question_id']} status={resp.status.value:12s} cache_hit={resp.cache_hit!s:5s} "
                  f"{resp.latency.total_ms:9.1f}ms  {'OK' if ok else 'FAIL'}")

    write_jsonl(rec_path, records)
    write_jsonl(trace_path, traces)
    print(summarize(cfg.name, traces, records))
    print(f"캐시 hits={cache.hits} misses={cache.misses}  (기대: hits {sum(not s.is_error for s in first_status.values())}"
          f", misses {2 * len(qs) + sum(s.is_error for s in first_status.values())})")
    print(f"저장: {rec_path}\n      {trace_path}\n분모: {len(records)} = 문항 {len(qs)} x 3단계")
    if failures:
        print("기대와 다름:\n  " + "\n  ".join(failures))
        sys.exit(1)


if __name__ == "__main__":
    main()
