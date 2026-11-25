# -*- coding: utf-8 -*-
"""31개 체류자격 절을 일괄 변환한다."""
import re, sys, os, subprocess
import convert as C

txt = open('/tmp/cheryu.txt', encoding='utf-8').read()
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
secs.append([528, 'F-4F-5', '재외동포·영주 특례', 662])
# 2단 표가 아닌 부록. 평가셋이 이 범위를 근거로 쓰므로 반드시 포함한다.
secs.append([663, 'ANNEX', '붙임 서식 및 취업제한분야', 704])
secs.append([705, 'WIDE', '광역형 비자 시범사업', 796])

os.makedirs('/tmp/corpus', exist_ok=True)
unknown = {}
for pg, cd, nm, end in secs:
    title = f'{nm}({cd})'
    doc_id = 'DOC-' + cd.replace('-', '')
    sel = [(i + 1, pages[i]) for i in range(pg - 1, min(end, len(pages)))]
    md = C.convert(sel, title, doc_id)
    fn = f'/tmp/corpus/{doc_id}_{nm}.md'
    open(fn, 'w', encoding='utf-8').write(md)
    h2 = len(re.findall(r'^## ', md, re.M))
    print(f'  {doc_id:10} {title:16} p.{pg}-{end:4}  {end-pg+1:3}쪽  ##{h2:3}개  {len(md):7}자')

print(f'\n총 {len(secs)}개 자격 변환 완료')
