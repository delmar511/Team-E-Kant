# -*- coding: utf-8 -*-
"""체류민원 자격별 안내 매뉴얼 PDF 텍스트 -> 구조화 Markdown

문서가 2단 표 레이아웃이다. 왼쪽 열(업무 구분)은 여러 줄에 걸쳐 쪼개져 있고
같은 줄 오른쪽에 본문이 붙어 있다. 알려진 업무명 목록으로 앞부분을 잘라낸다.

입력: pdftotext -layout 로 뽑은 텍스트 (페이지 구분 \f)
사용: python pdf_to_md.py cheryu.txt 35 55 "유학(D-2)" DOC-D2 > out.md

전처리 규칙은 docs/conversion_notes.md 에 기록한다.
"""
import re
import sys
import warnings

NOISE = [
    re.compile(r'^\s*[~␾�]*\s*목차\s*$'),      # 페이지마다 반복되는 목차 링크
    re.compile(r'^\s*-\s*\d{1,4}\s*-\s*$'),
    re.compile(r'^\s*체류자격별\s*대상\s*및\s*제출서류\s*등\s*안내메뉴얼\s*$'),   # [수정7] 쪽마다 반복되는 머리글              # 페이지 번호
]

LABELS = [
    '자격 해당자 및 활동범위',
    '활동범위 및 자격 해당자',      # 일반연수(D-4) 는 어순을 뒤집어 쓴다
    '1회에 부여할 수 있는 체류기간 상한',
    '별도 허가 없이 유학활동이 가능한 체류자격',
    '별도 허가 없이 연수활동이 가능한 체류자격',
    '체류자격외 활동',
    '시간제취업 활동 허가',   # 원문 쪽머리는 '시간제취업 / 활동 허가' 두 줄
    '활동 허가 제한대상',
    '체류자격 부여',
    '체류자격 변경허가',
    '체류기간 연장허가',
    '근무처 변경·추가',
    '근무처의 변경·추가',           # 쪽에 따라 '의' 가 붙는다
    '재입국허가',
    '외국인등록',
    '사증발급인정서',
]
# 표준 업무명이 없는 업무명. 원문 그대로 `##` 로 쓴다 (docs/conversion_notes.md 수정 12).
EXTRA_LABELS = [
    '관리기준',                          # H-1 (E-3 p.186 에도 있다). 허가·억제 하위 항목을 가진 별도 업무
    '결핵증명서',                        # F-3 p.422
    '체류자격변경 및 체류기간연장',        # B-1, B-2
    '근무처변경 (고용주재배정)',           # E-8
]
# 표기 변형 -> 표준 업무명. 키는 공백·가운뎃점을 뺀 글자로 비교한다.
LABEL_ALIASES = {
    '체류기간 상한': '1회에 부여할 수 있는 체류기간 상한',      # D-3, D-8 은 줄여 쓴다
    '활동범위 해 당 자': '자격 해당자 및 활동범위',            # 칸이 '활동범위' / '해 당 자' 로 쪼개진 쪽
    '활동범위 및 해당자': '자격 해당자 및 활동범위',            # E-7 p.213
}
ALL_LABELS = LABELS + EXTRA_LABELS      # `##` 로 허용되는 업무명 전체 (코퍼스 불변식 테스트가 쓴다)
KEYS = [re.sub(r'[\s·]', '', x) for x in LABELS + EXTRA_LABELS]
ALIAS_KEYS = {re.sub(r'[\s·]', '', k): v for k, v in LABEL_ALIASES.items()}
PUA = re.compile(r'[\uE000-\uF8FF]')   # 원문의 '·' 가 사설영역 글리프로 깨져 있다

# 번호/가나다 항목으로 인정하려면 뒤에 실질 내용이 있어야 한다 (날짜 '20. 3. 1.' 배제)
SUBSTANCE = re.compile(r'[가-힣A-Za-z]')   # 공백 제거 후 글자가 2자 이상인지로 판정

# PUA 글리프 -> 올바른 문자 매핑 (docs/conversion_notes.md 수정 13)
# U+F081-F083 -> 1②③ 은 Wingdings 0x81-0x83 추정, PDF 없이 미검증
_GLYPH_MAP = {
    '\uF024': '·',   # 가운뎃점 (변경·추가, 초·중등 등)
    '\uF023': '◦',   # 글머리 기호
    '\uF0A7': '◦',
    '\uF077': '◦',
    '\uF06D': '◦',
    '\uF06F': '◦',
    '\uF081': '①',   # Wingdings 0x81, PDF 미검증
    '\uF082': '②',   # Wingdings 0x82, PDF 미검증
    '\uF083': '③',   # Wingdings 0x83, PDF 미검증
}
_pua_counts: dict = {}


