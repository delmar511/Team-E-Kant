"""구어체 질문 -> 매뉴얼 용어 검색 질의 (configs/C_rewrite.toml).

- llm_fn 없음: 용어 사전 치환 (무료, 개발용)
- llm_fn 있음: LLM 리라이트. 입력은 원질문뿐이며 정답·근거(expected_facts, evidence)는 절대 넣지 않는다.
- 결과가 비정상이면 예외를 던지고, agent 가 원질문으로 fallback 한다.
"""
from langchain_core.prompts import PromptTemplate

from answer.generator import as_reply

REWRITE_PROMPT_VERSION = "rewrite_v2"

# 민원 현장 표현 -> 매뉴얼 용어 (problem.md 4절 3번 '표현 불일치')
TERMS = {
    "아르바이트": "시간제취업",
    "알바": "시간제취업",
    "어학당": "어학연수(D-4)",
    "비자 연장": "체류기간 연장허가",
    "비자 바꿔": "체류자격 변경허가",
}

REWRITE_PROMPT = PromptTemplate.from_template(
    "다음 질문을 「체류민원 자격별 안내 매뉴얼」 검색에 적합한 검색 질의 한 줄로 바꾸세요.\n"
    "- 질문의 의도와 조건(체류자격, 세부약호, 업무 종류)을 그대로 유지하고, 새로운 조건이나 답을 추가하지 마세요.\n"
    "- 구어체는 매뉴얼 용어로 바꾸세요 (예: 알바 -> 시간제취업, 비자 연장 -> 체류기간 연장허가).\n"
    "- 설명 없이 검색 질의만 출력하세요.\n\n"
    "질문: {question}\n검색 질의:"
)


def build_rewrite_prompt(query: str) -> str:
    return REWRITE_PROMPT.format(question=query)


def rewrite_query(query: str, llm_fn=None, usage=None) -> str:
    if llm_fn is None:
        out = query
        for k, v in TERMS.items():
            out = out.replace(k, v)
        return out
    reply = as_reply(llm_fn(build_rewrite_prompt(query)))
    if usage is not None:
        usage.add(reply)
    lines = [ln.strip() for ln in reply.text.splitlines() if ln.strip()]
    out = lines[0] if lines else ""
    if not out or len(out) > max(200, 3 * len(query)):
        raise ValueError(f"리라이트 결과 비정상: {reply.text[:80]!r}")
    return out
