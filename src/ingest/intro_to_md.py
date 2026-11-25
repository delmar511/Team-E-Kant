# -*- coding: utf-8 -*-
"""매뉴얼 앞부분(유의사항·공통사항) -> DOC-INTRO Markdown

본문 장(14쪽~)은 2단 표라 pdf_to_md.convert 로 변환하지만, 앞부분은 표가 아니라서
같은 규칙을 쓰면 '1. ...' 번호 항목이 ### 제목으로 올라가 문장이 반으로 잘린다
(뒷부분이 20자 미만이면 청킹에서 버려진다). 그래서 쪽별 주제를 ## 로 두고
번호 항목은 목록 한 줄로 이어붙이는 전용 변환을 쓴다.

변환 범위 (docs/conversion_notes.md 수정 11)
  p.3      유의사항
  p.4      공통사항 목차
  p.5      심사수수료 표  -> 아래 FEES 로 옮겨 적음 (-layout 추출은 칸이 뒤섞인다)
  p.6-8    공통사항 1~4
  p.12-13  공통사항 5 (결핵진단서)
제외: p.1 표지, p.2 목차, p.9-11 외국인 직업 신고서 빈 서식

입력: pdftotext -enc UTF-8 -layout 로 뽑은 텍스트 (페이지 구분 \\f)
사용: python src/ingest/intro_to_md.py cheryu.txt > docs/corpus/DOC-INTRO_유의사항및공통사항.md
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pdf_to_md import NOISE, norm_code, squash  # noqa: E402

DOC_ID = 'DOC-INTRO'
TITLE = '유의사항 및 공통사항(INTRO)'
VERSION = '2026-11-16'
PAGES = [3, 4, 5, 6, 7, 8, 12, 13]
CONTINUES = {13}            # 제목 없이 앞 쪽(12쪽)이 이어지는 쪽
FEE_PAGE = 5

# p.5 심사수수료. pdftotext -raw 는 내용 스트림 순서대로 업무명-수수료를 한 줄씩 내고
# -table / -simple 도 같은 짝을 낸다 (세 방식 대조). '결혼이민(F-6)' 두 줄은
# 바로 윗줄 업무의 결혼이민자 감액 행이다 (부여 8만->4만, 연장 6만->3만).
# 근거 법령 칸은 행 병합이라 어느 행까지인지 추출로 확정할 수 없어 표 밖에 적는다.
FEES = [
    ('체류자격 외 활동허가', '12만원'),
    ('근무처의 변경·추가', '12만원'),
    ('체류자격 부여', '8만원'),
    ('체류자격 부여 - 결혼이민(F-6)', '4만원'),
    ('체류자격 변경허가', '10만원'),
    ('영주(F-5) 자격 변경허가', '20만원'),
    ('체류기간 연장허가', '6만원'),
    ('체류기간 연장허가 - 결혼이민(F-6)', '3만원'),
    ('단수재입국허가', '3만원'),
    ('복수재입국허가', '5만원'),
    ('외국인등록증 발급 및 재발급', '3만 5천원'),
    ('거소등록증 발급 및 재발급', '3만 5천원'),
    ('출입국에 관한 사실증명', '2천원'),
    ('외국인등록 사실증명', '2천원'),
    ('국내거소신고 사실증명', '2천원'),
]
FEE_BASIS = ('근거: 출입국관리법 제87조 및 동법 시행규칙 제72조, '
             '재외동포의 출입국과 법적 지위에 관한 법률 시행규칙 제12조')

ITEM = re.compile(r'^(\d{1,2})\.\s+\S')       # 유의사항·목차의 '1. ...' 항목
NEW_LINE = re.compile(r'^[※▣•◯\-*]')          # 원문에서 새 줄로 시작하는 기호
# p.7 소제목. 원문 앞의 기호가 사설영역 글리프라 추출에서 빠져 기호로는 못 가려낸다
LABELS = {'신고대상', '신고시기', '신고방법'}


def clean_lines(page):
    out = []
    for raw in page.split('\n'):
        if not raw.strip() or any(p.match(raw) for p in NOISE):
            continue
        line = norm_code(squash(raw))
        if line:
            out.append(line)
    return out


def join_items(lines):
    """줄바꿈으로 잘린 문장을 잇는다. 번호 항목이나 기호로 시작하는 줄만 새 줄로 둔다."""
    out = []
    for line in lines:
        if not out or ITEM.match(line) or NEW_LINE.match(line) or line in LABELS or out[-1] in LABELS:
            out.append(line)
        else:
            out[-1] += ' ' + line
    return out


def fee_table():
    rows = ['| 업무명 | 수수료 |', '| --- | --- |']
    rows += [f'| {name} | {fee} |' for name, fee in FEES]
    return rows + ['', FEE_BASIS]


def convert(pages):
    out = ['---', f'doc_id: {DOC_ID}', f'title: {TITLE}',
           'source: 법무부 출입국·외국인정책본부 「체류민원 자격별 안내 매뉴얼」',
           f'version: {VERSION}', '---', '', f'# {TITLE}', '']
    for pno in PAGES:
        lines = clean_lines(pages[pno - 1])
        # chunk.py 는 청크를 내보내는 시점의 쪽을 기록한다. 쪽 표시를 ## 앞에 두면
        # 앞 절이 다음 쪽 번호를 받으므로 제목 뒤에 둔다. 이어지는 쪽(13)은 표시를
        # 생략해 그 절이 시작 쪽(12)으로 인용되게 한다.
        if pno not in CONTINUES:
            out += [f'## {lines[0]}', f'<!-- page: {pno} -->', '']
            lines = lines[1:]
        if pno == FEE_PAGE:
            out += fee_table()
        else:
            out += join_items(lines)
        out.append('')
    return '\n'.join(out).rstrip('\n') + '\n'


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', newline='\n')
    text = open(sys.argv[1], encoding='utf-8').read()
    sys.stdout.write(convert(text.split('\f')))
