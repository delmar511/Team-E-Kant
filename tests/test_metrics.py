"""experiments/metrics.py: Hit@5 는 후보에서 계산, 오류는 0점, 채점표 왕복, 분모 유지. API 호출 없음."""
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import metrics
from _common import load_questions, make_record, write_jsonl
from agent import run_agent
from answer.dev_stub import StubRetriever
from config import build_versions, load_config
from schemas import RunKind

ROOT = Path(__file__).resolve().parents[1]

EVAL = [
    {"id": "TEST-001", "split": "test", "type": "direct", "visa": ["D-2"], "question": "유학 체류기간 연장 제출서류는",
     "expected_facts": ["신청서, 여권"], "evidence": [{"chunk_id": "DOC-D2#00000000a1"}], "no_answer_reason": None},
    {"id": "TEST-002", "split": "test", "type": "confusable", "visa": ["D-4"], "question": "어학연수 시간제취업 요건은",
     "expected_facts": ["6개월"], "evidence": [{"chunk_id": "DOC-D4#00000000b1"}, {"chunk_id": "DOC-X#ffffffffff"}],
     "no_answer_reason": None},
    {"id": "TEST-003", "split": "test", "type": "no_answer", "visa": ["D-2"], "question": "건강보험료는 얼마인가",
     "expected_facts": [], "evidence": [], "no_answer_reason": "매뉴얼에 없음"},
]


def _broken_retriever(query):
    raise RuntimeError("index down")


@pytest.fixture
def run(tmp_path):
    ev = tmp_path / "eval.json"
    ev.write_text(json.dumps(EVAL, ensure_ascii=False), encoding="utf-8")
    cfg = load_config(ROOT / "configs" / "A.toml")
    versions = build_versions(cfg)
    qs = load_questions(ev, warn=False)
    recs = []
    for i, q in enumerate(qs, 1):
        retriever = _broken_retriever if q["question_id"] == "TEST-003" else StubRetriever()
        t = datetime.now(timezone.utc)
        res = run_agent(q["question"], cfg, retriever, versions=versions)
        recs.append(make_record(q, cfg, versions, res, f"r{i}", RunKind.CORE, t, datetime.now(timezone.utc)))
    path = tmp_path / "x.records.jsonl"
    write_jsonl(path, recs)
    return path, ev, tmp_path


def test_report_hit_and_denominators(run):
    path, ev, tmp = run
    out = tmp / "r.md"
    metrics.main(["report", str(path), "--eval", str(ev), "--out", str(out)])
    g = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))["A"]
    assert g["runs"] == 3
    assert g["hit5"].startswith("2/2")              # 두 답변 가능 문항 모두 근거 하나 이상 회수
    assert g["full_recall5"].startswith("1/2")      # TEST-002 는 근거 하나가 색인에 없음
    assert g["no_answer_correct"].startswith("0/1")  # 분모에서 빠지지 않음
    assert g["errors"] == 1 and g["retrieval_calls"].startswith("2/3")
    assert g["latency_n"] == 2                       # 오류 건은 응답 시간에서 제외


def test_sheet_prefills_errors_and_roundtrips(run):
    path, ev, tmp = run
    sheet = tmp / "s.csv"
    metrics.main(["sheet", str(path), "--eval", str(ev), "--out", str(sheet)])
    with pytest.raises(SystemExit):  # 채점한 파일을 덮어쓰지 않음
        metrics.main(["sheet", str(path), "--eval", str(ev), "--out", str(sheet)])
    rows = list(csv.DictReader(open(sheet, encoding="utf-8-sig")))
    err = next(r for r in rows if r["question_id"] == "TEST-003")
    assert err["no_answer_correct"] == "0" and err["failure_category"] == "system_error"
    for r in rows:
        if r["question_id"] == "TEST-001":
            r.update(answer_correct="1", citation_valid="1", rationale="핵심 사실 일치", scorer="kim", reviewer="park")
    with open(sheet, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, metrics.SHEET_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    out = tmp / "r.md"
    metrics.main(["report", str(path), "--eval", str(ev), "--scores", str(sheet), "--out", str(out)])
    g = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))["A"]
    assert g["answer_correct"].startswith("1/2") and "미채점 1" in g["answer_correct"]
    assert g["no_answer_correct"] == "0/1 (0.00)"


def test_scorer_must_differ_from_reviewer(run, tmp_path):
    path, ev, tmp = run
    sheet = tmp / "s.csv"
    metrics.main(["sheet", str(path), "--eval", str(ev), "--out", str(sheet)])
    rows = list(csv.DictReader(open(sheet, encoding="utf-8-sig")))
    rows[0].update(answer_correct="1", citation_valid="1", rationale="ok", scorer="kim", reviewer="kim")
    with open(sheet, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, metrics.SHEET_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    with pytest.raises(SystemExit, match="채점 행 오류"):
        metrics.main(["report", str(path), "--eval", str(ev), "--scores", str(sheet)])


def test_cache_experiment_15_runs(tmp_path, monkeypatch):
    """미적중 5 -> 적중 5 -> 문서 버전 변경 후 미적중 5. 기대와 어긋나면 SystemExit(1)."""
    import run_cache_experiment as rce
    paths = (tmp_path / "c.records.jsonl", tmp_path / "c.trace.jsonl")
    monkeypatch.setattr(rce, "out_paths", lambda stem: ("20260101000000", *paths))
    rce.main(["--stub", "--eval", str(ROOT / "eval" / "eval-dev.json")])
    rows = [json.loads(line) for line in open(paths[1], encoding="utf-8")]
    assert len(rows) == 15 and all(r["ok"] for r in rows)
    assert [r["phase"] for r in rows] == ["miss"] * 5 + ["hit"] * 5 + ["updated"] * 5
    assert len({r["doc_version"] for r in rows}) == 2
