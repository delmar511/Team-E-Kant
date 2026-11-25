"""버전이 지정된 설정 로더.

한 가지 실험 구성(A, B, C 또는 C+최적화)을 로드하고, 검증하며,
모든 RunRecord에 저장되고 모든 캐시 키에 사용되는 버전 문자열을 생성합니다.

레이아웃 (구성 파일의 경로는 repo 루트에 상대적):

    configs/
        base.toml        모든 구성에서 공유: docs, index, generation,
                         prompt, 답변 제한, eval 버전
        A.toml           base 확장; 벡터만
        B.toml           base 확장; 하이브리드(RRF)
        C.toml           base 확장; 하이브리드 + 순위 재조정
        C_cache.toml     C 확장; 최적화 분기(선택한 것 유지)
        C_rewrite.toml   C 확장; 최적화 분기

구성 파일은 `extends = "other.toml"` (자신에 상대적)을 설정할 수 있습니다;
테이블은 깊이 병합되고 자식 값이 우승합니다. TOML은 추가 사항이 필요 없습니다;
PyYAML이 설치되어 있으면 .yaml/.yml 파일도 작동합니다.

비밀(API 키)은 절대 구성 파일에 들어가지 않습니다. 환경/.env에서 옵니다,
.env.example을 참조하세요.

사용:
    cfg = load_config("configs/C.toml")
    versions = build_versions(cfg)          # -> schemas.Versions
    record_config = cfg.resolved()          # -> dict for RunRecord.config
    check_index_manifest(cfg)               # 오래된 인덱스에 빠르게 실패
    check_shared_settings([cfg_a, cfg_b, cfg_c])
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import tomllib
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

from schemas import Versions

HASH_LEN = 12
CORE_CONFIGS = {"A", "B", "C"}
CHUNKS_PATH = "data/chunks.jsonl"  # 검색기가 읽는 청크 파일 (search_adapter 기본값과 같음)


class ConfigError(ValueError):
    """유효하지 않거나, 불일치하거나, 오래된 구성에 대해 발생합니다."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---------------------------------------------------------------------------
# Config sections
# ---------------------------------------------------------------------------


class DocsConfig(_Strict):
    doc_version: str = Field(description="설명서 판 레이블, 예: 'MAN-STAY-YYMMDD'")
    source_path: Optional[str] = Field(
        default=None, description="원본 설명서 파일; 존재하면 해시가 doc_version에 추가됨"
    )
    documents_csv: str = "docs/documents.csv"


class IndexConfig(_Strict):
    """청킹 및 인덱싱 설정. 이들 중 하나를 변경하면 index_version이 변경됩니다."""

    chunk_size: int = Field(gt=0)
    chunk_overlap: int = Field(ge=0)
    chunk_unit: Literal["chars", "tokens"] = "chars"
    embedding_model: str
    bm25_tokenizer: str = Field(description="예: 'kiwi', 'mecab', 'whitespace'")
    index_dir: str = "index"

    @model_validator(mode="after")
    def _overlap_lt_size(self) -> "IndexConfig":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return self


class RetrievalMode(str, Enum):
    VECTOR = "vector"                  # config A
    HYBRID = "hybrid"                  # config B
    HYBRID_RERANK = "hybrid_rerank"    # config C


class FusionConfig(_Strict):
    method: Literal["rrf"] = "rrf"
    rrf_k: int = Field(default=60, gt=0, description="RRF 상수")
    candidate_k: int = Field(gt=0, description="융합된, 중복 제거된 후보자 유지")


class RerankerConfig(_Strict):
    model: str
    input_k: int = Field(gt=0, description="순위 재조정기에 전송된 융합 후보자")
    max_length: int = Field(default=1024, gt=0, description="질문+청크 쌍의 최대 토큰 수 (넘으면 잘림)")


