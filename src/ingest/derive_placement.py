# -*- coding: utf-8 -*-
"""PDF 좌표로 코퍼스의 `## 업무명` 위치·라벨 조각·문서 경계의 오류를 찾아 배치 작업으로 적는다.

입력: 원문 PDF(--pdf), docs/corpus/*.md (--corpus)
출력: 배치 작업 파일(--out, JSON Lines, status="proposed"), 검토표(--review, Markdown)
이 도구만 pdfplumber 가 필요하다 (requirements.txt 참고). 적용은 apply_placement.py (표준 라이브러리만).

원리 (docs/conversion_notes.md 수정 12):
  1. 쪽마다 괘선으로 업무명 칸을 나눈다 (pdf_cells.page_cells).
  2. 코퍼스 본문 줄을 그 쪽 오른쪽 열의 글과 순서대로 맞춰 본다 (줄이 어느 칸에 있는지 = 진짜 업무명).
  3. 진짜 업무명이 바뀌는 첫 줄 앞이 `##` 의 자리다. 기존 `##` 는 같은 업무명끼리 짝지어 옮기고(move),
     짝이 없으면 새로 넣는다(insert). 본문 줄은 옮기거나 고치지 않는다.
  4. 업무명 열에 있는 단어가 본문에 새어 든 줄은 지우거나(delete_line) 앞뒤 조각만 뗀다(strip_fragment).
  5. F-5(DOC-F3), E-2(DOC-E1) 의 표는 다른 자격 절이므로 새 문서로 가른다(split_doc).

사용:
  PYTHONPATH=<pdfplumber 위치> python src/ingest/derive_placement.py --pdf 매뉴얼.pdf \\
      --corpus docs/corpus --out docs/corpus_fixes/placement_v1.jsonl --review review.md
  python src/ingest/derive_placement.py --pdf 매뉴얼.pdf --corpus <적용 결과 폴더> --check
"""
import argparse
import bisect
import collections
import json
import re
import sys
from dataclasses import dataclass, replace
from pathlib import Path

try:
    from ingest import pdf_cells as PC
    from ingest import pdf_to_md as P
    from ingest.apply_placement import PlacementOp, is_label_fragment, strip_fragment_text, read_corpus
except ImportError:                                  # 스크립트로 직접 실행
    import pdf_cells as PC
    import pdf_to_md as P
    from apply_placement import PlacementOp, is_label_fragment, strip_fragment_text, read_corpus

SKIP_DOCS = {'DOC-INTRO', 'DOC-ANNEX', 'DOC-WIDE'}          # 2단 표가 아닌 문서
DEFAULT_SKIP = ['DOC-D10:166']                              # 서식 쪽: 서식의 첫 열을 업무명 열로 오인한다
# 다른 자격 절의 표가 들어 있는 문서. 쪽 안에서 제목이 있는 y 아래부터가 새 문서다.
SPLITS = {
    'DOC-F3': dict(page=427, pattern=r'영주\(F-5\)', doc_id='DOC-F5', title='영주(F-5)', file='DOC-F5_영주.md'),
    'DOC-E1': dict(page=174, pattern=r'회화지도\(E-2\)', doc_id='DOC-E2', title='회화지도(E-2)', file='DOC-E2_회화지도.md'),
}
# 문서에 같은 업무명이 아직 없을 때 새로 넣는 표기: PDF 와 코퍼스 대부분의 표기를 따른다
DEFAULT_SPELLING = {'근무처 변경·추가': '근무처의 변경·추가'}
PAGE_RE = re.compile(r'^<!-- page: (\d+) -->$')

SMOOTHED = []      # 한 줄만 튀어 무시한 업무명 판정 (검토표용)
SHORT = 8          # 이보다 짧은 줄은 위치가 포인터에서 가까워야 순서 일치로 본다
NEAR = 600         # 글자 수

tnorm_re = re.compile(r'\s+')


def tnorm(s):
    """공백·사설영역 글리프를 지우고 변환기와 같은 문자 대응을 한다."""
    s = s.replace('­', '').replace('‐', '-').replace('‑', '-').replace('–', '-')
    s = PC.PUA.sub('', s).replace('·', '')       # 코퍼스는 사설영역 가운뎃점 글리프를 '·' 로 바꿔 두었다
    return tnorm_re.sub('', s)


def pdf_norm(s):
    s = re.sub(r'\(cid:\d+\)', '', s)
    s = re.sub(r'[□■]', '', s)
    return tnorm(s)


