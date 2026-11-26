# -*- coding: utf-8 -*-
"""평가셋의 근거(evidence)에 chunk_id 를 채운다.

담당: 서종찬 | 평가표 3·5번
실행:
    python src/link_evidence.py eval/eval-dev.json                    # 미리보기만 (quote 모드)
    python src/link_evidence.py eval/eval-dev.json --write            # 파일에 반영
    python src/link_evidence.py eval/eval-test.json --mode page       # quote 가 없는 평가셋: 쪽 기준

왜 section 이 아니라 quote 로 찾나
-------------------------------
평가셋의 `section` 은 사람이 원문을 찾기 위한 자유 형식이다.
'체류자격외 활동 > 3', '나~다', '유의사항' 처럼 청크의 location 과
글자 그대로 맞지 않는 표기가 섞여 있다. 반면 `quote` 는 원문 발췌라
본문에서 직접 찾을 수 있다. 그래서 quote 를 1순위 단서로 쓰고,
section 은 후보가 여럿일 때 가려내는 보조 단서로만 쓴다.

쪽 모드(--mode page)
-------------------
시험셋(eval-test.json)의 근거에는 quote 가 없고 쪽(page)만 있다. 쪽 기준 연결은 틀리기 쉬워서
(같은 쪽에 청크가 여럿이면 어느 것인지 알 수 없다) 보수적으로만 한다.
  - 그 쪽을 쪽 범위에 가진 문서 안에서, 그 쪽에 있는 청크가 정확히 1개일 때만 연결한다.
  - 0개이거나 2개 이상이면 chunk_id 는 null, 후보 목록은 chunk_ids_all 에 남긴다.
  - 다른 문서나 첫 청크로 대체하지 않는다.
  - quote 모드에서도 quote 가 없는 근거는 쪽 모드로 처리한다.

한 근거의 quote 가 여러 청크에 걸치는 경우가 있다(표의 여러 칸을 ' / ' 로
이어붙인 경우). 그때는 chunk_id 에 가장 많이 겹치는 청크를 넣고,
나머지는 chunk_ids_all 에 함께 남겨 사람이 판단할 수 있게 한다.
"""
import argparse
import json
import re
import sys
from pathlib import Path

MIN_FRAG = 8     # 이보다 짧은 조각은 흔한 말이라 단서로 쓰지 않는다
MIN_FRAG_LOOSE = 5   # 1차에서 못 찾았을 때만 쓰는 느슨한 기준
PROBE = 30       # 조각의 앞 N 글자로 찾는다. 뒤쪽은 줄바꿈 때문에 어긋나기 쉽다


def norm(s):
    return re.sub(r'\s', '', s or '')


def fragments(quote, loose=False):
    """quote 를 찾기 좋은 조각들로 나눈다.

    평가셋의 quote 는 원문 여러 줄을 ' / ' 로 이어붙인 형태가 많다.
    통째로 찾으면 줄 사이에 낀 글자(표의 다른 칸 등) 때문에 어긋난다.
    """
    lim = MIN_FRAG_LOOSE if loose else MIN_FRAG
    parts = [norm(p) for p in re.split(r'\s*/\s*', quote)]
    parts = [p for p in parts if len(p) >= lim]
    if not parts:                       # 전부 짧으면 통째로 쓴다
        parts = [norm(quote)]
    return parts


def load_chunks(path):
    """청크를 읽어 (청크, 검색용 문자열) 쌍으로 돌려준다.

    본문뿐 아니라 location 도 검색 대상에 넣는다. 제목이 그대로 인용된
    근거가 있는데('1. \u201c유학(D-2) 자격 체류자격외 활동 허가\u201d 참조'),
    제목은 본문이 아니라 경로로 올라가 있어 text 만 보면 못 찾는다.
    """
    rows = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return [(c, norm(c['location']) + '\u241f' + norm(c['text'])) for c in rows]


def score_section(chunk, section):
    """section 과 location 이 얼마나 겹치는지. 후보가 여럿일 때만 쓴다."""
    a = set(re.split(r'\s*>\s*', norm(section)))
    b = set(re.split(r'\s*>\s*', norm(chunk['location'])))
    return len(a & b)


def _tally(frags, chunks):
    tally, found = {}, 0
    for f in frags:
        probe = f[:PROBE]
        hits = [c for c, t in chunks if probe in t]
        if hits:
            found += 1
        for c in hits:
            tally[c['chunk_id']] = tally.get(c['chunk_id'], 0) + 1
    return tally, found


