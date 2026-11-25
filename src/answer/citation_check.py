"""인용 검사: 답변의 인용 ID 가 모델에 실제로 준 청크에 있는지 확인하고, 없는 인용은 분리·표시한다."""
import re

# 팀 청크 ID 형식 'DOC-D2#94bd3000d6' (문서ID#해시). 더미·테스트용 'D01_c001' 형식도 받는다.
CITATION_PATTERN = re.compile(r"\[([A-Za-z][A-Za-z0-9_\-]*(?:#[0-9a-fA-F]{6,}|_c\d+))\]")


def extract_citations(answer: str):
    return list(dict.fromkeys(CITATION_PATTERN.findall(answer or "")))


def check_citations(cited_ids, context_chunk_ids):
    """(유효 인용, 무효 인용). 무효 인용 = 모델에 주지 않은 ID (임의 생성 등)."""
    allowed = set(context_chunk_ids)
    valid = [c for c in cited_ids if c in allowed]
    invalid = [c for c in cited_ids if c not in allowed]
    return valid, invalid


def mark_invalid(answer: str, invalid_ids):
    """답변 본문에서 무효 인용을 [검증 실패: ID] 로 바꿔 사용자에게 표시한다."""
    for cid in invalid_ids:
        answer = answer.replace(f"[{cid}]", f"[검증 실패: {cid}]")
    return answer