_LABEL_WORDS = {tnorm(t) for l in P.ALL_LABELS for t in l.split(' ')}
_LABEL_WORDS |= {tnorm(x) for x in ['체류자격변경', '체류기간연장', '근무처변경', '자격외', '허가', '해당자', '자격', '체류자격',
                                   '체류기간', '변경허가', '연장허가', '부 여', '변경·추가', '제한대상', '체류', '변경', '연장',
                                   '추가', '체류자격 변경', '체류자격 변경허가', '체류기간 연장허가']}
VOCAB = {v for v in _LABEL_WORDS if len(v) >= 2} - {tnorm('있는'), tnorm('없이'), tnorm('및'), tnorm('수')}


# ------------------------------------------------------------------ 코퍼스 읽기
@dataclass
class Item:
    no: int            # 1부터
    text: str
    kind: str          # front | title | page | h2 | h3 | h4 | body | blank
    page: int = None


def parse_md(lines):
    items, page, in_fm = [], None, False
    for i, l in enumerate(lines, 1):
        if i == 1 and l == '---':
            in_fm = True
            items.append(Item(i, l, 'front'))
            continue
        if in_fm:
            items.append(Item(i, l, 'front'))
            if l == '---':
                in_fm = False
            continue
        m = PAGE_RE.match(l)
        if m:
            page = int(m.group(1))
            items.append(Item(i, l, 'page', page))
            continue
        if not l.strip():
            items.append(Item(i, l, 'blank', page))
            continue
        h = re.match(r'^(#{1,4})\s+(.*)$', l)
        if h:
            kind = {1: 'title', 2: 'h2', 3: 'h3', 4: 'h4'}[len(h.group(1))]
            items.append(Item(i, l, kind, page))
            continue
        items.append(Item(i, l, 'body', page))
    return items


def heading_label(it):
    return it.text[3:].strip()


# ------------------------------------------------------------------ 쪽 단위 맞춰 보기
@dataclass
class LineTruth:
    line: int
    page: int
    kind: str                  # b(본문) | h(### / ####)
    text: str
    label: str = None          # 진짜 업무명 (None: 알 수 없음 -> 앞 업무가 이어진다)
    how: str = None            # seq | anywhere | glued | partial | None
    src: str = None            # 칸의 업무명 출처: exact | alias | fuzzy | inherited
    cell: tuple = None         # (top, bottom)
    label_raw: str = ''
    y: float = None
    glued: str = None          # 줄 앞에 붙은 라벨 조각
    glued_side: str = None     # lead | trail
    frag: bool = False         # 줄 전체가 라벨 조각
    frag_strong: bool = True
    frag_cand: bool = False    # 줄 전체가 업무명 열의 글자와 같다 (위치가 맞는 줄이어도 참)
    flip: bool = False         # A -> B -> A 로 한 줄만 튄 업무명이라 무시했다


def _variants(it):
    t = it.text
    if it.kind == 'body' and t.startswith('- '):
        v = [tnorm(t[2:]), tnorm(t)]
    else:
        t = re.sub(r'^#{3,4}\s+', '', t) if it.kind in ('h3', 'h4') else t
        v = [tnorm(t)]
    return [x for x in v if x]


def _is_frag_words(toks, joined, lw):
    """줄 앞(뒤)의 낱말들이 업무명 열의 글자인가: 이어 붙인 글자가 열의 낱말과 같거나 포함되거나,
    낱말마다 열의 낱말이다('활동범위 및' 처럼 연결어 '및' 하나는 허용)."""
    if any(joined == w or joined in w for w in lw):
        return True
    return all(tnorm(t) in lw or tnorm(t) == '및' for t in toks) and any(tnorm(t) in lw for t in toks)


class PageIndex:
    """한 쪽의 PDF 본문 글을 하나의 긴 글(s)로 이어 붙이고 칸·줄의 위치를 기억한다."""

    def __init__(self, pc, inherit):
        self.pc = pc
        self.cells, self.s, self.lw, last = [], '', set(), inherit
        for ci, c in enumerate(pc.cells):
            if c.how == 'empty':
                lab, src = last, 'inherited'
            elif not c.label:
                lab, src = None, 'unmatched'
            else:
                lab, src = c.label, c.how
                last = c.label
            lws = [tnorm(w) for w in c.left_words]
            for i in range(len(lws)):                  # '부' '여' 처럼 쪼개진 칸 글자는 이어 붙여서도 본다
                for j in range(i + 1, min(i + 4, len(lws) + 1)):
                    if ''.join(lws[i:j]) in VOCAB:
                        self.lw.add(''.join(lws[i:j]))
            start, offs = len(self.s), []
            for ln in c.lines:
                n = pdf_norm(ln.text)
                if not n:
                    continue
                offs.append((len(self.s), len(self.s) + len(n), ln.y))
                self.s += n
            self.cells.append(dict(label=lab, src=src, start=start, end=len(self.s), top=c.top, bottom=c.bottom,
                                   lines=offs, left_raw=c.left_raw))
        self.last = last
        self.lraw = [tnorm(c.left_raw.replace('~', '').replace('목차', '')) for c in pc.cells
                     if c.how in ('exact', 'fuzzy', 'alias')]
        self.starts = {a for c in self.cells for a, b, y in c['lines']}
        self.ends = {b for c in self.cells for a, b, y in c['lines']}

    def find(self, v, ptr=0):
        i = ptr
        while True:
            p = self.s.find(v, i)
            if p < 0:
                return -1
            if len(v) >= 8 or (p in self.starts and p + len(v) in self.ends):
                return p
            i = p + 1

    def cell_at(self, pos):
        for ci, c in enumerate(self.cells):
            if c['start'] <= pos < c['end']:
                return ci, c
        return None, None

    def y_at(self, c, pos):
        for a, b, y in c['lines']:
            if a <= pos < b:
                return y
        return None


