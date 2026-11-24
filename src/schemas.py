"""지식 에이전트 프로젝트의 공유 데이터 계약.

모듈 간에 데이터를 전달하는 모든 모듈은 이 모델을 사용하므로,
수집, 검색, 답변 및 평가가 하나의 형식에 동의합니다. 필드 이름, 타입 또는
의미를 변경하는 경우 SCHEMA_VERSION을 증가시킵니다. 이를 통해 이전 실행 기록과
새 기록을 구별할 수 있습니다.

섹션:
    1. Enums            - 상태, 소스, 실행 종류, 채점 카테고리
    2. Chunk            - 수집 출력, 인덱스 입력
    3. RetrievedCandidate - retrieve(query, config) 출력
    4. AgentResponse    - agent.py 출력
    5. RunRecord        - results/의 행 하나, metrics.py에서 읽음
    6. EvalItem         - eval/dev.json 또는 eval/test.json의 질문 하나

Pydantic>=2 필요.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "0.1.0"


class _Strict(BaseModel):
    """기본 모델: 알 수 없는 필드는 오류이므로 스키마 드리프트가 명확하게 실패합니다."""

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# 1. Enums
# ---------------------------------------------------------------------------


class Status(str, Enum):
    """에이전트 결과. problem.md 섹션 9와 일치해야 합니다.

    오류 상태는 항상 실패로 채점되며 올바른 "근거 없음" 응답으로
    계산되지 않습니다.
    """

    ANSWERED = "answered"
    NO_EVIDENCE = "no_evidence"
    RETRIEVAL_ERROR = "retrieval_error"
    MODEL_ERROR = "model_error"
    TIMEOUT = "timeout"

    @property
    def is_error(self) -> bool:
        return self in {Status.RETRIEVAL_ERROR, Status.MODEL_ERROR, Status.TIMEOUT}


class CandidateSource(str, Enum):
    """어느 검색기가 후보자의 최종 점수를 생성했는지."""

    BM25 = "bm25"
    VECTOR = "vector"
    FUSED = "fused"  # RRF 후 (config B, config C 순위 재조정 전)


class RunKind(str, Enum):
    """모든 실행에 레이블을 지정하여 워밍업, 재시도 및 추가 실행이 핵심 실행과 혼합되지 않도록 합니다."""

    CORE = "core"        # 공식적인 60개 A/B/C x 20 테스트 실행
    BRANCH = "branch"    # 15개 캐시 또는 20개 재작성 최적화 실행
    WARMUP = "warmup"
    RETRY = "retry"      # retry_of를 설정해야 함; 원본을 절대 대체하지 않음
    EXTRA = "extra"      # 최종 결과를 본 후 실행된 모든 항목
    DEV = "dev"          # dev.json에서 튜닝 실행


class QuestionType(str, Enum):
    DIRECT = "direct"
    PARAPHRASE = "paraphrase"
    CONFUSABLE = "confusable"
    NO_ANSWER = "no_answer"


class Split(str, Enum):
    DEV = "dev"
    TEST = "test"


class FailureCategory(str, Enum):
    """주요 실패 카테고리, problem.md 섹션 11.4. 실패한 실행당 하나."""

    RETRIEVAL_MISS = "retrieval_miss"
    RANKING_FAILURE = "ranking_failure"
    GENERATION_ERROR = "generation_error"
    WRONG_CITATION = "wrong_citation"
    NO_ANSWER_FAILURE = "no_answer_failure"
    SYSTEM_ERROR = "system_error"


class AnalysisTag(str, Enum):
    """보조 태그, problem.md 섹션 11.4. 실행당 임의의 개수."""

    VISA_CONFUSION = "visa_confusion"                # 비자 혼동
    PARTIAL_MULTI_EVIDENCE = "partial_multi_evidence"  # 부분적 다중 근거 회수
    MISSED_EXCEPTION = "missed_exception"            # 놓친 예외 조항
    OVER_REFUSAL = "over_refusal"                    # 과도한 거절


class ScorerKind(str, Enum):
    """LLM-judge 점수는 별도로 저장되며 절대 대상을 결정하지 않습니다."""

    HUMAN = "human"
    LLM_JUDGE = "llm_judge"


# ---------------------------------------------------------------------------
# 2. Chunk (ingest/chunker.py)
# ---------------------------------------------------------------------------


class Location(_Strict):
    """사람이 원본 설명서에서 청크를 찾을 수 있는 위치."""

    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    section_path: list[str] = Field(
        default_factory=list,
        description="제목 경로, 가장 바깥쪽부터, 예: ['D-2 유학', '체류기간 연장허가', '제출서류']",
    )

    @model_validator(mode="after")
    def _pages_ordered(self) -> "Location":
        if self.page_end < self.page_start:
            raise ValueError("page_end must be >= page_start")
        return self

    def label(self) -> str:
        """인용 및 평가 근거에 대한 인간이 읽을 수 있는 위치."""
        pages = (
            f"p.{self.page_start}"
            if self.page_start == self.page_end
            else f"p.{self.page_start}-{self.page_end}"
        )
        return f"{pages}, {' > '.join(self.section_path)}" if self.section_path else pages


class Chunk(_Strict):
    chunk_id: str = Field(
        min_length=1,
        description="결정적: 동일한 doc/설정은 재구성 시 동일한 ID를 제공해야 함",
    )
    doc_id: str = Field(min_length=1, description="docs/documents.csv의 장 수준 doc ID")
    text: str = Field(min_length=1)
    location: Location
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="자유형식, 예: 청크에서 발견된 비자 코드, 청크 인덱스, 문자 오프셋",
    )


# ---------------------------------------------------------------------------
# 3. RetrievedCandidate (retrieval/pipeline.py -> retrieve(query, config))
# ---------------------------------------------------------------------------


class RetrievedCandidate(_Strict):
    """retrieve()에서 반환된 목록의 한 항목. 목록은 `rank`(1 = 최고)로 정렬되며
    Hit@5가 채점되는 최종 순서입니다.
    """

    chunk: Chunk
    score: float = Field(description="이 구성의 순서에서 최종 점수")
    rank: int = Field(ge=1, description="에이전트에 반환된 최종 1-기반 순위")
    source: CandidateSource
    rank_before_rerank: Optional[int] = Field(
        default=None, ge=1, description="순위 재조정 전 융합 순위; config C만 해당"
    )
    rank_after_rerank: Optional[int] = Field(
        default=None, ge=1, description="순위 재조정 후 순위; config C만 해당(rank과 동일)"
    )
    component_scores: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "기록된 단계별 점수, 예: {'bm25': 12.3, 'vector': 0.81, 'rrf': 0.032, "
            "'rerank': 4.1}. 로깅 전용: 원본 BM25 및 벡터 점수는 "
            "다른 척도이며 절대 합산되지 않습니다."
        ),
    )

    @property
    def chunk_id(self) -> str:
        return self.chunk.chunk_id

    @model_validator(mode="after")
    def _rerank_ranks_paired(self) -> "RetrievedCandidate":
        if (self.rank_before_rerank is None) != (self.rank_after_rerank is None):
            raise ValueError("rank_before_rerank and rank_after_rerank must be set together")
        if self.rank_after_rerank is not None and self.rank_after_rerank != self.rank:
            raise ValueError("rank_after_rerank must equal rank")
        return self


# ---------------------------------------------------------------------------
# 4. AgentResponse (agent.py)
# ---------------------------------------------------------------------------


class LatencyBreakdown(_Strict):
    """단계별 밀리초. 실행되지 않은 단계는 None으로 유지됩니다."""

    cache_lookup_ms: Optional[float] = Field(default=None, ge=0)
    rewrite_ms: Optional[float] = Field(default=None, ge=0)
    retrieval_ms: Optional[float] = Field(
        default=None, ge=0, description="BM25 + 벡터 + 융합"
    )
    rerank_ms: Optional[float] = Field(default=None, ge=0)
    generation_ms: Optional[float] = Field(default=None, ge=0)
    total_ms: float = Field(ge=0, description="벽시계, 질문 입력에서 응답 출력까지")


class Usage(_Strict):
    """비용 입력, problem.md 섹션 11.1."""

    model_calls: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class AgentResponse(_Strict):
    status: Status
    answer: Optional[str] = Field(
        default=None,
        description="'answered'에 대한 답변 텍스트, 'no_evidence'에 대한 근거 부족 메시지, "
        "오류 상태에 대해 None",
    )
    cited_chunk_ids: list[str] = Field(default_factory=list)
    invalid_citation_ids: list[str] = Field(
        default_factory=list,
        description="검색된 세트에 없는 인용 ID, citation_check.py에 의해 표시됨",
    )
    error_message: Optional[str] = None
    latency: LatencyBreakdown
    usage: Usage = Field(default_factory=Usage)
    rewritten_query: Optional[str] = Field(
        default=None, description="쿼리 재작성이 실행되었을 때만 설정됨"
    )
    cache_hit: Optional[bool] = Field(
        default=None, description="캐시가 활성화되었을 때만 설정됨"
    )

    @model_validator(mode="after")
    def _consistent_with_status(self) -> "AgentResponse":
        if self.status is Status.ANSWERED:
            if not self.answer or not self.answer.strip():
                raise ValueError("'answered' requires a non-empty answer")
        elif self.status.is_error:
            if self.answer is not None or self.cited_chunk_ids:
                raise ValueError(f"'{self.status.value}' must have no answer or citations")
            if not self.error_message:
                raise ValueError(f"'{self.status.value}' requires error_message")
        # no_evidence는 청크를 인용할 수 있음: 부분 답변은 설명서에 있는 내용을 다루고
        # 나머지는 없다고 명시합니다 (problem.md 11.3, 규칙 5).
        return self


# ---------------------------------------------------------------------------
# 5. RunRecord (written by experiments/run_experiment.py, read by metrics.py)
# ---------------------------------------------------------------------------


class Versions(_Strict):
    """정확히 어떤 것이 실행을 생성했는지 말하는 데 필요한 모든 것.
    config.py에 의해 생성됨; 또한 모든 캐시 키의 기초.
    """

    schema_version: str = SCHEMA_VERSION
    doc_version: str = Field(description="설명서 판, 예: 'MAN-STAY-YYMMDD'")
    index_version: str
    embedding_model: str
    generation_model: str
    reranker_model: Optional[str] = None
    prompt_version: str = Field(description="템플릿 레이블 + 템플릿 파일의 해시")
    answer_config_version: str = Field(
        description="생성 매개변수, 컨텍스트 제한 및 근거 게이트 규칙"
    )
    retrieval_config_version: str
    eval_version: str = Field(description="Eval 세트 git 태그, 예: 'eval-v1.0'")
    code_commit: Optional[str] = Field(default=None, description="실행의 git SHA")


class Score(_Strict):
    """수동 점수, problem.md 섹션 11.3. Hit@5는 여기에 저장되지 않습니다:
    metrics.py가 후보자로부터 계산하므로 드리프트될 수 없습니다.
    질문 유형에 적용되지 않는 메트릭 필드는 None으로 유지됩니다.
    """

    scorer_kind: ScorerKind = ScorerKind.HUMAN
    scorer: str
    reviewer: Optional[str] = None
    answer_correct: Optional[bool] = Field(default=None, description="답변 가능한 항목만")
    citation_valid: Optional[bool] = Field(default=None, description="답변 가능한 항목만")
    no_answer_correct: Optional[bool] = Field(default=None, description="no_answer 항목만")
    failure_category: Optional[FailureCategory] = None
    analysis_tags: list[AnalysisTag] = Field(default_factory=list)
    rationale: str = Field(min_length=1)
    scored_at: datetime

    @model_validator(mode="after")
    def _reviewer_differs(self) -> "Score":
        if self.reviewer is not None and self.reviewer == self.scorer:
            raise ValueError("reviewer must differ from scorer")
        return self


class RunRecord(_Strict):
    run_id: str = Field(min_length=1)
    run_kind: RunKind
    retry_of: Optional[str] = Field(default=None, description="원본 실행의 run_id")
    question_id: str
    split: Split
    question: str = Field(description="전송된 원래 질문 텍스트")
    config_name: str = Field(description="예: 'A', 'B', 'C', 'C+rewrite', 'C+cache'")
    config: dict[str, Any] = Field(description="이 실행에 사용된 완전한 해결된 구성")
    versions: Versions
    candidates: list[RetrievedCandidate] = Field(
        default_factory=list, description="retrieval_error에서 비어 있음"
    )
    response: AgentResponse
    started_at: datetime
    finished_at: datetime
    scores: list[Score] = Field(
        default_factory=list,
        description="인간 점수 플러스 모든 LLM-judge 점수, 별도 항목으로 유지됨",
    )

    @model_validator(mode="after")
    def _checks(self) -> "RunRecord":
        if self.run_kind is RunKind.RETRY and not self.retry_of:
            raise ValueError("retry runs must set retry_of")
        if self.finished_at < self.started_at:
            raise ValueError("finished_at must be >= started_at")
        ranks = [c.rank for c in self.candidates]
        if ranks != sorted(ranks) or len(set(ranks)) != len(ranks):
            raise ValueError("candidates must be sorted by unique rank")
        return self

    def top_k_chunk_ids(self, k: int = 5) -> list[str]:
        """최종 상위 k 청크 ID, Hit@k에 사용됨."""
        return [c.chunk_id for c in self.candidates[:k]]


# ---------------------------------------------------------------------------
# 6. EvalItem (eval/dev.json, eval/test.json; see eval README section 2)
# ---------------------------------------------------------------------------


class Evidence(_Strict):
    doc_id: str = Field(min_length=1)
    location: str = Field(min_length=1)
    excerpt: str = Field(min_length=1)
    chunk_id: Optional[str] = Field(default=None, description="청킹이 완료될 때까지 None")
    required: bool


class EvalItem(_Strict):
    id: str = Field(pattern=r"^(DEV|TEST)-\d{3}$")
    split: Split
    type: QuestionType
    visa: list[str] = Field(min_length=1)
    question: str = Field(min_length=1)
    expected_facts: list[str]
    evidence: list[Evidence]
    no_answer_reason: Optional[str]
    verified_by: str
    verified_at: str
    reviewed_by: str
    reviewed_at: str

    @model_validator(mode="after")
    def _consistent(self) -> "EvalItem":
        if not self.id.startswith(self.split.value.upper() + "-"):
            raise ValueError("id prefix must match split")
        if self.type is QuestionType.NO_ANSWER:
            if self.expected_facts or self.evidence:
                raise ValueError("no_answer items must have empty expected_facts and evidence")
            if not self.no_answer_reason:
                raise ValueError("no_answer items need no_answer_reason")
        elif self.no_answer_reason is not None:
            raise ValueError("answerable items must have no_answer_reason = null")
        if self.verified_by and self.verified_by == self.reviewed_by:
            raise ValueError("reviewed_by must differ from verified_by")
        return self

    @property
    def is_answerable(self) -> bool:
        return self.type is not QuestionType.NO_ANSWER

    def is_complete(self) -> bool:
        """항목이 고정될 준비가 되었을 때 True: 사실, 청크 ID가 있는 근거,
        및 두 가지 검증 단계가 작성됨. validate_eval.py는 고정 시간에
        이를 강제합니다; 초안은 불완전할 수 있습니다.
        """
        filled = all([self.verified_by, self.verified_at, self.reviewed_by, self.reviewed_at])
        if not self.is_answerable:
            return filled
        return (
            filled
            and bool(self.expected_facts)
            and bool(self.evidence)
            and all(e.chunk_id for e in self.evidence)
            and any(e.required for e in self.evidence)
        )
