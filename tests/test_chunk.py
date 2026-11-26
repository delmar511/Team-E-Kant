# -*- coding: utf-8 -*-
"""src/ingest/chunk.py: 본문 없는 제목 접기(fold) / 버리기(drop), chunk_id 결정성, 쪽 번호."""
import json
from pathlib import Path

import pytest

from ingest import chunk

ROOT = Path(__file__).resolve().parents[1]
LONG = '이 문단은 스무 글자를 넘기는 충분히 긴 본문이다. 청크로 만들어져야 한다.'

FM = '---\ndoc_id: DOC-T\ntitle: 시험(T-1)\nsource: s\nversion: v\n---\n\n# 시험(T-1)\n\n<!-- page: 5 -->\n\n'


def write(tmp_path, body, name='DOC-T_시험.md'):
    p = tmp_path / name
    p.write_text(FM + body, encoding='utf-8', newline='\n')
    return p


# ── fold / drop ──────────────────────────────────────────────────────────────

def test_deterministic(tmp_path):
    p = write(tmp_path, f'## 가\n\n{LONG}\n\n### 1. 제목\n\n### 2. 제목\n')
    assert chunk.parse(p) == chunk.parse(p)


def test_consecutive_bodyless_siblings_fold_into_one_chunk(tmp_path):
    p = write(tmp_path, f'## 업무\n\n### 1. 첫째 항목\n\n### 2. 둘째 항목\n\n### 3. 셋째 항목\n\n{LONG}\n')
    rows = chunk.parse(p)
    fold = [r for r in rows if r['chunk_kind'] == 'fold']
    assert len(fold) == 1
    assert fold[0]['text'] == '1. 첫째 항목\n2. 둘째 항목'
    assert fold[0]['location'] == '시험(T-1) > 업무'          # 항목이 둘 이상이면 부모 경로
    assert fold[0]['page'] == 5
    body = [r for r in rows if r['chunk_kind'] == 'body']
    assert [r['location'] for r in body] == ['시험(T-1) > 업무 > 3. 셋째 항목']


def test_single_bodyless_item_uses_its_own_path(tmp_path):
    p = write(tmp_path, f'## 업무\n\n{LONG}\n\n### 1. 홀로 있는 항목\n')
    fold = [r for r in chunk.parse(p) if r['chunk_kind'] == 'fold']
    assert [r['location'] for r in fold] == ['시험(T-1) > 업무 > 1. 홀로 있는 항목']


def test_short_section_under_20_chars_is_kept_in_fold_mode_dropped_in_drop_mode(tmp_path):
    p = write(tmp_path, '## 업무\n\n2년\n\n## 다음\n\n' + LONG + '\n')
    fold = chunk.parse(p, bodyless='fold')
    drop = chunk.parse(p, bodyless='drop')
    assert any(r['chunk_kind'] == 'fold' and r['text'] == '업무\n2년' for r in fold)
    assert all('2년' not in r['text'] for r in drop)


def test_adding_bodyless_heading_keeps_existing_body_chunk_ids(tmp_path):
    base = f'## 업무\n\n{LONG}\n\n## 다음\n\n{LONG}2\n'
    extra = f'## 업무\n\n{LONG}\n\n### 1. 본문 없는 제목\n\n### 2. 또 다른 제목\n\n## 다음\n\n{LONG}2\n'
    a = [(r['chunk_id'], r['location']) for r in chunk.parse(write(tmp_path, base, 'DOC-T_a.md')) if r['chunk_kind'] == 'body']
    b = [(r['chunk_id'], r['location']) for r in chunk.parse(write(tmp_path, extra, 'DOC-T_b.md')) if r['chunk_kind'] == 'body']
    assert a == b
    assert any(r['chunk_kind'] == 'fold' for r in chunk.parse(write(tmp_path, extra, 'DOC-T_b.md')))


def test_heading_followed_by_child_heading_is_not_folded(tmp_path):
    p = write(tmp_path, f'## 업무\n\n### 1. 자식\n\n{LONG}\n')
    rows = chunk.parse(p)
    assert [r['chunk_kind'] for r in rows] == ['body']
    assert rows[0]['location'] == '시험(T-1) > 업무 > 1. 자식'     # 부모 제목은 자식 location 에 남는다


def test_toc_dotted_lines_and_deleted_items_are_not_folded(tmp_path):
    p = write(tmp_path, f'## 업무\n\n### 1. 개요 ··············· 3\n\n### 2. <삭제>\n\n### 3. 남는 항목\n\n{LONG}\n')
    rows = chunk.parse(p)
    assert not [r for r in rows if r['chunk_kind'] == 'fold']


def test_drop_mode_matches_chunks_before_the_fix():
    """chunks.jsonl 이 idx-v2(접기 없음) 일 때만 의미가 있다. 접기 이후 색인이면 건너뛴다."""
    cj = ROOT / 'data' / 'chunks.jsonl'
    old = [json.loads(l) for l in cj.read_text(encoding='utf-8').split('\n') if l.strip()]
    if any(c.get('chunk_kind') == 'fold' for c in old):
        pytest.skip('data/chunks.jsonl 은 이미 접기(idx-v3) 이후의 색인이다')
    corpus = ROOT / 'docs' / 'corpus'
    if (corpus / 'DOC-F5_영주.md').exists():
        pytest.skip('docs/corpus 는 이미 배치 수정(수정 12) 이후라 옛 색인과 비교할 수 없다')
    rows = []
    for f in sorted(corpus.glob('*.md')):
        rows += chunk.parse(f, bodyless='drop')
    assert [r['chunk_id'] for r in rows] == [c['chunk_id'] for c in old]
    assert all(r['chunk_kind'] == 'body' for r in rows)


