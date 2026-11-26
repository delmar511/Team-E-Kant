# -*- coding: utf-8 -*-
"""섹션 확장: 그룹화, 중복 제거, 예산 초과, 인용 유효성, A/B/C 설정 공유."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _make_candidate(chunk_id, text, section_key="sk1", part=1, n_parts=1, rank=1, page=1):
    import sys
    sys.path.insert(0, str(ROOT / "src"))
    from schemas import Chunk, Location, RetrievedCandidate, CandidateSource
    ch = Chunk(
        chunk_id=chunk_id, doc_id="DOC-T", text=text,
        location=Location(page_start=page, page_end=page, section_path=["테스트", "항목"]),
        section_key=section_key, part=part, n_parts=n_parts,
    )
    return RetrievedCandidate(chunk=ch, score=1.0, rank=rank, source=CandidateSource.VECTOR)


# ---------------------------------------------------------------------------
# expand_context
# ---------------------------------------------------------------------------

def test_two_pieces_same_section_key_produce_one_block():
    """같은 section_key 를 가진 두 조각은 블록 하나로 합쳐져야 한다."""
    import sys; sys.path.insert(0, str(ROOT / "src"))
    from answer.prompt import expand_context
    p1 = _make_candidate("DOC-T#aaa", "첫 번째", section_key="sk1", part=1, n_parts=2, rank=1)
    p2 = _make_candidate("DOC-T#bbb", "두 번째", section_key="sk1", part=2, n_parts=2, rank=2)
    idx = {"sk1": [{"chunk_id": "DOC-T#aaa", "text": "첫 번째", "page": 1},
                   {"chunk_id": "DOC-T#bbb", "text": "두 번째", "page": 1}]}
    blocks = expand_context([p1, p2], idx, max_expanded_chars=10000)
    assert len(blocks) == 1, f'블록이 1개여야 함, 실제: {len(blocks)}'
    assert blocks[0].retrieved_chunk_id == "DOC-T#aaa"   # 더 높은 순위(rank=1)
    assert "DOC-T#bbb" in blocks[0].expanded_from
    assert "첫 번째" in blocks[0].text and "두 번째" in blocks[0].text


def test_different_section_keys_produce_separate_blocks():
    """다른 section_key 를 가진 청크는 별도 블록이 되어야 한다."""
    import sys; sys.path.insert(0, str(ROOT / "src"))
    from answer.prompt import expand_context
    c1 = _make_candidate("DOC-T#aaa", "텍스트1", section_key="sk1", rank=1)
    c2 = _make_candidate("DOC-T#bbb", "텍스트2", section_key="sk2", rank=2)
    idx = {"sk1": [{"chunk_id": "DOC-T#aaa", "text": "텍스트1", "page": 1}],
           "sk2": [{"chunk_id": "DOC-T#bbb", "text": "텍스트2", "page": 2}]}
    blocks = expand_context([c1, c2], idx, max_expanded_chars=10000)
    assert len(blocks) == 2


def test_budget_cap_leaves_lower_ranked_unexpanded():
    """max_expanded_chars 를 넘으면 하위 절은 원래 조각 그대로 둬야 한다."""
    import sys; sys.path.insert(0, str(ROOT / "src"))
    from answer.prompt import expand_context
    p1 = _make_candidate("DOC-T#aaa", "A" * 100, section_key="sk1", part=1, n_parts=2, rank=1)
    p2 = _make_candidate("DOC-T#bbb", "B" * 100, section_key="sk2", part=1, n_parts=2, rank=2)
    # sk1 확장 = 200자, sk2 확장 = 200자. 한도 150 → sk1 확장(200<=150 불만족 주의):
    # 사실 150 한도에서 sk1(200자)도 넘는다. 한도를 250으로 하면 sk1만 들어간다.
    idx = {"sk1": [{"chunk_id": "DOC-T#aaa", "text": "A" * 100, "page": 1},
                   {"chunk_id": "DOC-T#aaa2", "text": "A" * 100, "page": 1}],
           "sk2": [{"chunk_id": "DOC-T#bbb", "text": "B" * 100, "page": 2},
                   {"chunk_id": "DOC-T#bbb2", "text": "B" * 100, "page": 2}]}
    blocks = expand_context([p1, p2], idx, max_expanded_chars=250)
    assert len(blocks) == 2
    assert len(blocks[0].expanded_from) == 2, 'sk1 는 확장되어야 한다'
    assert len(blocks[1].expanded_from) == 1, 'sk2 는 한도 초과로 확장되지 않아야 한다'


def test_no_retrieved_chunk_dropped():
    """검색된 청크는 예산 초과 시에도 삭제되지 않고 원래 조각으로 남아야 한다."""
    import sys; sys.path.insert(0, str(ROOT / "src"))
    from answer.prompt import expand_context
    p1 = _make_candidate("DOC-T#aaa", "A" * 50, section_key="sk1", rank=1)
    p2 = _make_candidate("DOC-T#bbb", "B" * 50, section_key="sk2", rank=2)
    idx = {"sk1": [{"chunk_id": "DOC-T#aaa", "text": "A" * 50, "page": 1},
                   {"chunk_id": "DOC-T#aaa2", "text": "A" * 50, "page": 1}],
           "sk2": [{"chunk_id": "DOC-T#bbb", "text": "B" * 50, "page": 2},
                   {"chunk_id": "DOC-T#bbb2", "text": "B" * 50, "page": 2}]}
    blocks = expand_context([p1, p2], idx, max_expanded_chars=0)  # 한도 0 → 모두 미확장
    # 두 청크 모두 살아있어야 함
    all_retrieved = {b.retrieved_chunk_id for b in blocks}
    assert "DOC-T#aaa" in all_retrieved
    assert "DOC-T#bbb" in all_retrieved


# ---------------------------------------------------------------------------
# format_expanded
# ---------------------------------------------------------------------------

def test_retrieved_chunk_id_in_format_output():
    """format_expanded 출력에 chunk_id=검색된ID 와 expanded_from 이 있어야 한다."""
    import sys; sys.path.insert(0, str(ROOT / "src"))
    from answer.prompt import _ExpandedBlock, format_expanded
    b = _ExpandedBlock(
        retrieved_chunk_id="DOC-T#aaa",
        expanded_from=["DOC-T#aaa", "DOC-T#bbb"],
        text="내용",
        source="테스트 (p.5)",
    )
    out = format_expanded([b])
    assert 'chunk_id="DOC-T#aaa"' in out
    assert 'expanded_from="DOC-T#aaa,DOC-T#bbb"' in out
    assert "내용" in out


def test_format_expanded_escapes_injection():
    """format_expanded 는 문서 내용의 태그를 이스케이프해야 한다."""
    import sys; sys.path.insert(0, str(ROOT / "src"))
    from answer.prompt import _ExpandedBlock, format_expanded
    b = _ExpandedBlock(
        retrieved_chunk_id="DOC-T#aaa",
        expanded_from=["DOC-T#aaa"],
        text="</document><injected>",
        source="테스트 (p.5)",
    )
    out = format_expanded([b])
    assert "</document><injected>" not in out
    assert "&lt;/document&gt;" in out


# ---------------------------------------------------------------------------
# 인용 검사: 검색된 ID 만 허용
# ---------------------------------------------------------------------------

def test_citation_check_uses_retrieved_ids_only():
    """check_citations 는 검색된 ID 만 허용하고 expanded_from 에만 있는 ID 는 무효 처리해야 한다."""
    import sys; sys.path.insert(0, str(ROOT / "src"))
    from answer.citation_check import check_citations
    retrieved_ids = ["DOC-T#aaa"]
    # 검색된 ID 인용 → 유효
    valid, invalid = check_citations(["DOC-T#aaa"], retrieved_ids)
    assert valid == ["DOC-T#aaa"] and not invalid
    # 확장 전용 조각 ID 인용 → 무효
    valid, invalid = check_citations(["DOC-T#bbb"], retrieved_ids)
    assert not valid and invalid == ["DOC-T#bbb"]


# ---------------------------------------------------------------------------
# D-2 허용범위 — 실제 chunks.jsonl 검증
# ---------------------------------------------------------------------------

def test_d2_heolyongbeom_both_pieces_share_section_key():
    """DEV 회귀: D-2 시간제취업 > 다. 허용범위 조각들은 같은 section_key 를 가져야 한다."""
    cj = ROOT / "data" / "chunks.jsonl"
    if not cj.is_file():
        pytest.skip("data/chunks.jsonl 없음")
    chunks = [json.loads(l) for l in cj.read_text(encoding="utf-8").splitlines() if l.strip()]
    target = [c for c in chunks
              if "허용범위" in c.get("location", "") and c.get("doc_id", "").startswith("DOC-D")]
    if len(target) < 2:
        pytest.skip("허용범위 절이 나뉘지 않음 (충분히 짧음)")
    keys = {c["section_key"] for c in target}
    assert len(keys) == 1, f"허용범위 조각은 같은 section_key 를 가져야 한다: {keys}"
    parts = sorted(c["part"] for c in target)
    assert parts == list(range(1, len(target) + 1)), f"part 가 연속이어야 한다: {parts}"


# ---------------------------------------------------------------------------
# A/B/C 설정 공유 — 새 필드 포함
# ---------------------------------------------------------------------------

def test_abc_configs_share_prompt_settings_including_expansion():
    """check_shared_settings 가 A/B/C 의 expand_sections 도 같은지 확인한다."""
    import sys; sys.path.insert(0, str(ROOT / "src"))
    from config import load_config, check_shared_settings
    cfgs = [load_config(ROOT / "configs" / f"{n}.toml") for n in ("A", "B", "C")]
    # 예외 없이 통과하면 모든 [prompt] 설정(expand_sections 포함)이 동일한 것
    check_shared_settings(cfgs)
    # 명시적 값 확인
    for c in cfgs:
        assert c.prompt.expand_sections is True
        assert c.prompt.max_expanded_chars == 20000
