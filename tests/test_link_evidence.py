# -*- coding: utf-8 -*-
"""src/link_evidence.py: 빈 quote, 쪽 기준 연결 (합성 청크)."""
import json

import link_evidence as L


def make(tmp_path, rows):
    p = tmp_path / 'chunks.jsonl'
    p.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n', encoding='utf-8')
    return L.load_chunks(p)


def chunk(cid, doc, page, text='본문 내용이 충분히 길어야 한다 가나다라마바사', loc='문서 > 제목'):
    return dict(chunk_id=cid, doc_id=doc, location=loc, page=page, text=text)


ROWS = [chunk('DOC-A#1', 'DOC-A', 10), chunk('DOC-A#2', 'DOC-A', 11), chunk('DOC-A#3', 'DOC-A', 11),
        chunk('DOC-B#1', 'DOC-B', 20), chunk('DOC-B#2', 'DOC-B', 21)]


def test_empty_quote_is_not_found_and_never_falls_back_to_first_chunk(tmp_path):
    chunks = make(tmp_path, ROWS)
    for q in ('', '   ', None):
        cid, cands, st = L.link_one({'page': 10, 'quote': q}, chunks)
        assert (cid, cands, st) == (None, [], 'not_found')
    assert L.link_one({'page': 10}, chunks) == (None, [], 'not_found')


def test_page_mode_single_candidate_links(tmp_path):
    chunks = make(tmp_path, ROWS)
    dp = L.doc_page_ranges(chunks)
    assert dp == {'DOC-A': (10, 11), 'DOC-B': (20, 21)}
    assert L.link_by_page({'page': 10}, chunks, dp) == ('DOC-A#1', ['DOC-A#1'], 'page_ok')
    assert L.link_by_page({'page': 20}, chunks, dp)[0] == 'DOC-B#1'


def test_page_mode_several_candidates_returns_none_and_the_list(tmp_path):
    chunks = make(tmp_path, ROWS)
    dp = L.doc_page_ranges(chunks)
    cid, cands, st = L.link_by_page({'page': 11}, chunks, dp)
    assert cid is None and cands == ['DOC-A#2', 'DOC-A#3'] and st == 'page_ambiguous'


def test_page_mode_no_candidate_is_none_and_does_not_fall_back_to_other_doc(tmp_path):
    chunks = make(tmp_path, ROWS)
    dp = L.doc_page_ranges(chunks)
    assert L.link_by_page({'page': 15}, chunks, dp) == (None, [], 'not_found')      # 어느 문서 범위에도 없음
    assert L.link_by_page({'page': 99}, chunks, dp) == (None, [], 'not_found')
    assert L.link_by_page({}, chunks, dp) == (None, [], 'not_found')
    # 문서 범위 안이지만 그 쪽에 청크가 없다 -> 다른 쪽 청크로 대체하지 않는다
    rows = [chunk('DOC-A#1', 'DOC-A', 10), chunk('DOC-A#9', 'DOC-A', 12)]
    c2 = make(tmp_path, rows)
    assert L.link_by_page({'page': 11}, c2, L.doc_page_ranges(c2)) == (None, [], 'not_found')


def test_page_mode_respects_explicit_doc_id(tmp_path):
    rows = [chunk('DOC-A#1', 'DOC-A', 30), chunk('DOC-B#1', 'DOC-B', 30)]      # 한 쪽을 두 문서가 나눠 쓴다 (분리 쪽)
    chunks = make(tmp_path, rows)
    dp = L.doc_page_ranges(chunks)
    assert L.link_by_page({'page': 30}, chunks, dp)[2] == 'page_ambiguous'
    assert L.link_by_page({'page': 30, 'doc_id': 'DOC-B'}, chunks, dp)[0] == 'DOC-B#1'


def test_quote_mode_still_finds_by_quote(tmp_path):
    rows = [chunk('DOC-A#1', 'DOC-A', 10, text='신청서와 여권을 제출해야 한다 이것은 길이가 충분한 문장'),
            chunk('DOC-A#2', 'DOC-A', 11, text='전혀 다른 문장이 여기에 들어 있다 이것도 충분히 길다')]
    chunks = make(tmp_path, rows)
    cid, _, st = L.link_one({'page': 11, 'quote': '신청서와 여권을 제출해야 한다 이것은 길이가 충분한 문장'}, chunks)
    assert cid == 'DOC-A#1' and st == 'ok'
