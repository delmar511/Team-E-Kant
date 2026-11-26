# -*- coding: utf-8 -*-
"""src/ingest/apply_placement.py: 본문 보존·작업 5종·오류 처리 (합성 문서, PDF 불필요)."""
import copy
import json

import pytest

from ingest import apply_placement as A
from ingest import chunk

FM = ['---', 'doc_id: DOC-T', 'title: 시험(T-1)', 'source: 법무부 매뉴얼', 'version: 2026-11-16', '---']
BODY = [
    '',
    '# 시험(T-1)',
    '',
    '<!-- page: 5 -->',
    '',
    '## 자격 해당자 및 활동범위',
    '',
    '첫째 본문 줄은 해당자에 관한 내용이다 이 줄은 충분히 길다',
    '둘째 본문 줄도 해당자에 관한 내용이다 이 줄도 충분히 길다',
    '체류기간 상한 항목의 본문이지만 여기에 잘못 들어 있는 줄이다',
    '2년',
    '',
    '### 1. 하위 제목',
    '',
    '하위 제목 아래의 본문이다 이 줄도 스무 글자를 넘긴다',
    '',
    '## 체류자격외 활동',
    '',
    '체류자격외 활동에 대한 본문이다 이 줄도 스무 글자를 넘긴다',
    '근무처의',
    '해당사항 없음 뒤에 붙은 줄 이 줄도 충분히 길게 쓴다',
    '체류자격 제출서류 신청서 여권 수수료 등 충분히 긴 줄',
    '<!-- page: 6 -->',
    '다음 쪽의 본문이다 이 줄도 스무 글자를 넘긴다',
]
LINES = FM + BODY


def ln(text):
    """원본에서 text 와 정확히 같은 줄의 번호(1부터)."""
    return LINES.index(text) + 1


def doc(lines=None):
    return {'DOC-T_시험.md': list(lines or LINES)}


def move_op(**kw):
    """`## 1회에 ...` 를 만들 필요 없이: 기존 '체류자격외 활동' 제목을 '2년' 앞으로 옮긴다."""
    d = dict(op='move_heading', file='DOC-T_시험.md', line=ln('## 체류자격외 활동'), expect='## 체류자격외 활동',
             to_line=ln('2년'), expect_to='2년', heading='체류자격외 활동', id='P1')
    d.update(kw)
    return A.PlacementOp(**d)


def insert_op(**kw):
    d = dict(op='insert_heading', file='DOC-T_시험.md', line=ln('2년'), expect='2년', to_line=ln('2년'),
             expect_to='2년', heading='1회에 부여할 수 있는 체류기간 상한', id='P2')
    d.update(kw)
    return A.PlacementOp(**d)


def content(lines):
    return A._content(lines)


def test_move_and_insert_preserve_body_lines_and_bytes():
    wrong = '체류기간 상한 항목의 본문이지만 여기에 잘못 들어 있는 줄이다'
    ops = [move_op(), insert_op(line=ln(wrong), expect=wrong, to_line=ln(wrong), expect_to=wrong)]
    before = doc()
    out = A.apply(before, ops)
    assert before == doc()                                   # 입력은 바뀌지 않는다
    assert content(out['DOC-T_시험.md']) == content(LINES)
    heads = [l for l in out['DOC-T_시험.md'] if l.startswith('## ')]
    assert heads == ['## 자격 해당자 및 활동범위', '## 1회에 부여할 수 있는 체류기간 상한', '## 체류자격외 활동']


def test_moved_h3_chunk_path(tmp_path):
    op = move_op(to_line=ln('### 1. 하위 제목'), expect_to='### 1. 하위 제목')
    out = A.apply(doc(), [op])
    A.write_corpus(tmp_path, out)
    rows = chunk.parse(tmp_path / 'DOC-T_시험.md')
    sub = [r for r in rows if '하위 제목 아래의 본문' in r['text']]
    assert sub and sub[0]['location'] == '시험(T-1) > 체류자격외 활동 > 1. 하위 제목'


def test_expect_mismatch_raises_and_writes_nothing(tmp_path):
    corpus = tmp_path / 'corpus'
    corpus.mkdir()
    A.write_corpus(corpus, doc())
    bad = tmp_path / 'ops.jsonl'
    op = insert_op(expect='2년 ')
    bad.write_text(op.to_json().replace('"proposed"', '"accepted"') + '\n', encoding='utf-8')
    before = (corpus / 'DOC-T_시험.md').read_bytes()
    with pytest.raises(A.PlacementError):
        A.main(['--ops', str(bad), '--corpus', str(corpus), '--write'])
    assert (corpus / 'DOC-T_시험.md').read_bytes() == before
    with pytest.raises(A.PlacementError):
        A.apply(doc(), [op])


def test_insert_outside_allow_list_rejected():
    with pytest.raises(A.PlacementError, match='허용 목록'):
        A.apply(doc(), [insert_op(heading='임의로 만든 제목')])


