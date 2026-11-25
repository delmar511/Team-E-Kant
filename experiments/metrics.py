"""지표 계산과 채점표 (역할 6·7, 박태환). problem.md 11절, 발제 STEP 6.

두 단계로 쓴다.

1) 채점표 만들기: 실행 기록(records.jsonl)에서 사람이 채울 CSV 를 만든다.
   python experiments/metrics.py sheet results/runs/<...>.records.jsonl --eval eval/eval-test.json
   -> results/scores/<...>.scores.csv  (Excel 에서 바로 열리도록 UTF-8 BOM)
   호출 오류 건은 0점과 사유를 미리 채운다 (오류를 올바른 거절로 세지 않는다).
   모델에 주지 않은 청크를 인용한 건은 citation_valid 를 0 으로 미리 채운다.
   나머지는 사람이 채운다: answer_correct / citation_valid (답변 가능), no_answer_correct (근거 없음),
   rationale, scorer, reviewer(채점자와 달라야 함), failure_category, analysis_tags(';' 구분).

2) 보고: 실행 기록 + (있으면) 채점표 -> 구성별 표.
   python experiments/metrics.py report results/runs/<...>.records.jsonl --eval eval/eval-test.json \
          --scores results/scores/<...>.scores.csv --out results/<이름>.md

Hit@5 는 채점표가 아니라 검색 후보에서 직접 계산한다 (schemas.Score 주석: 드리프트 방지).
검색 오류는 Hit@5 = 0. 결과가 5개 미만이면 있는 결과로만 판정. 정답 청크가 없는 문항은 0 이 아니라 '측정 불가'로 따로 센다.
Hit@5 는 근거 하나라도 있으면 1 이므로, 근거 전체가 상위 5개에 있는 비율(전체 근거 회수)을 따로 보고한다.
warmup 실행은 집계에서 뺀다. retry·extra 는 본 실행을 대체하지 않고 별도 묶음으로 집계한다.
"""
import argparse
import csv
import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from _common import ROOT, QUESTION_TYPES, hit_at_k, load_questions

from schemas import AnalysisTag, FailureCategory, RunKind, RunRecord, Score, ScorerKind  # noqa: E402

SCORES_DIR = ROOT / "results" / "scores"
K = 5

SHEET_COLUMNS = [
    "run_id", "run_kind", "config_name", "question_id", "type", "status", "hit_at_5",
    "question", "expected_facts", "answer", "cited_chunk_ids", "invalid_citation_ids",
    "answer_correct", "citation_valid", "no_answer_correct",
    "failure_category", "analysis_tags", "rationale",
    "scorer_kind", "scorer", "reviewer", "scored_at",
]
SCORE_FIELDS = ("answer_correct", "citation_valid", "no_answer_correct")


# ---------------- 입력 ----------------

def load_records(paths):
    out = []
    for p in paths:
        with open(p, encoding="utf-8") as f:
            out += [RunRecord.model_validate_json(line) for line in f if line.strip()]
    ids = [r.run_id for r in out]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        raise SystemExit(f"run_id 중복 (같은 파일을 두 번 넣었는지 확인): {', '.join(dup[:5])}")
    return out