def link_one(ev, chunks):
    """근거 하나 -> (대표 chunk_id, 전체 후보, 상태)"""
    quote = ev.get('quote') or ''
    page = ev.get('page')
    # 빈 quote 는 단서가 아니다. fragments('') == [''] 이고 '' in 문자열 은 항상 참이라
    # 모든 청크가 후보가 되어 같은 쪽 청크 -> 첫 청크로 떨어졌다 (DOC-A1#f137905102 가 그 결과)
    if not norm(quote):
        return None, [], 'not_found'

    frags = fragments(quote)
    tally, found = _tally(frags, chunks)
    if not tally:                       # 1차 실패 -> 느슨한 기준으로 한 번 더
        frags = fragments(quote, loose=True)
        tally, found = _tally(frags, chunks)

    if not tally:
        return None, [], 'not_found'

    by_id = {c['chunk_id']: c for c, _ in chunks}

    def rank(cid):
        c = by_id[cid]
        same_page = 1 if page is not None and c.get('page') == page else 0
        return (tally[cid], same_page, score_section(c, ev.get('section', '')))

    ordered = sorted(tally, key=rank, reverse=True)
    best = ordered[0]
    status = 'ok' if found == len(frags) else 'partial'
    if len(frags) > 1 and tally[best] < len(frags):
        status = 'spans_multiple' if found == len(frags) else status
    return best, ordered, status


FACTS_N = 8          # expected_facts 를 이 길이로 쪼갠다
FACTS_STEP = 4
FACTS_MIN = 0.20     # 이 비율 이상 겹쳐야 배정한다
FACTS_MARGIN = 3.0   # 2위보다 이 배 이상이어야 배정한다


def _grams(text):
    t = re.sub(r'[\s·ㆍ,./()\[\]「」『』]', '', text or '')
    return {t[i:i + FACTS_N] for i in range(0, max(1, len(t) - FACTS_N + 1), FACTS_STEP)
            if len(t[i:i + FACTS_N]) == FACTS_N}


def link_by_facts(ev, question_facts, chunks, doc_pages):
    """quote 가 없을 때 expected_facts 로 찾는다.

    expected_facts 는 평가셋 작성자가 **원문을 보고** 적은 문장이므로 quote 와 같은
    역할을 한다. 검색 결과를 쓰지 않으므로 순환이 아니다.

    빈 quote 로 모든 청크가 후보가 되던 예전 버그(그 쪽 첫 청크가 그대로 chunk_id 로
    박혔다)의 피해를 되돌리기 위한 모드다.

    확신이 없으면 배정하지 않는다. 겹침 비율이 FACTS_MIN 미만이거나
    2위와 FACTS_MARGIN 배 미만 차이면 'facts_weak' 로 둔다.
    """
    page = ev.get('page')
    if page is None or not question_facts:
        return None, [], 'not_found'
    docs = {d for d, (lo, hi) in doc_pages.items() if lo <= page <= hi}
    cand = [c for c, _ in chunks if c['doc_id'] in docs and c.get('page') == page]
    if not cand:
        return None, [], 'not_found'

    fg = _grams(' '.join(question_facts))
    if not fg:
        return None, [c['chunk_id'] for c in cand], 'page_ambiguous'

    scored = []
    for c in cand:
        t = re.sub(r'[\s·ㆍ,./()\[\]「」『』]', '', c['text'])
        scored.append((sum(1 for g in fg if g in t) / len(fg), c['chunk_id']))
    scored.sort(reverse=True)
    best, runner = scored[0], (scored[1][0] if len(scored) > 1 else 0.0)
    ids = [cid for _, cid in scored]
    if best[0] < FACTS_MIN or best[0] < runner * FACTS_MARGIN:
        return None, ids, 'facts_weak'
    return best[1], ids, 'facts_ok'


def doc_page_ranges(chunks):
    """청크 목록 -> {doc_id: (가장 작은 쪽, 가장 큰 쪽)}. link_by_page 의 doc_pages."""
    rng = {}
    for c, _ in chunks:
        p = c.get('page')
        if p is None:
            continue
        lo, hi = rng.get(c['doc_id'], (p, p))
        rng[c['doc_id']] = (min(lo, p), max(hi, p))
    return rng