# ── page 번호 ─────────────────────────────────────────────────────────────────

DOC_PAGE = """\
---
doc_id: DOC-T
title: 테스트
source: s
version: v
---

# 테스트

<!-- page: 10 -->
## 가. 첫 항목

첫 항목 본문은 10쪽에서 시작해서 다음 쪽으로 넘어간다
<!-- page: 11 -->
11쪽에 이어지는 본문
<!-- page: 12 -->
12쪽까지 이어지는 본문

## 나. 둘째 항목
<!-- page: 13 -->

둘째 항목 본문은 제목 다음 쪽 표시 뒤에 시작한다
"""


def test_page_is_start_page_of_section(tmp_path):
    p = tmp_path / 'doc.md'
    p.write_text(DOC_PAGE, encoding='utf-8', newline='\n')
    chunks = chunk.parse(p)
    assert [c['page'] for c in chunks] == [10, 13]


def test_split_parts_get_their_own_start_page(tmp_path):
    from ingest.chunk import MAXLEN
    line = '가' * 100
    body = '\n'.join([line] * 10) + '\n<!-- page: 21 -->\n' + '\n'.join([line] * 10)
    text = FM + f'## 긴 항목\n{body}\n'
    p = tmp_path / 'DOC-T_시험.md'
    p.write_text(text, encoding='utf-8', newline='\n')
    chunks = chunk.parse(p)
    assert len(chunks) >= 2 and all(len(c['text']) <= MAXLEN + len(line) + 1 for c in chunks)
    assert chunks[0]['page'] == 5
    assert chunks[-1]['page'] == 21


# ── section_key / part / n_parts ─────────────────────────────────────────────

def test_split_pieces_share_section_key(tmp_path):
    """MAXLEN 을 넘어 나뉜 조각들은 같은 section_key 를 가져야 한다."""
    from ingest.chunk import MAXLEN
    line = '가' * 100
    body = '\n'.join([line] * 15)   # > 1200 chars
    p = write(tmp_path, f'## 긴 항목\n{body}\n')
    rows = chunk.parse(p)
    assert len(rows) >= 2, '조각이 2개 이상이어야 한다'
    keys = [r['section_key'] for r in rows]
    assert len(set(keys)) == 1, f'분할 조각은 같은 section_key 를 가져야 한다: {set(keys)}'
    parts = [r['part'] for r in rows]
    assert parts == list(range(1, len(rows) + 1)), f'part 가 1-based 연속이어야 한다: {parts}'
    for r in rows:
        assert r['n_parts'] == len(rows), f'n_parts={r["n_parts"]} != {len(rows)}'


def test_unsplit_section_has_part_1_n_parts_1(tmp_path):
    """나뉘지 않은 절은 part=1, n_parts=1 이어야 한다."""
    p = write(tmp_path, f'## 항목\n\n{LONG}\n')
    rows = [r for r in chunk.parse(p) if r['chunk_kind'] == 'body']
    assert len(rows) == 1
    assert rows[0]['part'] == 1
    assert rows[0]['n_parts'] == 1


def test_repeated_heading_different_occurrence_different_section_key(tmp_path):
    """같은 경로가 문서 안에서 두 번 나오면 (예: F-4 반복) section_key 가 달라야 한다."""
    body = '이 문단은 스무 글자를 넘기는 충분히 긴 본문이다. 청크로 만들어져야 한다.'
    # 같은 제목이 두 번 — 다른 ## 아래에서
    p = write(tmp_path, f'## 같은 제목\n\n{body}\n\n## 다른 부모\n\n{body}2\n\n## 같은 제목\n\n{body}3\n')
    rows = chunk.parse(p)
    body_rows = [r for r in rows if r['chunk_kind'] == 'body']
    same_loc = [r for r in body_rows if '같은 제목' in r['location']]
    assert len(same_loc) == 2, '같은 제목 청크가 두 개여야 한다'
    assert same_loc[0]['section_key'] != same_loc[1]['section_key'], \
        '반복된 제목은 다른 section_key 를 가져야 한다'


def test_all_chunks_have_section_key(tmp_path):
    """parse() 결과 모든 청크에 section_key, part, n_parts 가 있어야 한다."""
    p = write(tmp_path, f'## 항목\n\n{LONG}\n\n### 1. 첫째 항목\n\n### 2. 둘째 항목\n')
    rows = chunk.parse(p)
    assert rows, '청크가 있어야 한다'
    for r in rows:
        assert 'section_key' in r and r['section_key'], f'section_key 누락: {r}'
        assert 'part' in r and r['part'] >= 1, f'part 누락: {r}'
        assert 'n_parts' in r and r['n_parts'] >= 1, f'n_parts 누락: {r}'
