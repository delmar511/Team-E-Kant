"""검색 연결 (김선규): 서종찬의 src/retrieve.py 함수를 config 대로 묶어
retrieve(query) -> list[schemas.RetrievedCandidate] 하나로 만든다.

docs/retrieval-interface.md 3절: 구성은 바뀔 수 있으니 코드에 고정하지 말 것.
-> [retrieval] mode 로 고른다.
   vector        (A) search_vector 상위 vector_k -> top_k
   hybrid        (B) search_bm25(bm25_k) + search_vector(vector_k) -> rrf(rrf_k, candidate_k) -> top_k
   hybrid_rerank (C) B 의 rrf 상위 input_k -> cross-encoder 재정렬 (src/rerank.py) -> top_k
retrieve.py 의 청크 dict 는 schemas.Chunk 로 바꾼다 (location 문자열 -> section_path, page -> page_start/end).
서종찬이 retrieve(query, config) 단일 진입점을 만들면 이 파일은 그걸 부르는 얇은 층으로 줄인다.
"""
import os
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path

from config import ConfigError, RetrievalMode
from schemas import CandidateSource, Chunk, Location, RetrievedCandidate

SRC = Path(__file__).resolve().parent
_META_KEYS = ("doc_title", "doc_version", "source", "visa_codes")
WARMUP_QUERY = "체류기간 연장허가 제출서류"  # 평가 문항과 무관한 고정 질의


def to_chunk(c: dict) -> Chunk:
    section = [s.strip() for s in str(c.get("location") or "").split(">") if s.strip()]
    page = int(c.get("page") or 1)
    return Chunk(chunk_id=c["chunk_id"], doc_id=c["doc_id"], text=c["text"],
                 location=Location(page_start=page, page_end=page, section_path=section),
                 metadata={k: c[k] for k in _META_KEYS if k in c},
                 section_key=c.get("section_key", ""),
                 part=c.get("part", 1),
                 n_parts=c.get("n_parts", 1))


def to_candidates(ranked, chunks, source, component, top_k, extra=None):
    """ranked: [(chunk_id, 점수)] 최종 순서. extra: {단계명: {chunk_id: 점수}} 기록용 단계별 점수."""
    out = []
    for rank, (cid, score) in enumerate(ranked[:top_k], 1):
        comp = {component: float(score)}
        for name, scores in (extra or {}).items():
            if cid in scores:
                comp[name] = float(scores[cid])
        out.append(RetrievedCandidate(chunk=to_chunk(chunks[cid]), score=float(score), rank=rank,
                                      source=source, component_scores=comp))
    return out


class ManualRetriever:
    """색인을 한 번 읽어 두고 질의마다 호출한다. 색인: python src/build_index.py, python src/build_vectors.py"""

    def __init__(self, cfg, index_dir="data/index", chunks_path="data/chunks.jsonl"):
        if str(SRC) not in sys.path:
            sys.path.insert(0, str(SRC))
        import retrieve as R  # 서종찬 (kiwipiepy 필요)

        self.R = R
        self.r = cfg.retrieval
        self.scorer = None
        self._tls = threading.local()  # per-thread last_rerank_ms (병렬 실행 시 경쟁 방지)
        if self.r.mode is RetrievalMode.HYBRID_RERANK:
            from rerank import CrossEncoderScorer
            self.scorer = CrossEncoderScorer(self.r.reranker.model, self.r.reranker.max_length)
        R.load_env(str(cfg.repo_root / ".env"))
        root = cfg.repo_root
        self.bm25, self.chunk_ids, self.chunks, self.meta = R.load_index(str(root / index_dir), str(root / chunks_path))
        self.vecs, vmeta = R.load_vectors(str(root / index_dir))
        if self.vecs is None:
            raise ConfigError("벡터 색인이 없습니다: python src/build_vectors.py 를 먼저 실행")
        self.model = vmeta["embedding_model"]
        for where, name in (("EMBEDDING_MODEL(.env)", os.environ.get("EMBEDDING_MODEL")),
                            ("[index] embedding_model", cfg.index.embedding_model)):
            if name and name != "TBD" and name != self.model:
                raise ConfigError(f"벡터 색인은 {self.model} 로 만들었는데 {where} 는 {name} 입니다")
        # 섹션 인덱스: section_key -> 조각 목록(part 순서). 프롬프트 확장에 쓴다.
        _sk_idx: dict = defaultdict(list)
        for raw in self.chunks.values():
            sk = raw.get("section_key")
            if sk:
                _sk_idx[sk].append(raw)
        self.section_index: dict = {sk: sorted(pieces, key=lambda p: p.get("part", 1))
                                    for sk, pieces in _sk_idx.items()}
        # 워밍업: 임베딩 모델·형태소 분석기·재정렬기 적재(첫 호출 수 초)가 첫 문항의 응답 시간에 섞이지 않게 한다
        self(WARMUP_QUERY)
        self._tls.last_rerank_ms = None

    @property
    def last_rerank_ms(self):
        return getattr(self._tls, "last_rerank_ms", None)

    @last_rerank_ms.setter
    def last_rerank_ms(self, v):
        self._tls.last_rerank_ms = v

    def __call__(self, query):
        R, r = self.R, self.r
        vec = R.search_vector(self.vecs, self.chunk_ids, query, self.model, n=r.vector_k)
        if r.mode is RetrievalMode.VECTOR:
            return to_candidates(vec, self.chunks, CandidateSource.VECTOR, "vector", r.top_k)
        bm = R.search_bm25(self.bm25, self.chunk_ids, query, n=r.bm25_k)
        fused = R.rrf(bm, vec, k=r.fusion.rrf_k, n=r.fusion.candidate_k)
        extra = {"bm25": dict(bm), "vector": dict(vec)}
        if r.mode is RetrievalMode.HYBRID:
            return to_candidates(fused, self.chunks, CandidateSource.FUSED, "rrf", r.top_k, extra=extra)
        return self._rerank(query, fused, extra)

    def _rerank(self, query, fused, extra):
        from rerank import rerank
        r = self.r
        t0 = time.perf_counter()
        rows = rerank(query, fused, self.chunks, self.scorer, r.reranker.input_k)
        self.last_rerank_ms = round((time.perf_counter() - t0) * 1000, 2)
        rrf = dict(fused)
        out = []
        for rank, (cid, score, before) in enumerate(rows[:r.top_k], 1):
            comp = {"rerank": score, "rrf": float(rrf[cid])}
            for name, scores in extra.items():
                if cid in scores:
                    comp[name] = float(scores[cid])
            out.append(RetrievedCandidate(chunk=to_chunk(self.chunks[cid]), score=score, rank=rank,
                                          source=CandidateSource.RERANKED, rank_before_rerank=before,
                                          rank_after_rerank=rank, component_scores=comp))
        return out


def make_retriever(cfg, stub=False):
    if stub:
        from answer.dev_stub import StubRetriever
        return StubRetriever(cfg.retrieval.top_k)
    return ManualRetriever(cfg)
