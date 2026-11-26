"""구성(configs/*.toml) x 평가 질문 x 1회. 실행마다 schemas.RunRecord 한 줄을 기록한다.  [김선규, 역할 6]

결과: results/runs/<시각>_<이름>.records.jsonl  (RunRecord, metrics.py 입력)
      results/runs/<시각>_<이름>.trace.jsonl    (근거 없음 사유, 모델에 넣은 청크, Hit@5 등 분석용)
오류 건도 기록해 분모에 포함하고, 실패를 덮어쓰거나 버리지 않는다 (재실행은 --kind retry 로 별도 파일).

예) python experiments/run_experiment.py --configs A --eval eval/eval-dev.json --stub          # 색인 없이 무료 리허설
    python experiments/run_experiment.py --configs A B --eval eval/eval-dev.json --kind dev      # 실제 검색 + 더미 생성 (무료)
    python experiments/run_experiment.py --configs A B C --eval eval/eval-test.json --llm claude --kind core   # 본 평가 (비용 발생)
"""
import argparse
import os
import sys
from datetime import datetime, timezone

from _common import ROOT, JsonlWriter, load_questions, make_record, out_paths, summarize, trace_row

from agent import run_agent  # noqa: E402  (_common 이 src 를 경로에 넣음)
from answer.generator import dummy_llm, make_answer_llm, make_rewrite_llm  # noqa: E402
from config import OptimizationKind, build_versions, check_shared_settings, load_config  # noqa: E402
from optimize.cache import AnswerCache  # noqa: E402
from schemas import RunKind  # noqa: E402
from search_adapter import make_retriever  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("--configs", nargs="+", default=["A"], help="configs/ 아래 파일 이름 (예: A B C, C_cache)")
p.add_argument("--eval", default=str(ROOT / "eval/eval-dev.json"))
p.add_argument("--llm", choices=["dummy", "claude", "openai"], default="dummy",
               help="claude / openai = 실제 API 호출 (비용 발생)")
p.add_argument("--openai-model", default=None, help="--llm openai 일 때 모델 (없으면 .env 의 OPENAI_MODEL, 기본 gpt-6-luna)")
p.add_argument("--kind", choices=[k.value for k in RunKind], default="dev",
               help="core=본 평가 60건, branch=최적화, dev=dev 튜닝, warmup, retry, extra")
p.add_argument("--stub", action="store_true", help="색인 없이 더미 검색기 사용")
p.add_argument("--only", nargs="*", help="일부 문항 ID 만 실행")
p.add_argument("--name", default="", help="결과 파일 이름에 붙일 꼬리표")
a = p.parse_args()

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")  # ANTHROPIC_API_KEY, EMBEDDING_MODEL, LLM_EFFORT
if a.llm == "claude" and not os.environ.get("ANTHROPIC_API_KEY", "").strip():
    # 키 없이 돌리면 모든 문항이 model_error 로 기록되어 실행 기록이 오염된다. 시작 전에 멈춘다.
    sys.exit("ANTHROPIC_API_KEY 가 없습니다. .env 를 확인하세요 (--llm claude)")
if a.llm == "openai" and not os.environ.get("OPENAI_API_KEY", "").strip():
    sys.exit("OPENAI_API_KEY 가 없습니다. .env 를 확인하세요 (--llm openai)")

cfgs = [load_config(ROOT / "configs" / f"{name}.toml") for name in a.configs]
core = [c for c in cfgs if c.optimization.kind is OptimizationKind.NONE]
if len(core) > 1:
    check_shared_settings(core)  # A/B/C 는 검색만 달라야 한다
qs = load_questions(a.eval)
if a.only:
    qs = [q for q in qs if q["question_id"] in a.only]
kind = RunKind(a.kind)

stem = f"{a.kind}_{'-'.join(c.name.replace('+', '_') for c in cfgs)}" + (f"_{a.name}" if a.name else "")
run_stamp, rec_path, trace_path = out_paths(stem)
n_done = 0
# 실행마다 바로 한 줄씩 쓴다: 중간에 멈춰도 그때까지의 기록(과 API 비용)이 남는다
with JsonlWriter(rec_path) as rec_out, JsonlWriter(trace_path) as trace_out:
    for cfg in cfgs:
        llm_fn = (make_answer_llm(cfg, provider=a.llm, model=a.openai_model) if a.llm in ("claude", "openai")
                  else dummy_llm)
        # effort 는 config 에 칸이 없어 생성 모델 이름에 붙여 기록한다 (예: claude-opus-5-5@medium). 캐시 키에도 반영됨
        versions = build_versions(cfg).model_copy(update={"generation_model": llm_fn.model_id})
        retriever = make_retriever(cfg, stub=a.stub)
        # 설정이 TBD 면 실제 색인을 만든 임베딩 모델을 기록한다 (기록만 보고 어느 모델 결과인지 알 수 있게)
        actual = getattr(retriever, "model", None)
        if actual and versions.embedding_model in ("", "TBD"):
            versions = versions.model_copy(update={"embedding_model": actual})
        rewrite_fn = (make_rewrite_llm(cfg) if a.llm == "claude" and cfg.optimization.kind is OptimizationKind.REWRITE
                      else None)
        cache = (AnswerCache(cfg.optimization.cache.ttl_s) if cfg.optimization.kind is OptimizationKind.CACHE
                 else None)
        recs, trs = [], []
        for i, q in enumerate(qs, 1):
            started = datetime.now(timezone.utc)
            result = run_agent(q["question"], cfg, retriever, llm_fn, rewrite_fn, cache, versions)
            # run_id 에 실행 시각을 넣어 같은 인자로 다시 돌려도 겹치지 않게 한다
            rec = make_record(q, cfg, versions, result, f"{run_stamp}_{stem}_{cfg.name}_{i:03d}", kind, started,
                              datetime.now(timezone.utc))
            tr = trace_row(q, rec, {**result.trace, "config_name": cfg.name})
            rec_out.write(rec)
            trace_out.write(tr)
            recs.append(rec)
            trs.append(tr)
            n_done += 1
        print(summarize(cfg.name, trs, recs))

print(f"저장: {rec_path}\n      {trace_path}\n분모(전체 시도): {n_done} = 구성 {len(cfgs)} x 문항 {len(qs)}")