class RetrievalConfig(_Strict):
    mode: RetrievalMode
    top_k: int = Field(ge=5, description="반환된 최종 후보자; Hit@5의 경우 >= 5")
    vector_k: int = Field(gt=0, description="벡터 검색의 후보자")
    bm25_k: Optional[int] = Field(default=None, gt=0, description="BM25의 후보자")
    fusion: Optional[FusionConfig] = None
    reranker: Optional[RerankerConfig] = None

    @model_validator(mode="after")
    def _mode_consistent(self) -> "RetrievalConfig":
        m = self.mode
        if m is RetrievalMode.VECTOR:
            if self.bm25_k or self.fusion or self.reranker:
                raise ValueError("벡터 모드는 bm25_k, fusion 또는 reranker를 사용하지 않음")
            if self.top_k > self.vector_k:
                raise ValueError("top_k는 vector_k를 초과할 수 없음")
            return self
        if not (self.bm25_k and self.fusion):
            raise ValueError(f"{m.value} 모드는 bm25_k 및 fusion이 필요함")
        if self.fusion.candidate_k > self.vector_k + self.bm25_k:
            raise ValueError("fusion.candidate_k는 vector_k + bm25_k를 초과할 수 없음")
        if m is RetrievalMode.HYBRID:
            if self.reranker:
                raise ValueError("하이브리드 모드는 reranker를 사용하지 않음 (config C)")
            if self.top_k > self.fusion.candidate_k:
                raise ValueError("top_k는 fusion.candidate_k를 초과할 수 없음")
        else:
            if not self.reranker:
                raise ValueError("hybrid_rerank 모드는 순위 재조정기 필요")
            if self.reranker.input_k > self.fusion.candidate_k:
                raise ValueError("reranker.input_k는 fusion.candidate_k를 초과할 수 없음")
            if self.top_k > self.reranker.input_k:
                raise ValueError("top_k는 reranker.input_k를 초과할 수 없음")
        return self


class GenerationConfig(_Strict):
    """A, B 및 C에 대해 동일해야 합니다."""

    model: str
    temperature: float = Field(default=0.0, ge=0)
    max_output_tokens: int = Field(gt=0)
    timeout_s: float = Field(gt=0)
    max_retries: int = Field(default=1, ge=0)


class PromptConfig(_Strict):
    """A, B 및 C에 대해 동일해야 합니다."""

    label: str = Field(description="인간 레이블, 예: 'v1'")
    template_path: str
    max_context_chunks: int = Field(gt=0)
    max_context_chars: int = Field(gt=0)


class EvidenceGateConfig(_Strict):
    """근거 부족 규칙, dev.json에서만 튜닝됨.
    `params`는 자유형식(예: 순위 재조정기 점수 임계값)이며 answer_config_version에 해시됩니다.
    """

    method: Literal["none", "score_threshold", "model_judgment", "both"] = "model_judgment"
    params: dict[str, Any] = Field(default_factory=dict)


class OptimizationKind(str, Enum):
    NONE = "none"
    CACHE = "cache"
    REWRITE = "rewrite"


class CacheConfig(_Strict):
    ttl_s: int = Field(gt=0)


class RewriteConfig(_Strict):
    model: str
    timeout_s: float = Field(gt=0)


class OptimizationConfig(_Strict):
    kind: OptimizationKind = OptimizationKind.NONE
    cache: Optional[CacheConfig] = None
    rewrite: Optional[RewriteConfig] = None

    @model_validator(mode="after")
    def _kind_consistent(self) -> "OptimizationConfig":
        if self.kind is OptimizationKind.CACHE and (not self.cache or self.rewrite):
            raise ValueError("kind 'cache'는 [optimization.cache]가 필요하고 재작성 테이블이 없음")
        if self.kind is OptimizationKind.REWRITE and (not self.rewrite or self.cache):
            raise ValueError("kind 'rewrite'는 [optimization.rewrite]가 필요하고 캐시 테이블이 없음")
        if self.kind is OptimizationKind.NONE and (self.cache or self.rewrite):
            raise ValueError("kind 'none'은 캐시 또는 재작성 테이블을 사용하지 않음")
        return self


class EvalConfig(_Strict):
    version: str = Field(description="Eval 세트 git 태그, 예: 'eval-v1.0'")


