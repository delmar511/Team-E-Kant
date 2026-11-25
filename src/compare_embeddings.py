# -*- coding: utf-8 -*-
"""임베딩 모델 비교 (구성 A 기준)

담당: 서종찬 | 평가표 4번 (검색 설계 근거)
실행:
    python src/compare_embeddings.py text-embedding-3-small text-embedding-3-large

왜 구성 A 로 비교하나
------------------
구성 B(RRF)는 BM25 가 섞여서 모델 차이가 가려진다. dev 에서 이미 8/8 이라
어떤 모델을 써도 8/8 이 나올 것이다. 벡터 단독으로 재야 모델만의 차이가 보인다.

왜 Hit@5 만 보지 않나
-------------------
Hit@5 는 1위로 찾은 것과 5위로 겨우 찾은 것을 똑같이 'O' 로 처리한다.
문항이 8개뿐이라 그 해상도로는 모델 간 차이를 구분할 수 없다.
정답 청크가 **몇 위**였는지를 같이 본다.

- gold_rank : 정답 청크 중 가장 높은 순위 (1이 최고, 못 찾으면 없음)
- MRR       : 1/gold_rank 의 평균. 순위를 하나의 숫자로 요약한 값
              (1위=1.0, 2위=0.5, 5위=0.2, 못 찾음=0)
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import retrieve as R
from build_vectors import slug

INDEX = Path('data/index')
EVAL = 'eval/eval-dev.json'
DEPTH = 20          # 순위를 어디까지 들여다볼지


def ensure_vectors(model):
    """해당 모델의 벡터가 없으면 만든다."""
    f = INDEX / f'vectors_{slug(model)}.npy'
    if f.exists():
        print(f'  {model}: 이미 있음')
        return f
    print(f'  {model}: 임베딩 생성 중...')
    r = subprocess.run([sys.executable, 'src/build_vectors.py', '--model', model])
    if r.returncode != 0 or not f.exists():
        # 모델 하나가 막혀 있다고 비교 전체를 멈출 이유는 없다
        print(f'  {model}: 건너뛴다')
        return None
    return f


def measure(model, chunk_ids, rows):
    vecs = np.load(INDEX / f'vectors_{slug(model)}.npy')
    hit = 0
    rr = []
    ranks = []
    for r in rows:
        gold = {e['chunk_id'] for e in r['evidence'] if e.get('chunk_id')}
        if not gold:
            continue
        got = [cid for cid, _ in R.search_vector(vecs, chunk_ids, r['question'], model, n=DEPTH)]
        pos = next((i for i, c in enumerate(got, 1) if c in gold), None)
        if pos and pos <= R.TOP_K:
            hit += 1
        rr.append(1.0 / pos if pos else 0.0)
        ranks.append(pos)
    return {
        'model': model,
        'dim': int(vecs.shape[1]),
        'hit@5': f'{hit}/{len(rr)}',
        'MRR': round(sum(rr) / len(rr), 3),
        'ranks': ranks,
    }


def main():
    models = sys.argv[1:]
    if not models:
        sys.exit('비교할 모델명을 인자로 줄 것')
    R.load_env()
    _, chunk_ids, _, _ = R.load_index()
    rows = [r for r in json.loads(Path(EVAL).read_text(encoding='utf-8'))
            if r['type'] != 'no_answer']

    print('벡터 준비')
    usable = [m for m in models if ensure_vectors(m)]
    if not usable:
        sys.exit('쓸 수 있는 모델이 없다')
    if len(usable) < len(models):
        print(f'제외됨: {", ".join(set(models) - set(usable))}')

    print('\n측정 (구성 A, 벡터 단독)')
    results = [measure(m, chunk_ids, rows) for m in usable]

    ids = [r['id'] for r in rows if any(e.get('chunk_id') for e in r['evidence'])]
    w = max(len(r['model']) for r in results) + 2
    print()
    print(f'{"모델":{w}} {"차원":>6} {"Hit@5":>7} {"MRR":>7}   정답 순위 (- 는 20위 밖)')
    print('-' * (w + 34 + len(ids) * 4))
    for r in results:
        rk = ' '.join(f'{x if x else "-":>3}' for x in r['ranks'])
        print(f'{r["model"]:{w}} {r["dim"]:>6} {r["hit@5"]:>7} {r["MRR"]:>7}   {rk}')
    print(' ' * (w + 24) + '   ' + ' '.join(f'{i.split("-")[1]:>3}' for i in ids))

    out = Path('results/runs/embedding_compare.json')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({'eval': EVAL, 'config': 'A', 'results': results},
                              ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\n{out} 에 저장')


if __name__ == '__main__':
    main()
