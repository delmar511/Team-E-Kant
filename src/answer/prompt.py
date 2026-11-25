"""모든 구성(A/B/C)에 공통인 프롬프트. 템플릿은 configs/base.toml 의 [prompt] template_path 파일이다.

- 컨텍스트 청크마다 chunk_id 와 원문 위치를 붙인다 (<document chunk_id="..." source="...">).
- 컨텍스트 수·길이 제한을 적용한다 (select_context, [prompt] max_context_chunks / max_context_chars).
- 검색된 텍스트는 지시가 아닌 데이터로 표시하고 이스케이프한다 (문서 속 프롬프트 인젝션 방지).
템플릿 파일을 고치면 config.prompt_version() 의 해시가 바뀌어 로그·캐시 키에 반영된다.
"""
import html
from functools import lru_cache
from pathlib import Path

from langchain_core.prompts import PromptTemplate

NO_EVIDENCE_MESSAGE = "제공된 문서에서 근거를 찾을 수 없습니다."
DEFAULT_TEMPLATE = Path(__file__).resolve().parent / "templates" / "answer_v1.txt"


@lru_cache(maxsize=8)
def load_template(path: str) -> PromptTemplate:
    return PromptTemplate.from_template(Path(path).read_text(encoding="utf-8"))


def select_context(candidates, max_chunks, max_chars):
    """검색 순위대로 청크를 넣되 개수·총 글자 수 상한을 지킨다. 1위 청크는 항상 포함."""
    out, used = [], 0
    for c in candidates[:max_chunks]:
        n = len(c.chunk.text)
        if out and used + n > max_chars:
            break
        out.append(c)
        used += n
    return out


def source_label(chunk) -> str:
    """사람이 원문을 찾을 수 있는 위치. 예: '유학(D-2) > 시간제취업 활동 허가 > 나. 대상 (p.38)'"""
    loc = chunk.location
    pages = f"p.{loc.page_start}" if loc.page_start == loc.page_end else f"p.{loc.page_start}-{loc.page_end}"
    path = " > ".join(loc.section_path)
    return f"{path} ({pages})" if path else pages


def _escape(s):
    # 문서 내용이 태그를 닫고 지시문처럼 보이지 않도록 <, >, &, " 를 이스케이프한다
    return html.escape(str(s or ""), quote=True)


def format_context(candidates):
    return "\n".join(
        f'<document chunk_id="{_escape(c.chunk.chunk_id)}" source="{_escape(source_label(c.chunk))}">\n'
        f"{_escape(c.chunk.text)}\n</document>"
        for c in candidates
    )


def build_prompt(question, candidates, template_path=DEFAULT_TEMPLATE):
    return load_template(str(template_path)).format(
        context=format_context(candidates), question=_escape(question), no_evidence=NO_EVIDENCE_MESSAGE)