def load_traces(record_paths):
    """records 옆의 trace.jsonl (리라이트 fallback 등). 없으면 빈 dict."""
    out = {}
    for p in record_paths:
        t = Path(str(p).replace(".records.jsonl", ".trace.jsonl"))
        if t.is_file():
            with open(t, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        row = json.loads(line)
                        out[row["run_id"]] = row
    return out


def _bool(v):
    v = str(v or "").strip().lower()
    if v in ("1", "true", "y", "yes", "o"):
        return True
    if v in ("0", "false", "n", "no", "x"):
        return False
    if v == "":
        return None
    raise ValueError(f"0/1 이 아닌 값: {v!r}")


def load_scores(path):
    """채점표 CSV -> {run_id: {"human": Score|None, "llm_judge": [Score]}}. 형식 오류는 행 번호와 함께 멈춘다."""
    out = defaultdict(lambda: {"human": None, "llm_judge": []})
    with open(path, encoding="utf-8-sig", newline="") as f:
        for n, row in enumerate(csv.DictReader(f), 2):
            if not any(row.get(c, "").strip() for c in SCORE_FIELDS):
                continue  # 아직 채점 안 함
            try:
                tags = [AnalysisTag(t.strip()) for t in (row.get("analysis_tags") or "").split(";") if t.strip()]
                score = Score(
                    scorer_kind=ScorerKind(row.get("scorer_kind") or "human"),
                    scorer=row.get("scorer") or "",
                    reviewer=row.get("reviewer") or None,
                    answer_correct=_bool(row.get("answer_correct")),
                    citation_valid=_bool(row.get("citation_valid")),
                    no_answer_correct=_bool(row.get("no_answer_correct")),
                    failure_category=FailureCategory(row["failure_category"]) if row.get("failure_category") else None,
                    analysis_tags=tags,
                    rationale=row.get("rationale") or "",
                    scored_at=row.get("scored_at") or datetime.now(timezone.utc).isoformat(),
                )
            except Exception as e:
                raise SystemExit(f"{path}:{n} ({row.get('run_id')}) 채점 행 오류: {e}")
            slot = out[row["run_id"]]
            if score.scorer_kind is ScorerKind.HUMAN:
                if slot["human"] is not None:
                    raise SystemExit(f"{path}:{n} {row['run_id']} 사람 채점이 두 번 있음")
                slot["human"] = score
            else:
                slot["llm_judge"].append(score)
    return out


# ---------------- 계산 ----------------

def group_key(r):
    kind = r.run_kind.value
    return f"{r.config_name}" if kind in ("core", "branch") else f"{r.config_name} [{kind}]"


def frac(num, den):
    return f"{num}/{den}" + (f" ({num / den:.2f})" if den else "")


def summarize_group(records, questions, scores, traces):
    qs = {q["question_id"]: q for q in questions}
    ans = [r for r in records if qs[r.question_id]["answerable"]]
    noans = [r for r in records if not qs[r.question_id]["answerable"]]

    # 검색 지표 (채점과 무관, 후보에서 계산)
    hits, full, unmeasured, by_type = [], [], [], defaultdict(list)
    for r in ans:
        gold = qs[r.question_id]["gold_chunk_ids"]
        top = r.top_k_chunk_ids(K)
        h = hit_at_k(top, gold, K)
        if h is None:
            unmeasured.append(r.question_id)
            continue
        hits.append(h)
        by_type[qs[r.question_id]["type"]].append(h)
        full.append(int(set(gold) <= set(top)))

    # 호출·시간
    status = Counter(r.response.status.value for r in records)
    retrieval_tried = len(records) - sum(1 for r in records if r.response.cache_hit)
    retrieval_ok = retrieval_tried - status.get("retrieval_error", 0)
    gen_tried = sum(1 for r in records if r.response.latency.generation_ms is not None)
    gen_ok = gen_tried - status.get("model_error", 0) - status.get("timeout", 0)
    ok_lat = [r.response.latency.total_ms for r in records if not r.response.status.is_error]
    calls = sum(r.response.usage.model_calls for r in records)
    tok_in = sum(r.response.usage.input_tokens for r in records)
    tok_out = sum(r.response.usage.output_tokens for r in records)

    # 사람 채점
    def human(r):
        s = scores.get(r.run_id)
        return s["human"] if s else None

    def tally(rs, field):
        vals = [getattr(human(r), field) if human(r) else None for r in rs]
        return sum(1 for v in vals if v is True), sum(1 for v in vals if v is None)

    correct, correct_missing = tally(ans, "answer_correct")
    cite, cite_missing = tally(ans, "citation_valid")
    refuse, refuse_missing = tally(noans, "no_answer_correct")
    unreviewed = sum(1 for r in records if human(r) and not human(r).reviewer)

    row = {
        "runs": len(records),
        "hit5": frac(sum(hits), len(hits)) + (f" · 측정 불가 {len(unmeasured)}" if unmeasured else ""),
        "full_recall5": frac(sum(full), len(full)),
        "hit5_by_type": {t: frac(sum(v), len(v)) for t, v in by_type.items()},
        "answer_correct": frac(correct, len(ans)) + (f" · 미채점 {correct_missing}" if correct_missing else ""),
        "citation_valid": frac(cite, len(ans)) + (f" · 미채점 {cite_missing}" if cite_missing else ""),
        "no_answer_correct": frac(refuse, len(noans)) + (f" · 미채점 {refuse_missing}" if refuse_missing else ""),
        "unreviewed": unreviewed,
        "retrieval_calls": frac(retrieval_ok, retrieval_tried),
        "generation_calls": frac(gen_ok, gen_tried),
        "errors": status.get("retrieval_error", 0) + status.get("model_error", 0),
        "timeouts": status.get("timeout", 0),
        "status": dict(status),
        "latency_mean_s": round(statistics.mean(ok_lat) / 1000, 2) if ok_lat else None,
        "latency_median_s": round(statistics.median(ok_lat) / 1000, 2) if ok_lat else None,
        "latency_n": len(ok_lat),
        "model_calls": calls, "input_tokens": tok_in, "output_tokens": tok_out,
        "unmeasured_ids": unmeasured,
    }
    cache = [r.response.cache_hit for r in records if r.response.cache_hit is not None]
    if cache:
        row["cache_hits"] = frac(sum(cache), len(cache))
    rw = [traces[r.run_id] for r in records if r.response.rewritten_query is not None and r.run_id in traces]
    if rw:
        row["rewrite_fallbacks"] = frac(sum(1 for t in rw if t.get("rewrite_fallback")), len(rw))
    return row


def version_check(records):
    """한 묶음 안에서 바뀌면 안 되는 버전이 섞였는지, 자리표시 값이 남았는지."""
    warns = []
    core = [r for r in records if r.run_kind in (RunKind.CORE, RunKind.BRANCH)]
    for field in ("doc_version", "index_version", "embedding_model", "generation_model",
                  "prompt_version", "answer_config_version", "eval_version"):
        vals = {getattr(r.versions, field) for r in core}
        if len(vals) > 1:
            warns.append(f"본 실행 안에서 {field} 가 섞임: {sorted(vals)}")
    for r in core:
        v = r.versions
        bad = [f for f in ("doc_version", "embedding_model") if "TBD" in getattr(v, f) or "YYMMDD" in getattr(v, f)]
        if v.reranker_model == "TBD":
            bad.append("reranker_model")
        if bad:
            warns.append(f"자리표시 버전 값이 남음 ({', '.join(bad)}) — 예: {r.run_id}")
            break
    dirty = sorted({r.versions.code_commit for r in core if r.versions.code_commit and r.versions.code_commit.endswith("-dirty")})
    if dirty:
        warns.append(f"커밋 안 된 코드로 실행됨: {dirty}")
    return warns


# ---------------- 출력 ----------------

def render(groups, questions, warns, sources):
    n_ans = sum(q["answerable"] for q in questions)
    lines = [f"# 평가 결과 ({datetime.now():%Y-%m-%d %H:%M})", "",
             f"- 실행 기록: {', '.join(f'`{Path(s).name}`' for s in sources)}",
             f"- 평가셋: {len(questions)}문항 (답변 가능 {n_ans}, 근거 없음 {len(questions) - n_ans})",
             "- Hit@5 는 검색 후보에서 계산. 정답 충족·근거 적합·근거 없음 대응은 사람 채점 (LLM 판정은 반영하지 않음).",
             "- 응답 시간은 오류가 아닌 실행의 전체 시간(리라이트·검색·생성 포함). 캐시 적중은 일반 응답 시간과 분리해 볼 것.", ""]
    if warns:
        lines += ["## 경고", ""] + [f"- {w}" for w in warns] + [""]
    cols = [("실행", "runs"), ("Hit@5", "hit5"), ("근거 전체 회수@5", "full_recall5"),
            ("정답 충족", "answer_correct"), ("근거 적합", "citation_valid"), ("근거 없음 대응", "no_answer_correct"),
            ("검색 호출 성공", "retrieval_calls"), ("생성 호출 성공", "generation_calls"),
            ("오류", "errors"), ("timeout", "timeouts"),
            ("평균(초)", "latency_mean_s"), ("중앙값(초)", "latency_median_s"), ("n", "latency_n")]
    lines += ["## 구성별 요약", "", "| 구성 | " + " | ".join(c for c, _ in cols) + " |",
              "|---" * (len(cols) + 1) + "|"]
    for name, row in groups.items():
        lines.append(f"| {name} | " + " | ".join(str(row[k]) for _, k in cols) + " |")
    lines += ["", "## 유형별 Hit@5", "", "| 구성 | " + " | ".join(t for t in QUESTION_TYPES if t != "no_answer") + " |",
              "|---" * 4 + "|"]
    for name, row in groups.items():
        lines.append(f"| {name} | " + " | ".join(row["hit5_by_type"].get(t, "-") for t in QUESTION_TYPES
                                                  if t != "no_answer") + " |")
    lines += ["", "## 상태·사용량", "", "| 구성 | 상태 | 모델 호출 | 입력 토큰 | 출력 토큰 | 기타 |", "|---|---|---|---|---|---|"]
    for name, row in groups.items():
        extra = "; ".join(f"{k} {row[k]}" for k in ("cache_hits", "rewrite_fallbacks") if k in row)
        st = ", ".join(f"{k} {v}" for k, v in sorted(row["status"].items()))
        lines.append(f"| {name} | {st} | {row['model_calls']} | {row['input_tokens']} | {row['output_tokens']} | {extra} |")
    return "\n".join(lines) + "\n"


# ---------------- 명령 ----------------

def cmd_sheet(a):
    records = [r for r in load_records(a.records) if r.run_kind is not RunKind.WARMUP]
    qs = {q["question_id"]: q for q in load_questions(a.eval)}
    out = Path(a.out) if a.out else SCORES_DIR / (Path(a.records[0]).name.replace(".records.jsonl", ".scores.csv"))
    if out.exists() and not a.force:
        raise SystemExit(f"{out} 가 이미 있습니다 (채점 내용 보호). 덮어쓰려면 --force")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, SHEET_COLUMNS)
        w.writeheader()
        for r in records:
            q = qs[r.question_id]
            resp = r.response
            row = {c: "" for c in SHEET_COLUMNS}
            row.update(run_id=r.run_id, run_kind=r.run_kind.value, config_name=r.config_name,
                       question_id=r.question_id, type=q["type"], status=resp.status.value,
                       hit_at_5=hit_at_k(r.top_k_chunk_ids(K), q["gold_chunk_ids"], K) if q["answerable"] else "",
                       question=r.question, expected_facts="\n".join(q.get("expected_facts") or []),
                       answer=resp.answer or resp.error_message or "",
                       cited_chunk_ids=";".join(resp.cited_chunk_ids),
                       invalid_citation_ids=";".join(resp.invalid_citation_ids), scorer_kind="human")
            if resp.status.is_error:
                auto = {"answer_correct": 0, "citation_valid": 0} if q["answerable"] else {"no_answer_correct": 0}
                row.update(auto, failure_category="system_error", scorer="auto",
                           rationale=f"호출 오류({resp.status.value})는 0점. 올바른 거절로 세지 않음")
            elif q["answerable"] and resp.invalid_citation_ids:
                row.update(citation_valid=0, rationale="모델에 주지 않은 청크 인용 (invalid_citation_ids)")
            w.writerow(row)
    print(f"채점표: {out} ({len(records)}행). 사람이 채운 뒤 report --scores 로 넘기세요.")


