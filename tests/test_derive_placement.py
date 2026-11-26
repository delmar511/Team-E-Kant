# -*- coding: utf-8 -*-
"""src/ingest/derive_placement.py, pdf_cells.py: 쪽을 넘는 칸·--check 사각·누락 사례 (합성 칸, PDF·pdfplumber 불필요)."""
from ingest import derive_placement as D
from ingest import pdf_cells as PC

FM = ['---', 'doc_id: DOC-T', 'title: 시험(T-1)', 'source: 법무부 매뉴얼', 'version: 2026-11-16', '---', '', '# 시험(T-1)']


def cell(top, bottom, left_raw, left_words, lines):
    lab, how = PC.resolve_label(left_raw)
    return PC.Cell(top, bottom, left_raw, left_words, lab or '', how, [PC.CellLine(y, t) for y, t in lines])


def page(n, *cells):
    return PC.PageCells(n, 132.0, list(cells))


def doc(*body):
    return FM + [''] + list(body)


def ops_of(lines, cells):
    ops = D.propose('DOC-T_시험.md', lines, cells)
    real, _ = D.finalize(ops)
    return real


# 앞 쪽(p19) 맨 아래에서 시작하는 '체류자격 변경허가' 칸: 앞 쪽에는 왼쪽 '체류자격' 만, 나머지 '변경허가' 는 p20 첫 칸.
CROSS_CELLS = {
    19: page(19,
             cell(57, 700, '체류자격 부 여', ['체류자격', '부', '여'], [(61.9, '출생일부터 90일 이내 신청')]),
             cell(756, 777, '체류자격', ['체류자격'], [(758.4, '제출서류')])),
    20: page(20,
             cell(57, 389, '변경허가', ['변경허가'], [(64.2, '① 신청서(별지 제34호 서식), 여권'),
                                                     (78.4, '② 파견재직을 입증하는 서류 또는 자국 소속부처')])),
}


def cross_doc(heading_after_first_line):
    body = ['<!-- page: 19 -->', '', '## 체류자격 부여', '', '출생일부터 90일 이내 신청', '체류자격 제출서류',
            '<!-- page: 20 -->', '']
    if heading_after_first_line:       # 반려된 옛 작업의 결과: 첫 본문 줄이 체류자격 부여에 남는다
        body += ['① 신청서(별지 제34호 서식), 여권', '## 체류자격 변경허가', '', '② 파견재직을 입증하는 서류 또는 자국 소속부처']
    else:
        body += ['## 체류자격 변경허가', '', '① 신청서(별지 제34호 서식), 여권', '② 파견재직을 입증하는 서류 또는 자국 소속부처']
    return doc(*body)


def test_cell_starting_at_bottom_of_previous_page_puts_heading_before_first_line():
    lines = cross_doc(heading_after_first_line=False)
    lines = [l for l in lines if l != '## 체류자격 변경허가']
    ops = ops_of(lines, CROSS_CELLS)
    ins = [o for o in ops if o.op == 'insert_heading' and o.heading == '체류자격 변경허가']
    assert len(ins) == 1
    assert lines[ins[0].line - 1] == '체류자격 제출서류'           # p19 아래의 첫 줄 앞. p20 첫 줄 앞이 아니다
    assert any(o.op == 'strip_fragment' and o.line == ins[0].line and o.fragment == '체류자격' for o in ops)


def test_move_heading_to_cross_page_cell_start():
    lines = cross_doc(heading_after_first_line=True)
    ops = ops_of(lines, CROSS_CELLS)
    mv = [o for o in ops if o.op == 'move_heading' and o.heading == '체류자격 변경허가']
    assert len(mv) == 1 and lines[mv[0].to_line - 1] == '체류자격 제출서류'


