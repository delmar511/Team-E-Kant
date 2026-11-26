# -*- coding: utf-8 -*-
"""PDF 의 괘선(ruling line)으로 '업무명 칸'과 그 칸의 본문 줄을 읽는다.

체류자격 절의 쪽은 2단 표다. 왼쪽 열(업무명)과 오른쪽 열(본문)을 가르는 세로선과
업무 사이의 가로선이 PDF 안에 선(edge)으로 들어 있다. 이 선으로 칸(cell)을 나누면
본문 한 줄이 어느 업무명 칸에 속하는지 좌표로 알 수 있다.
pdftotext -layout 은 업무명이 칸의 세로 한가운데에 있다는 점 때문에 칸 위쪽 본문을
앞 업무로 잘못 붙였다 (docs/conversion_notes.md 수정 12).

pdfplumber 는 이 모듈에서 처음 쓸 때만 import 한다. 적용(apply_placement)·청킹·pytest 는
pdfplumber 없이 돌아가야 한다. 이 모듈은 ingest/derive_placement 전용이다.
"""
import re
from dataclasses import dataclass, field, asdict
from functools import lru_cache
from pathlib import Path

try:
    from ingest import pdf_to_md as P
except ImportError:                                  # 스크립트로 직접 실행
    import pdf_to_md as P

PUA = re.compile(r'[-]')


def knorm(s):
    """업무명 비교용: 사설영역 글리프·공백·가운뎃점 제거."""
    s = PUA.sub('', s or '')
    return re.sub(r'[\s·]', '', s)


# 표준 업무명(+원문 그대로 쓰는 업무명) -> 정규화 키
KEYS = {knorm(lab): lab for lab in P.ALL_LABELS}
ALIAS_KEYS = {knorm(k): v for k, v in P.LABEL_ALIASES.items()}
# 같은 업무명의 표기 변형을 한 부류로 본다 (표시는 문서에서 쓰는 표기를 따른다)
CANON = {
    '활동범위 및 자격 해당자': '자격 해당자 및 활동범위',
    '근무처의 변경·추가': '근무처 변경·추가',
    '별도 허가 없이 연수활동이 가능한 체류자격': '별도 허가 없이 유학활동이 가능한 체류자격',
}


def canon(label):
    return CANON.get(label, label) if label else label


def resolve_label(left_raw):
    """왼쪽 칸의 글자 -> (업무명 | None, 방식).

    방식: exact(표준 업무명과 일치) | alias(LABEL_ALIASES) | fuzzy(조각만 보이는 업무명:
    '활동범위' / '해 당 자' 처럼 쪼개진 칸) | empty(글자 없음, 앞 업무가 이어진다) |
    unmatched(업무명이 아닌 칸, 중첩 표의 첫 열 등).
    """
    raw = (left_raw or '').replace('~', ' ').replace('목차', ' ')
    k = knorm(raw)
    if not k:
        return None, 'empty'
    if k in KEYS:
        return KEYS[k], 'exact'
    if k in ALIAS_KEYS:
        return ALIAS_KEYS[k], 'alias'
    cands = set()
    for key, lab in KEYS.items():
        if (key in k and len(k) <= 2 * len(key) + 4) or (len(k) >= 3 and k in key):
            cands.add(canon(lab))
    if len(cands) == 1:
        return cands.pop(), 'fuzzy'
    return None, 'unmatched'


@dataclass
class CellLine:
    y: float
    text: str


@dataclass
class Cell:
    top: float
    bottom: float
    left_raw: str
    left_words: list
    label: str            # 업무명(표준 또는 원문), 없으면 ''
    how: str              # exact | alias | fuzzy | empty | unmatched
    lines: list = field(default_factory=list)      # [CellLine]


@dataclass
class PageCells:
    page: int
    x: float              # 업무명 칸/본문 칸 경계선 x
    cells: list           # [Cell] 위에서 아래로

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        cells = [Cell(c['top'], c['bottom'], c['left_raw'], c['left_words'], c['label'], c['how'],
                      [CellLine(l['y'], l['text']) for l in c['lines']]) for c in d['cells']]
        return cls(d['page'], d['x'], cells)


@lru_cache(maxsize=2)
def _open(pdf):
    import pdfplumber                       # 지연 import: derive 에서만 필요
    return pdfplumber.open(str(pdf))


