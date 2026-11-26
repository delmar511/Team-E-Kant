# -*- coding: utf-8 -*-
"""experiments/metrics.py: 추가 채점 엣지 케이스 (재정렬 순서, 전체 근거 회수, 오류 상태). API 호출 없음."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "experiments"))

import metrics
from _common import load_questions, make_record, write_jsonl
from agent import run_agent
from answer.dev_stub import StubRetriever
from config import build_versions, load_config
from schemas import RunKind, CandidateSource, Chunk, Location, RetrievedCandidate


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _cand(chunk_id, doc_id, score, rank, rank_before=None, rank_after=None):
    return RetrievedCandidate(
        chunk=Chunk(chunk_id=chunk_id, doc_id=doc_id, text="본문",
                    location=Location(page_start=1, page_end=1)),
        score=score, rank=rank,
        source=CandidateSource.RERANKED if rank_before is not None else CandidateSource.VECTOR,
        rank_before_rerank=rank_before,
        rank_after_rerank=rank_after,
    )


def _eval_item(qid, chunk_ids, qtype="direct"):
    return {
        "id": qid, "split": "test", "type": qtype,
        "visa": ["D-2"], "question": f"질문 {qid}",
        "expected_facts": ["사실"], "evidence": [{"chunk_id": c} for c in chunk_ids],
        "no_answer_reason": None,
    }


def _no_answer_item(qid, reason="매뉴얼에 없음"):
    return {
        "id": qid, "split": "test", "type": "no_answer",
        "visa": ["D-2"], "question": f"질문 {qid}",
        "expected_facts": [], "evidence": [],
        "no_answer_reason": reason,
    }


# ---------------------------------------------------------------------------
# 재정렬 후 순위로 Hit@5 계산
# ---------------------------------------------------------------------------

def test_hit5_uses_candidate_order_as_stored():
    """RunRecord.top_k_chunk_ids 는 candidates 의 rank 순서를 쓴다.
    재정렬 전 1위였다가 재정렬 후 6위가 된 청크는 Hit@5 에서 0 이어야 한다.
    (top_k_chunk_ids 반환 값이 정답 청크를 포함하는지 여부로 검증)"""
    from schemas import RunRecord
    cfg = load_config(ROOT / "configs" / "C.toml")
    versions = build_versions(cfg)

    # 재정렬 전 1위였지만 재정렬 후 순위가 5위 밖 → rank=6
    gold = "DOC-D2#gold"
    deep = _cand(gold, "DOC-D2", score=0.5, rank=6, rank_before=1, rank_after=6)
    top5 = [_cand(f"DOC-D4#c{i}", "DOC-D4", score=1.0 - i * 0.1, rank=i, rank_before=i + 1, rank_after=i)
            for i in range(1, 6)]

    from schemas import AgentResponse, LatencyBreakdown, Status, Usage
    response = AgentResponse(
        status=Status.ANSWERED, answer="답변 [DOC-D4#c1]", cited_chunk_ids=["DOC-D4#c1"],
        latency=LatencyBreakdown(retrieval_ms=10, generation_ms=50, total_ms=60),
        usage=Usage(model_calls=1),
    )
    record = RunRecord(
        run_id="test-rank-001", run_kind=RunKind.CORE, question_id="TEST-RANK",
        split="test", question="질문", config_name="C",
        config=cfg.model_dump(mode="json"),
        versions=versions.model_dump(mode="json"),
        candidates=top5 + [deep],
        response=response,
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )

    top = record.top_k_chunk_ids(5)
    assert gold not in top, f"재정렬 후 6위인 청크가 top-5 에 들어가면 안 됨: {top}"


# ---------------------------------------------------------------------------
# 전체 근거 회수@5 (full_recall@5)
# ---------------------------------------------------------------------------

EVAL_MULTI = [
    _eval_item("TEST-M1", ["DOC-D2#req1", "DOC-D2#req2"]),   # 필수 근거 2개
    _eval_item("TEST-M2", ["DOC-D4#only"]),                    # 필수 근거 1개
    _no_answer_item("TEST-M3"),
]


def test_full_recall5_requires_all_evidence_chunks(tmp_path):
    """full_recall@5: 필수 근거 중 하나라도 top-5 밖이면 0 이어야 한다."""
    ev = tmp_path / "eval.json"
    ev.write_text(json.dumps(EVAL_MULTI, ensure_ascii=False), encoding="utf-8")

    cfg = load_config(ROOT / "configs" / "A.toml")
    versions = build_versions(cfg)
    qs = load_questions(ev, warn=False)

    def controlled_retriever(question_id):
        """TEST-M1 은 근거 중 하나(req2)만 top-5 에 반환. TEST-M2 는 정답 반환."""
        if "M1" in question_id:
            # req1 은 1위, req2 는 6위 (top-5 밖)
            return [_cand("DOC-D2#req1", "DOC-D2", 0.9, 1)] + \
                   [_cand(f"DOC-X#noise{i}", "DOC-X", 0.5 - i * 0.1, i + 1) for i in range(1, 5)]
        else:
            return [_cand("DOC-D4#only", "DOC-D4", 0.9, 1)] + \
                   [_cand(f"DOC-X#n{i}", "DOC-X", 0.1, i + 1) for i in range(1, 4)]

    recs = []
    for i, q in enumerate(qs, 1):
        retriever = lambda query, qid=q["question_id"]: controlled_retriever(qid)
        t = datetime.now(timezone.utc)
        res = run_agent(q["question"], cfg, retriever, versions=versions)
        recs.append(make_record(q, cfg, versions, res, f"m{i}", RunKind.CORE, t, datetime.now(timezone.utc)))

    path = tmp_path / "m.records.jsonl"
    write_jsonl(path, recs)
    out = tmp_path / "m.md"
    metrics.main(["report", str(path), "--eval", str(ev), "--out", str(out)])
    g = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))["A"]

    # Hit@5: TEST-M1 은 req1 이 1위이므로 hit=1, TEST-M2 도 hit=1 → 2/2
    assert g["hit5"].startswith("2/2")
    # full_recall@5: TEST-M1 은 req2 가 없으므로 0, TEST-M2 는 1 → 1/2
    assert g["full_recall5"].startswith("1/2")


# ---------------------------------------------------------------------------
# 오류 상태는 근거 없음 대응으로 세지 않는다
# ---------------------------------------------------------------------------

EVAL_NOANS = [_no_answer_item("TEST-NA1")]


def test_error_status_not_counted_as_correct_no_answer(tmp_path):
    """retrieval_error 로 끝난 근거 없음 문항은 no_answer_correct 에서 0 이어야 한다."""
    ev = tmp_path / "eval.json"
    ev.write_text(json.dumps(EVAL_NOANS, ensure_ascii=False), encoding="utf-8")

    cfg = load_config(ROOT / "configs" / "A.toml")
    versions = build_versions(cfg)
    qs = load_questions(ev, warn=False)

    def broken(query):
        raise RuntimeError("index down")

    recs = []
    for q in qs:
        t = datetime.now(timezone.utc)
        res = run_agent(q["question"], cfg, broken, versions=versions)
        recs.append(make_record(q, cfg, versions, res, "err1", RunKind.CORE, t, datetime.now(timezone.utc)))

    path = tmp_path / "e.records.jsonl"
    write_jsonl(path, recs)
    out = tmp_path / "e.md"
    metrics.main(["report", str(path), "--eval", str(ev), "--out", str(out)])
    g = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))["A"]

    # 오류는 올바른 거절로 세지 않는다 → no_answer_correct 분자는 0
    assert g["no_answer_correct"].startswith("0/1")
    # 오류 카운트는 1
    assert g["errors"] >= 1
