# -*- coding: utf-8 -*-
"""검토된 배치 작업(placement_v1.jsonl)을 docs/corpus/*.md 에 적용한다. 표준 라이브러리만 쓴다.

작업 5종 (docs/conversion_notes.md 수정 12):
  move_heading   기존 `## 업무명` 줄을 to_line 앞으로 옮긴다 (줄 글자는 그대로)
  insert_heading `## 업무명` 줄을 to_line 앞에 넣는다 (허용 목록의 업무명만)
  delete_line    라벨 조각만으로 된 줄을 지운다
  strip_fragment 줄 앞(또는 뒤)에 붙은 라벨 조각만 떼어 낸다
  split_doc      line 부터 끝까지를 새 문서로 옮긴다

원문 보존: 본문 줄의 순서와 글자는 바뀌지 않는다. 바뀌는 것은 `##` 줄의 위치·삽입,
승인된 라벨 조각, 문서 분리뿐이다. check_invariants 가 이를 증명하고, 어긋나면
PlacementError 를 내며 아무것도 쓰지 않는다.

사용:
  python src/ingest/apply_placement.py --ops docs/corpus_fixes/placement_v1.jsonl \\
         --corpus docs/corpus --out /tmp/corpus_dry --include-proposed      # 모의 적용
  python src/ingest/apply_placement.py --ops ... --corpus docs/corpus --write   # accepted 만 반영
"""
import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

try:
    from ingest import pdf_to_md as P
except ImportError:                                  # 스크립트로 직접 실행
    import pdf_to_md as P

OPS = ('move_heading', 'insert_heading', 'delete_line', 'strip_fragment', 'split_doc')
PAGE_RE = re.compile(r'^<!-- page: (\d+) -->$')


class PlacementError(Exception):
    pass


@dataclass
class PlacementOp:
    op: str
    file: str
    line: int                       # 원본 파일의 줄 번호 (1부터)
    expect: str                     # 그 줄의 정확한 원문. 다르면 적용하지 않는다
    to_line: int = None             # move/insert: 이 원본 줄 앞에 넣는다
    expect_to: str = None           # to_line 줄의 원문
    heading: str = None             # move/insert: `## ` 뒤의 글자
    fragment: str = None            # strip: 떼어 낼 조각
    new_doc: dict = None            # split_doc: {doc_id, title, file}
    mech: str = ''
    evidence: dict = field(default_factory=dict)    # {page, y, cell, label_raw}
    cands: list = field(default_factory=list)       # 다른 배치 후보 줄 번호 등
    confidence: str = 'high'        # high | low
    status: str = 'proposed'        # proposed | accepted | rejected
    reviewer: str = None
    id: str = ''

    def to_json(self):
        return json.dumps(asdict(self), ensure_ascii=False)


def load_ops(path, statuses=('accepted',)):
    ops = []
    for n, line in enumerate(Path(path).read_text(encoding='utf-8').split('\n'), 1):
        if not line.strip():
            continue
        d = json.loads(line)
        if d.get('op') not in OPS:
            raise PlacementError(f'{path}:{n} 알 수 없는 작업 {d.get("op")!r}')
        if d.get('status') in statuses:
            ops.append(PlacementOp(**d))
    return ops


# ---------------------------------------------------------------- 라벨 조각
def _knorm(s):
    return re.sub(r'[\s·]', '', re.sub(r'[-]', '', s or ''))


_LABEL_KEYS = [_knorm(x) for x in P.ALL_LABELS] + [_knorm(x) for x in P.LABEL_ALIASES]


def is_label_fragment(text):
    """text 가 업무명 글자의 일부분(조각)뿐인가. 공백·가운뎃점은 무시한다.

    '근무처의', '변경추가', '부 여', '체류자격', '활동범위', '해 당 자' 는 조각이다.
    """
    k = _knorm(text)
    return len(k) >= 2 and any(k in key for key in _LABEL_KEYS)


