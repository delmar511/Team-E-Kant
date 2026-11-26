# -*- coding: utf-8 -*-
"""src/retrieve.py: rrf 공식, 중복 제거, BM25 단독, 가중치. 색인 파일 불필요 (합성 입력)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from retrieve import rrf, RRF_K


# ---------------------------------------------------------------------------
# rrf 공식 검증
# ---------------------------------------------------------------------------

def test_rrf_score_formula_matches_definition():
    """score(d) = Σ 1/(k+rank_i(d))  — 한 목록에만 있어도 올바르게 계산돼야 한다."""
    bm = [("A", 10.0), ("B", 8.0)]
    vec = [("B", 0.9), ("C", 0.7)]
    result = dict(rrf(bm, vec, k=RRF_K, n=10))

    # A: BM25 1위, 벡터 없음
    assert abs(result["A"] - (1 / (RRF_K + 1))) < 1e-9
    # B: BM25 2위, 벡터 1위
    assert abs(result["B"] - (1 / (RRF_K + 2) + 1 / (RRF_K + 1))) < 1e-9
    # C: 벡터 2위, BM25 없음
    assert abs(result["C"] - (1 / (RRF_K + 2))) < 1e-9


def test_rrf_deduplication_one_result_per_chunk():
    """같은 chunk_id 가 두 목록에 모두 있어도 결과에서 한 번만 나온다."""
    shared = [("X", 1.0), ("Y", 0.5)]
    result = rrf(shared, shared, k=RRF_K, n=10)
    ids = [cid for cid, _ in result]
    assert len(ids) == len(set(ids)), "chunk_id 중복 발생"
    assert len(ids) == 2


def test_rrf_top_n_limits_output():
    lst = [(str(i), float(i)) for i in range(20)]
    assert len(rrf(lst, k=RRF_K, n=5)) == 5


def test_rrf_descending_order():
    """점수가 높은 순서여야 한다."""
    bm = [(str(i), float(10 - i)) for i in range(10)]
    vec = [(str(9 - i), float(i)) for i in range(10)]
    result = rrf(bm, vec, k=RRF_K, n=10)
    scores = [s for _, s in result]
    assert scores == sorted(scores, reverse=True)


def test_rrf_weights_scale_contribution():
    """가중치가 높은 목록의 기여가 더 크다."""
    # A 는 BM25 1위 / 벡터 없음, B 는 BM25 없음 / 벡터 1위
    # BM25 에 가중치 2를 주면 A 가 B 보다 높아야 한다
    bm = [("A", 1.0)]
    vec = [("B", 1.0)]
    equal = dict(rrf(bm, vec, weights=[1.0, 1.0], k=RRF_K, n=5))
    weighted = dict(rrf(bm, vec, weights=[2.0, 1.0], k=RRF_K, n=5))
    assert equal["A"] == equal["B"]           # 동등 가중치: 같은 순위이므로 같은 점수
    assert weighted["A"] > weighted["B"]      # BM25 가중치 2: A 가 더 높아야 함


def test_rrf_single_list_gives_harmonic_ranks():
    """목록 하나만 넣으면 1위가 1/(k+1), 2위가 1/(k+2)."""
    lst = [("first", 99.0), ("second", 50.0), ("third", 10.0)]
    result = dict(rrf(lst, k=RRF_K, n=10))
    assert result["first"] > result["second"] > result["third"]
    assert abs(result["first"] - 1 / (RRF_K + 1)) < 1e-9
    assert abs(result["second"] - 1 / (RRF_K + 2)) < 1e-9


def test_rrf_empty_list_does_not_crash():
    result = rrf([], k=RRF_K, n=5)
    assert result == []


def test_rrf_chunk_missing_from_one_list_still_appears():
    """한 쪽 목록에만 있는 chunk 도 결과에 포함돼야 한다."""
    bm = [("only_bm25", 5.0)]
    vec = [("only_vec", 0.8)]
    result = dict(rrf(bm, vec, k=RRF_K, n=10))
    assert "only_bm25" in result and "only_vec" in result