def carry_cells(cells_by_page):
    """쪽 아래에서 시작해 다음 쪽으로 이어지는 칸의 업무명을 그 쪽 아래 칸에 붙인다.

    업무명은 칸의 세로 가운데에 쓰므로, 칸이 쪽 맨 아래(y~750)에서 시작하면 앞 쪽에는 '체류자격' 처럼
    조각만 남고(unmatched) 나머지 '변경허가' 는 다음 쪽 첫 칸에 있다. 조각 + 다음 쪽 첫 칸 글자가 다음 쪽
    첫 칸의 업무명과 같은 업무명이 되면, 앞 쪽의 그 칸 줄은 같은 업무명이다 (본문 첫 줄이 거기 있다).
    입력은 바꾸지 않고 복사본을 돌려준다.
    """
    out = dict(cells_by_page)
    for pn in sorted(cells_by_page):
        a, b = cells_by_page.get(pn), cells_by_page.get(pn + 1)
        if a is None or b is None or not a.cells or not b.cells:
            continue
        last, first = a.cells[-1], b.cells[0]
        if last.how != 'unmatched' or first.how not in ('exact', 'alias', 'fuzzy') or not last.left_raw.strip():
            continue
        # 조각이 다음 쪽 첫 칸 업무명의 앞부분이고, 그 첫 칸 글자가 나머지 부분으로 시작한다
        key, frag = PC.knorm(first.label), PC.knorm(last.left_raw)
        if len(frag) >= 2 and key.startswith(frag) and len(key) > len(frag) and PC.knorm(first.left_raw).startswith(key[len(frag):]):
            out[pn] = replace(a, cells=a.cells[:-1] + [replace(last, label=first.label, how=first.how)])
    return out


