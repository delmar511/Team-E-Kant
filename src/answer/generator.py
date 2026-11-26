"""답변 생성: 구조화 출력(답변 + 인용 chunk_id + 근거 부족 여부)으로 LLM 호출, 형식 검증, 재시도.

llm_fn(prompt) -> str 또는 LLMReply 를 주입받는다.
- dummy_llm: 무료 개발용 (API 호출 없음)
- ClaudeLLM: LangChain ChatAnthropic. 모델·토큰 상한·timeout·재시도는 configs 의 [generation] 에서 온다.

재시도는 두 층이다.
- API 오류·timeout: ChatAnthropic(max_retries=[generation] max_retries) 이 재시도. 끝내 실패하면 예외
  -> agent 가 model_error / timeout 으로 기록
- 형식 오류(JSON 아님, 인용 누락 등): 오류 내용을 알려주고 FORMAT_RETRIES 번 다시 요청. 끝내 실패하면 OutputFormatError

Claude Opus 5.5 는 temperature 를 보내면 400 이다. [generation] temperature 는 API 에 넘기지 않는다.
사고 깊이는 effort 로 정한다 (.env 의 LLM_EFFORT, 기본 medium). config 에 effort 칸이 생기면 그쪽으로 옮긴다.
"""
import json
import os
import re
from dataclasses import dataclass

from pydantic import BaseModel, Field, ValidationError

from answer.citation_check import extract_citations
from answer.prompt import NO_EVIDENCE_MESSAGE

FORMAT_RETRIES = 1

# 거절(refusal) 시 서버가 다른 모델로 자동 재시도하는 기능(server-side fallback)을 지원하는 모델
_FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-1", "claude-fable-5-2"}


class AnswerOutput(BaseModel):
    answer: str
    cited_chunk_ids: list[str] = Field(default_factory=list)
    insufficient_evidence: bool = False


ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "cited_chunk_ids": {"type": "array", "items": {"type": "string"}},
        "insufficient_evidence": {"type": "boolean"},
    },
    "required": ["answer", "cited_chunk_ids", "insufficient_evidence"],
    "additionalProperties": False,
}


class OutputFormatError(ValueError):
    """재시도 후에도 모델 출력이 형식을 지키지 않음 (agent 에서 model_error)."""


@dataclass
class LLMReply:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


def as_reply(x) -> LLMReply:
    return x if isinstance(x, LLMReply) else LLMReply(str(x or ""))


@dataclass
class CallUsage:
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, reply: LLMReply):
        self.model_calls += 1
        self.input_tokens += reply.input_tokens
        self.output_tokens += reply.output_tokens


def parse_output(raw: str) -> AnswerOutput:
    text = (raw or "").strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, flags=re.S)
    if fence:
        text = fence.group(1)
    try:
        out = AnswerOutput.model_validate(json.loads(text))
    except (json.JSONDecodeError, ValidationError) as e:
        raise OutputFormatError(f"JSON 형식 오류: {e}") from e
    if not out.answer.strip():
        raise OutputFormatError("answer 가 비어 있음")
    inline = extract_citations(out.answer)
    if not out.insufficient_evidence and not inline:
        raise OutputFormatError("근거가 있다고 했지만 답변에 [chunk_id] 인라인 인용이 없음")
    out.cited_chunk_ids = list(dict.fromkeys(inline + out.cited_chunk_ids))  # 순서 유지, 중복 제거
    return out


def generate(prompt, llm_fn, usage: CallUsage, format_retries=FORMAT_RETRIES) -> AnswerOutput:
    last = None
    for _ in range(format_retries + 1):
        reply = as_reply(llm_fn(prompt if last is None else
                                f"{prompt}\n\n이전 출력이 형식을 지키지 않았습니다 ({last}). "
                                "지정한 JSON 객체 하나만 다시 출력하세요."))
        usage.add(reply)
        try:
            return parse_output(reply.text)
        except OutputFormatError as e:
            last = e
    raise OutputFormatError(f"{format_retries + 1}회 시도 후에도 형식 오류: {last}")


# ---------------- LLM 함수 ----------------

def dummy_llm(prompt: str) -> str:
    """개발용: 첫 청크를 인용하는 고정 JSON 답변. API 호출·비용 없음."""
    ids = re.findall(r'<document chunk_id="([^"]+)"', prompt)
    if not ids:
        return json.dumps({"answer": NO_EVIDENCE_MESSAGE, "cited_chunk_ids": [], "insufficient_evidence": True},
                          ensure_ascii=False)
    return json.dumps({"answer": f"문서에 따르면 해당 내용이 있습니다. [{ids[0]}]", "cited_chunk_ids": [ids[0]],
                       "insufficient_evidence": False}, ensure_ascii=False)


dummy_llm.model_id = "dummy"