def strip_fragment_text(text, fragment):
    """줄 앞(없으면 뒤)의 fragment 를 떼고 남은 글자를 돌려준다. 앞·뒤가 아니면 None."""
    if text.startswith(fragment):
        rest = text[len(fragment):]
        if rest[:1] in (' ', '\t'):
            return rest.lstrip(' \t')
        return None
    if text.endswith(fragment):
        rest = text[:-len(fragment)]
        if rest[-1:] in (' ', '\t'):
            return rest.rstrip(' \t')
    return None


# ---------------------------------------------------------------- 적용
def _is_content(line):
    """불변식이 지키는 줄: 빈 줄·쪽 표시·`#`/`##` 제목이 아닌 줄 (###/#### 제목은 본문 취급)."""
    if not line.strip() or PAGE_RE.match(line):
        return False
    if re.match(r'^#{1,2}\s', line):
        return False
    return True


def _front_matter(lines):
    if lines and lines[0] == '---':
        for i in range(1, len(lines)):
            if lines[i] == '---':
                return lines[:i + 1]
    return []


def _validate(lines_by_file, ops):
    by_file = {}
    for op in ops:
        if op.file not in lines_by_file:
            raise PlacementError(f'{op.id or op.op}: 파일이 없다 {op.file}')
        by_file.setdefault(op.file, []).append(op)
    for f, fops in by_file.items():
        lines = lines_by_file[f]
        for op in fops:
            if not (1 <= op.line <= len(lines)) or lines[op.line - 1] != op.expect:
                got = lines[op.line - 1] if 1 <= op.line <= len(lines) else None
                raise PlacementError(f'{f}:{op.line} {op.op} expect 불일치: 기대 {op.expect!r}, 실제 {got!r}'
                                     ' (이미 적용했거나 코퍼스가 바뀌었다)')
            if op.op in ('move_heading', 'insert_heading'):
                if op.to_line is None or not (1 <= op.to_line <= len(lines)):
                    raise PlacementError(f'{f}:{op.line} to_line 이 없다')
                if op.expect_to is not None and lines[op.to_line - 1] != op.expect_to:
                    raise PlacementError(f'{f}:{op.to_line} expect_to 불일치: 기대 {op.expect_to!r}, '
                                         f'실제 {lines[op.to_line - 1]!r}')
                if not op.heading or '\n' in op.heading:
                    raise PlacementError(f'{f}:{op.line} heading 이 비어 있다')
                if op.op == 'insert_heading' and op.heading not in P.ALL_LABELS:
                    raise PlacementError(f'{f}:{op.line} 허용 목록에 없는 업무명 {op.heading!r}')
                if op.op == 'move_heading' and op.expect != '## ' + op.heading:
                    raise PlacementError(f'{f}:{op.line} move 의 heading 이 expect 와 다르다')
                # 이미 적용한 작업을 다시 적용하지 않는다: 도착 줄 바로 앞에 같은 제목이 있으면 오류
                k = op.to_line - 2
                while k >= 0 and not lines[k].strip():
                    k -= 1
                while k >= 0 and PAGE_RE.match(lines[k]):
                    k -= 1
                    while k >= 0 and not lines[k].strip():
                        k -= 1
                if k >= 0 and lines[k] == '## ' + op.heading:
                    raise PlacementError(f'{f}:{op.to_line} 이미 같은 제목이 있다 (두 번 적용?)')
                if op.op == 'move_heading' and op.to_line == op.line:
                    raise PlacementError(f'{f}:{op.line} 제자리 move')
            if op.op == 'move_heading' and not lines[op.line - 1].startswith('## '):
                raise PlacementError(f'{f}:{op.line} `## ` 줄이 아니다')
            if op.op == 'delete_line':
                if not is_label_fragment(op.expect):
                    raise PlacementError(f'{f}:{op.line} 라벨 조각이 아닌 줄은 지울 수 없다: {op.expect!r}')
            if op.op == 'strip_fragment':
                if not op.fragment or not is_label_fragment(op.fragment):
                    raise PlacementError(f'{f}:{op.line} 라벨 조각이 아니다: {op.fragment!r}')
                if strip_fragment_text(op.expect, op.fragment) is None:
                    raise PlacementError(f'{f}:{op.line} 조각이 줄의 앞·뒤에 있지 않다: {op.fragment!r}')
                if not strip_fragment_text(op.expect, op.fragment):
                    raise PlacementError(f'{f}:{op.line} 조각을 떼면 줄이 비어 버린다')
            if op.op == 'split_doc':
                nd = op.new_doc or {}
                if not all(nd.get(k) for k in ('doc_id', 'title', 'file')):
                    raise PlacementError(f'{f}:{op.line} split_doc 의 new_doc 에 doc_id/title/file 이 필요하다')
                if nd['file'] in lines_by_file:
                    raise PlacementError(f'{nd["file"]} 이미 있다')
        if sum(1 for o in fops if o.op == 'split_doc') > 1:
            raise PlacementError(f'{f}: split_doc 은 파일당 1개만 지원한다')
        seen = {}
        for op in fops:
            if op.op in ('move_heading', 'delete_line', 'strip_fragment'):
                if (op.op, op.line) in seen:
                    raise PlacementError(f'{f}:{op.line} 같은 줄에 {op.op} 가 두 번이다')
                seen[(op.op, op.line)] = 1
        dl = {o.line for o in fops if o.op in ('delete_line', 'move_heading')}
        for op in fops:
            if op.op == 'strip_fragment' and op.line in dl:
                raise PlacementError(f'{f}:{op.line} strip 과 delete 가 겹친다')
    return by_file


