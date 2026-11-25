"""근거 부족(no_evidence) 판정. configs 의 [evidence_gate] 를 따른다. 임계값은 dev 평가셋으로만 튜닝한다.

method:
  none            판정 안 함 (검색 결과 0건만 근거 없음)
  score_threshold 생성 전 점수 게이트만: params.min_score 이상 청크가 params.min_chunks(기본 1)개 미만이면 생성하지 않음
  model_judgment  생성 후 모델 자기 판단만: insufficient_evidence=true 면 근거 없음 (기본값)
  both            둘 다
검색은 질문과 무관해도 항상 top_k 개를 돌려주므로 (docs/retrieval-interface.md 4절) 판정은 이쪽 책임이다.
점수 척도는 구성마다 다르다 (A: 코사인, B: RRF). 점수는 사실일 확률이 아니라 임계값 용도다.
"""
from answer.prompt import NO_EVIDENCE_MESSAGE

__all__ = ["NO_EVIDENCE_MESSAGE", "gate_modes", "score_gate", "model_gate"]


def gate_modes(gate_cfg):
    """(점수 게이트 사용, 모델 판단 사용, min_score, min_chunks)."""
    method = gate_cfg.method
    use_score = method in ("score_threshold", "both")
    use_model = method in ("model_judgment", "both")
    params = gate_cfg.params or {}
    if use_score and params.get("min_score") is None:
        raise ValueError(f"[evidence_gate] method={method} 은 params.min_score 가 필요합니다")
    return use_score, use_model, params.get("min_score"), int(params.get("min_chunks", 1))


def score_gate(candidates, min_score, min_chunks=1):
    """(근거 부족 여부, 사유)."""
    if not candidates:
        return True, "검색 결과 0건"
    good = [c for c in candidates if c.score >= min_score]
    if len(good) < min_chunks:
        return True, f"점수 게이트: 임계값({min_score}) 이상 청크 {len(good)}개 < 최소 {min_chunks}개"
    return False, ""


def model_gate(output):
    """(근거 부족 여부, 사유). output: generator.AnswerOutput."""
    if output.insufficient_evidence:
        return True, "모델 자기 판단: 근거 부족"
    return False, ""