def _find_boundary(page):
    """업무명 칸/본문 칸 경계 세로선의 x 와 그 선이 만드는 칸 [(top, bottom)].

    x=112..165 에서 총 길이가 가장 긴 세로선을 고른다. 바깥 표 테두리(x<70)도 있어야 한다.
    """
    segs = {}
    for e in page.edges:
        if e['orientation'] == 'v' and e['bottom'] - e['top'] > 20 and 112 <= e['x0'] <= 165:
            segs.setdefault(round(e['x0'] / 2), []).append(e)
    best = None
    for es in segs.values():
        tot = sum(e['bottom'] - e['top'] for e in es)
        if best is None or tot > best[0]:
            best = (tot, es)
    if best:
        # 쪽 안에 '【공통기준】' 같은 중첩 상자가 있으면 그 상자의 왼쪽 선이 더 길 수 있다. 그 선이 만드는 칸이
        # 모두 다른 세로선의 칸 안에 들어 있으면(상자는 칸 하나 안에 있다) 바깥 칸을 만드는 선을 쓴다.
        def inside(es_in, es_out):
            return all(any(o['top'] - 8 <= e['top'] and e['bottom'] <= o['bottom'] + 8 for o in es_out) for e in es_in)
        outer = [es for es in segs.values() if es is not best[1] and sum(e['bottom'] - e['top'] for e in es) >= 150
                 and inside(best[1], es) and not inside(es, best[1])]
        if outer:
            es = max(outer, key=lambda es: sum(e['bottom'] - e['top'] for e in es))
            best = (sum(e['bottom'] - e['top'] for e in es), es)
    if not best or best[0] < 150:
        return None, []
    if not any(e['orientation'] == 'v' and e['x0'] < 70 and e['bottom'] - e['top'] > 100 for e in page.edges):
        return None, []
    es = best[1]
    x = sum(e['x0'] for e in es) / len(es)
    # 쪽 맨 아래에 걸친 칸은 20pt 보다 낮을 수 있다(예: DOC-D9 p.130 y 767~785). 같은 x 의 짧은 선도 칸으로 쓴다.
    es = es + [e for e in page.edges if e['orientation'] == 'v' and 10 <= e['bottom'] - e['top'] <= 20
               and abs(e['x0'] - x) <= 3 and e['top'] > 700 and e not in es]
    ivs = sorted({(round(e['top']), round(e['bottom'])) for e in es})
    cells = []
    for t, b in ivs:
        if b - t < 8:
            continue
        if cells and abs(cells[-1][0] - t) <= 2 and abs(cells[-1][1] - b) <= 2:
            continue
        cells.append([t, b])
    return x, cells


def _lines_of(words):
    ws = sorted(words, key=lambda w: (w['top'], w['x0']))
    lines = []
    for w in ws:
        if lines and abs(lines[-1]['top'] - w['top']) <= 3:
            lines[-1]['w'].append(w)
        else:
            lines.append({'top': w['top'], 'w': [w]})
    for l in lines:
        l['w'].sort(key=lambda w: w['x0'])
        l['text'] = ' '.join(w['text'] for w in l['w'])
    return lines


def page_cells(pdf, page):
    """PDF(Path) 의 page(1부터) -> PageCells. 괘선으로 업무명 열을 찾지 못하면 None.

    None 인 쪽: 전폭 글, 서식, 훈령, 전폭 표. 이 쪽에는 업무명 `##` 가 없고 앞 업무가 이어진다.
    """
    pg = _open(Path(pdf)).pages[page - 1]
    x, spans = _find_boundary(pg)
    if x is None:
        return None
    words = pg.extract_words(keep_blank_chars=False, use_text_flow=False, x_tolerance=2, y_tolerance=2)
    cells = []
    for t, b in spans:
        cw = [w for w in words if t - 1 <= (w['top'] + w['bottom']) / 2 <= b + 1]
        left = [w for w in cw if w['x1'] <= x + 2 and w['text'] not in ('~', '목차', '')]
        right = [w for w in cw if w['x0'] >= x - 2]
        lraw = ' '.join(l['text'] for l in _lines_of(left))
        lab, how = resolve_label(lraw)
        cells.append(Cell(t, b, lraw, [w['text'] for w in sorted(left, key=lambda w: (w['top'], w['x0']))],
                          lab or '', how,
                          [CellLine(round(l['top'], 1), l['text']) for l in _lines_of(right)]))
    return PageCells(page, x, cells)


def find_text_y(pdf, page, pattern):
    """쪽 안에서 정규식과 맞는 줄의 (y, 줄 글자) 목록. 문서 분리 지점을 찾을 때 쓴다."""
    pg = _open(Path(pdf)).pages[page - 1]
    words = pg.extract_words(x_tolerance=2, y_tolerance=2)
    hits = []
    for l in _lines_of(words):
        flat = re.sub(r'\s+', '', l['text'])
        if re.search(pattern, flat):
            hits.append((round(l['top'], 1), l['text']))
    return hits