class ClaudeLLM:
    """LangChain ChatAnthropic 호출 (키: .env 의 ANTHROPIC_API_KEY). 모델은 처음 호출할 때 만든다."""

    def __init__(self, model, max_tokens=16000, timeout_s=60.0, max_retries=2, effort=None, structured=True):
        self.model = model
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.effort = effort or os.getenv("LLM_EFFORT", "medium")  # low | medium | high | xhigh | max
        self.structured = structured
        self._chat = None

    @property
    def model_id(self):
        return f"{self.model}@{self.effort}"

    def _get_chat(self):
        if self._chat is None:
            from langchain_anthropic import ChatAnthropic

            extra = {}
            if self.model in _FALLBACK_MODELS:
                extra = {"betas": ["server-side-fallback-2026-07-01"], "model_kwargs": {"fallbacks": "default"}}
            self._chat = ChatAnthropic(
                model=self.model,
                max_tokens=self.max_tokens,
                default_request_timeout=self.timeout_s,  # 초과 시 APITimeoutError -> agent 가 status=timeout
                max_retries=self.max_retries,
                output_config={"effort": self.effort},
                **extra,
            )
        return self._chat

    def __call__(self, prompt: str) -> LLMReply:
        kwargs = {}
        if self.structured:  # effort 설정과 합쳐서 전송됨
            kwargs["output_config"] = {"effort": self.effort,
                                       "format": {"type": "json_schema", "schema": ANSWER_SCHEMA}}
        msg = self._get_chat().invoke(prompt, **kwargs)
        stop = msg.response_metadata.get("stop_reason")
        if stop == "refusal":
            category = (msg.response_metadata.get("stop_details") or {}).get("category")
            raise RuntimeError(f"모델이 답변을 거절함 (category={category})")
        if stop == "max_tokens":
            raise RuntimeError("max_tokens 도달로 답변이 잘림")
        u = msg.usage_metadata or {}
        return LLMReply(msg.text.strip(), int(u.get("input_tokens", 0)), int(u.get("output_tokens", 0)))


class OpenAILLM:
    """OpenAI Chat Completions 호출 (키: .env 의 OPENAI_API_KEY). ClaudeLLM 과 같은 구조화 출력(ANSWER_SCHEMA).

    키는 .env 값을 먼저 쓴다. 시스템 환경변수에 오래된 키가 남아 있으면 load_dotenv 가 덮어쓰지 않기 때문.
    temperature 는 보내지 않는다 (추론 모델은 거부). 사고 깊이는 reasoning_effort (.env 의 LLM_EFFORT).
    """

    def __init__(self, model, max_tokens=16000, timeout_s=60.0, max_retries=2, effort=None, structured=True):
        self.model = model
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.effort = effort or os.getenv("LLM_EFFORT", "medium")
        self.structured = structured
        self._client = None

    @property
    def model_id(self):
        return f"{self.model}@{self.effort}"

    def _get_client(self):
        if self._client is None:
            from dotenv import dotenv_values
            from pathlib import Path

            from openai import OpenAI

            root = Path(__file__).resolve().parents[2]  # src/answer/generator.py -> 저장소 루트
            key = (dotenv_values(root / ".env").get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
            self._client = OpenAI(api_key=key, timeout=self.timeout_s, max_retries=self.max_retries)
        return self._client

    def __call__(self, prompt: str) -> LLMReply:
        kwargs = {}
        if self.structured:
            kwargs["response_format"] = {"type": "json_schema",
                                         "json_schema": {"name": "answer", "schema": ANSWER_SCHEMA, "strict": True}}
        r = self._get_client().chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=self.max_tokens,
            reasoning_effort=self.effort,
            **kwargs,
        )
        choice = r.choices[0]
        if getattr(choice.message, "refusal", None):
            raise RuntimeError(f"모델이 답변을 거절함 ({choice.message.refusal})")
        if choice.finish_reason == "length":
            raise RuntimeError("max_completion_tokens 도달로 답변이 잘림")
        u = r.usage
        return LLMReply((choice.message.content or "").strip(),
                        int(getattr(u, "prompt_tokens", 0) or 0), int(getattr(u, "completion_tokens", 0) or 0))


def make_answer_llm(cfg, provider="claude", model=None):
    """provider='openai' 이면 model(없으면 .env 의 OPENAI_MODEL)로 생성. 나머지 설정은 [generation] 그대로."""
    g = cfg.generation
    if provider == "openai":
        return OpenAILLM(model or os.getenv("OPENAI_MODEL", "gpt-6-luna"), max_tokens=g.max_output_tokens,
                         timeout_s=g.timeout_s, max_retries=g.max_retries)
    return ClaudeLLM(g.model, max_tokens=g.max_output_tokens, timeout_s=g.timeout_s, max_retries=g.max_retries)


def make_rewrite_llm(cfg) -> ClaudeLLM:
    r = cfg.optimization.rewrite
    return ClaudeLLM(r.model, max_tokens=2000, timeout_s=r.timeout_s, max_retries=1, effort="low", structured=False)