def locate(items, cells_by_page, skip=()):
    """코퍼스 줄 -> LineTruth 목록 (###/####/본문 줄 전부, 문서 순서).

    cells_by_page: {쪽: PageCells | None}. None 이면 그 쪽의 줄은 업무명을 모른다.
    skip: {쪽} 판정하지 않을 쪽 (서식 쪽).
    """
    cells_by_page = carry_cells(cells_by_page)
    truths, inherit = [], None
    pages = collections.OrderedDict()
    cur = None
    for it in items:
        if it.kind == 'page':
            cur = it.page
            pages.setdefault(cur, [])
        elif it.kind in ('body', 'h3', 'h4') and cur is not None:
            pages[cur].append(it)
        elif it.kind in ('body', 'h3', 'h4'):
            truths.append(LineTruth(it.no, None, 'b' if it.kind == 'body' else 'h', it.text))
    out = {t.line: t for t in truths}
    for pn, its in pages.items():
        for it in its:
            out[it.no] = LineTruth(it.no, pn, 'b' if it.kind == 'body' else 'h', it.text)
        pc = cells_by_page.get(pn)
        if pc is None or pn in skip:
            continue
        pi = PageIndex(pc, inherit)
        inherit = pi.last
        ptr = 0
        for it in its:
            t = out[it.no]
            if it.kind == 'body':
                _toks = [tnorm(x) for x in it.text.split(' ') if x]
                _tt = tnorm(it.text)
                t.frag_cand = bool(_toks) and len(_tt) >= 2 and (all(x in pi.lw for x in _toks)
                                                                 or any(_tt in x for x in pi.lraw))
                t.frag_strong = bool(_toks) and all(x in pi.lw for x in _toks)
            vs = _variants(it)
            pos, vlen, how = -1, 0, None
            for v in vs:
                p = pi.find(v, ptr)
                # 짧은 줄('활동범위', '해당사항 없음')은 쪽 아래쪽 표 안의 같은 글자에 걸려 포인터가 멀리 뛰기 쉽다.
                # 포인터에서 가까울 때만 '순서대로 맞음'으로 본다.
                if p >= 0 and (len(v) >= SHORT or p - ptr <= NEAR):
                    pos, vlen, how = p, len(v), 'seq'
                    break
            if pos < 0:
                for v in vs:
                    p = pi.find(v)
                    if p >= 0 and len(v) >= 6:
                        pos, vlen, how = p, len(v), 'anywhere'
                        break
            glued, side = None, None
            if pos < 0 and it.kind == 'body':
                toks = it.text.split(' ')

                def _find_rest(rest, strict):
                    """조각을 뗀 나머지가 PDF 본문 줄의 맨 앞에서 시작하는 자리. strict 가 아니면 아무 데나."""
                    for start in (ptr, 0):
                        i = start
                        while True:
                            p = pi.s.find(rest, i)
                            if p < 0 or not strict or p in pi.starts:
                                break
                            i = p + 1
                        if p >= 0:
                            return p
                    return -1
                # 먼저 나머지가 PDF 줄 맨 앞과 맞는 쪽을 찾고(줄 경계를 건너 우연히 맞는 것을 피한다), 못 찾으면 느슨하게 본다.
                # 조각은 가장 긴 것부터 본다 ('해 당 자' 를 '해 당' 에서 멈추지 않는다).
                for strict in (True, False):
                    for k in range(min(3, len(toks) - 1), 0, -1):
                        pre = tnorm(' '.join(toks[:k]))
                        if pre and len(pre) >= 2 and _is_frag_words(toks[:k], pre, pi.lw):
                            rest = tnorm(' '.join(toks[k:]))
                            if rest and len(rest) >= 3:
                                p = _find_rest(rest, strict)
                                if p >= 0:
                                    pos, vlen, how, glued, side = p, len(rest), 'glued', ' '.join(toks[:k]), 'lead'
                                    break
                    if pos < 0:                      # 줄 끝에 붙은 조각
                        for k in range(min(3, len(toks) - 1), 0, -1):
                            post = tnorm(' '.join(toks[-k:]))
                            if post and len(post) >= 2 and _is_frag_words(toks[-k:], post, pi.lw):
                                rest = tnorm(' '.join(toks[:-k]))
                                if rest and len(rest) >= 3:
                                    p = _find_rest(rest, strict)
                                    if p >= 0:
                                        pos, vlen, how, glued, side = p, len(rest), 'glued', ' '.join(toks[-k:]), 'trail'
                                        break
                    if pos >= 0:
                        break
            if pos < 0:
                v = vs[0] if vs else ''
                for frag in (v[:12], v[-12:]):
                    if len(frag) >= 8 and pi.s.find(frag) >= 0:
                        pos, vlen, how = pi.s.find(frag), len(frag), 'partial'
                        break
            if pos < 0 and it.kind == 'body':
                toks = [tnorm(x) for x in it.text.split(' ') if x]
                tt = tnorm(it.text)
                strong = bool(toks) and all(x in pi.lw for x in toks)
                if toks and len(tt) >= 2 and (strong or any(tt in x for x in pi.lraw)):
                    t.frag, t.frag_strong = True, strong
                    continue
            if pos < 0:
                continue
            if how == 'seq' and not t.frag_cand:      # 업무명 열의 글자와 같은 줄은 포인터를 옮기지 않는다
                ptr = pos + vlen
            ci, c = pi.cell_at(pos)
            if c is None:
                continue
            t.label, t.how, t.src = c['label'], how, c['src']
            t.cell, t.label_raw, t.y = (c['top'], c['bottom']), c['left_raw'], pi.y_at(c, pos)
            t.glued, t.glued_side = glued, side
    res = [out[k] for k in sorted(out)]
    _smooth(res, skip)
    return res


def _smooth(res, skip):
    """업무명이 A -> B -> A 로 한 줄만 튀는 경우, 그 줄이 짧거나 순서 일치가 아니면 우연히 다른 칸의 같은
    글자에 걸린 것으로 보고 업무명을 비운다(무시). 줄이 업무명 열의 글자 그대로면 라벨 조각 줄이다."""
    bearing = [t for t in res if t.label and t.page not in skip]
    for a, b, c in zip(bearing, bearing[1:], bearing[2:]):
        if (PC.canon(b.label) != PC.canon(a.label) == PC.canon(c.label)
                and (len(tnorm(b.text)) < SHORT or b.how != 'seq')):
            b.flip = True
    for t in bearing:
        if t.flip:
            t.label = None
            if t.kind == 'b' and t.frag_cand and is_label_fragment(t.text):
                t.frag = True


