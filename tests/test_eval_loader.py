"""experiments/_common.py 평가셋 로더: 팀 평가셋 형식(eval/eval-*.json) 그대로 읽기."""
import json

from _common import check_questions, gold_from_evidence, hit_at_k, load_questions


def _q(qid, qtype, evidence=None, reason=None):
    return {"id": qid, "split": "dev", "type": qtype, "visa": ["D-2"], "question": f"질문 {qid}",
            "expected_facts": [], "evidence": evidence or [], "no_answer_reason": reason}


def test_team_format(tmp_path):
    p = tmp_path / "eval-dev.json"
    p.write_text(json.dumps([
        _q("DEV-001", "direct", [{"page": 44, "section": "x", "quote": "q", "chunk_id": "DOC-D2#a1",
                                  "chunk_ids_all": ["DOC-D2#a1", "DOC-D4#b1"]}]),
        _q("DEV-006", "confusable", [{"page": 30, "section": "시간제취업", "chunk_id": None}]),
        _q("DEV-009", "no_answer", reason="판정 요청"),
    ], ensure_ascii=False), encoding="utf-8")
    qs = {q["question_id"]: q for q in load_questions(p, warn=False)}
    assert [q["answerable"] for q in qs.values()] == [True, True, False]
    assert qs["DEV-001"]["gold_chunk_ids"] == ["DOC-D2#a1"]  # chunk_ids_all 은 정답으로 치지 않음
    assert qs["DEV-006"]["gold_chunk_ids"] == [] and qs["DEV-009"]["split"] == "dev"
    warns = "\n".join(check_questions(list(qs.values())))
    assert "Hit@5 측정 불가: DEV-006" in warns


def test_hit_at_k_unmeasurable_is_none():
    assert hit_at_k(["a", "b"], []) is None
    assert hit_at_k(["a", "b", "c", "d", "e", "g"], ["g"]) == 0
    assert hit_at_k(["a", "g"], ["g", "x"]) == 1
    assert gold_from_evidence(["a", {"chunk_id": "b"}, {"page": 1}]) == ["a", "b"]
