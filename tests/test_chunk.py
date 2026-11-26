# -*- coding: utf-8 -*-
<<<<<<< HEAD
"""청크의 page 는 본문이 시작하는 쪽이어야 한다 (구간이 끝나는 쪽이 아니라)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "ingest"))
from chunk import MAXLEN, parse  # noqa: E402

DOC = """---
doc_id: DOC-T
title: 테스트
---
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


def _parse(tmp_path, text):
    p = tmp_path / "doc.md"
    p.write_text(text, encoding="utf-8")
    return parse(str(p))


def test_page_is_start_page_of_section(tmp_path):
    chunks = _parse(tmp_path, DOC)
    assert [c["page"] for c in chunks] == [10, 13]


def test_split_parts_get_their_own_start_page(tmp_path):
    line = "가" * 100
    body = "\n".join([line] * 10) + "\n<!-- page: 21 -->\n" + "\n".join([line] * 10)
    text = f"---\ndoc_id: DOC-T\ntitle: t\n---\n<!-- page: 20 -->\n## 긴 항목\n{body}\n"
    chunks = _parse(tmp_path, text)
    assert len(chunks) >= 2 and all(len(c["text"]) <= MAXLEN + len(line) + 1 for c in chunks)
    assert chunks[0]["page"] == 20
    assert chunks[-1]["page"] == 21
=======
"""src/ingest/chunk.py: 본문 없는 제목 접기(fold) / 버리기(drop), chunk_id 결정성."""
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
>>>>>>> main
