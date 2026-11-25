# -*- coding: utf-8 -*-
"""진단: BM25 와 벡터의 후보가 실제로 얼마나 겹치나

RRF 는 두 검색기가 같은 문서를 각자 찾아냈을 때 그 문서를 밀어 올리는 방식이다.
겹치는 문서가 없으면 모든 문서의 점수가 1/(k+순위) 하나뿐이라
동점이 무더기로 생기고, 정렬은 먼저 넘긴 목록을 앞에 둔다.
그러면 RRF 가 '합치기' 가 아니라 '이어붙이기' 가 된다.

실행: python src/diag_overlap.py eval/eval-dev.json
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import retrieve as R


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'eval/eval-dev.json'
    R.load_env()
    bm25, chunk_ids, chunks, _ = R.load_index()
    vecs, vmeta = R.load_vectors()
    model = os.environ['EMBEDDING_MODEL']

    rows = [r for r in json.loads(Path(path).read_text(encoding='utf-8'))
            if r['type'] != 'no_answer']

    print(f'{"문항":10} {"겹침/20":>8}  {"B상위5의 출처":>14}')
    print('-' * 46)
    tot = 0
    for r in rows:
        b = R.search_bm25(bm25, chunk_ids, r['question'])
        v = R.search_vector(vecs, chunk_ids, r['question'], model)
        bset = {c for c, _ in b}
        vset = {c for c, _ in v}
        inter = bset & vset
        tot += len(inter)

        top5 = [c for c, _ in R.rrf(b, v)]
        src = ''.join('B' if c in bset and c not in vset else
                      'V' if c in vset and c not in bset else
                      '*' for c in top5)
        print(f'{r["id"]:10} {len(inter):4}/20     {src:>14}')
    print('-' * 46)
    print(f'평균 겹침 {tot / len(rows):.1f} / 20')
    print('B=BM25에만, V=벡터에만, *=양쪽 모두')


if __name__ == '__main__':
    main()