class AppConfig(_Strict):
    name: str = Field(description="'A', 'B', 'C', 또는 예: 'C+cache' / 'C+rewrite'")
    docs: DocsConfig
    index: IndexConfig
    retrieval: RetrievalConfig
    generation: GenerationConfig
    prompt: PromptConfig
    evidence_gate: EvidenceGateConfig = Field(default_factory=EvidenceGateConfig)
    optimization: OptimizationConfig = Field(default_factory=OptimizationConfig)
    eval: EvalConfig

    _repo_root: Path = PrivateAttr()
    _source: Path = PrivateAttr()

    @model_validator(mode="after")
    def _core_rules(self) -> "AppConfig":
        expected = {"A": RetrievalMode.VECTOR, "B": RetrievalMode.HYBRID,
                    "C": RetrievalMode.HYBRID_RERANK}
        if self.name in CORE_CONFIGS:
            if self.retrieval.mode is not expected[self.name]:
                raise ValueError(f"config {self.name}은(는) '{expected[self.name].value}' 모드를 사용해야 함")
            if self.optimization.kind is not OptimizationKind.NONE:
                raise ValueError("핵심 config A/B/C에서는 최적화가 꺼져야 함")
        elif self.optimization.kind is OptimizationKind.NONE:
            raise ValueError(f"config '{self.name}'은(는) A/B/C가 아니므로 최적화를 활성화해야 함")
        if self.prompt.max_context_chunks > self.retrieval.top_k:
            raise ValueError("prompt.max_context_chunks는 retrieval.top_k를 초과할 수 없음")
        return self

    @property
    def repo_root(self) -> Path:
        return self._repo_root

    def path(self, rel: str) -> Path:
        """구성에서 repo 상대 경로를 해결합니다."""
        return (self._repo_root / rel).resolve()

    def resolved(self) -> dict[str, Any]:
        """RunRecord.config에 대한 JSON 안전 dict로 완전히 해결된 구성."""
        return self.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _read_file(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix == ".toml":
        with path.open("rb") as f:
            return tomllib.load(f)
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError as e:
            raise ConfigError("YAML config는 PyYAML이 필요함; .toml을 사용하거나 pip install pyyaml") from e
        with path.open(encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    raise ConfigError(f"지원되지 않는 config 형식: {path.name}")


def _deep_merge(base: dict[str, Any], child: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in child.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _load_raw(path: Path, seen: tuple[Path, ...] = ()) -> dict[str, Any]:
    path = path.resolve()
    if path in seen:
        chain = " -> ".join(p.name for p in (*seen, path))
        raise ConfigError(f"순환 extends: {chain}")
    if not path.is_file():
        raise ConfigError(f"config 파일을 찾을 수 없음: {path}")
    data = _read_file(path)
    parent = data.pop("extends", None)
    if parent is None:
        return data
    return _deep_merge(_load_raw(path.parent / parent, (*seen, path)), data)


def load_config(path: str | Path, repo_root: str | Path | None = None) -> AppConfig:
    """하나의 config를 로드, 병합 및 검증합니다. repo_root는 기본값으로
    configs/ 디렉토리의 부모로 설정됩니다.
    """
    path = Path(path).resolve()
    root = Path(repo_root).resolve() if repo_root else path.parent.parent
    try:
        cfg = AppConfig.model_validate(_load_raw(path))
    except ConfigError:
        raise
    except Exception as e:  # pydantic ValidationError -> 호출자를 위한 하나의 오류 타입
        raise ConfigError(f"{path.name}: {e}") from e
    cfg._repo_root = root
    cfg._source = path
    return cfg


# ---------------------------------------------------------------------------
# Version strings
# ---------------------------------------------------------------------------


def _hash(obj: Any) -> str:
    """JSON 직렬화 가능한 데이터의 안정적인 짧은 해시 (키 순서 독립적)."""
    blob = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:HASH_LEN]


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()[:HASH_LEN]


def doc_version(cfg: AppConfig) -> str:
    """판 레이블, 플러스 원본 설명서 파일이 존재하면 컨텐츠 해시,
    따라서 다른 파일의 무음 재다운로드가 감지됩니다.
    """
    label = cfg.docs.doc_version
    if cfg.docs.source_path:
        src = cfg.path(cfg.docs.source_path)
        if src.is_file():
            return f"{label}+{_file_hash(src)}"
    return label


def index_version(cfg: AppConfig) -> str:
    """문서와 모든 청킹/인덱싱 설정에 따라 다릅니다.
    build_index.py는 이 동일한 문자열을 인덱스 매니페스트에 작성해야 합니다.
    청크 파일 내용 해시도 넣는다: 설정 변경 없이 재청킹·재변환만 해도 버전이 바뀌어
    이전 색인으로 만든 캐시 답변이 재사용되지 않는다.
    """
    chunks = cfg.path(CHUNKS_PATH)
    # 줄바꿈 정규화: Windows(CRLF) 체크아웃과 macOS(LF) 체크아웃에서 같은 버전이 나오게
    chunks_hash = (hashlib.sha256(chunks.read_bytes().replace(b"\r\n", b"\n")).hexdigest()[:HASH_LEN]
                   if chunks.is_file() else None)
    return "idx-" + _hash({"doc": doc_version(cfg), "index": cfg.index.model_dump(mode="json"),
                           "chunks": chunks_hash})


def prompt_version(cfg: AppConfig) -> str:
    """레이블 + 템플릿 파일의 해시, 따라서 레이블을 변경하지 않고
    템플릿을 편집하는 것도 감지됩니다.
    """
    tpl = cfg.path(cfg.prompt.template_path)
    if not tpl.is_file():
        raise ConfigError(f"prompt 템플릿을 찾을 수 없음: {tpl}")
    return f"prompt-{cfg.prompt.label}-{_file_hash(tpl)}"


def answer_config_version(cfg: AppConfig) -> str:
    return "ans-" + _hash({
        "generation": cfg.generation.model_dump(mode="json"),
        "context": {"max_context_chunks": cfg.prompt.max_context_chunks,
                    "max_context_chars": cfg.prompt.max_context_chars},
        "evidence_gate": cfg.evidence_gate.model_dump(mode="json"),
    })


def retrieval_config_version(cfg: AppConfig) -> str:
    """검색 설정 플러스 최적화, 재작성이 검색되는 내용을 변경하므로.
    """
    return "ret-" + _hash({
        "retrieval": cfg.retrieval.model_dump(mode="json"),
        "optimization": cfg.optimization.model_dump(mode="json"),
    })


def git_commit(repo_root: Path) -> Optional[str]:
    """현재 커밋 SHA, 커밋되지 않은 변경 사항이 있으면 '-dirty' 접미사.
    git checkout 외부에서는 None.
    """
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True,
                             text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=repo_root,
                               capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return f"{sha}-dirty" if dirty else sha


def build_versions(cfg: AppConfig) -> Versions:
    """RunRecord의 모든 버전 필드. 또한 캐시 키의 기초."""
    return Versions(
        doc_version=doc_version(cfg),
        index_version=index_version(cfg),
        embedding_model=cfg.index.embedding_model,
        generation_model=cfg.generation.model,
        reranker_model=cfg.retrieval.reranker.model if cfg.retrieval.reranker else None,
        prompt_version=prompt_version(cfg),
        answer_config_version=answer_config_version(cfg),
        retrieval_config_version=retrieval_config_version(cfg),
        eval_version=cfg.eval.version,
        code_commit=git_commit(cfg.repo_root),
    )


# ---------------------------------------------------------------------------
# Consistency checks
# ---------------------------------------------------------------------------


def check_index_manifest(cfg: AppConfig, manifest_name: str = "manifest.json") -> dict[str, Any]:
    """빌드된 인덱스가 이 구성과 일치하지 않으면 실패합니다 (예: B가 재청킹되었지만
    인덱스가 재구축되지 않음). 매니페스트를 반환합니다.
    """
    manifest_path = cfg.path(cfg.index.index_dir) / manifest_name
    if not manifest_path.is_file():
        raise ConfigError(f"인덱스 매니페스트를 찾을 수 없음: {manifest_path} (build_index.py 실행)")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = index_version(cfg)
    if manifest.get("index_version") != expected:
        raise ConfigError(
            f"오래된 인덱스: 매니페스트에 {manifest.get('index_version')!r}, "
            f"구성은 {expected!r}를 예상합니다. 인덱스를 다시 빌드하세요."
        )
    return manifest


def check_shared_settings(configs: list[AppConfig]) -> None:
    """A, B 및 C는 검색에서만 다릅니다. 동일한 문서, 인덱스,
    생성 모델 및 제한, 프롬프트 및 컨텍스트 제한, 그리고 평가 버전.
    근거 게이트는 다를 수 있습니다. 점수 임계값 규칙은 하나의 구성이만
    생성하는 점수에 따라 달라질 수 있기 때문입니다; 그렇다면 이유를 기록하세요.
    """
    shared = ("docs", "index", "generation", "prompt", "eval")
    names = [c.name for c in configs]
    if len(set(names)) != len(names):
        raise ConfigError(f"중복된 config 이름: {names}")
    ref = configs[0]
    for other in configs[1:]:
        for section in shared:
            a = getattr(ref, section).model_dump(mode="json")
            b = getattr(other, section).model_dump(mode="json")
            if a != b:
                raise ConfigError(
                    f"[{section}]은(는) {ref.name}과(와) {other.name} 사이에 다릅니다; "
                    f"비교된 config들 간에 동일해야 합니다"
                )