def cmd_report(a):
    records = [r for r in load_records(a.records) if r.run_kind is not RunKind.WARMUP]
    questions = load_questions(a.eval)
    qids = {q["question_id"] for q in questions}
    stray = sorted({r.question_id for r in records} - qids)
    if stray:
        raise SystemExit(f"평가셋에 없는 문항이 기록에 있음 (--eval 파일 확인): {', '.join(stray[:5])}")
    scores = load_scores(a.scores) if a.scores else {}
    traces = load_traces(a.records)
    by_group = defaultdict(list)
    for r in records:
        by_group[group_key(r)].append(r)
    groups = {name: summarize_group(rs, questions, scores, traces) for name, rs in by_group.items()}
    warns = version_check(records)
    for name, rs in by_group.items():
        seen = Counter(r.question_id for r in rs)
        dup = [q for q, n in seen.items() if n > 1]
        if dup and "[" not in name:
            warns.append(f"{name}: 같은 문항이 여러 번 실행됨 {dup[:5]} — 본 평가는 문항당 1회")
        missing = sorted(qids - set(seen))
        if missing and "[" not in name:
            warns.append(f"{name}: 실행되지 않은 문항 {len(missing)}개 {missing[:5]}")
    md = render(groups, questions, warns, a.records)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(md, encoding="utf-8")
        Path(a.out).with_suffix(".json").write_text(json.dumps(groups, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"저장: {a.out} (+ .json)")
    sys.stdout.reconfigure(encoding="utf-8")
    print(md)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sheet", help="사람이 채울 채점표 CSV 생성")
    s.add_argument("records", nargs="+")
    s.add_argument("--eval", required=True)
    s.add_argument("--out")
    s.add_argument("--force", action="store_true")
    r = sub.add_parser("report", help="구성별 지표 표")
    r.add_argument("records", nargs="+")
    r.add_argument("--eval", required=True)
    r.add_argument("--scores")
    r.add_argument("--out")
    a = p.parse_args(argv)
    (cmd_sheet if a.cmd == "sheet" else cmd_report)(a)


if __name__ == "__main__":
    main()
