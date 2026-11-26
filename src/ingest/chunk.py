# -*- coding: utf-8 -*-
"""구조화 Markdown -> 청크 (chunks.jsonl)

청킹 단위는 #### (가./나./다. 항목). #### 가 없는 구간은 ### 또는 ## 를 쓴다.
상위 제목은 버리지 않고 메타데이터(path)로 보존해 맥락을 유지한다.

본문이 없거나(20자 미만) 짧은 제목은 예전에는 버렸다(bodyless_heading_mode="drop").
이제는 "fold" 가 기본이다: 같은 부모·같은 수준의 연속된 짧은 제목들을 한 청크로 묶는다.
  - 본문 없는 제목 바로 뒤에 더 깊은 제목이 오면(deeper) 묶지 않는다. 그 제목은 자식의 location 에 남는다.
  - 목차 점선 줄, '<삭제>' 항목은 묶지 않는다.
  - 묶음 청크의 chunk_id 는 make_id(seq='h{n}') 이고 본문 청크의 ID·순번(seen_loc)에는 영향이 없다.
  - chunk_kind 키: 'body' | 'fold' (해시에 넣지 않는다)

사용: python chunk.py "docs/corpus/*.md" > data/chunks.jsonl
      python chunk.py --bodyless-mode drop "docs/corpus/*.md"     # 예전(idx-v2) 동작
기본값은 configs/base.toml [index] 의 bodyless_heading_mode / min_chunk_chars 와 같아야 한다
(tests/test_corpus_invariants.py 가 확인한다).
"""
import argparse
import glob
import hashlib
import json
import re
import sys

MAXLEN = 1200          # 이보다 길면 문단 경계로 더 쪼갠다
CODE = re.compile(r'[A-Za-z]-\d+(?:-\d+)?')

# configs/base.toml [index] 와 같은 값. 바꾸면 두 곳을 함께 바꾼다.
DEFAULT_BODYLESS_MODE = 'fold'
DEFAULT_MIN_CHARS = 20

TOC_DOTS = re.compile(r'[·․⋯∙・.]{4,}')                 # 목차 점선(+쪽번호)
NUM_PREFIX = re.compile(r'^(?:\d{1,2}\.|[가-힣]\.|[①-⑳])\s*')
DELETED = re.compile(r'^\W*<삭제>\W*$')


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


def _is_noise(title, body):
    """접지 않을 항목: 목차 점선 줄, '<삭제>' 만 있는 항목."""
    if TOC_DOTS.search(title) or TOC_DOTS.search(body):
        return True
    if not body and DELETED.match(NUM_PREFIX.sub('', title)):
        return True
    return False


def _read_sections(raw):
    """본문을 제목 단위 구간 목록으로 나눈다.

    구간 하나 = 제목 한 줄 + 다음 제목 전까지의 본문. 제목 앞의 본문은 level 0 구간.
    page_open = 제목 줄을 읽을 때의 쪽, page_close = 다음 제목(또는 EOF)을 읽을 때의 쪽
    (본문 청크의 page 는 예전부터 page_close 다).
    """
    stack = []                     # [(제목 수준, 제목)] — 실제 중첩을 추적한다
    path0 = None
    secs = []
    page = None
    cur = {'level': 0, 'title': None, 'parent': [], 'path': None, 'page_open': None, 'buf': []}

    def close():
        cur['page_close'] = page
        secs.append(cur)

    for line in raw.split('\n'):
        pg = re.match(r'^<!-- page: (\d+) -->$', line)
        if pg:
            page = int(pg.group(1))
            continue
        h = re.match(r'^(#{1,4})\s+(.*)$', line)
        if h:
            level, title = len(h.group(1)), h.group(2).strip()
            close()
            # 같거나 더 깊은 수준은 걷어내고 쌓는다.
            # path[:level-1] 로 자르면 '##' 다음에 '###' 없이 '####' 가 올 때
            # 형제인 '가./나./다.' 가 서로 부모-자식으로 엮인다.
            #   (잘못) 체류기간 연장허가 > 가. 기본원칙 > 다. 제출서류
            #   (바름) 체류기간 연장허가 > 다. 제출서류
            parent_stack = list(stack)
            if level == 1:
                stack = []
                path0 = title
            else:
                while stack and stack[-1][0] >= level:
                    stack.pop()
                parent_stack = list(stack)
                stack.append((level, title))
            cur = {'level': level, 'title': title,
                   'parent': [path0] + [t for _, t in parent_stack] if level > 1 else [],
                   'path': [path0] + [t for _, t in stack] if level > 1 else [title],
                   'page_open': page, 'buf': []}
            continue
        cur['buf'].append(line)
    close()
    return secs


