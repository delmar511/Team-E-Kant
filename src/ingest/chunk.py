# -*- coding: utf-8 -*-
"""구조화 Markdown -> 청크 (chunks.jsonl)

청킹 단위는 #### (가./나./다. 항목). #### 가 없는 구간은 ### 또는 ## 를 쓴다.
상위 제목은 버리지 않고 메타데이터(path)로 보존해 맥락을 유지한다.

사용: python chunk.py docs/corpus/*.md > data/chunks.jsonl
"""
import glob
import hashlib
import json
import re
import sys

MAXLEN = 1200          # 이보다 길면 문단 경계로 더 쪼갠다
CODE = re.compile(r'[A-Za-z]-\d+(?:-\d+)?')


def make_id(doc_id, path, text, seq):
    """결정적 청크 ID. 같은 입력 -> 같은 ID.

    매뉴얼은 같은 제목 아래 같은 문장을 여러 곳에 반복해 싣는다
    (예: F-4 자격부여 요건이 p.601 과 p.618 에 동일하게 등장).
    doc_id + 경로 + 본문만 해싱하면 이런 청크가 같은 ID 를 받아
    평가셋의 gold_chunks 가 어느 쪽을 가리키는지 알 수 없게 된다.
    문서 안에서 같은 경로가 몇 번째로 나왔는지(seq)를 섞어 구분한다.
    """
    key = f'{doc_id}|{">".join(path)}|{seq}|{text[:200]}'
    h = hashlib.sha1(key.encode('utf-8'))
    return f"{doc_id}#{h.hexdigest()[:10]}"


def parse(md_path):
    raw = open(md_path, encoding='utf-8').read()
    fm = {}
    m = re.match(r'^---\n(.*?)\n---\n', raw, re.S)
    if m:
        for line in m.group(1).split('\n'):
            if ':' in line:
                k, v = line.split(':', 1)
                fm[k.strip()] = v.strip()
        raw = raw[m.end():]

    doc_id = fm.get('doc_id', 'DOC')
    stack = []                     # [(제목 수준, 제목)] — 실제 중첩을 추적한다
    path = [fm.get('title', '')]
    page = None
    # buf 는 (줄, 그 줄이 속한 쪽) 쌍. 청크의 page 는 첫 본문 줄의 쪽이다.
    # (예전에는 emit 시점의 쪽 = 구간이 끝나는 쪽을 넣어, 여러 쪽에 걸친 구간이
    #  끝 쪽으로 기록됐다. 예: D-2 '라. 제출서류' 는 p.45 에서 시작하는데 p.55)
    buf, out = [], []
    seen_loc = {}          # 경로 -> 지금까지 몇 번 나왔는지

    def emit():
        text = '\n'.join(line for line, _ in buf).strip()
        if len(re.sub(r'\s', '', text)) < 20:        # 너무 짧은 조각은 버린다
            return
        loc = ' > '.join([p for p in path if p])
        for part, part_page in split_long(buf):
            seq = seen_loc.get(loc, 0)
            seen_loc[loc] = seq + 1
            # 같은 경로가 두 번 이상이면 인용할 때 구분되도록 순번을 붙인다
            loc_shown = loc if seq == 0 else f'{loc} ({seq + 1})'
            out.append({
                'chunk_id': make_id(doc_id, path, part, seq),
                'doc_id': doc_id,
                'doc_title': fm.get('title', ''),
                'doc_version': fm.get('version', ''),
                'source': fm.get('source', ''),
                'location': loc_shown,
                'page': part_page,
                'visa_codes': sorted(set(CODE.findall(' '.join(path) + ' ' + part))),
                'text': part,
            })

    def first_page(rows):
        """조각의 첫 본문(공백 아닌) 줄이 속한 쪽."""
        for line, pg in rows:
            if line.strip():
                return pg
        return rows[0][1] if rows else page

    def split_long(rows):
        """rows: [(줄, 쪽)] -> [(조각 본문, 조각 첫 줄의 쪽)]. 본문은 예전과 같게 자른다."""
        rows = list(rows)
        # 앞뒤 빈 줄 제거 (예전 text.strip() 과 같은 효과. 청크 본문·ID 를 바꾸지 않기 위함)
        while rows and not rows[0][0].strip():
            rows.pop(0)
        while rows and not rows[-1][0].strip():
            rows.pop()
        text = '\n'.join(line for line, _ in rows).strip()
        lines = text.split('\n')                 # strip 은 첫·끝 줄 안쪽 공백만 지우므로 줄 수는 같다
        assert len(lines) == len(rows)
        rows = list(zip(lines, (pg for _, pg in rows)))
        if len(text) <= MAXLEN:
            return [(text, first_page(rows))]
        parts, cur = [], []
        for row in rows:
            cur.append(row)
            if len('\n'.join(line for line, _ in cur)) > MAXLEN:
                parts.append(cur)
                cur = []
        if cur:
            parts.append(cur)
        return [('\n'.join(line for line, _ in p), first_page(p)) for p in parts]

    for line in raw.split('\n'):
        pg = re.match(r'^<!-- page: (\d+) -->$', line)
        if pg:
            page = int(pg.group(1))
            continue
        h = re.match(r'^(#{1,4})\s+(.*)$', line)
        if h:
            level, title = len(h.group(1)), h.group(2).strip()
            if buf:
                emit()
                buf = []
            # 같거나 더 깊은 수준은 걷어내고 쌓는다.
            # path[:level-1] 로 자르면 '##' 다음에 '###' 없이 '####' 가 올 때
            # 형제인 '가./나./다.' 가 서로 부모-자식으로 엮인다.
            #   (잘못) 체류기간 연장허가 > 가. 기본원칙 > 다. 제출서류
            #   (바름) 체류기간 연장허가 > 다. 제출서류
            if level == 1:
                stack = []
                path = [title]
            else:
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, title))
                path = [path[0]] + [t for _, t in stack]
            continue
        buf.append((line, page))
    if buf:
        emit()
    return out


if __name__ == '__main__':
    # Windows 콘솔 기본 인코딩(cp1252/cp949)으로는 한글 출력이 깨지거나 실패한다. 줄바꿈도 LF 로 고정
    sys.stdout.reconfigure(encoding='utf-8', newline='\n')
    rows = []
    for pattern in sys.argv[1:]:
        for f in sorted(glob.glob(pattern)):
            rows += parse(f)
    for r in rows:
        print(json.dumps(r, ensure_ascii=False))