def fix_glyphs(s: str) -> str:
    """PDF 심볼 폰트 PUA 글리프를 올바른 문자로 교체하거나 제거한다.

    매핑된 코드 포인트는 _GLYPH_MAP 의 값으로 교체하고,
    그 외 PUA(U+E000-U+F8FF) 는 제거한다. 각 코드 포인트 발생 횟수를
    _pua_counts 에 누적해 호출자가 보고할 수 있도록 한다.
    """
    if not PUA.search(s):
        return s
    result = []
    for ch in s:
        cp = ord(ch)
        if 0xE000 <= cp <= 0xF8FF:
            _pua_counts[cp] = _pua_counts.get(cp, 0) + 1
            result.append(_GLYPH_MAP.get(ch, ''))
        else:
            result.append(ch)
    return ''.join(result)


def squash(s):
    """공백 정리. 단어 경계(한 칸)는 보존한다."""
    s = fix_glyphs(s)
    s = s.replace('­', '').replace('‐', '-')
    s = s.replace('‑', '-').replace('–', '-')
    core = s.replace(' ', '')
    # 자간 벌림('유 학', '국   적')만 붙인다
    if len(core) <= 20 and len(re.findall(r'(?<![가-힣])[가-힣](?=\s)', s)) >= 3:
        # 한 칸짜리 자간만 붙인다. 두 칸 이상은 표의 칸 경계이므로 남긴다.
        # ('약 호   약 호   대 상 자' -> '약호 약호 대상자')
        s = re.sub(r'(?<=[가-힣]) (?=[가-힣])', '', s)
    return re.sub(r'\s{2,}', ' ', s).strip()


def norm_code(s):
    """'E- 7' -> 'E-7'. 다른 판·다른 문서 대비 정규화."""
    return re.sub(r'\b([A-Z])-\s+(\d)', r'\1-\2', s)


def label_state(buf):
    """buf 가 업무명으로 완성됐는가 / 아직 모으는 중인가.

    표준 업무명·원문 그대로 쓰는 업무명·표기 변형(LABEL_ALIASES)과 정확히 같으면 완성,
    그 어느 것의 앞부분이면 모으는 중이다. 정확한 일치를 먼저 본다.
    """
    k = re.sub(r'[\s·]', '', PUA.sub('', buf))
    if not k:
        return None, False
    for lab, key in zip(ALL_LABELS, KEYS):
        if k == key:
            return lab, False
    if k in ALIAS_KEYS:
        return ALIAS_KEYS[k], False
    if any(key.startswith(k) for key in KEYS) or any(key.startswith(k) for key in ALIAS_KEYS):
        return None, True
    return None, False


def split_left(raw):
    """'별도 허가 없이      외교(A-1)~...' -> ('별도 허가 없이', '외교(A-1)~...')"""
    m = re.match(r'^\s{0,14}(\S.{0,16}?)\s{2,}(\S.*)$', raw)
    if not m:
        return None, raw
    return squash(m.group(1)), m.group(2)


def join_spread(title):
    """제목의 자간 벌림만 붙인다. '대    상' -> '대상'

    공백으로 나눈 조각이 전부 한 글자일 때만 붙인다.
    '허가 기준 등'(조각이 2글자 포함)은 그대로 둔다.
    """
    parts = title.split()
    if len(parts) >= 2 and all(len(x) == 1 for x in parts):
        return ''.join(parts)
    return title


def column_split(raw):
    """한 줄을 (왼쪽 업무명 칸, 오른쪽 본문 칸) 으로 나눈다.

    pdftotext -layout 은 2단 표의 가로 위치를 공백으로 보존한다.
    그 성질을 그대로 쓴다. 어느 칸이 비어 있는지가 중요하다.
    """
    if not raw.strip():
        return '', ''
    indent = len(raw) - len(raw.lstrip())
    if indent >= 12:                       # 오른쪽 칸만 있는 줄
        return '', raw.strip()
    m = re.match(r'^\s{0,11}(\S.{0,15}?)\s{2,}(\S.*)$', raw)
    if m:                                  # 양쪽에 다 있는 줄
        return squash(m.group(1)), m.group(2)
    if len(raw.strip()) <= 20:             # 왼쪽 칸만 있는 짧은 줄 (업무명 조각)
        return squash(raw), ''
    return '', raw.strip()


