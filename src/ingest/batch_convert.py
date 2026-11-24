# -*- coding: utf-8 -*-
"""체류민원 매뉴얼 전체를 자격별 Markdown 으로 일괄 변환한다.

선행 조건: poppler 의 pdftotext 로 PDF 를 텍스트로 뽑아둘 것.
    pdftotext -layout 매뉴얼.pdf cheryu.txt

사용: python src/ingest/batch_convert.py cheryu.txt docs/corpus
"""
import os
import re
import sys

import pdf_to_md as C

if len(sys.argv) < 3:
    sys.exit('사용: python batch_convert.py <텍스트파일> <출력폴더>')

SRC, OUT = sys.argv[1], sys.argv[2]

txt = open(SRC, encoding='utf-8').read()
pages = txt.split('\f')

# 절 시작 감지 (페이지 첫 2줄에 '명칭(코드)' 단독)
cand = []
for i, p in enumerate(pages, 1):
    for l in [x.strip() for x in p.split('\n') if x.strip()][:2]:
        m = re.fullmatch(r'([가-힣·]{2,14})\(([A-Z]-\d+)\)', re.sub(r'\s+', '', l))
        if m:
            cand.append((i, m.group(2), m.group(1)))
            break

# 오탐 제거를 먼저 한다. 뒤로 미루면 seen 에 이미 들어가서
# 진짜 절(G-1 p.498)까지 같이 날아간다.
cand = [c for c in cand if not (c[1] == 'G-1' and c[0] < 400)]

# 페이지가 증가하고 코드가 처음 나오는 것만 채택 (중간 오탐 제거)
secs, seen, last = [], set(), 0
for pg, cd, nm in cand:
    if cd in seen or pg < last:
        continue
    seen.add(cd); last = pg
    secs.append([pg, cd, nm])
for k in range(len(secs) - 1):
    secs[k].append(secs[k + 1][0] - 1)
secs[-1].append(527)          # H-1 끝. 이후는 동포 특례 + 붙임이라 별도 처리
secs.append([528, 'F-4F-5', '재외동포·영주 특례', 662])   # 붙임 직전까지

os.makedirs(OUT, exist_ok=True)
for pg, cd, nm, end in secs:
    title = f'{nm}({cd})'
    doc_id = 'DOC-' + cd.replace('-', '')
    sel = [(i + 1, pages[i]) for i in range(pg - 1, min(end, len(pages)))]
    md = C.convert(sel, title, doc_id)
    fn = os.path.join(OUT, f'{doc_id}_{nm}.md'.replace('\u00b7', '').replace(' ', ''))
    open(fn, 'w', encoding='utf-8').write(md)
    h2 = len(re.findall(r'^## ', md, re.M))
    print(f'  {doc_id:10} {title:16} p.{pg}-{end:4}  {end-pg+1:3}쪽  ##{h2:3}개  {len(md):7}자')

print(f'\n총 {len(secs)}개 자격 변환 완료')