# ------------------------------------------------------------------ 작업 만들기
def doc_variants(items):
    """문서에서 쓰는 `##` 표기: canon 업무명 -> 가장 많이 쓴 표기."""
    cnt = collections.defaultdict(collections.Counter)
    for it in items:
        if it.kind == 'h2':
            cnt[PC.canon(heading_label(it))][heading_label(it)] += 1
    return {k: v.most_common(1)[0][0] for k, v in cnt.items()}


def heading_text(label, src, variants):
    """새로 넣을 `##` 글자. 칸 글자가 표준 업무명과 같으면(exact/alias) 그대로, 쪼개진 칸(fuzzy)이면
    그 문서가 이미 쓰는 표기를, 없으면 표준 표기를 쓴다."""
    if src in ('exact', 'alias'):
        return label
    if src in ('fuzzy', 'inherited'):
        return variants.get(PC.canon(label), DEFAULT_SPELLING.get(PC.canon(label), PC.canon(label)))
    return label


def _in_skip(page, doc, skip):
    return (doc, page) in skip


def propose(md_name, lines, cells_by_page, skip=(), split_line=None, split_doc=None):
    """한 문서의 작업 목록 (아직 id 없음)."""
    doc = md_name.split('_')[0]
    items = parse_md(lines)
    skip_pages = {p for d, p in skip if d == doc}
    truths = locate(items, cells_by_page, skip_pages)
    by_no = {it.no: it for it in items}
    ops = []

    for t in truths:
        if t.flip:
            SMOOTHED.append((md_name, t.line, t.page, t.text[:30], t.label_raw))
    # --- 라벨 조각: 지우기/떼기
    deleted = set()
    for t in truths:
        if t.page in skip_pages:
            continue
        if t.frag and is_label_fragment(t.text):
            deleted.add(t.line)
            ops.append(PlacementOp(
                op='delete_line', file=md_name, line=t.line, expect=lines[t.line - 1], mech='M3b',
                evidence={'page': t.page, 'y': None, 'cell': None, 'label_raw': ''},
                confidence='high' if t.frag_strong else 'low'))
        elif t.glued and is_label_fragment(t.glued) and strip_fragment_text(lines[t.line - 1], t.glued):
            ops.append(PlacementOp(
                op='strip_fragment', file=md_name, line=t.line, expect=lines[t.line - 1], fragment=t.glued, mech='M3b',
                evidence={'page': t.page, 'y': t.y, 'cell': list(t.cell) if t.cell else None, 'label_raw': t.label_raw},
                confidence='high' if t.glued_side == 'lead' else 'low'))

    kept = [t for t in truths if t.line not in deleted]
    variants = doc_variants(items)
    if split_line:
        parts = [(0, split_line), (split_line, 10 ** 9)]
    else:
        parts = [(0, 10 ** 9)]

    if split_line:
        it = by_no[split_line]
        ops.append(PlacementOp(
            op='split_doc', file=md_name, line=split_line, expect=lines[split_line - 1], mech='M3d',
            new_doc=dict(doc_id=split_doc['doc_id'], title=split_doc['title'], file=split_doc['file']),
            evidence=split_doc.get('evidence', {}), confidence=split_doc.get('confidence', 'high')))

    first_part = True
    for lo, hi in parts:
        part = [t for t in kept if lo <= t.line < hi]
        part_nos = [t.line for t in part]
        # 목표: 진짜 업무명이 바뀌는 첫 줄
        T, cur = [], None
        prev_truth_idx = None
        for idx, t in enumerate(part):
            if t.label and t.page not in skip_pages:
                lab = PC.canon(t.label)
                if lab != cur:
                    window = [x.line for x in part[(prev_truth_idx + 1 if prev_truth_idx is not None else 0):idx]]
                    T.append(dict(label=t.label, lab=lab, idx=idx, t=t, window=window,
                                  prev_how=part[prev_truth_idx].how if prev_truth_idx is not None else None))
                    cur = lab
                prev_truth_idx = idx
        # 현재: 이 부분의 `##`
        E = []
        for it in items:
            if it.kind == 'h2' and lo <= it.no < hi and it.page not in skip_pages and not (it.page is None):
                pos = bisect.bisect_left(part_nos, it.no)
                E.append(dict(it=it, lab=PC.canon(heading_label(it)), idx=pos))
        # 1) 제자리: 같은 업무명이 같은 자리
        Tl, El = list(T), list(E)
        for tk in list(Tl):
            for e in El:
                if e['lab'] == tk['lab'] and e['idx'] == tk['idx']:
                    Tl.remove(tk)
                    El.remove(e)
                    break
        # 2) 짝짓기: 같은 업무명끼리 가까운 것부터
        pairs = []
        cand = sorted(((abs(e['idx'] - tk['idx']), ei, ti)
                       for ei, e in enumerate(El) for ti, tk in enumerate(Tl) if e['lab'] == tk['lab']),
                      key=lambda x: x[0])
        used_e, used_t = set(), set()
        for d, ei, ti in cand:
            if ei in used_e or ti in used_t:
                continue
            used_e.add(ei)
            used_t.add(ti)
            pairs.append((El[ei], Tl[ti]))
        for e, tk in pairs:
            t = tk['t']
            ops.append(_heading_op('move_heading', md_name, lines, tk, e['it']))
        for ti, tk in enumerate(Tl):
            if ti not in used_t:
                ops.append(_heading_op('insert_heading', md_name, lines, tk, None,
                                       heading=heading_text(tk['label'], tk['t'].src, variants),
                                       first=first_part and not any(x.kind == 'h2' and x.no < tk['t'].line for x in items),
                                       split=(not first_part)))
        extras = [El[ei]['it'] for ei in range(len(El)) if ei not in used_e]
        for it in extras:
            ops.append(PlacementOp(op='_extra', file=md_name, line=it.no, expect=it.text, mech='extra',
                                   evidence={'page': it.page}, confidence='low'))
        first_part = False
    return ops


