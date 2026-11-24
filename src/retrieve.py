"""
검색 구성 A / B / C

담당: 서종찬(BM25, RRF 결합) | 평가표 4·5번
A: Vector 단독   B: BM25 + Vector (RRF)   C: B + re-ranking

[의도적으로 본문을 비워뒀습니다.]

주의 — 평가표 4번의 '직접 구현'
----------------------------
라이브러리의 하이브리드 검색 함수 하나를 호출하고 끝내면 안 된다.
BM25 검색과 벡터 검색을 따로 호출하고, 결합 로직을 내 코드로 가지고 있어야 한다.

RRF 공식
--------
    score(d) = 1/(60 + rank_bm25(d)) + 1/(60 + rank_vector(d))

점수를 버리고 순위만 쓴다. BM25 는 상한이 없고 코사인은 0~1 이라
단순 합산하면 BM25 가 벡터를 압도하기 때문이다. (발제가 단순 합산을 금지)

기록해야 하는 것
--------------
- 각 검색기의 후보 수 (20)
- RRF 의 k 값 (60)
- 중복 청크 병합 규칙
- 모든 실행의 before_rerank / after_rerank 순위 배열  <- 평가표 5번 증빙
"""

RRF_K = 60
CANDIDATES_PER_RETRIEVER = 20
FINAL_K = 5


def search_bm25(query, k=CANDIDATES_PER_RETRIEVER):
    raise NotImplementedError


def search_vector(query, k=CANDIDATES_PER_RETRIEVER):
    raise NotImplementedError


def rrf_fuse(bm25_hits, vector_hits, k=RRF_K):
    """두 순위 목록을 RRF 로 합친다. 중복 chunk_id 는 점수를 합산."""
    raise NotImplementedError


def rerank(query, candidates, k=FINAL_K):
    """Cross-encoder 로 질의-청크 관련도를 재계산한다.

    RRF 점수로 다시 정렬하는 것은 재정렬이 아니다.
    """
    raise NotImplementedError


def retrieve(query, config):
    """config: 'A' | 'B' | 'C'. 전후 순위를 함께 돌려준다."""
    raise NotImplementedError