def link_by_page(ev, chunks, doc_pages):
    """근거 하나를 쪽으로 연결한다 -> (chunk_id | None, 후보 chunk_id 목록, 상태)

    그 쪽을 쪽 범위(doc_pages)에 가진 문서들 안에서, 청크의 page 가 그 쪽인 것이 후보다.
    후보가 정확히 1개일 때만 chunk_id 를 돌려주고 상태는 'page_ok'.
    0개면 (None, [], 'not_found'), 2개 이상이면 (None, 후보들, 'page_ambiguous').
    근거에 doc_id 가 있으면 그 문서만 본다. 범위 밖 문서나 첫 청크로는 절대 대체하지 않는다.
    """
    page = ev.get('page')
    if page is None:
        return None, [], 'not_found'
    docs = {d for d, (lo, hi) in doc_pages.items() if lo <= page <= hi}
    if ev.get('doc_id'):
        docs &= {ev['doc_id']}
    cands = [c['chunk_id'] for c, _ in chunks if c['doc_id'] in docs and c.get('page') == page]
    if len(cands) == 1:
        return cands[0], cands, 'page_ok'
    if not cands:
        return None, [], 'not_found'
    return None, cands, 'page_ambiguous'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('evalfile')
    ap.add_argument('--chunks', default='data/chunks.jsonl')
    ap.add_argument('--mode', choices=('quote', 'page', 'facts'), default='quote',
                    help='quote: 원문 발췌로 찾기 (없으면 page). '
                         'page: 쪽 기준, 후보 1개일 때만. '
                         'facts: quote 가 없을 때 expected_facts 로 찾기 (확신 없으면 배정 안 함)')
    ap.add_argument('--detail', action='store_true', help='근거마다 연결 결과를 한 줄씩 출력')
    ap.add_argument('--write', action='store_true', help='평가셋 파일에 직접 반영')
    a = ap.parse_args()

    chunks = load_chunks(a.chunks)
    by_id = {c['chunk_id']: c for c, _ in chunks}
    doc_pages = doc_page_ranges(chunks)
    rows = json.loads(Path(a.evalfile).read_text(encoding='utf-8'))

    counts = {'ok': 0, 'partial': 0, 'spans_multiple': 0, 'not_found': 0,
              'page_ok': 0, 'page_ambiguous': 0, 'facts_ok': 0, 'facts_weak': 0}
    report, detail = [], []
    for r in rows:
        for i, ev in enumerate(r.get('evidence', [])):
            if a.mode == 'facts' and not norm(ev.get('quote')):
                cid, allc, st = link_by_facts(ev, r.get('expected_facts'), chunks, doc_pages)
            elif a.mode == 'page' or not norm(ev.get('quote')):
                cid, allc, st = link_by_page(ev, chunks, doc_pages)
            else:
                cid, allc, st = link_one(ev, chunks)
            counts[st] += 1
            ev['chunk_id'] = cid
            if len(allc) > 1:
                ev['chunk_ids_all'] = allc[:5]
            elif 'chunk_ids_all' in ev:
                del ev['chunk_ids_all']
            if st not in ('ok', 'page_ok', 'facts_ok'):
                report.append((st, r['id'], i, ev.get('page'), (ev.get('quote') or '')[:60]))
            c = by_id.get(cid)
            detail.append(f"  {r['id']} evidence[{i}] p.{ev.get('page')} {st:14} -> {cid}"
                          + (f" | {c['location']} | p.{c.get('page')}" if c else f' | 후보 {len(allc)}개'))

    total = sum(counts.values())
    print(f'근거 {total}건 (mode={a.mode})')
    for k in ('ok', 'page_ok', 'facts_ok', 'spans_multiple', 'partial',
              'page_ambiguous', 'facts_weak', 'not_found'):
        if counts[k] or k in ('ok', 'not_found'):
            print(f'  {k:16} {counts[k]}')
    if a.detail:
        print('\n--- 근거별 결과 ---')
        print('\n'.join(detail))
    if report:
        print('\n--- 사람이 확인할 것 ---')
        for st, qid, i, page, q in report:
            print(f'  [{st:14}] {qid} evidence[{i}] p.{page} | {q}')

    if a.write:
        Path(a.evalfile).write_text(
            json.dumps(rows, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(f'\n{a.evalfile} 에 반영했다.')
    else:
        print('\n(미리보기만 했다. 반영하려면 --write)')
    return 0 if counts['not_found'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
