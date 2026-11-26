# -*- coding: utf-8 -*-
"""src/ingest/pdf_to_md.py 의 수정 12 규칙: 업무명 별칭, 쪽을 넘는 업무명, 머리글 규칙 (합성 -layout 텍스트)."""
import warnings

import pytest

from ingest import pdf_to_md as P

PAD = ' ' * 16          # 오른쪽 칸만 있는 줄 (들여쓰기 12 이상)


def convert(*pages):
    return P.convert([(i + 1, p) for i, p in enumerate(pages)], '시험(T-1)', 'DOC-T')


def h2(md):
    return [l[3:] for l in md.split('\n') if l.startswith('## ')]


def test_split_label_hwaldong_beomwi_and_haedangja_is_recognised():
    page = (' 활동범위     첫째 본문 줄\n'
            f'{PAD}둘째 본문 줄\n'
            ' 해 당 자     셋째 본문 줄\n')
    md = convert(page)
    assert h2(md) == ['자격 해당자 및 활동범위']
    assert '활동범위 첫째' not in md and '해 당 자 셋째' not in md      # 업무명 조각이 본문에 남지 않는다
    assert '첫째 본문 줄' in md and '셋째 본문 줄' in md


def test_label_split_across_page_break_is_recognised():
    p1 = (' 체류기간 연장허가     본문 A\n'
          f'{PAD}본문 B\n'
          ' 자격 해당자     본문 C\n')
    p2 = (' 및 활동범위     본문 D\n'
          f'{PAD}본문 E\n')
    md = convert(p1, p2)
    assert h2(md) == ['체류기간 연장허가', '자격 해당자 및 활동범위']
    body = [l for l in md.split('\n') if l and not l.startswith(('#', '<!--', '---', 'doc_id', 'title', 'source', 'version'))]
    assert all('및 활동범위' not in l and not l.startswith('자격 해당자') for l in body)


def test_label_carry_that_never_completes_returns_to_body():
    p1 = (' 체류기간 연장허가     본문 A\n'
          ' 자격 해당자     본문 C\n')
    p2 = (' 무관한      본문 D\n')
    md = convert(p1, p2)
    assert '자격 해당자' in md          # 완성되지 않은 조각은 본문으로 돌아간다 (글이 사라지지 않는다)


def test_alias_chegi_sanghan_maps_to_standard_label():
    md = convert(' 체류기간 상한     3년\n')
    assert h2(md) == ['1회에 부여할 수 있는 체류기간 상한']


def test_extra_label_is_kept_verbatim():
    md = convert(' 관리기준     허가 기준 본문\n')
    assert h2(md) == ['관리기준']


def test_all_labels_contains_standard_and_extra_labels():
    assert set(P.LABELS) <= set(P.ALL_LABELS)
    assert {'관리기준', '결핵증명서', '체류자격변경 및 체류기간연장', '근무처변경 (고용주재배정)'} <= set(P.ALL_LABELS)


def test_mid_page_title_like_line_is_kept_with_warning_but_page_header_is_dropped():
    page = (f'{PAD}유 학(D-2)\n'
            f'{PAD}첫째 본문 줄\n'
            f'{PAD}영 주(F-5)\n'
            f'{PAD}셋째 본문 줄\n')
    with pytest.warns(UserWarning, match='영 주'):
        md = convert(page)
    assert '영 주(F-5)' in md                      # 쪽 중간의 제목은 지우지 않는다
    assert '유 학(D-2)' not in md                  # 쪽 첫 2줄의 머리글은 지운다


def test_page_header_in_first_two_lines_gives_no_warning():
    page = f'{PAD}유 학(D-2)\n{PAD}본문 줄\n'
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        md = convert(page)
    assert '유 학(D-2)' not in md


# --- fix_glyphs 테스트 (수정 13) ---

def test_fix_glyphs_f024_becomes_middle_dot():
    from ingest.pdf_to_md import fix_glyphs
    assert fix_glyphs('') == '·'   # U+F024 -> ·

def test_fix_glyphs_bullet_glyphs_become_white_bullet():
    from ingest.pdf_to_md import fix_glyphs
    for cp in ['', '', '', '', '']:
        assert fix_glyphs(cp) == '◦', f"U+{ord(cp):04X} should map to ◦"

def test_fix_glyphs_f081_f082_f083_become_circled_numbers():
    from ingest.pdf_to_md import fix_glyphs
    assert fix_glyphs('') == '①'   # ①
    assert fix_glyphs('') == '②'   # ②
    assert fix_glyphs('') == '③'   # ③

def test_fix_glyphs_unknown_pua_is_removed():
    from ingest.pdf_to_md import fix_glyphs
    # U+F04C 는 매핑 없음 -> 제거
    assert fix_glyphs('') == ''
    assert fix_glyphs('앞뒤') == '앞뒤'

def test_fix_glyphs_plain_text_unchanged():
    from ingest.pdf_to_md import fix_glyphs
    s = '변경·추가 사항입니다.'
    assert fix_glyphs(s) == s

def test_fix_glyphs_mixed():
    from ingest.pdf_to_md import fix_glyphs
    # "변경[F024]추가" -> "변경·추가"
    assert fix_glyphs('변경추가') == '변경·추가'