def _apply_file(lines, fops, name):
    """한 파일에 적용 -> (새 줄 목록, split 이 있으면 (새 파일 이름, 새 줄 목록))"""
    delete = {o.line for o in fops if o.op in ('delete_line', 'move_heading')}
    strip = {o.line: o for o in fops if o.op == 'strip_fragment'}
    pre = {}                                        # to_line -> [heading, ...] (작업 순서)
    for o in sorted((o for o in fops if o.op in ('move_heading', 'insert_heading')), key=lambda o: (o.to_line, o.id)):
        pre.setdefault(o.to_line, []).append(o.heading)
    split = next((o for o in fops if o.op == 'split_doc'), None)

    out = []                                        # (attach_line | None, text); attach = 이 줄에 딸린 것
    for i, text in enumerate(lines, 1):
        for h in pre.get(i, []):
            if out and out[-1][1].strip():
                out.append((i, ''))
            out.append((i, '## ' + h))
            out.append((i, ''))
        if i in delete:
            # 지운 줄 때문에 빈 줄이 겹치지 않게 한다
            if i < len(lines) and not lines[i].strip() and out and not out[-1][1].strip():
                delete.add(i + 1)
            continue
        if i in strip:
            o = strip[i]
            text = strip_fragment_text(text, o.fragment)
        out.append((i, text))

    if split is None:
        return [t for _, t in out], None
    # split: split.line 에 딸린 항목(삽입한 제목 포함)부터가 새 문서
    pos = next(k for k, (a, _) in enumerate(out) if a == split.line)
    head, tail = out[:pos], out[pos:]
    page = None
    for _, t in head:
        m = PAGE_RE.match(t)
        if m:
            page = int(m.group(1))
    while head and not head[-1][1].strip():
        head.pop()
    carried_marker = None
    if head and PAGE_RE.match(head[-1][1]):        # 쪽이 막 시작한 자리에서 갈라지면 쪽 표시는 새 문서가 가져간다
        carried_marker = head.pop()[1]
        while head and not head[-1][1].strip():
            head.pop()
    nd = split.new_doc
    fm = [l for l in _front_matter(lines)]
    new_fm = []
    for l in fm:
        if l.startswith('doc_id:'):
            l = f'doc_id: {nd["doc_id"]}'
        elif l.startswith('title:'):
            l = f'title: {nd["title"]}'
        new_fm.append(l)
    if not new_fm:
        raise PlacementError(f'{name}: front matter 가 없어 새 문서를 만들 수 없다')
    # 새 문서의 시작 쪽: split 줄 앞의 쪽 표시. 새 쪽이 곧바로 시작하면 tail 의 첫 쪽 표시를 쓴다
    body = [t for _, t in tail]
    while body and not body[0].strip():
        body.pop(0)
    new_lines = new_fm + ['', f'# {nd["title"]}', '']
    marker = carried_marker or (f'<!-- page: {page} -->' if page is not None and not (body and PAGE_RE.match(body[0])) else None)
    if marker:
        new_lines += [marker, '']
    new_lines += body
    return [t for _, t in head] + [''], (nd['file'], new_lines)


