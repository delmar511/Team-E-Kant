"""모든 구성(A/B/C)에 공통인 프롬프트. 템플릿은 configs/base.toml 의 [prompt] template_path 파일이다.

- 컨텍스트 청크마다 chunk_id 와 원문 위치를 붙인다 (<document chunk_id="..." source="...">).
- 컨텍스트 수·길이 제한을 적용한다 (select_context, [prompt] max_context_chunks / max_context_chars).
- 검색된 텍스트는 지시가 아닌 데이터로 표시하고 이스케이프한다 (문서 속 프롬프트 인젝션 방지).
- expand_sections=true 일 때: 선택된 청크를 해당 절 전체로 대체 (expand_context, format_expanded).
  chunk_id 속성은 검색된 조각 ID, expanded_from 속성이 실제 포함된 조각 목록.
  인용 검사는 검색된 ID만 허용하는 기존 규칙 그대로.
템플릿 파일을 고치면 config.prompt_version() 의 해시가 바뀌어 로그·캐시 키에 반영된다.
"""
import html
from dataclasses import dataclass, field
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


# ---------------------------------------------------------------------------
# 섹션 확장 (expand_sections = true)
# ---------------------------------------------------------------------------


@dataclass
class _ExpandedBlock:
    """프롬프트에 삽입할 하나의 절 블록."""
    retrieved_chunk_id: str           # 검색된 조각 ID (인용 검사 대상)
    expanded_from: list = field(default_factory=list)  # 실제 포함된 조각 ID 목록 (순서 유지)
    text: str = ""                    # 절 전체 텍스트 (조각 연결)
    source: str = ""                  # 사람이 읽을 수 있는 위치 (페이지 범위 포함)


def expand_context(candidates, section_index, max_expanded_chars):
    """선택된 청크를 절 전체로 확장한다.

    - 같은 section_key 를 가진 청크가 여럿 선택됐으면 가장 순위가 높은 것의 ID 를 대표 ID 로 쓴다.
    - 순위 순서대로 확장을 시도; 한도(max_expanded_chars)를 넘으면 하위 절은 원래 조각 그대로 둔다.
    - 검색된 청크는 절대 삭제하지 않는다.

    반환: list[_ExpandedBlock] — 각 절이 하나의 블록.
    인용 검사: retrieved_chunk_id 만 context_ids 에 포함되므로 기존 check_citations 규칙이 그대로 작동.
    """
    # section_key -> (rank, candidate): 각 절의 최고 순위 후보
    seen_sk: dict = {}
    for c in candidates:
        sk = c.chunk.section_key or c.chunk.chunk_id  # section_key 없으면 자신 ID 를 키로
        if sk not in seen_sk or c.rank < seen_sk[sk][0]:
            seen_sk[sk] = (c.rank, c)

    ordered = sorted(seen_sk.values(), key=lambda x: x[0])

    total_chars = 0
    blocks = []
    for _, candidate in ordered:
        sk = candidate.chunk.section_key
        pieces = section_index.get(sk, []) if sk else []

        if len(pieces) > 1:
            expanded_text = "\n".join(p["text"] for p in pieces)
            if total_chars + len(expanded_text) <= max_expanded_chars:
                pages = [p.get("page", candidate.chunk.location.page_start) for p in pieces]
                page_start, page_end = min(pages), max(pages)
                path = " > ".join(candidate.chunk.location.section_path)
                pages_label = (f"p.{page_start}" if page_start == page_end
                               else f"p.{page_start}-{page_end}")
                src = f"{path} ({pages_label})" if path else pages_label
                blocks.append(_ExpandedBlock(
                    retrieved_chunk_id=candidate.chunk.chunk_id,
                    expanded_from=[p["chunk_id"] for p in pieces],
                    text=expanded_text,
                    source=src,
                ))
                total_chars += len(expanded_text)
                continue

        # 확장 불가(조각 하나이거나 한도 초과): 원래 조각 그대로
        blocks.append(_ExpandedBlock(
            retrieved_chunk_id=candidate.chunk.chunk_id,
            expanded_from=[candidate.chunk.chunk_id],
            text=candidate.chunk.text,
            source=source_label(candidate.chunk),
        ))
        total_chars += len(candidate.chunk.text)

    return blocks


def format_expanded(blocks):
    """_ExpandedBlock 목록 -> 프롬프트 삽입 문자열.

    <document chunk_id="검색된_ID" expanded_from="id1,id2,..." source="위치 (p.N)">
    본문
    </document>
    chunk_id 는 검색된 ID 이므로 모델이 인용하면 check_citations 가 유효로 판정한다.
    expanded_from 은 실제 포함된 조각을 기록해 trace 에서 추적할 수 있게 한다.
    """
    return "\n".join(
        f'<document chunk_id="{_escape(b.retrieved_chunk_id)}" '
        f'expanded_from="{_escape(",".join(b.expanded_from))}" '
        f'source="{_escape(b.source)}">\n'
        f'{_escape(b.text)}\n</document>'
        for b in blocks
    )


def build_prompt_expanded(question, blocks, template_path=DEFAULT_TEMPLATE):
    return load_template(str(template_path)).format(
        context=format_expanded(blocks), question=_escape(question), no_evidence=NO_EVIDENCE_MESSAGE)
