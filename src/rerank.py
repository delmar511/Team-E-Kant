"""구성 C 재정렬: RRF 결합 후보를 cross-encoder 로 질의-청크 관련도를 다시 계산해 정렬한다.

RRF 점수로 다시 정렬하는 것이 아니다 (docs/design.md 5절). 질문과 청크를 한 쌍으로 모델에 넣어
관련도 점수를 새로 매기고, 그 점수로만 순서를 정한다. RRF 점수·BM25·벡터 점수는 기록용으로만 남는다.

- 입력: RRF 상위 input_k 개 (configs/C.toml [retrieval.reranker] input_k)
- 청크 입력 텍스트: 절 경로 + 본문 (벡터 색인과 같은 방식, src/build_vectors.py embed_text)
- 동점이면 재정렬 전 순위가 앞선 쪽을 먼저 둔다 (결정적 순서)
- 모델은 처음 호출할 때 한 번만 읽는다. CPU 에서도 돌아가지만 질의당 수 초가 걸린다 (rerank_ms 로 기록)
"""
from __future__ import annotations

from typing import Callable, Sequence

ScoreFn = Callable[[str, Sequence[str]], Sequence[float]]


def rerank_text(chunk: dict) -> str:
    """재정렬기에 넣는 청크 텍스트. 절 경로가 있으면 앞에 붙여 '어느 자격의 어느 항목인지' 를 알려 준다."""
    loc = str(chunk.get("location") or "").strip()
    return f"{loc}\n{chunk['text']}" if loc else chunk["text"]


def rerank(query: str, fused: Sequence[tuple[str, float]], chunks: dict, score_fn: ScoreFn,
           input_k: int) -> list[tuple[str, float, int]]:
    """fused: [(chunk_id, rrf 점수)] RRF 순서. -> [(chunk_id, 재정렬 점수, 재정렬 전 순위)] 재정렬 순서."""
    inputs = list(fused[:input_k])
    if not inputs:
        return []
    scores = list(score_fn(query, [rerank_text(chunks[cid]) for cid, _ in inputs]))
    if len(scores) != len(inputs):
        raise RuntimeError(f"재정렬기 점수 개수 {len(scores)} != 후보 {len(inputs)}")
    rows = [(cid, float(s), before) for before, ((cid, _), s) in enumerate(zip(inputs, scores), 1)]
    return sorted(rows, key=lambda r: (-r[1], r[2]))


class CrossEncoderScorer:
    """sentence-transformers CrossEncoder. 예: BAAI/bge-reranker-v2-m3 (다국어, 한국어 포함)."""

    def __init__(self, model: str, max_length: int = 1024, batch_size: int = 8):
        self.model_name = model
        self.max_length = max_length
        self.batch_size = batch_size
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder(self.model_name, max_length=self.max_length)
        return self._model

    def __call__(self, query: str, texts: Sequence[str]) -> list[float]:
        m = self._load()
        return [float(s) for s in m.predict([(query, t) for t in texts], batch_size=self.batch_size,
                                            show_progress_bar=False)]