def test_check_counts_misfiled_first_line_in_unmatched_cell(monkeypatch):
    bad = D.check_doc('DOC-T_시험.md', cross_doc(True), CROSS_CELLS)
    assert '체류자격 제출서류' in [r[3] for r in bad['1_wrong_label']]
    monkeypatch.setattr(D, 'carry_cells', lambda c: c)         # 고치기 전: unmatched 칸의 줄은 업무명을 몰라 세지 못했다
    old = D.check_doc('DOC-T_시험.md', cross_doc(True), CROSS_CELLS)
    assert '체류자격 제출서류' not in [r[3] for r in old['1_wrong_label']]
    monkeypatch.undo()
    fixed = doc('<!-- page: 19 -->', '', '## 체류자격 부여', '', '출생일부터 90일 이내 신청', '',
                '## 체류자격 변경허가', '', '제출서류', '<!-- page: 20 -->', '', '① 신청서(별지 제34호 서식), 여권',
                '② 파견재직을 입증하는 서류 또는 자국 소속부처')
    good = D.check_doc('DOC-T_시험.md', fixed, CROSS_CELLS)
    assert not good['1_wrong_label']


def test_carry_does_not_touch_unrelated_unmatched_cell():
    cells = dict(CROSS_CELLS)
    cells[20] = page(20, cell(57, 389, '재입국허가', ['재입국허가'], [(64.2, '본문')]))
    out = D.carry_cells(cells)
    assert out[19].cells[-1].label == '' and out[19].cells[-1].how == 'unmatched'


def test_carry_cells_does_not_mutate_input():
    D.carry_cells(CROSS_CELLS)
    assert CROSS_CELLS[19].cells[-1].how == 'unmatched'


# ------------------------------------------------------------------ 쪽 맨 위의 체류자격 부여 칸 (D5·D8)
def test_split_left_words_boo_yeo_recognised_as_fragment():
    cells = {7: page(7,
                     cell(71, 196, '근무처의 변경추가', ['근무처의', '변경추가'], [(83.3, '근무처 변경추가 신고대상 아님')]),
                     cell(196, 231, '체류자격 부 여', ['체류자격', '부', '여'], [(213.8, '해당사항 없음')]),
                     cell(231, 500, '체류자격 변경허가', ['체류자격', '변경허가'], [(243.4, '1. 일시취재 자격 소지자에 대하여 필요성이 입증될')]))}
    lines = doc('<!-- page: 7 -->', '', '## 근무처의 변경·추가', '', '근무처 변경추가 신고대상 아님', '체류자격',
                '부 여 해당사항 없음', '', '### 1. 일시취재 자격 소지자에 대하여 필요성이 입증될')
    ops = ops_of(lines, cells)
    no = lambda s: next(i for i, l in enumerate(lines, 1) if l == s)
    assert any(o.op == 'strip_fragment' and o.fragment == '부 여' and o.line == no('부 여 해당사항 없음') for o in ops)
    assert any(o.op == 'insert_heading' and o.heading == '체류자격 부여' and o.line == no('부 여 해당사항 없음') for o in ops)
    assert any(o.op == 'delete_line' and o.line == no('체류자격') for o in ops)


def test_corpus_middle_dot_matches_pdf_pua_glyph():
    """코퍼스는 PDF 의 사설영역 가운뎃점을 '·' 로 바꿔 두었다. 단독 조각 줄 '변경·추가' 를 알아본다."""
    cells = {15: page(15, cell(649, 711, '근무처의 변경추가', ['근무처의', '변경추가'], [(674.8, '“해당사항 없음”')]),
                      cell(712, 777, '체류자격 부 여', ['체류자격', '부', '여'], [(720.1, '출생일부터 90일 이내 신청')]))}
    lines = doc('<!-- page: 15 -->', '', '## 근무처의 변경·추가', '', '근무처의', '“해당사항 없음”', '변경·추가',
                '출생일부터 90일 이내 신청')
    ops = ops_of(lines, cells)
    deleted = {lines[o.line - 1] for o in ops if o.op == 'delete_line'}
    assert {'근무처의', '변경·추가'} <= deleted