def _heading_op(kind, md_name, lines, tk, old, heading=None, first=False, split=False):
    t = tk['t']
    low = (t.src not in ('exact', 'alias') or t.how != 'seq' or bool(tk['window']) or tk['prev_how'] not in (None, 'seq'))
    if kind == 'move_heading':
        old_idx_line = old.no
        mech = 'M1' if t.line < old_idx_line else 'M2'
        return PlacementOp(
            op='move_heading', file=md_name, line=old.no, expect=old.text, to_line=t.line, expect_to=lines[t.line - 1],
            heading=heading_label(old), mech=mech,
            evidence={'page': t.page, 'y': t.y, 'cell': list(t.cell) if t.cell else None, 'label_raw': t.label_raw},
            cands=tk['window'], confidence='low' if low else 'high')
    if split:
        mech = 'M3d'
    elif first:
        mech = 'FL'
    elif t.src == 'fuzzy':
        mech = 'M3a' if PC.canon(heading) == '자격 해당자 및 활동범위' else 'M3b'
    elif t.src == 'alias' or heading not in P.LABELS:
        mech = 'M3c'
    else:
        mech = 'M3b'
    return PlacementOp(
        op='insert_heading', file=md_name, line=t.line, expect=lines[t.line - 1], to_line=t.line,
        expect_to=lines[t.line - 1], heading=heading, mech=mech,
        evidence={'page': t.page, 'y': t.y, 'cell': list(t.cell) if t.cell else None, 'label_raw': t.label_raw},
        cands=tk['window'], confidence='low' if low else 'high')


# ------------------------------------------------------------------ 분리 지점
def find_split_line(md_name, lines, cells_by_page, pdf, spec):
    """새 자격 절의 제목 y 아래 첫 본문 줄. 제목이 쪽 맨 아래라서 그 쪽에 줄이 없으면 다음 쪽의 첫 줄."""
    page = spec['page']
    hits = PC.find_text_y(pdf, page, spec['pattern'])
    if not hits:
        raise SystemExit(f'{md_name}: p.{page} 에서 {spec["pattern"]} 를 찾지 못했다')
    title_y, title_text = hits[0]
    items = parse_md(lines)
    truths = locate(items, cells_by_page)
    cand = [t for t in truths if t.kind in ('b', 'h') and t.page is not None and t.page >= page]
    chosen, why = None, ''
    for t in cand:
        if t.page == page and t.y is not None and t.y >= title_y:
            chosen, why = t, f'p.{page} y={t.y} >= 제목 y={title_y}'
            break
        if t.page > page:
            chosen, why = t, f'p.{page} 제목(y={title_y})보다 아래 줄이 없어 p.{t.page} 첫 줄'
            break
    if chosen is None:
        raise SystemExit(f'{md_name}: 분리 지점을 찾지 못했다')
    spec = dict(spec)
    spec['evidence'] = {'page': page, 'y': title_y, 'cell': None, 'label_raw': title_text, 'why': why}
    return chosen.line, spec


# ------------------------------------------------------------------ 전체 실행
def load_cells(pdf, pages, cache=None):
    cells = {}
    cached = {}
    if cache and Path(cache).exists():
        cached = json.loads(Path(cache).read_text(encoding='utf-8'))
    for p in sorted(pages):
        k = str(p)
        if k in cached:
            cells[p] = PC.PageCells.from_dict(cached[k]) if cached[k] else None
        else:
            pc = PC.page_cells(pdf, p)
            cached[k] = pc.to_dict() if pc else None
            cells[p] = pc
    if cache:
        Path(cache).write_text(json.dumps(cached, ensure_ascii=False), encoding='utf-8')
    return cells