def parse(md_path, bodyless=DEFAULT_BODYLESS_MODE, min_chars=DEFAULT_MIN_CHARS):
    if bodyless not in ('drop', 'fold'):
        raise ValueError(f'bodyless 는 drop|fold 여야 한다: {bodyless!r}')
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
    doc_title = fm.get('title', '')
    secs = _read_sections(raw)
    for s in secs:                       # 첫 # 제목 앞 구간은 경로가 문서 제목뿐이다
        if s['path'] is None:
            s['path'] = [doc_title]
    # 첫 # 제목이 없는 문서 대비: path[0] 이 None 이면 문서 제목으로 대체
    for s in secs:
        s['path'] = [p if p is not None else doc_title for p in s['path']]
        s['parent'] = [p if p is not None else doc_title for p in s['parent']]

    out = []
    seen_loc = {}          # 경로 -> 지금까지 몇 번 나왔는지 (본문 청크 전용)
    seen_fold = {}         # 경로 -> 묶음 청크 순번 (묶음 청크 전용)

    def base(loc_shown, page, path_for_codes, part, chunk_id, kind):
        return {
            'chunk_id': chunk_id,
            'doc_id': doc_id,
            'doc_title': doc_title,
            'doc_version': fm.get('version', ''),
            'source': fm.get('source', ''),
            'location': loc_shown,
            'page': page,
            'visa_codes': sorted(set(CODE.findall(' '.join(path_for_codes) + ' ' + part))),
            'text': part,
            'chunk_kind': kind,
        }

    def emit_body(path, page, text):
        loc = ' > '.join([p for p in path if p])
        for part in split_long(text):
            seq = seen_loc.get(loc, 0)
            seen_loc[loc] = seq + 1
            # 같은 경로가 두 번 이상이면 인용할 때 구분되도록 순번을 붙인다
            loc_shown = loc if seq == 0 else f'{loc} ({seq + 1})'
            out.append(base(loc_shown, page, path, part, make_id(doc_id, path, part, seq), 'body'))

    def emit_fold(items):
        if len(items) >= 2:
            path = items[0]['parent']
        else:
            path = items[0]['path']
        loc = ' > '.join([p for p in path if p])
        text = '\n'.join(i['text'] for i in items)
        for part in split_long(text):
            n = seen_fold.get(loc, 0)
            seen_fold[loc] = n + 1
            loc_shown = loc if n == 0 else f'{loc} ({n + 1})'
            out.append(base(loc_shown, items[0]['page'], path, part,
                            make_id(doc_id, path, part, f'h{n}'), 'fold'))

    pending = []                         # 아직 묶음에 모으는 중인 항목들

    def flush():
        if pending:
            emit_fold(list(pending))
            pending.clear()

    for i, s in enumerate(secs):
        body = '\n'.join(s['buf']).strip()
        if len(re.sub(r'\s', '', body)) >= min_chars:    # 충분한 본문 -> 본문 청크
            flush()
            emit_body(s['path'], s['page_close'], body)
            continue
        # 짧거나 없는 본문
        if bodyless != 'fold' or s['level'] < 2:         # 예전 동작: 버린다 (level 0/1 은 늘 버린다)
            flush()
            continue
        nxt = secs[i + 1] if i + 1 < len(secs) else None
        if not body and nxt is not None and nxt['level'] > s['level']:
            flush()                      # deeper: 제목은 자식 location 에 남는다
            continue
        if _is_noise(s['title'], body):
            continue                     # 목차 점선·<삭제> 는 건너뛴다 (묶음을 끊지 않는다)
        text = s['title'] + ('\n' + body if body else '')
        key = (tuple(s['parent']), s['level'])
        if pending and (tuple(pending[0]['parent']), pending[0]['level']) != key:
            flush()
        pending.append({'parent': s['parent'], 'path': s['path'], 'level': s['level'],
                        'page': s['page_open'], 'text': text})
    flush()
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description='구조화 Markdown -> chunks.jsonl (stdout)')
    ap.add_argument('patterns', nargs='+', help='md 파일 또는 glob')
    ap.add_argument('--bodyless-mode', choices=('drop', 'fold'), default=DEFAULT_BODYLESS_MODE)
    ap.add_argument('--min-chars', type=int, default=DEFAULT_MIN_CHARS)
    a = ap.parse_args(argv)
    # Windows 콘솔 기본 인코딩(cp1252/cp949)으로는 한글 출력이 깨지거나 실패한다. 줄바꿈도 LF 로 고정
    sys.stdout.reconfigure(encoding='utf-8', newline='\n')
    rows = []
    for pattern in a.patterns:
        for f in sorted(glob.glob(pattern)):
            rows += parse(f, bodyless=a.bodyless_mode, min_chars=a.min_chars)
    for r in rows:
        print(json.dumps(r, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
