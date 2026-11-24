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
    re.compile(r'^\s*-\s*\d{1,4}\s*-\s*$'),              # 페이지 번호
]

LABELS = [
    '자격 해당자 및 활동범위',
    '1회에 부여할 수 있는 체류기간 상한',
    '별도 허가 없이 유학활동이 가능한 체류자격',
    '별도 허가 없이 연수활동이 가능한 체류자격',
    '체류자격외 활동',
    '시간제취업',
    '활동 허가 제한대상',
    '체류자격 부여',
    '체류자격 변경허가',
    '체류기간 연장허가',
    '근무처 변경·추가',
    '재입국허가',
    '외국인등록',
    '사증발급인정서',
]
KEYS = [re.sub(r'[\s·]', '', x) for x in LABELS]

# 번호/가나다 항목으로 인정하려면 뒤에 실질 내용이 있어야 한다 (날짜 '20. 3. 1.' 배제)
SUBSTANCE = re.compile(r'[가-힣A-Za-z]')   # 공백 제거 후 글자가 2자 이상인지로 판정


def squash(s):
    """공백 정리. 단어 경계(한 칸)는 보존한다."""
    s = s.replace('­', '').replace('‐', '-')
    s = s.replace('‑', '-').replace('–', '-')
    core = s.replace(' ', '')
    # 자간 벌림('유 학', '국   적')만 붙인다
    if len(core) <= 20 and len(re.findall(r'(?<![가-힣])[가-힣](?=\s)', s)) >= 3:
        s = re.sub(r'(?<=[가-힣])\s+(?=[가-힣])', '', s)
    return re.sub(r'\s{2,}', ' ', s).strip()


def norm_code(s):
    """'E- 7' -> 'E-7'. 다른 판·다른 문서 대비 정규화."""
    return re.sub(r'\b([A-Z])-\s+(\d)', r'\1-\2', s)


def label_state(buf):
    """buf 가 업무명으로 완성됐는가 / 아직 모으는 중인가."""
    k = re.sub(r'[\s·]', '', buf)
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


def convert(pages, title, code, version='2026-11-16'):
    out = ['---', f'doc_id: {code}', f'title: {title}',
           'source: 법무부 출입국·외국인정책본부 「체류민원 자격별 안내 매뉴얼」',
           f'version: {version}', '---', '', f'# {title}', '']
    buf, hold, last_lab = [], [], None

    def flush(lab=None):
        nonlocal hold, last_lab
        if lab and lab != last_lab:
            out.extend(['', f'## {lab}', ''])
            last_lab = lab
        out.extend(hold)
        hold = []

    for pno, page in pages:
        out.append(f'<!-- page: {pno} -->')
        buf = []                                   # [수정2] 페이지 경계에서 버퍼 초기화
        for raw in page.split('\n'):
            if not raw.strip() or any(p.match(raw) for p in NOISE):
                continue
            raw = re.sub(r'^\s*[~\u243e\ufffd]+\s*목차\s*', '', raw)   # [수정4] 본문 앞 목차 링크
            if not raw.strip():
                continue
            left, rest = split_left(raw)
            if left is None:
                cand = squash(raw)
                lab, part = label_state(' '.join(buf + [cand]))
                if lab:
                    buf = []
                    flush(lab)
                    continue
                if part and len(cand) <= 18:
                    buf.append(cand)
                    continue
            if left:
                lab, partial = label_state(' '.join(buf + [left]))
                if not lab and not partial:
                    lab, partial = label_state(left)   # [수정1] 단독 매칭 fallback
                    if lab or partial:
                        buf = []
                if lab:
                    buf = []
                    flush(lab)
                elif partial:
                    buf.append(left)
                    continue
                else:
                    rest = left + ' ' + rest
                    buf = []
            line = norm_code(squash(rest))
            if not line or re.fullmatch(r'[가-힣]{2,8}\([A-Z]-\d+\)', line):
                continue
            # [수정3] 날짜·빈칸을 번호 항목으로 오인하지 않는다
            if re.match(r'^\d{1,2}\.\s', line) and len(re.sub(r'[^가-힣A-Za-z]', '', line[2:])) >= 2:
                hold.extend(['', f'### {line}', ''])
            elif re.match(r'^[가-힣]\.\s', line) and len(re.sub(r'[^가-힣A-Za-z]', '', line[2:])) >= 2:
                hold.extend(['', f'#### {line}', ''])
            elif re.match(r'^[□■]', line):
                hold.append('- ' + line.lstrip('□■ '))
            else:
                hold.append(line)
            if len(hold) > 6:
                flush()
    flush()
    return '\n'.join(out) + '\n'


if __name__ == '__main__':
    txt = open(sys.argv[1], encoding='utf-8').read()
    pages = txt.split('\f')
    a, b = int(sys.argv[2]), int(sys.argv[3])
    sel = [(i + 1, pages[i]) for i in range(a - 1, min(b, len(pages)))]
    sys.stdout.write(convert(sel, sys.argv[4], sys.argv[5]))