def doc_pages(lines):
    return sorted({int(m.group(1)) for l in lines for m in [PAGE_RE.match(l)] if m})


def derive(pdf, corpus, skip, cache=None):
    files = read_corpus(corpus)
    all_ops = []
    for name, lines in files.items():
        doc = name.split('_')[0]
        if doc in SKIP_DOCS:
            continue
        cells = load_cells(pdf, doc_pages(lines), cache)
        split_line = split_spec = None
        if doc in SPLITS:
            split_line, split_spec = find_split_line(name, lines, cells, pdf, SPLITS[doc])
        ops = propose(name, lines, cells, skip, split_line, split_spec)
        all_ops += ops
    return all_ops, files


def finalize(ops):
    """_extra 를 떼어 내고 정렬·번호를 붙인다 -> (작업 목록, 남은 기존 제목 목록)"""
    extras = [o for o in ops if o.op == '_extra']
    real = [o for o in ops if o.op != '_extra']
    order = {'split_doc': 0, 'delete_line': 1, 'strip_fragment': 2, 'move_heading': 3, 'insert_heading': 4}
    real.sort(key=lambda o: (o.file, o.line, order[o.op]))
    for i, o in enumerate(real, 1):
        o.id = f'P{i:04d}'
    return real, extras


def write_ops(path, ops):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        for o in ops:
            f.write(o.to_json() + '\n')


def write_review(path, ops, extras, files):
    """검토표: 문서·쪽 묶음별, 확신 낮은 것 먼저."""
    blocks = collections.OrderedDict()
    for o in ops:
        blocks.setdefault((o.file, o.evidence.get('page')), []).append(o)
    low_blocks = [k for k, v in blocks.items() if any(o.confidence == 'low' for o in v)]
    high_blocks = [k for k in blocks if k not in low_blocks]
    cnt = collections.Counter((o.op, o.confidence) for o in ops)
    out = ['# 배치 작업 검토표 (placement_v1)', '',
           f'작업 {len(ops)}건 (확신 낮음 {sum(1 for o in ops if o.confidence == "low")}건). '
           f'낮은 확신이 있는 묶음 {len(low_blocks)}개를 먼저, 나머지 {len(high_blocks)}개를 뒤에 둔다.', '',
           '| 작업 | high | low |', '|---|---|---|']
    for op in ('split_doc', 'delete_line', 'strip_fragment', 'move_heading', 'insert_heading'):
        out.append(f'| {op} | {cnt[(op, "high")]} | {cnt[(op, "low")]} |')
    out += ['', '열: id 작업 / 줄(원본) -> 도착 줄 / 업무명(또는 조각) / mech / 확신 / 쪽·y·칸 글자 / 줄 글자. '
            '`cands` 는 같은 자리로 볼 수 있는 앞쪽 줄(근거 없는 줄) 번호.', '']
    for title, keys in (('확신 낮은 묶음', low_blocks), ('확신 높은 묶음', high_blocks)):
        out += [f'## {title}', '']
        for k in sorted(keys, key=lambda k: (k[0], k[1] or 0)):
            out.append(f'### {k[0]} p.{k[1]}')
            out.append('')
            out.append('| id | 작업 | 줄 -> 도착 | 업무명/조각 | mech | 확신 | y / 칸 글자 | 줄 글자 | cands |')
            out.append('|---|---|---|---|---|---|---|---|---|')
            for o in sorted(blocks[k], key=lambda o: (0 if o.confidence == 'low' else 1, o.line)):
                tgt = f'{o.line}' + (f' -> {o.to_line}' if o.to_line and o.to_line != o.line else '')
                name = o.heading or o.fragment or (o.new_doc or {}).get('doc_id', '')
                ev = o.evidence
                yy = f'y={ev.get("y")} / {ev.get("label_raw", "")[:24]}'
                ln = (o.expect or '')[:40].replace('|', '\\|')
                out.append(f'| {o.id} | {o.op} | {tgt} | {name} | {o.mech} | {o.confidence} | {yy} | {ln} | '
                           f'{",".join(map(str, o.cands[:6]))} |')
            out.append('')
    if SMOOTHED:
        out += ['## 한 줄만 튀어 무시한 판정 (A -> B -> A)', '', '| 파일 | 줄 | 쪽 | 줄 글자 | 판정된 업무명 |', '|---|---|---|---|---|']
        for f_, ln_, pg_, tx_, lb_ in SMOOTHED:
            out.append(f'| {f_} | {ln_} | {pg_} | {tx_.replace("|", chr(92) + "|")} | {lb_} |')
        out.append('')
    if extras:
        out += ['## 짝이 없는 기존 `##` (그대로 둔다)', '', '| 파일 | 줄 | 제목 |', '|---|---|---|']
        for e in extras:
            out.append(f'| {e.file} | {e.line} | {e.expect} |')
        out.append('')
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text('\n'.join(out) + '\n', encoding='utf-8')


