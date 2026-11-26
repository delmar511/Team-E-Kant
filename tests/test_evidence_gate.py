# -*- coding: utf-8 -*-
"""src/answer/evidence_gate.py: score_gate, model_gate, gate_modes. API 호출 없음."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from answer.evidence_gate import gate_modes, model_gate, score_gate
from schemas import CandidateSource, Chunk, Location, RetrievedCandidate


def _cand(score, chunk_id="DOC-D2#aaa"):
    return RetrievedCandidate(
        chunk=Chunk(chunk_id=chunk_id, doc_id="DOC-D2", text="본문",
                    location=Location(page_start=1, page_end=1)),
        score=score, rank=1, source=CandidateSource.VECTOR,
    )


def _gate_cfg(method, **params):
    return SimpleNamespace(method=method, params=params or {})


def _answer_output(insufficient):
    return SimpleNamespace(insufficient_evidence=insufficient)


# ---------------------------------------------------------------------------
# gate_modes
# ---------------------------------------------------------------------------

def test_gate_modes_model_judgment():
    use_score, use_model, min_score, min_chunks = gate_modes(_gate_cfg("model_judgment"))
    assert not use_score and use_model
    assert min_score is None


def test_gate_modes_score_threshold_requires_min_score():
    with pytest.raises(ValueError, match="min_score"):
        gate_modes(_gate_cfg("score_threshold"))  # params 없음 → 오류


def test_gate_modes_score_threshold_ok():
    use_score, use_model, min_score, min_chunks = gate_modes(
        _gate_cfg("score_threshold", min_score=0.3, min_chunks=2))
    assert use_score and not use_model
    assert min_score == 0.3 and min_chunks == 2


def test_gate_modes_both():
    use_score, use_model, _, _ = gate_modes(_gate_cfg("both", min_score=0.1))
    assert use_score and use_model


def test_gate_modes_none():
    use_score, use_model, _, _ = gate_modes(_gate_cfg("none"))
    assert not use_score and not use_model


# ---------------------------------------------------------------------------
# score_gate
# ---------------------------------------------------------------------------

def test_score_gate_no_candidates_is_lacking():
    lacking, reason = score_gate([], min_score=0.3)
    assert lacking and "0건" in reason


def test_score_gate_top_candidate_above_threshold_passes():
    cands = [_cand(0.9), _cand(0.1)]
    lacking, _ = score_gate(cands, min_score=0.5)
    assert not lacking


def test_score_gate_all_below_threshold_is_lacking():
    cands = [_cand(0.1), _cand(0.2)]
    lacking, reason = score_gate(cands, min_score=0.5)
    assert lacking and "점수 게이트" in reason


def test_score_gate_min_chunks_requires_enough_above_threshold():
    """min_chunks=2 일 때 임계값 이상 청크가 1개면 게이트 통과 실패."""
    cands = [_cand(0.9, "A"), _cand(0.1, "B"), _cand(0.05, "C")]
    lacking_one, _ = score_gate(cands, min_score=0.5, min_chunks=1)
    lacking_two, _ = score_gate(cands, min_score=0.5, min_chunks=2)
    assert not lacking_one   # 1개면 충분
    assert lacking_two       # 2개 필요한데 1개뿐


def test_score_gate_exactly_at_threshold_passes():
    cands = [_cand(0.5)]
    lacking, _ = score_gate(cands, min_score=0.5)
    assert not lacking


# ---------------------------------------------------------------------------
# model_gate
# ---------------------------------------------------------------------------

def test_model_gate_sufficient_evidence_passes():
    lacking, _ = model_gate(_answer_output(insufficient=False))
    assert not lacking


def test_model_gate_insufficient_evidence_is_lacking():
    lacking, reason = model_gate(_answer_output(insufficient=True))
    assert lacking and "모델" in reason
