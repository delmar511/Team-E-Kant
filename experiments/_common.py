"""실험 공통 (역할 6, 김선규): 평가셋 로딩, 실행마다 schemas.RunRecord 한 줄 기록, 간단 요약.

실패를 덮어쓰거나 버리지 않는다: 오류 건도 RunRecord 로 남기고, 파일명에 시각을 넣어 덮어쓰지 않는다.
지표 확정·보고서 표는 박태환 담당 (metrics.py) 이고, 여기 요약은 실행 직후 확인용이다.
"""
import json
import statistics
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from schemas import RunRecord, Split, Status  # noqa: E402

QUESTION_TYPES = ("direct", "paraphrase", "confusable", "no_answer")
RUNS_DIR = ROOT / "results" / "runs"


# ---------------- 평가셋 ----------------

def gold_from_evidence(evidence):
    """Hit@5 정답 = evidence[].chunk_id (서종찬 retrieve.py evaluate() 와 같은 기준).
    chunk_ids_all(같은 문장이 들어 있는 다른 청크)은 쓰지 않는다: 다른 자격 문서가 섞여 있어 자격 혼동을 정답으로 칠 수 있다."""
    ids = []
    for e in evidence or []:
        cid = e if isinstance(e, str) else (e.get("chunk_id") if isinstance(e, dict) else None)
        if cid and cid not in ids:
            ids.append(cid)
    return ids


def _normalize(q, version):
    qid = q.get("question_id") or q["id"]
    qtype = q.get("type", "")
    answerable = q["answerable"] if isinstance(q.get("answerable"), bool) else qtype != "no_answer"
    split = q.get("split") or ("test" if qid.upper().startswith("TEST") else "dev")
    return {**q, "question_id": qid, "type": qtype, "split": split, "answerable": answerable,
            "gold_chunk_ids": gold_from_evidence(q.get("evidence")),
            "no_answer_reason": q.get("no_answer_reason") or q.get("absence_reason") or "", "eval_version": version}


def check_questions(questions):
    """평가셋 경고 목록. 실행은 막지 않지만 본 평가(core) 전에는 비어 있어야 한다."""
    warns = []
    ids = [q["question_id"] for q in questions]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        warns.append(f"문항 ID 중복: {', '.join(dup)}")
    bad = [q["question_id"] for q in questions if q["type"] not in QUESTION_TYPES]
    if bad:
        warns.append(f"알 수 없는 type ({'/'.join(QUESTION_TYPES)} 중 하나): {', '.join(bad)}")
    no_gold = [q["question_id"] for q in questions if q["answerable"] and not q["gold_chunk_ids"]]
    if no_gold:
        warns.append(f"답변 가능 문항인데 evidence.chunk_id 없음 → Hit@5 측정 불가: {', '.join(no_gold)}")
    gold_on_no = [q["question_id"] for q in questions if not q["answerable"] and q["gold_chunk_ids"]]
    if gold_on_no:
        warns.append(f"근거 없음 문항인데 정답 청크 있음: {', '.join(gold_on_no)}")
    no_reason = [q["question_id"] for q in questions if not q["answerable"] and not q["no_answer_reason"]]
    if no_reason:
        warns.append(f"근거 없음 문항인데 no_answer_reason 없음: {', '.join(no_reason)}")
    return warns


def load_questions(path, warn=True):
    """eval/eval-dev.json, eval/eval-test.json (문항 리스트) 또는 {"version", "questions"} 형태."""
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    version = data.get("version", path.stem) if isinstance(data, dict) else path.stem
    items = data["questions"] if isinstance(data, dict) else data
    out = [_normalize(q, version) for q in items]
    if warn:
        n_ans = sum(q["answerable"] for q in out)
        print(f"[평가셋] {path.name}: {len(out)}문항 (답변 가능 {n_ans}, 근거 없음 {len(out) - n_ans})")
        for w in check_questions(out):
            print(f"[평가셋 경고] {w}")
    return out


# ---------------- 기록 ----------------

def hit_at_k(retrieved_ids, gold_ids, k=5):
    """정답 청크가 없으면 None (측정 불가, 0점이 아님)."""
    if not gold_ids:
        return None
    return int(bool(set(retrieved_ids[:k]) & set(gold_ids)))


def make_record(q, cfg, versions, result, run_id, kind, started_at, finished_at, retry_of=None) -> RunRecord:
    return RunRecord(run_id=run_id, run_kind=kind, retry_of=retry_of, question_id=q["question_id"],
                     split=Split(q["split"]), question=q["question"], config_name=cfg.name, config=cfg.resolved(),
                     versions=versions, candidates=result.candidates, response=result.response,
                     started_at=started_at, finished_at=finished_at)


def trace_row(q, record: RunRecord, trace):
    top = record.top_k_chunk_ids(5)
    return {"run_id": record.run_id, "question_id": q["question_id"], "type": q["type"],
            "answerable": q["answerable"], "status": record.response.status.value,
            "gold_chunk_ids": q["gold_chunk_ids"], "top5_chunk_ids": top,
            "hit_at_5": hit_at_k(top, q["gold_chunk_ids"]), **trace}


def out_paths(stem):
    """(실행 시각 stamp, records 경로, trace 경로). stamp 는 run_id 에도 넣어 실행 간 run_id 가 겹치지 않게 한다."""
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = f"{datetime.now():%Y%m%d%H%M%S}"
    base = RUNS_DIR / f"{datetime.now():%Y-%m-%d_%H%M%S}_{stem}"
    return stamp, base.with_suffix(".records.jsonl"), base.with_suffix(".trace.jsonl")


def _line(r):
    return (r.model_dump_json() if hasattr(r, "model_dump_json") else json.dumps(r, ensure_ascii=False)) + "\n"


class JsonlWriter:
    """한 줄씩 바로 쓰고 flush 한다. 실행 도중 멈춰도 그때까지의 기록이 파일에 남는다. 기존 파일은 덮어쓰지 않는다."""

    def __init__(self, path):
        self.path = path
        self._f = None

    def __enter__(self):
        self._f = open(self.path, "x", encoding="utf-8")
        return self

    def write(self, row):
        self._f.write(_line(row))
        self._f.flush()

    def __exit__(self, *exc):
        self._f.close()
        return False


def write_jsonl(path, rows):
    with JsonlWriter(path) as w:
        for r in rows:
            w.write(r)


def summarize(config_name, traces, records):
    n = len(records)
    status = Counter(r.response.status.value for r in records)
    hits = [t["hit_at_5"] for t in traces if t["answerable"] and t["hit_at_5"] is not None]
    unmeasured = sum(1 for t in traces if t["answerable"] and t["hit_at_5"] is None)
    no_ans = [t for t in traces if not t["answerable"]]
    lat = [r.response.latency.total_ms for r in records if not r.response.status.is_error]
    parts = [f"[{config_name}] {n}건", " ".join(f"{k} {v}" for k, v in sorted(status.items()))]
    parts.append(f"Hit@5 {sum(hits)}/{len(hits)}" + (f" (측정 불가 {unmeasured})" if unmeasured else ""))
    if no_ans:
        ok = sum(1 for t in no_ans if t["status"] == Status.NO_EVIDENCE.value)
        parts.append(f"근거 없음 자동 판정 {ok}/{len(no_ans)} (참고용, 최종은 사람 채점)")
    if lat:
        parts.append(f"응답 시간 중앙값 {statistics.median(lat) / 1000:.2f}초 (성공 {len(lat)}건)")
    return " | ".join(parts)