def _content(lines):
    """불변식이 지키는 본문 줄 목록 (front matter 제외)."""
    return [l for l in lines[len(_front_matter(lines)):] if _is_content(l)]


def check_invariants(before, after, ops):
    """원문 보존을 증명한다. 위반하면 PlacementError.

    - 원본 파일마다 본문 줄(빈 줄·쪽 표시·# / ## 제목 제외)의 순서와 글자가, 승인된 delete/strip 만
      반영한 기대값과 같다 (split 으로 새로 생긴 문서까지 이어 붙여 비교한다)
    - 작업이 없는 파일은 줄 단위로 같다
    - 새 문서에는 front matter(doc_id/title/source/version), `# 제목`, 쪽 표시가 있다
    - 쪽 표시의 순서가 같다 (새 문서의 시작 쪽 표시는 예외로 하나 더 올 수 있다)
    """
    by_file = {}
    for op in ops:
        by_file.setdefault(op.file, []).append(op)
    new_files = {op.new_doc['file']: op for op in ops if op.op == 'split_doc'}
    for f, lines in before.items():
        a = after.get(f)
        if a is None:
            raise PlacementError(f'{f}: 결과에 없다')
        fops = by_file.get(f)
        if not fops:
            if a != lines:
                raise PlacementError(f'{f}: 작업이 없는데 바뀌었다')
            continue
        exp = []
        dele = {o.line for o in fops if o.op == 'delete_line'}
        strip = {o.line: o for o in fops if o.op == 'strip_fragment'}
        nfm = len(_front_matter(lines))
        for i, l in enumerate(lines, 1):
            if i <= nfm or i in dele:
                continue
            if i in strip:
                l = strip_fragment_text(l, strip[i].fragment)
            if _is_content(l):
                exp.append(l)
        split = next((o for o in fops if o.op == 'split_doc'), None)
        got = _content(a)
        if split:
            nf = after.get(split.new_doc['file'])
            if nf is None:
                raise PlacementError(f'{split.new_doc["file"]}: 새 문서가 결과에 없다')
            got = got + _content(nf)
        if got != exp:
            n = next((k for k, (x, y) in enumerate(zip(got, exp)) if x != y), min(len(got), len(exp)))
            raise PlacementError(f'{f}: 본문 줄이 달라졌다 (본문 {n + 1}번째 줄 근처, 결과 {len(got)}줄 / 기대 {len(exp)}줄)')
        # 쪽 표시 순서
        pg_b = [l for l in lines if PAGE_RE.match(l)]
        pg_a = [l for l in a if PAGE_RE.match(l)]
        if split:
            pg_a += [l for l in after[split.new_doc['file']] if PAGE_RE.match(l)]
            # 새 문서가 쪽 표시를 하나 더 가진다 (쪽 중간에서 갈라졌을 때)
            if len(pg_a) == len(pg_b) + 1:
                pg_a = [l for k, l in enumerate(pg_a)]
                for k in range(len(pg_a)):
                    if pg_a[:k] + pg_a[k + 1:] == pg_b:
                        pg_a = pg_b
                        break
        if pg_a != pg_b:
            raise PlacementError(f'{f}: 쪽 표시가 달라졌다')
        # 삽입한 제목은 허용 목록뿐: 새로 생긴 `## ` 가 기존 줄 목록에 없으면 허용 목록이어야 한다
        old_h2 = set(l for l in lines if l.startswith('## '))
        allowed = {'## ' + x for x in P.ALL_LABELS}
        for l in list(a) + (list(after[split.new_doc['file']]) if split else []):
            if l.startswith('## ') and l not in old_h2 and l not in allowed:
                raise PlacementError(f'{f}: 허용 목록에 없는 새 제목 {l!r}')
    for nf, op in new_files.items():
        lines = after[nf]
        head = '\n'.join(lines[:12])
        nd = op.new_doc
        for key, val in (('doc_id', nd['doc_id']), ('title', nd['title'])):
            if f'{key}: {val}' not in head:
                raise PlacementError(f'{nf}: front matter 의 {key} 가 없다')
        for key in ('source:', 'version:'):
            if key not in head:
                raise PlacementError(f'{nf}: front matter 에 {key} 가 없다')
        if f'# {nd["title"]}' not in lines[:12]:
            raise PlacementError(f'{nf}: `# 제목` 이 없다')
        if not any(PAGE_RE.match(l) for l in lines):
            raise PlacementError(f'{nf}: 쪽 표시가 없다')


