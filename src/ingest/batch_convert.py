# -*- coding: utf-8 -*-
"""31개 체류자격 절을 일괄 변환한다.

사용: python src/ingest/batch_convert.py --text cheryu.txt --out /tmp/corpus
  cheryu.txt 는 `pdftotext -layout` 로 뽑은 전체 텍스트(쪽 구분 \\f).

주의: 현재 docs/corpus/*.md 는 이 스크립트를 다시 돌려 만든 것이 아니다.
수정 12 (docs/conversion_notes.md) 는 좌표 기반 재배치(placement_v1.jsonl)로 고쳤다.
이 스크립트는 변환기 규칙(pdf_to_md.py)이 바뀌었을 때 처음부터 다시 만드는 경로로 남겨 둔다.
"""
import argparse
import os
import re
import sys

try:
    from ingest import pdf_to_md as C
except ImportError:                                  # 스크립트로 직접 실행
    import pdf_to_md as C

# 한 자격 절 안에 다른 자격의 표가 쪽 중간부터 들어 있는 경우. (코드, 이름, 시작쪽, 끝쪽, 들어 있는 절의 코드)
# 시작쪽은 부모 절과 같은 쪽을 공유한다. 쪽 안의 시작 줄은 변환 때 정할 수 없고
# derive_placement 가 PDF 좌표로 정해 split_doc 작업으로 적는다 (수정 12 M3d).
EMBEDDED = [
    ('E-2', '회화지도', 174, 185, 'E-1'),
    ('F-5', '영주', 427, 473, 'F-3'),
]

WIDE_ANNEX = [
    ('F-4F-5', '재외동포·영주 특례', 528, 662),
    # 2단 표가 아닌 부록. 평가셋이 이 범위를 근거로 쓰므로 반드시 포함한다.
    ('ANNEX', '붙임 서식 및 취업제한분야', 663, 704),
    ('WIDE', '광역형 비자 시범사업', 705, 796),
]
H1_END = 527      # H-1 끝. 이후는 동포 특례 + 붙임이라 별도 처리


def find_sections(pages):
    """쪽 목록 -> [[시작쪽, 코드, 이름, 끝쪽], ...] (자격 절만)"""
    cand = []
    for i, p in enumerate(pages, 1):            # 절 시작 감지 (페이지 첫 2줄에 '명칭(코드)' 단독)
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
        seen.add(cd)
        last = pg
        secs.append([pg, cd, nm])
    for k in range(len(secs) - 1):
        secs[k].append(secs[k + 1][0] - 1)
    secs[-1].append(H1_END)
    return secs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--text', required=True, help='pdftotext -layout 출력 파일')
    ap.add_argument('--out', required=True, help='md 를 쓸 폴더')
    a = ap.parse_args(argv)

    pages = open(a.text, encoding='utf-8').read().split('\f')
    secs = find_sections(pages)
    for code, name, start, end, parent in EMBEDDED:
        for s in secs:
            if s[1] == parent:
                s[3] = start                # 부모는 시작쪽까지 (그 쪽은 둘이 나눠 쓴다)
        secs.append([start, code, name, end])
    for code, name, start, end in WIDE_ANNEX:
        secs.append([start, code, name, end])

    os.makedirs(a.out, exist_ok=True)
    for pg, cd, nm, end in secs:
        title = f'{nm}({cd})'
        doc_id = 'DOC-' + cd.replace('-', '')
        sel = [(i + 1, pages[i]) for i in range(pg - 1, min(end, len(pages)))]
        md = C.convert(sel, title, doc_id)
        fn = os.path.join(a.out, f'{doc_id}_{nm}.md')
        with open(fn, 'w', encoding='utf-8', newline='\n') as f:
            f.write(md)
        h2 = len(re.findall(r'^## ', md, re.M))
        print(f'  {doc_id:10} {title:16} p.{pg}-{end:4}  {end-pg+1:3}쪽  ##{h2:3}개  {len(md):7}자')

    print(f'\n총 {len(secs)}개 자격 변환 완료')
    return 0


if __name__ == '__main__':
    sys.exit(main())
