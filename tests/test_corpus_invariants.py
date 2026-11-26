# -*- coding: utf-8 -*-
"""수정 12 (좌표 기반 재배치) 이후의 코퍼스가 지켜야 할 성질. 저장소 파일만 쓴다 (PDF 불필요).

이 테스트는 '수정 이후' 코퍼스를 서술한다. docs/corpus 가 아직 수정 전이면(DOC-F5 문서가 없으면)
건너뛴다. 모의 적용 결과를 검사하려면:
    CORPUS_DIR=<폴더> CHUNKS_FILE=<chunks.jsonl> python -m pytest tests/test_corpus_invariants.py
"""
import json
import os
import re
import tomllib
from pathlib import Path

import pytest

from ingest import apply_placement as A
from ingest import chunk
from ingest import pdf_to_md as P

ROOT = Path(__file__).resolve().parents[1]
ENV_DIR = os.environ.get('CORPUS_DIR')
CORPUS = Path(ENV_DIR) if ENV_DIR else ROOT / 'docs' / 'corpus'
CHUNKS = Path(os.environ.get('CHUNKS_FILE') or ROOT / 'data' / 'chunks.jsonl')
NON_TWO_COLUMN = {'DOC-INTRO', 'DOC-ANNEX', 'DOC-WIDE', 'DOC-F4F5'}      # 업무명 `##` 규칙이 적용되지 않는 문서

# 사람이 검토해 남기기로 한 예외 (docs/conversion_notes.md 수정 12)
# 첫 `##` 앞에 본문이 있는 문서: E-9 p.326 의 '고용허가제란?' 칸(업무명 목록에 없는 중첩 칸)과 F-2 p.365 의 낱글자 '.'
BODY_BEFORE_FIRST_H2 = {'DOC-E9_비전문취업.md': 9, 'DOC-F2_거주.md': 1}
# 업무명 칸에서 본문으로 새는 조각(수정 12 에서 PDF 좌표로 확인해 지운 낱말들). 줄 전체가 이 낱말 하나일 때만 본다.
# 일반 낱말('외국인', '기준')까지 보면 본문과 구별되지 않아 오탐이 많다.
LEAK_WORDS = {'체류자격', '부여', '변경추가', '근무처의', '활동범위', '변경허가', '해당자', '연장허가', '체류기간',
              '체류자격외', '활동', '체류기간연장', '체류기간상한'}
# 줄 전체가 위 낱말이지만 검토 결과 본문이거나(표의 칸·서식) 좌표로 증명되지 않아 남긴 줄. {파일: {줄 글자}}
FRAGMENT_LIKE_BODY_OK = {
    'DOC-D10_구직.md': {'체류기간 상한', '체류기간', '상한'},      # 점수제 표의 칸 글자
    'DOC-D5_취재.md': {'활동'},
    'DOC-E2_회화지도.md': {'해 당 자'},
    'DOC-E7_특정활동.md': {'체류자격', '체류기간'},              # 서식(접수증) 안의 칸 글자
    'DOC-F1_방문동거.md': {'연장허가'},
    'DOC-F2_거주.md': {'변경 허가', '변경허가', '부여'},
    # 알려진 미해결: p.117 은 업무명 칸 괘선이 일부만 잡혀 '부 여' 가 남았다 (docs/conversion_notes.md 수정 12 한계)
    'DOC-D8_기업투자.md': {'부 여'},
}

pytestmark = pytest.mark.skipif(
    not (CORPUS / 'DOC-F5_영주.md').exists(),
    reason=f'{CORPUS} 는 아직 수정 12 이전의 코퍼스다 (DOC-F5_영주.md 없음). 적용 후 실행된다.')


def md_files():
    return sorted(CORPUS.glob('*.md'))


def doc_of(p):
    return p.name.split('_')[0]


def read(p):
    return p.read_text(encoding='utf-8').split('\n')


def front_len(lines):
    return len(A._front_matter(lines))


def test_chunks_file_equals_chunker_output_on_corpus():
    rows = []
    for f in md_files():
        rows += chunk.parse(f)
    stored = [json.loads(l) for l in CHUNKS.read_text(encoding='utf-8').split('\n') if l.strip()]
    assert stored == rows


