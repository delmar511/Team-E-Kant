# -*- coding: utf-8 -*-
"""두 chunks.jsonl(예: idx-v2 / idx-v3)의 chunk_id 대응표를 만든다. 표준 라이브러리만 쓴다.

chunk_id = sha1(doc_id | 경로 | 순번 | 본문 앞 200자) 이므로, ID 가 바뀐 이유는 네 가지 중 하나다.
  doc_split  문서가 갈라져 doc_id 가 바뀜 (F-3 -> F-5, E-1 -> E-2)
  path       제목 경로(location 에서 순번을 뺀 것)가 바뀜 (`##` 이동·삽입)
  head200    본문 앞 200자가 바뀜 (라벨 조각 제거, 줄이 다른 청크로 이동)
  seq_shift  같은 경로의 순번이 바뀜 (같은 경로의 앞쪽 청크가 늘거나 줄어서)
  unchanged  ID 가 그대로
짝을 못 찾으면 removed(옛 청크만 있음) / added(새 청크만 있음).

짝 찾기: 본문이 같은 것 -> 앞 200자가 같은 것 -> 줄 겹침이 가장 큰 것 순서로, 같은 문서를 먼저 본다.

사용: python src/ingest/chunk_diff.py data/chunks.jsonl new/chunks.jsonl --out chunk_diff.jsonl
"""
import argparse
import collections
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

REASONS = ('unchanged', 'path', 'head200', 'seq_shift', 'doc_split', 'removed', 'added')
MIN_OVERLAP = 0.4


@dataclass
class IdChange:
    reason: str
    old_id: str = None
    new_id: str = None
    old_doc: str = None
    new_doc: str = None
    old_location: str = None
    new_location: str = None
    old_page: int = None
    new_page: int = None


def _base(loc):
    return re.sub(r' \(\d+\)$', '', loc or '')


def read_chunks(path):
    return [json.loads(l) for l in Path(path).read_text(encoding='utf-8').split('\n') if l.strip()]


def _reason(old, new):
    if old['doc_id'] != new['doc_id']:
        return 'doc_split'
    if _base(old['location']) != _base(new['location']):
        return 'path'
    if old['text'][:200] != new['text'][:200]:
        return 'head200'
    return 'seq_shift'


def _lineset(c):
    return {l.strip() for l in c['text'].split('\n') if l.strip()}


def diff(old, new):
    """청크 목록 두 개 -> [IdChange]"""
    new_by_id = {c['chunk_id']: c for c in new}
    changes, used_new = [], set()
    pending = []
    for o in old:
        n = new_by_id.get(o['chunk_id'])
        if n is not None and n['doc_id'] == o['doc_id']:
            used_new.add(n['chunk_id'])
            changes.append(_mk('unchanged', o, n))
        else:
            pending.append(o)

    free = [c for c in new if c['chunk_id'] not in used_new]
    by_text = collections.defaultdict(list)
    by_head = collections.defaultdict(list)
    for c in free:
        by_text[c['text']].append(c)
        by_head[c['text'][:200]].append(c)
    sets = {c['chunk_id']: _lineset(c) for c in free}

    def pick(cands, o):
        cands = [c for c in cands if c['chunk_id'] not in used_new
                 and (c['doc_id'] == o['doc_id'] or _split_pair(o, c))]
        if not cands:
            return None
        cands.sort(key=lambda c: (c['doc_id'] != o['doc_id'], _base(c['location']) != _base(o['location']),
                                  abs((c.get('page') or 0) - (o.get('page') or 0))))
        return cands[0]

    rest = []
    for o in pending:
        n = pick(by_text.get(o['text'], []), o) or pick(by_head.get(o['text'][:200], []), o)
        if n is None:
            rest.append(o)
            continue
        used_new.add(n['chunk_id'])
        changes.append(_mk(_reason(o, n), o, n))
    for o in rest:
        so = _lineset(o)
        best, score = None, 0.0
        for c in free:
            if c['chunk_id'] in used_new or (c['doc_id'] != o['doc_id'] and not _split_pair(o, c)):
                continue
            sc = len(so & sets[c['chunk_id']]) / max(1, len(so))
            if sc > score:
                best, score = c, sc
        if best is not None and score >= MIN_OVERLAP:
            used_new.add(best['chunk_id'])
            changes.append(_mk(_reason(o, best), o, best))
        else:
            changes.append(_mk('removed', o, None))
    for c in new:
        if c['chunk_id'] not in used_new:
            changes.append(_mk('added', None, c))
    return changes


def _split_pair(o, c):
    """문서 분리로 doc_id 가 바뀔 수 있는 쌍(F-3->F-5, E-1->E-2)인가."""
    return (o['doc_id'], c['doc_id']) in {('DOC-F3', 'DOC-F5'), ('DOC-E1', 'DOC-E2')}


def _mk(reason, o, n):
    return IdChange(reason, o and o['chunk_id'], n and n['chunk_id'], o and o['doc_id'], n and n['doc_id'],
                    o and o['location'], n and n['location'], o and o.get('page'), n and n.get('page'))


def summarize(changes):
    by_reason = collections.Counter(c.reason for c in changes)
    per_doc = collections.defaultdict(collections.Counter)
    for c in changes:
        per_doc[c.old_doc or c.new_doc][c.reason] += 1
    return by_reason, per_doc


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('old')
    ap.add_argument('new')
    ap.add_argument('--out', help='대응표 JSON Lines')
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding='utf-8')
    old, new = read_chunks(a.old), read_chunks(a.new)
    ch = diff(old, new)
    if a.out:
        with open(a.out, 'w', encoding='utf-8', newline='\n') as f:
            for c in ch:
                f.write(json.dumps(asdict(c), ensure_ascii=False) + '\n')
    by_reason, per_doc = summarize(ch)
    print(f'옛 청크 {len(old)}개, 새 청크 {len(new)}개')
    for r in REASONS:
        print(f'  {r:10} {by_reason[r]}')
    changed_old = sum(by_reason[r] for r in ('path', 'head200', 'seq_shift', 'doc_split', 'removed'))
    print(f'옛 chunk_id 가 바뀌거나 사라진 수: {changed_old}')
    print('문서별:')
    for d in sorted(per_doc):
        print(f'  {d:10} ' + ' '.join(f'{r}={per_doc[d][r]}' for r in REASONS if per_doc[d][r]))
    return 0


if __name__ == '__main__':
    sys.exit(main())
