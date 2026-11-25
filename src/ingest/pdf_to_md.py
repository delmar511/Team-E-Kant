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
KEYS = [re.sub(r'[\s·]', '', x) for x in LABELS]
PUA = re.compile(r'[\uE000-\uF8FF]')   # 원문의 '·' 가 사설영역 글리프로 깨져 있다

# 번호/가나다 항목으로 인정하려면 뒤에 실질 내용이 있어야 한다 (날짜 '20. 3. 1.' 배제)
SUBSTANCE = re.compile(r'[가-힣A-Za-z]')   # 공백 제거 후 글자가 2자 이상인지로 판정


def squash(s):
    """공백 정리. 단어 경계(한 칸)는 보존한다."""
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
    """buf 가 업무명으로 완성됐는가 / 아직 모으는 중인가."""
    k = re.sub(r'[\s·]', '', PUA.sub('', buf))
    if not k:
        return None, False
    for lab, key in zip(LABELS, KEYS):
        if k == key:
            return lab, False
        if key.startswith(k):
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


def find_labels(cols):
    """왼쪽 칸 조각들을 모아 업무명과 그 줄 범위를 찾는다.

    업무명은 제 본문의 세로 한가운데에 걸쳐 있고, 조각 사이에 본문 줄이
    끼어든다(A-1: '자격 해당자'(4행) / 본문(5행) / '및 활동범위'(6행)).
    그래서 '연속된 줄'이 아니라 '사이에 본문이 끼어도 이어지는' 누적이 필요하다.

    돌려주는 값: [(업무명, 시작줄, 끝줄), ...]  그리고 업무명이 아니라고
    판명돼 본문으로 되돌려야 할 줄 번호 집합.
    """
    labels, reclaim = [], set()
    buf, start, used = [], None, []
    for idx, (left, right) in enumerate(cols):
        if not left:
            continue
        lab, partial = label_state(' '.join(buf + [left]))
        if not lab and not partial:
            lab2, partial2 = label_state(left)     # 단독 매칭 fallback
            if lab2 or partial2:
                reclaim.update(used)               # 앞서 모은 건 업무명이 아니었다
                buf, start, used = [], None, []
                lab, partial = lab2, partial2
        if lab:
            if start is None:
                start = idx
            labels.append((lab, start, idx))
            buf, start, used = [], None, []
        elif partial:
            if start is None:
                start = idx
            buf.append(left)
            used.append(idx)
        else:
            reclaim.update(used)
            reclaim.add(idx)
            buf, start, used = [], None, []
    reclaim.update(used)
    return labels, reclaim


def convert(pages, title, code, version='2026-11-16'):
    out = ['---', f'doc_id: {code}', f'title: {title}',
           'source: 법무부 출입국·외국인정책본부 「체류민원 자격별 안내 매뉴얼」',
           f'version: {version}', '---', '', f'# {title}', '']
    last_lab = None

    def render(line):
        """본문 한 줄을 Markdown 으로. 번호 항목은 소제목으로 올린다."""
        line = norm_code(squash(line))
        # 쪽마다 반복되는 머리글('유 학(D-2)'). 자간이 벌어져 있어 공백을 지우고 본다.
        if not line or re.fullmatch(r'[가-힣]{2,8}\([A-Z]-\d+\)', re.sub(r'\s', '', line)):
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
        labels, reclaim = find_labels(cols)
        # 업무명이 아니라고 판명된 왼쪽 조각은 본문으로 되돌린다
        for k in reclaim:
            left, right = cols[k]
            cols[k] = ('', (left + ' ' + right).strip())

        if not labels:
            # 업무명이 없는 쪽은 직전 구간이 이어지는 것으로 본다
            for left, right in cols:
                if right:
                    out.extend(render(right))
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
        for idx, (left, right) in enumerate(cols):
            if not right:
                continue
            if idx < starts[0]:
                # 첫 업무명 바로 위(3줄 이내)면 그 구간의 첫 줄, 아니면 앞 구간의 꼬리
                if starts[0] - idx <= 3 or last_lab is None:
                    bucket[0].append(right)
                else:
                    carry.append(right)
                continue
            t = max(k for k in range(len(starts)) if starts[k] <= idx)
            bucket[t].append(right)

        for ln in carry:                # 앞 구간 제목 아래로 먼저 흘린다
            out.extend(render(ln))

        for (lab, _, _), lines in zip(labels, bucket):
            if lab != last_lab:
                out.extend(['', f'## {lab}', ''])
                last_lab = lab
            for ln in lines:
                out.extend(render(ln))

    return '\n'.join(out) + '\n'


if __name__ == '__main__':
    txt = open(sys.argv[1], encoding='utf-8').read()
    pages = txt.split('\f')
    a, b = int(sys.argv[2]), int(sys.argv[3])
    sel = [(i + 1, pages[i]) for i in range(a - 1, min(b, len(pages)))]
    sys.stdout.write(convert(sel, sys.argv[4], sys.argv[5]))
