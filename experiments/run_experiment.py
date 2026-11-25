"""구성(configs/*.toml) x 평가 질문 x 1회. 실행마다 schemas.RunRecord 한 줄을 기록한다.  [김선규, 역할 6]

결과: results/runs/<시각>_<이름>.records.jsonl  (RunRecord, metrics.py 입력)
      results/runs/<시각>_<이름>.trace.jsonl    (근거 없음 사유, 모델에 넣은 청크, Hit@5 등 분석용)
오류 건도 기록해 분모에 포함하고, 실패를 덮어쓰거나 버리지 않는다 (재실행은 --kind retry 로 별도 파일).

예) python experiments/run_experiment.py --configs A --eval eval/eval-dev.json --stub          # 색인 없이 무료 리허설
    python experiments/run_experiment.py --configs A B --eval eval/eval-dev.json --kind dev      # 실제 검색 + 더미 생성 (무료)
    python experiments/run_experiment.py --configs A B C --eval eval/eval-test.json --llm claude --kind core   # 본 평가 (비용 발생)
"""
import argparse
from datetime import datetime, timezone

from _common import ROOT, load_questions, make_record, out_paths, summarize, trace_row, write_jsonl

from agent import run_agent  # noqa: E402  (_common 이 src 를 경로에 넣음)
from answer.generator import dummy_llm, make_answer_llm, make_rewrite_llm  # noqa: E402
from config import OptimizationKind, build_versions, check_shared_settings, load_config  # noqa: E402
from optimize.cache import AnswerCache  # noqa: E402
from schemas import RunKind  # noqa: E402
from search_adapter import make_retriever  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("--configs", nargs="+", default=["A"], help="configs/ 아래 파일 이름 (예: A B C, C_cache)")
p.add_argument("--eval", default=str(ROOT / "eval/eval-dev.json"))
p.add_argument("--llm", choices=["dummy", "claude"], default="dummy", help="claude = 실제 API 호출 (비용 발생)")
p.add_argument("--kind", choices=[k.value for k in RunKind], default="dev",
               help="core=본 평가 60건, branch=최적화, dev=dev 튜닝, warmup, retry, extra")
p.add_argument("--stub", action="store_true", help="색인 없이 더미 검색기 사용")
p.add_argument("--only", nargs="*", help="일부 문항 ID 만 실행")
p.add_argument("--name", default="", help="결과 파일 이름에 붙일 꼬리표")
a = p.parse_args()

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")  # ANTHROPIC_API_KEY, EMBEDDING_MODEL, LLM_EFFORT

cfgs = [load_config(ROOT / "configs" / f"{name}.toml") for name in a.configs]
core = [c for c in cfgs if c.optimization.kind is OptimizationKind.NONE]
if len(core) > 1:
    check_shared_settings(core)  # A/B/C 는 검색만 달라야 한다
qs = load_questions(a.eval)
if a.only:
    qs = [q for q in qs if q["question_id"] in a.only]
kind = RunKind(a.kind)

stem = f"{a.kind}_{'-'.join(c.name.replace('+', '_') for c in cfgs)}" + (f"_{a.name}" if a.name else "")
rec_path, trace_path = out_paths(stem)
records, traces, lines = [], [], []
for cfg in cfgs:
    versions = build_versions(cfg)
    retriever = make_retriever(cfg, stub=a.stub)
    llm_fn = make_answer_llm(cfg) if a.llm == "claude" else dummy_llm
    rewrite_fn = (make_rewrite_llm(cfg) if a.llm == "claude" and cfg.optimization.kind is OptimizationKind.REWRITE
                  else None)
    cache = (AnswerCache(cfg.optimization.cache.ttl_s) if cfg.optimization.kind is OptimizationKind.CACHE else None)
    recs, trs = [], []
    for i, q in enumerate(qs, 1):
        started = datetime.now(timezone.utc)
        result = run_agent(q["question"], cfg, retriever, llm_fn, rewrite_fn, cache, versions)
        rec = make_record(q, cfg, versions, result, f"{stem}_{cfg.name}_{i:03d}", kind, started,
                          datetime.now(timezone.utc))
        recs.append(rec)
        trs.append(trace_row(q, rec, {**result.trace, "config_name": cfg.name}))
    lines.append(summarize(cfg.name, trs, recs))
    print(lines[-1])
    records += recs
    traces += trs

write_jsonl(rec_path, records)
write_jsonl(trace_path, traces)
print(f"저장: {rec_path}\n      {trace_path}\n분모(전체 시도): {len(records)} = 구성 {len(cfgs)} x 문항 {len(qs)}")