def test_delete_requires_label_fragment_only():
    with pytest.raises(A.PlacementError, match='라벨 조각'):
        A.apply(doc(), [A.PlacementOp(op='delete_line', file='DOC-T_시험.md', line=ln('2년'), expect='2년', id='P3')])
    ok = A.PlacementOp(op='delete_line', file='DOC-T_시험.md', line=ln('근무처의'), expect='근무처의', id='P3')
    out = A.apply(doc(), [ok])
    assert '근무처의' not in out['DOC-T_시험.md']
    assert len(content(out['DOC-T_시험.md'])) == len(content(LINES)) - 1


def test_strip_only_leading_or_trailing_fragment():
    line = '체류자격 제출서류 신청서 여권 수수료 등 충분히 긴 줄'
    op = A.PlacementOp(op='strip_fragment', file='DOC-T_시험.md', line=ln(line), expect=line, fragment='체류자격', id='P4')
    out = A.apply(doc(), [op])
    assert '제출서류 신청서 여권 수수료 등 충분히 긴 줄' in out['DOC-T_시험.md']
    # 줄 가운데의 조각은 떼지 않는다
    mid = '체류자격 제출서류 신청서 여권 수수료 등 충분히 긴 줄'
    bad = A.PlacementOp(op='strip_fragment', file='DOC-T_시험.md', line=ln(mid), expect=mid, fragment='신청서', id='P5')
    with pytest.raises(A.PlacementError):
        A.apply(doc(), [bad])
    # 조각이 아닌 낱말은 떼지 않는다
    bad2 = A.PlacementOp(op='strip_fragment', file='DOC-T_시험.md', line=ln(mid), expect=mid, fragment='제출서류', id='P6')
    with pytest.raises(A.PlacementError, match='라벨 조각'):
        A.apply(doc(), [bad2])
    # 뒤쪽 조각
    tail = A.strip_fragment_text('해당사항 없음 근무처의', '근무처의')
    assert tail == '해당사항 없음'


def test_split_doc_result_format():
    line = '체류자격외 활동에 대한 본문이다 이 줄도 스무 글자를 넘긴다'
    op = A.PlacementOp(op='split_doc', file='DOC-T_시험.md', line=ln(line), expect=line, id='P7',
                       new_doc=dict(doc_id='DOC-T2', title='새자격(T-2)', file='DOC-T2_새자격.md'))
    ins = A.PlacementOp(op='insert_heading', file='DOC-T_시험.md', line=ln(line), expect=line, to_line=ln(line),
                        expect_to=line, heading='체류자격 부여', id='P8')
    out = A.apply(doc(), [op])
    new = out['DOC-T2_새자격.md']
    assert new[:6] == ['---', 'doc_id: DOC-T2', 'title: 새자격(T-2)', 'source: 법무부 매뉴얼', 'version: 2026-11-16', '---']
    assert '# 새자격(T-2)' in new and any(A.PAGE_RE.match(l) for l in new)
    assert content(out['DOC-T_시험.md']) + content(new) == content(LINES)
    # split 줄 앞에 넣는 제목은 새 문서의 첫 제목이 된다
    out2 = A.apply(doc(), [op, ins])
    assert [l for l in out2['DOC-T2_새자격.md'] if l.startswith('## ')][:1] == ['## 체류자격 부여']
    assert '## 체류자격 부여' not in out2['DOC-T_시험.md']


def test_reapplying_ops_raises():
    ops = [move_op()]
    once = A.apply(doc(), ops)
    with pytest.raises(A.PlacementError):
        A.apply(once, ops)
    ins = [insert_op()]
    once = A.apply(doc(), ins)
    with pytest.raises(A.PlacementError):
        A.apply(once, ins)


def test_files_without_ops_are_unchanged():
    other = ['---', 'doc_id: DOC-U', 'title: u', 'source: s', 'version: v', '---', '', '# u', '', '본문']
    both = {'DOC-T_시험.md': list(LINES), 'DOC-U_다른.md': other}
    out = A.apply(both, [insert_op()])
    assert out['DOC-U_다른.md'] == other


def test_load_ops_accepts_only_accepted_by_default(tmp_path):
    p = tmp_path / 'ops.jsonl'
    a, b = insert_op(id='A'), insert_op(id='B')
    a.status = 'accepted'
    p.write_text(a.to_json() + '\n' + b.to_json() + '\n', encoding='utf-8')
    assert [o.id for o in A.load_ops(p)] == ['A']
    assert [o.id for o in A.load_ops(p, ('accepted', 'proposed'))] == ['A', 'B']


def test_write_refuses_include_proposed(tmp_path):
    with pytest.raises(SystemExit):
        A.main(['--ops', str(tmp_path / 'x'), '--corpus', str(tmp_path), '--write', '--include-proposed'])


def test_check_invariants_detects_changed_body_line():
    before = doc()
    after = copy.deepcopy(before)
    after['DOC-T_시험.md'][ln('2년') - 1] = '3년'
    with pytest.raises(A.PlacementError, match='본문 줄'):
        A.check_invariants(before, after, [insert_op()])