def test_glued_fragment_takes_longest_label_words():
    """'해 당 자 가. …' 는 '해 당' 이 아니라 '해 당 자' 를 뗀다 (앞 줄 끝의 '자' + 다음 줄 '가. …' 가 줄 경계를 넘어 맞는다)."""
    cells = {365: page(365,
                       cell(134, 165, '활동범위', ['활동범위'], [(144.4, '영주자격을 부여받기 위하여 국내 장기체류하려는 자')]),
                       cell(166, 700, '해 당 자', ['해', '당', '자'], [(175.4, '가. 국민의 미성년 외국인 자녀 또는 별표 1의3 영주 체류자격을 가지')]))}
    lines = doc('<!-- page: 365 -->', '', '## 자격 해당자 및 활동범위', '',
                '활동범위 영주자격을 부여받기 위하여 국내 장기체류하려는 자',
                '해 당 자 가. 국민의 미성년 외국인 자녀 또는 별표 1의3 영주 체류자격을 가지')
    ops = ops_of(lines, cells)
    frags = {(o.line, o.fragment) for o in ops if o.op == 'strip_fragment'}
    assert (len(lines), '해 당 자') in frags
    assert (len(lines) - 1, '활동범위') in frags


def test_glued_lead_with_connector_and_duplicate_label_word():
    cells = {213: page(213, cell(121, 300, '활동범위 해당자', ['활동범위', '해당자'],
                                 [(151.0, '대한민국 내의 공·사기관 등과의 계약에 따라 법무부장관이 특별히 지정'),
                                  (170.0, '하는 활동에 종사하려고 하는 사람')]))}
    lines = doc('<!-- page: 213 -->', '', '## 자격 해당자 및 활동범위', '',
                '활동범위 및 대한민국 내의 공·사기관 등과의 계약에 따라 법무부장관이 특별히 지정',
                '해당자 하는 활동에 종사하려고 하는 사람')
    ops = ops_of(lines, cells)
    frags = {(o.line, o.fragment) for o in ops if o.op == 'strip_fragment'}
    assert (len(lines) - 1, '활동범위 및') in frags and (len(lines), '해당자') in frags


# ------------------------------------------------------------------ 표기
def test_new_heading_spelling_follows_pdf_and_corpus():
    assert D.heading_text('근무처 변경·추가', 'fuzzy', {}) == '근무처의 변경·추가'
    assert D.heading_text('근무처 변경·추가', 'fuzzy', {'근무처 변경·추가': '근무처 변경·추가'}) == '근무처 변경·추가'   # 문서에 이미 있으면 그대로
    assert D.heading_text('근무처 변경·추가', 'exact', {}) == '근무처 변경·추가'


# ------------------------------------------------------------------ pdf_cells._find_boundary (가짜 쪽)
class FakePage:
    def __init__(self, edges):
        self.edges = edges


def v(x, top, bottom):
    return dict(orientation='v', x0=x, x1=x, top=top, bottom=bottom)


OUTER_BORDER = v(57, 71, 785)


def test_nested_box_does_not_replace_label_column_boundary():
    """'【공통기준】' 상자(x 152, y 315~779)의 왼쪽 선이 바깥 경계(x 146)보다 길어도 바깥 경계를 쓴다."""
    edges = [OUTER_BORDER, v(146, 71, 240.7), v(146, 241, 313.7), v(146, 314, 785.8), v(152, 315, 779.6), v(152, 315, 779.0)]
    x, spans = PC._find_boundary(FakePage(edges))
    assert abs(x - 146) < 1
    assert [71, 241] [0] == spans[0][0] and any(abs(a - 241) <= 1 and abs(b - 314) <= 1 for a, b in spans)


def test_plain_page_boundary_unchanged():
    edges = [OUTER_BORDER, v(132, 57, 300), v(132, 301, 600)]
    x, spans = PC._find_boundary(FakePage(edges))
    assert abs(x - 132) < 1 and spans == [[57, 300], [301, 600]]


def test_short_cell_at_page_bottom_is_kept():
    """y 767~785 (18.5pt) 처럼 쪽 맨 아래의 낮은 칸도 칸으로 센다 (DOC-D9 p.130 '근무처의')."""
    edges = [OUTER_BORDER, v(146, 396, 766.7), v(146, 767, 785.5)]
    x, spans = PC._find_boundary(FakePage(edges))
    assert any(abs(a - 767) <= 1 and abs(b - 785.5) <= 1 for a, b in spans)
