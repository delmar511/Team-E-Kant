"""정확 일치 답변 캐시 (configs/C_cache.toml).

키 = 정규화한 원질문 + 사용자 범위 + config.build_versions() 의 버전들(문서·색인·모델·프롬프트·답변/검색 설정).
문서나 색인을 바꾸면 doc_version / index_version 이 바뀌어 이전 답변이 재사용되지 않는다 (명시적 무효화).
code_commit 은 키에서 뺀다 (커밋마다 캐시가 비지 않도록). [optimization.cache] ttl_s 로 만료도 둔다.
오류 결과와 리라이트 fallback 결과는 저장하지 않는다 (src/agent.py).
"""
import hashlib
import json
import time

KEY_EXCLUDE = {"code_commit"}


def normalize_question(q: str) -> str:
    return " ".join((q or "").lower().split())


def make_key(question: str, versions, user_scope: str = "public") -> str:
    v = {k: val for k, val in versions.model_dump(mode="json").items() if k not in KEY_EXCLUDE}
    payload = {"q": normalize_question(question), "scope": user_scope, "versions": v}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class AnswerCache:
    """프로세스 메모리 캐시. 값은 agent.AgentResult."""

    def __init__(self, ttl_seconds=None):
        self._store = {}
        self.ttl_seconds = ttl_seconds
        self.hits = 0
        self.misses = 0

    def get(self, key):
        item = self._store.get(key)
        if item is not None and self.ttl_seconds is not None and time.time() - item[0] > self.ttl_seconds:
            del self._store[key]
            item = None
        if item is None:
            self.misses += 1
            return None
        self.hits += 1
        return item[1]

    def set(self, key, value):
        self._store[key] = (time.time(), value)

    def clear(self):
        self._store.clear()