def apply(lines_by_file, ops):
    """{파일: 줄 목록} 과 작업 -> {파일: 새 줄 목록} (분리된 새 문서 포함). 입력은 바꾸지 않는다."""
    by_file = _validate(lines_by_file, ops)
    after = {f: list(l) for f, l in lines_by_file.items()}
    for f, fops in by_file.items():
        new_lines, extra = _apply_file(lines_by_file[f], fops, f)
        after[f] = new_lines
        if extra:
            after[extra[0]] = extra[1]
    check_invariants(lines_by_file, after, ops)
    return after


def read_corpus(corpus_dir):
    out = {}
    for p in sorted(Path(corpus_dir).glob('*.md')):
        text = p.read_text(encoding='utf-8')                 # 줄바꿈은 LF 로 읽는다
        lines = text.split('\n')
        if lines and lines[-1] == '':
            lines.pop()
        out[p.name] = lines
    return out


def write_corpus(out_dir, files):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, lines in files.items():
        data = '\n'.join(lines).rstrip('\n') + '\n'
        with open(out / name, 'w', encoding='utf-8', newline='\n') as f:
            f.write(data)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--ops', required=True)
    ap.add_argument('--corpus', default='docs/corpus')
    ap.add_argument('--out', help='모의 적용 결과 폴더 (--write 가 없을 때 필수)')
    ap.add_argument('--write', action='store_true', help='--corpus 에 직접 반영 (accepted 작업만)')
    ap.add_argument('--include-proposed', action='store_true', help='proposed 작업도 적용 (모의 적용 전용)')
    a = ap.parse_args(argv)
    if a.write and a.include_proposed:
        ap.error('--write 는 accepted 작업만 적용한다 (--include-proposed 와 함께 못 쓴다)')
    if not a.write and not a.out:
        ap.error('--out 이 필요하다 (또는 --write)')
    statuses = ('accepted', 'proposed') if a.include_proposed else ('accepted',)
    ops = load_ops(a.ops, statuses)
    before = read_corpus(a.corpus)
    after = apply(before, ops)
    changed = [f for f in after if f not in before or after[f] != before[f]]
    if a.write:
        write_corpus(a.corpus, {f: after[f] for f in changed})
        target = a.corpus
    else:
        write_corpus(a.out, after)                      # 전체 복사본
        target = a.out
    print(f'작업 {len(ops)}건 적용, 문서 {len(after)}개 (바뀐 문서 {len(changed)}개) -> {target}')
    print('check_invariants 통과')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except PlacementError as e:
        print(f'PlacementError: {e}', file=sys.stderr)
        sys.exit(2)
