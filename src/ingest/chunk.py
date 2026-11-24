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
    path = [fm.get('title', '')]
    page = None
    buf, out = [], []
    seen_loc = {}          # 경로 -> 지금까지 몇 번 나왔는지

    def emit():
        text = '\n'.join(buf).strip()
        if len(re.sub(r'\s', '', text)) < 20:        # 너무 짧은 조각은 버린다
            return
        loc = ' > '.join([p for p in path if p])
        for part in split_long(text):
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
                'page': page,
                'visa_codes': sorted(set(CODE.findall(' '.join(path) + ' ' + part))),
                'text': part,
            })

    def split_long(text):
        if len(text) <= MAXLEN:
            return [text]
        parts, cur = [], []
        for line in text.split('\n'):
            cur.append(line)
            if len('\n'.join(cur)) > MAXLEN:
                parts.append('\n'.join(cur))
                cur = []
        if cur:
            parts.append('\n'.join(cur))
        return parts

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
            path = path[:level - 1] + [title] if level > 1 else [title]
            continue
        buf.append(line)
    if buf:
        emit()
    return out


if __name__ == '__main__':
    rows = []
    for pattern in sys.argv[1:]:
        for f in sorted(glob.glob(pattern)):
            rows += parse(f)
    for r in rows:
        print(json.dumps(r, ensure_ascii=False))
