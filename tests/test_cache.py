# -*- coding: utf-8 -*-
"""src/optimize/cache.py: TTL 만료, user_scope 격리, 버전 필드별 무효화. API 호출 없음."""
import time
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from optimize.cache import AnswerCache, make_key, normalize_question


# ---------------------------------------------------------------------------
# 정규화
# ---------------------------------------------------------------------------

def test_normalize_lowercases_and_collapses_whitespace():
    assert normalize_question("  D-2  연장   서류는 ") == "d-2 연장 서류는"
    assert normalize_question("") == ""
    assert normalize_question(None) == ""


# ---------------------------------------------------------------------------
# make_key
# ---------------------------------------------------------------------------

def _versions(**overrides):
    """최소한의 Versions-like 객체를 만든다 (실제 Pydantic 모델 필요 없음)."""
    from pydantic import BaseModel

    class FakeVersions(BaseModel):
        schema_version: str = "0.1.0"
        doc_version: str = "MAN-STAY-261116"
        index_version: str = "idx-abc123"
        embedding_model: str = "nlpai-lab/KURE-v1"
        generation_model: str = "claude-opus-5-5"
        reranker_model: str | None = None
        prompt_version: str = "prompt-v1-aabbcc"
        answer_config_version: str = "ans-aabbcc"
        retrieval_config_version: str = "ret-aabbcc"
        eval_version: str = "eval-v0.1"
        code_commit: str = "abc123dirty"  # 키에서 제외돼야 함

    return FakeVersions(**overrides)


def test_key_is_deterministic():
    v = _versions()
    assert make_key("질문", v) == make_key("질문", v)


def test_key_excludes_code_commit():
    """code_commit 이 달라도 나머지가 같으면 같은 키여야 한다."""
    v1 = _versions(code_commit="aaa")
    v2 = _versions(code_commit="bbb")
    assert make_key("질문", v1) == make_key("질문", v2)


def test_key_differs_by_index_version():
    v1 = _versions(index_version="idx-v1")
    v2 = _versions(index_version="idx-v2")
    assert make_key("질문", v1) != make_key("질문", v2)


def test_key_differs_by_prompt_version():
    """프롬프트를 바꾸면 이전 캐시 답변을 재사용하면 안 된다."""
    v1 = _versions(prompt_version="prompt-v1-aaa")
    v2 = _versions(prompt_version="prompt-v1-bbb")
    assert make_key("질문", v1) != make_key("질문", v2)


def test_key_differs_by_retrieval_config_version():
    v1 = _versions(retrieval_config_version="ret-aaa")
    v2 = _versions(retrieval_config_version="ret-bbb")
    assert make_key("질문", v1) != make_key("질문", v2)


def test_key_differs_by_user_scope():
    """사용자 범위가 다르면 같은 질문이어도 다른 키여야 한다."""
    v = _versions()
    assert make_key("질문", v, user_scope="public") != make_key("질문", v, user_scope="admin")


def test_key_normalized_question_is_case_insensitive():
    """대소문자와 여백 차이는 같은 키로 처리한다."""
    v = _versions()
    assert make_key("D-2 연장", v) == make_key("d-2  연장", v)


# ---------------------------------------------------------------------------
# AnswerCache: hit / miss / TTL
# ---------------------------------------------------------------------------

class _FakeResult:
    """캐시에 저장할 최소한의 더미 값."""
    def __init__(self, label):
        self.label = label


def test_cache_miss_then_hit():
    cache = AnswerCache()
    v = _versions()
    key = make_key("질문", v)
    assert cache.get(key) is None          # miss
    obj = _FakeResult("first")
    cache.set(key, obj)
    assert cache.get(key) is obj           # hit
    assert cache.hits == 1 and cache.misses == 1


def test_cache_ttl_expiry_forces_miss():
    cache = AnswerCache(ttl_seconds=0.05)
    v = _versions()
    key = make_key("TTL 질문", v)
    cache.set(key, _FakeResult("stale"))
    time.sleep(0.1)                        # TTL 초과
    assert cache.get(key) is None          # 만료 → miss


def test_cache_ttl_not_expired_returns_value():
    cache = AnswerCache(ttl_seconds=10)
    v = _versions()
    key = make_key("TTL 질문 2", v)
    obj = _FakeResult("fresh")
    cache.set(key, obj)
    assert cache.get(key) is obj           # 아직 살아 있음


def test_user_scope_isolation():
    """사용자 A 의 캐시가 사용자 B 에게 노출되지 않는다."""
    cache = AnswerCache()
    v = _versions()
    key_a = make_key("질문", v, user_scope="user_a")
    key_b = make_key("질문", v, user_scope="user_b")
    cache.set(key_a, _FakeResult("for_a"))
    assert cache.get(key_b) is None        # B 는 A 의 답변을 볼 수 없다


def test_cache_clear_removes_all_entries():
    cache = AnswerCache()
    v = _versions()
    key = make_key("질문", v)
    cache.set(key, _FakeResult("x"))
    cache.clear()
    assert cache.get(key) is None


def test_cache_version_change_invalidates_entry():
    """색인 버전이 바뀌면 이전 답변을 재사용하지 않는다."""
    cache = AnswerCache()
    v1 = _versions(index_version="idx-old")
    v2 = _versions(index_version="idx-new")
    key1 = make_key("질문", v1)
    key2 = make_key("질문", v2)
    cache.set(key1, _FakeResult("old_answer"))
    assert cache.get(key2) is None         # 새 버전은 miss
    assert cache.get(key1) is not None     # 이전 버전은 여전히 존재