# ------------------------------------------------------------------ --check
def check_doc(name, lines, cells, skip_pages=()):
    """한 문서에 남은 오류 {종류: [행]}. cells: {쪽: PageCells | None}.

    쪽을 넘는 칸의 앞 쪽 조각 칸('체류자격' 만 보여 unmatched)도 carry_cells 로 업무명을 받으므로,
    그 칸의 첫 본문 줄이 `##` 아래 엉뚱한 업무명에 남아 있어도 ① 로 센다.
    """
    res = collections.defaultdict(list)
    items = parse_md(lines)
    truths = locate(items, cells, skip_pages)
    label_at, cur = {}, None
    for it in items:
        if it.kind == 'h2':
            cur = heading_label(it)
        label_at[it.no] = cur
    first_h2 = next((it.no for it in items if it.kind == 'h2'), None)
    for t in truths:
        if t.page in skip_pages:
            continue
        cl = label_at.get(t.line)
        if t.label and cl is not None and PC.canon(t.label) != PC.canon(cl):
            res['1_wrong_label'].append((name, t.line, t.page, t.text[:40], cl, t.label))
        if t.label and cl is None:
            res['1b_no_label_yet'].append((name, t.line, t.page, t.text[:40], cl, t.label))
        if t.frag and is_label_fragment(t.text):
            res['3_fragment_line'].append((name, t.line, t.page, t.text[:40]))
        if t.glued and is_label_fragment(t.glued) and strip_fragment_text(t.text, t.glued):
            res['3_glued'].append((name, t.line, t.page, t.text[:40], t.glued))
    for it in items:
        if first_h2 and it.kind in ('body', 'h3', 'h4') and it.no < first_h2 and it.page is not None:
            res['2_before_first_h2'].append((name, it.no, it.page, it.text[:40]))
    return res


def check(pdf, corpus, skip, cache=None):
    """코퍼스에 남은 오류 수. ① 업무명 아래의 본문이 진짜 업무명과 다름, ② 첫 `##` 앞 본문,
    ③ 남은 라벨 조각(단독 줄 / 붙은 조각)."""
    files = read_corpus(corpus)
    res = collections.defaultdict(list)
    for name, lines in files.items():
        doc = name.split('_')[0]
        if doc in SKIP_DOCS:
            continue
        cells = load_cells(pdf, doc_pages(lines), cache)
        skip_pages = {p for d, p in skip if d == doc}
        for k, rows in check_doc(name, lines, cells, skip_pages).items():
            res[k] += rows
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--pdf', required=True, help='원문 PDF (저장소 밖에 둔다)')
    ap.add_argument('--corpus', default='docs/corpus')
    ap.add_argument('--out', help='배치 작업 파일 (JSON Lines)')
    ap.add_argument('--review', help='검토표 (Markdown)')
    ap.add_argument('--skip', nargs='*', default=DEFAULT_SKIP, help='판정하지 않을 문서:쪽 (기본 DOC-D10:166)')
    ap.add_argument('--cells-cache', help='쪽별 칸 읽기 결과를 저장·재사용할 JSON (개발용)')
    ap.add_argument('--check', action='store_true', help='--corpus 에 남은 오류 수만 센다')
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding='utf-8')
    skip = {(s.split(':')[0], int(s.split(':')[1])) for s in a.skip}

    if a.check:
        res = check(a.pdf, a.corpus, skip, a.cells_cache)
        total1 = len(res['1_wrong_label'])
        print(f'남은 ① (본문이 진짜와 다른 업무명 아래): {total1}')
        for k in ('1b_no_label_yet', '2_before_first_h2', '3_fragment_line', '3_glued'):
            print(f'{k}: {len(res[k])}')
        for k, rows in res.items():
            for r in rows[:40]:
                print(' ', k, r)
        return 0 if total1 == 0 else 1

    if not a.out:
        ap.error('--out 이 필요하다')
    ops, files = derive(a.pdf, a.corpus, skip, a.cells_cache)
    real, extras = finalize(ops)
    write_ops(a.out, real)
    if a.review:
        write_review(a.review, real, extras, files)
    c_op = collections.Counter(o.op for o in real)
    c_mech = collections.Counter(o.mech for o in real)
    c_conf = collections.Counter(o.confidence for o in real)
    print(f'작업 {len(real)}건 -> {a.out}')
    print('op:', dict(c_op))
    print('mech:', dict(c_mech))
    print('confidence:', dict(c_conf))
    print('짝 없는 기존 ##:', len(extras))
    return 0


if __name__ == '__main__':
    sys.exit(main())