def find_labels(cols, carry=()):
    """왼쪽 칸 조각들을 모아 업무명과 그 줄 범위를 찾는다.

    업무명은 제 본문의 세로 한가운데에 걸쳐 있고, 조각 사이에 본문 줄이
    끼어든다(A-1: '자격 해당자'(4행) / 본문(5행) / '및 활동범위'(6행)).
    그래서 '연속된 줄'이 아니라 '사이에 본문이 끼어도 이어지는' 누적이 필요하다.

    carry: 앞 쪽 끝에서 완성되지 못한 조각들. 업무명이 쪽 경계를 넘어 쪼개진 경우
    (수정 12 M3b) 이 쪽 첫 조각과 이어 붙여 본다.

    돌려주는 값: (labels, reclaim, tail, lost)
      labels  [(업무명, 시작줄, 끝줄), ...]
      reclaim 업무명이 아니라고 판명돼 본문으로 되돌려야 할 줄 번호 집합
      tail    이 쪽 끝에서 아직 완성되지 않은 조각 목록 (다음 쪽의 carry)
      lost    carry 가 이어지지 않아 업무명이 아니었던 조각 (앞 쪽 글자, 본문으로 되돌릴 것)
    """
    labels, reclaim = [], set()
    buf, start, used = list(carry), None, []
    carried = len(buf)
    lost = []
    for idx, (left, right) in enumerate(cols):
        if not left:
            continue
        lab, partial = label_state(' '.join(buf + [left]))
        if not lab and not partial:
            lab2, partial2 = label_state(left)     # 단독 매칭 fallback
            if lab2 or partial2:
                reclaim.update(used)               # 앞서 모은 건 업무명이 아니었다
                if carried:
                    lost, carried = list(buf[:carried]), 0
                buf, start, used = [], None, []
                lab, partial = lab2, partial2
        if lab:
            if start is None:
                start = idx
            labels.append((lab, start, idx))
            buf, start, used, carried = [], None, [], 0
        elif partial:
            if start is None:
                start = idx
            buf.append(left)
            used.append(idx)
        else:
            reclaim.update(used)
            reclaim.add(idx)
            if carried:
                lost, carried = list(buf[:carried]), 0
            buf, start, used = [], None, []
    # 쪽 끝에 남은 조각은 다음 쪽으로 넘긴다. 이 쪽에서 그 조각을 쓴 줄은 본문에 남기지 않는다.
    if carried and not used:             # 이 쪽에 이어질 조각이 없었다 -> 앞 쪽 조각은 업무명이 아니었다
        lost, buf = list(buf[:carried]), []
    tail = list(buf)
    return labels, reclaim, tail, lost


HEADER = re.compile(r'[가-힣]{2,8}\([A-Z]-\d+\)')