def test_chunk_ids_unique():
    ids = [json.loads(l)['chunk_id'] for l in CHUNKS.read_text(encoding='utf-8').split('\n') if l.strip()]
    assert len(ids) == len(set(ids))


def test_no_body_before_first_h2():
    bad = {}
    for p in md_files():
        if doc_of(p) in NON_TWO_COLUMN:
            continue
        lines = read(p)
        n = 0
        seen_h2 = any(l.startswith('## ') for l in lines)
        if not seen_h2:
            continue
        for l in lines[front_len(lines):]:
            if l.startswith('## '):
                break
            if A._is_content(l):
                n += 1
        if n:
            bad[p.name] = n
    assert bad == BODY_BEFORE_FIRST_H2


def test_all_h2_headings_are_in_the_allow_list():
    allowed = set(P.ALL_LABELS)
    bad = []
    for p in md_files():
        if doc_of(p) in NON_TWO_COLUMN:
            continue
        for n, l in enumerate(read(p), 1):
            if l.startswith('## ') and l[3:].strip() not in allowed:
                bad.append((p.name, n, l))
    assert not bad, bad[:10]


def test_no_body_line_made_only_of_label_fragments():
    bad = []
    for p in md_files():
        if doc_of(p) in NON_TWO_COLUMN:
            continue
        lines = read(p)
        ok = FRAGMENT_LIKE_BODY_OK.get(p.name, set())
        for n, l in enumerate(lines[front_len(lines):], front_len(lines) + 1):
            if not A._is_content(l) or l.startswith('#') or l in ok:
                continue
            if A._knorm(l) not in LEAK_WORDS:
                continue
            # '활동범위' 는 '...대한 단기 / 활동범위 / (C-4-5)자격으로의 자격외 활동' 처럼 본문 낱말로도 나온다 (검토 완료)
            if A._knorm(l) == '활동범위' and lines[n].startswith('(C-4-5)자격으로의'):
                continue
            bad.append((p.name, n, l))
    assert not bad, bad[:10]


def test_split_docs_exist_with_front_matter():
    for fname, doc_id, title in (('DOC-F5_영주.md', 'DOC-F5', '영주(F-5)'), ('DOC-E2_회화지도.md', 'DOC-E2', '회화지도(E-2)')):
        lines = read(CORPUS / fname)
        head = '\n'.join(lines[:12])
        assert f'doc_id: {doc_id}' in head and f'title: {title}' in head and f'# {title}' in head
        assert any(A.PAGE_RE.match(l) for l in lines)


def test_cli_defaults_equal_config():
    cfg = tomllib.loads((ROOT / 'configs' / 'base.toml').read_text(encoding='utf-8'))['index']
    assert chunk.DEFAULT_BODYLESS_MODE == cfg['bodyless_heading_mode']
    assert chunk.DEFAULT_MIN_CHARS == cfg['min_chunk_chars']


def test_eval_chunk_ids_exist_and_pages_are_in_the_doc_range():
    if ENV_DIR:
        pytest.skip('모의 적용 코퍼스에서는 평가셋 연결(옛 색인 기준)을 검사하지 않는다')
    chunks = {}
    for l in CHUNKS.read_text(encoding='utf-8').split('\n'):
        if l.strip():
            c = json.loads(l)
            chunks[c['chunk_id']] = c
    pages = {}
    for c in chunks.values():
        lo, hi = pages.get(c['doc_id'], (c['page'], c['page']))
        pages[c['doc_id']] = (min(lo, c['page']), max(hi, c['page']))
    bad = []
    for f in ('eval-dev.json', 'eval-test.json'):
        for item in json.loads((ROOT / 'eval' / f).read_text(encoding='utf-8')):
            for i, ev in enumerate(item.get('evidence') or []):
                cid = ev.get('chunk_id')
                if cid is None:
                    continue
                if cid not in chunks:
                    bad.append((item['id'], i, 'chunk_id 없음', cid))
                    continue
                lo, hi = pages[chunks[cid]['doc_id']]
                if ev.get('page') is not None and not (lo <= ev['page'] <= hi):
                    bad.append((item['id'], i, '쪽이 문서 범위 밖', ev['page'], (lo, hi)))
    assert not bad, bad[:10]