def convert(pages, title, code, version='2026-11-16'):
    out = ['---', f'doc_id: {code}', f'title: {title}',
           'source: 법무부 출입국·외국인정책본부 「체류민원 자격별 안내 매뉴얼」',
           f'version: {version}', '---', '', f'# {title}', '']
    last_lab = None
    tail = []                           # 앞 쪽 끝에서 이어지는 업무명 조각

    def render(line, first2=False, pno=None):
        """본문 한 줄을 Markdown 으로. 번호 항목은 소제목으로 올린다."""
        line = norm_code(squash(line))
        # 쪽마다 반복되는 머리글('유 학(D-2)'). 자간이 벌어져 있어 공백을 지우고 본다.
        # [수정12] 쪽의 첫 2줄일 때만 머리글로 보고 지운다. 쪽 중간에서 같은 모양이 나오면
        # 다른 자격 절의 제목('영 주(F-5)', '회화지도(E-2)')일 수 있어 지우지 않고 경고한다.
        if line and HEADER.fullmatch(re.sub(r'\s', '', line)):
            if first2:
                return []
            warnings.warn(f'p.{pno}: 쪽 중간의 제목 모양 줄을 지우지 않았다: {line!r} '
                          f'(다른 자격 절의 시작일 수 있다)', stacklevel=2)
            return [line]
        if not line:
            return []
        # 날짜('20. 3. 1.')를 번호 항목으로 오인하지 않는다
        m = re.match(r'^(\d{1,2}\.)\s+(.*)$', line)
        if m and len(re.sub(r'[^가-힣A-Za-z]', '', m.group(2))) >= 2:
            return ['', f'### {m.group(1)} {join_spread(m.group(2))}', '']
        m = re.match(r'^([가-힣]\.)\s+(.*)$', line)
        if m and len(re.sub(r'[^가-힣A-Za-z]', '', m.group(2))) >= 2:
            return ['', f'#### {m.group(1)} {join_spread(m.group(2))}', '']
        if re.match(r'^[□■]', line):
            return ['- ' + line.lstrip('□■ ')]
        return [line]

    for pno, page in pages:
        out.append(f'<!-- page: {pno} -->')

        raws = []
        for raw in page.split('\n'):
            if not raw.strip() or any(p.match(raw) for p in NOISE):
                continue
            raw = re.sub(r'^\s*[~\u243e\ufffd]+\s*목차\s*', '', raw)
            if raw.strip():
                raws.append(raw)

        cols = [column_split(r) for r in raws]
        labels, reclaim, new_tail, lost = find_labels(cols, tail)
        tail = new_tail
        for frag in lost:               # 이어지지 않은 앞 쪽 조각은 업무명이 아니었다
            out.extend(render(frag, pno=pno))
        # 업무명이 아니라고 판명된 왼쪽 조각은 본문으로 되돌린다
        for k in reclaim:
            left, right = cols[k]
            cols[k] = ('', (left + ' ' + right).strip())

        def body_lines(rows):
            for idx, (left, right) in rows:
                if right:
                    yield idx, right

        if not labels:
            # 업무명이 없는 쪽은 직전 구간이 이어지는 것으로 본다
            for idx, right in body_lines(enumerate(cols)):
                out.extend(render(right, idx < 2, pno))
            continue

        # 본문 줄을 구간으로 배정한다.
        # 한 업무의 영역 = 그 업무명이 시작하는 줄 ~ 다음 업무명이 시작하기 직전.
        #
        # '가장 가까운 업무명'(중앙 거리)으로 하면 본문이 업무명보다 훨씬 길 때
        # 뒤쪽 업무명으로 끌려간다. D-2 35쪽의 '적용대상별 세부약호' 표(16~27행)가
        # 「자격 해당자」(1~2행)가 아니라 「체류기간 상한」(28~30행)으로 넘어갔다.
        #
        # 업무명은 제 본문의 세로 한가운데에 놓이므로 첫 줄은 업무명보다
        # 한두 줄 위에서 시작한다. 그래서 첫 업무명 위의 본문도 그 구간에 넣는다.
        starts = [a for _, a, _ in labels]
        carry = []                      # 앞 쪽에서 이어지는 본문
        bucket = [[] for _ in labels]
        for idx, right in body_lines(enumerate(cols)):
            if idx < starts[0]:
                # 첫 업무명 바로 위(3줄 이내)면 그 구간의 첫 줄, 아니면 앞 구간의 꼬리
                if starts[0] - idx <= 3 or last_lab is None:
                    bucket[0].append((idx, right))
                else:
                    carry.append((idx, right))
                continue
            t = max(k for k in range(len(starts)) if starts[k] <= idx)
            bucket[t].append((idx, right))

        for idx, ln in carry:           # 앞 구간 제목 아래로 먼저 흘린다
            out.extend(render(ln, idx < 2, pno))

        for (lab, _, _), lines in zip(labels, bucket):
            if lab != last_lab:
                out.extend(['', f'## {lab}', ''])
                last_lab = lab
            for idx, ln in lines:
                out.extend(render(ln, idx < 2, pno))

    for frag in tail:                   # 마지막 쪽 끝에서 끝내 완성되지 않은 조각은 본문으로 둔다
        out.extend(render(frag))
    return '\n'.join(out) + '\n'


if __name__ == '__main__':
    txt = open(sys.argv[1], encoding='utf-8').read()
    pages = txt.split('\f')
    a, b = int(sys.argv[2]), int(sys.argv[3])
    sel = [(i + 1, pages[i]) for i in range(a - 1, min(b, len(pages)))]
    sys.stdout.write(convert(sel, sys.argv[4], sys.argv[5]))
