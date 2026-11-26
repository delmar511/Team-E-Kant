# -*- coding: utf-8 -*-
"""검색 구성 A / B / C

담당: 서종찬 | 평가표 4·5번
A: Vector 단독   B: BM25 + Vector (RRF)   C: B + 재정렬

실행:
    python src/retrieve.py "어학연수 비자로 알바해도 되나요"
    python src/retrieve.py --eval eval/eval-dev.json     # dev 전체로 Hit@5 측정

평가표 4번의 '직접 구현'
----------------------
라이브러리의 하이브리드 검색 함수 하나를 호출하고 끝내면 안 된다.
BM25 검색과 벡터 검색을 따로 호출하고, 결합 로직을 우리 코드로 가지고 있어야 한다.

RRF 공식
--------
    score(d) = 1/(K + rank_bm25(d)) + 1/(K + rank_vector(d))

점수를 버리고 순위만 쓴다. BM25 는 상한이 없고 코사인은 0~1 이라
단순 합산하면 BM25 가 벡터를 압도한다. (발제가 단순 합산을 금지)
"""
import argparse
import json
import os
import pickle
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tokenizer import tokenize                      # noqa: E402

RRF_K = 60                  # RRF 상수. 원 논문 권고값
CANDIDATES = 20             # 각 검색기가 내놓는 후보 수
TOP_K = 5                   # 최종 반환 수. Hit@5 와 맞춘다


def load_env(path='.env'):
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())


def load_vectors(index_dir='data/index'):
    """벡터 색인을 읽는다. 없으면 (None, None)."""
    d = Path(index_dir)
    f = d / 'vectors.npy'
    if not f.exists():
        return None, None
    vecs = np.load(f)
    meta = json.loads((d / 'vectors_meta.json').read_text(encoding='utf-8'))
    return vecs, meta


_LOCAL_CACHE = {}


def embed_query(query, model):
    """질의를 임베딩한다. 색인할 때와 반드시 같은 모델이어야 한다.

    허깅페이스 모델('org/name')은 내 컴퓨터에서, 그 외는 OpenAI API 로 돌린다.
    로컬 모델은 적재가 느려서 한 번 띄우면 캐시해 둔다.
    """
    if '/' in model:                       # 로컬(sentence-transformers)
        if model not in _LOCAL_CACHE:
            from sentence_transformers import SentenceTransformer
            _LOCAL_CACHE[model] = SentenceTransformer(model)
        v = _LOCAL_CACHE[model].encode([query], normalize_embeddings=True,
                                       convert_to_numpy=True)[0]
        return np.asarray(v, dtype=np.float32)
    from openai import OpenAI
    v = OpenAI().embeddings.create(model=model, input=[query]).data[0].embedding
    v = np.asarray(v, dtype=np.float32)
    return v / np.linalg.norm(v)


def search_vector(vecs, chunk_ids, query, model, n=CANDIDATES):
    """질의 -> [(chunk_id, 코사인유사도)] 상위 n 개.

    색인할 때 정규화해 뒀으므로 내적이 곧 코사인 유사도다.
    1,646개면 전수 비교가 순식간이라 ANN 인덱스가 필요 없다.
    """
    q = embed_query(query, model)
    sims = vecs @ q
    idx = np.argsort(-sims)[:n]
    return [(chunk_ids[i], float(sims[i])) for i in idx]


# ============================================================ 본인 작성 구간
def rrf(*ranked_lists, weights=None, k=RRF_K, n=TOP_K):
    """여러 검색기의 순위를 RRF 로 합친다. -> [(chunk_id, rrf점수)] 상위 n 개

    평가표 4번이 '직접 구현' 을 요구하는 지점이다.
    라이브러리의 하이브리드 함수를 부르는 게 아니라 이 결합을 우리가 가지고 있어야 한다.

    공식
    ----
        score(d) = Σ  1 / (k + rank_i(d))
                   i

    rank 는 그 검색기에서 d 가 몇 등이었나다. 1등이면 1, 2등이면 2.
    어느 검색기에도 안 나온 문서는 그 검색기에서 더하는 값이 0 이다.

    왜 점수가 아니라 순위인가
    ----------------------
    BM25 점수는 상한이 없고(오늘 본 값은 8~18), 코사인은 0~1 이다.
    그냥 더하면 BM25 가 벡터를 압도한다. 순위로 바꾸면 두 검색기가 대등해진다.

    할 일
    -----
    1. 결과를 모을 딕셔너리를 하나 만든다 (chunk_id -> 누적 점수)
    2. ranked_lists 안의 각 목록을 돌면서
       - 목록 안에서 몇 등인지(rank)를 센다. enumerate(목록, 1) 을 쓰면 1 부터 센다
       - 그 chunk_id 의 누적 점수에 1 / (k + rank) 를 더한다
         (아직 없는 chunk_id 면 0 에서 시작해야 한다. dict.get(cid, 0) 을 쓰면 된다)
    3. 누적 점수가 높은 순으로 정렬해 상위 n 개를 [(chunk_id, 점수)] 로 돌려준다

    인자
    ----
    ranked_lists : 각각 [(chunk_id, 점수)] 형태. 점수는 여기서 쓰지 않는다. 순서만 쓴다.
    weights      : 검색기별 가중치. 없으면 전부 1.0 (= 원래 RRF)

    왜 가중치가 필요한가
    ------------------
    동등 가중치 RRF 는 두 검색기의 품질이 비슷할 때를 가정한다.
    한쪽이 뚜렷이 약하면 그 검색기의 1·2위가 강한 검색기의 1위와 거의 동점이 되어
    앞자리를 거저 가져간다. 실제로 KURE 벡터(MRR 0.792)에 BM25(0.453)를
    동등 가중치로 합치자 MRR 이 0.557 로 떨어졌다.
    """
    # 가중치: 검색기마다 신뢰도가 다르면 기여도를 다르게 준다.
    # 다 1.0 이면 원래의 RRF 와 같다.
    w = weights or [1.0] * len(ranked_lists)
    scores = {}
    for lst, wi in zip(ranked_lists, w):
        for rank, (cid, _) in enumerate(lst, 1):
            scores[cid] = scores.get(cid, 0) + wi / (k + rank)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)[:n]
# =========================================================== /본인 작성 구간


def load_index(index_dir='data/index', chunks_path='data/chunks.jsonl'):
    """BM25 색인, 청크 순서 목록, chunk_id -> 청크 사전, 색인 메타를 읽는다."""
    d = Path(index_dir)
    with open(d / 'bm25.pkl', 'rb') as f:
        blob = pickle.load(f)
    chunk_ids = json.loads((d / 'chunk_ids.json').read_text(encoding='utf-8'))
    chunks = {}
    with open(chunks_path, encoding='utf-8') as f:
        for line in f:
            if line.strip():
                c = json.loads(line)
                chunks[c['chunk_id']] = c
    meta = json.loads((d / 'meta.json').read_text(encoding='utf-8'))
    return blob['bm25'], chunk_ids, chunks, meta


# ============================================================ 본인 작성 구간
def search_bm25(bm25, chunk_ids, query, n=CANDIDATES, protect=True):
    """질의 -> [(chunk_id, 점수)] 상위 n 개, 점수 내림차순

    할 일
    -----
    1. query 를 tokenize() 로 토큰 목록으로 바꾼다.
       색인을 만들 때와 같은 토크나이저를 써야 한다. 다르면 아예 안 걸린다.

    2. bm25.get_scores(토큰목록) 을 부른다.
       -> 청크 1,646개 각각에 대한 점수 배열이 나온다 (색인 순서와 같다)

    3. 점수가 높은 순으로 상위 n 개의 '순번' 을 고른다.
       힌트: sorted(range(len(scores)), key=..., reverse=True)[:n]

    4. 순번을 chunk_id 로 바꿔 [(chunk_id, 점수)] 로 돌려준다.
       chunk_ids[순번] 이 그 순번의 chunk_id 다.
    """
    tokens = tokenize(query, protect)
    scores = bm25.get_scores(tokens)
    idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse= True)[:n]
    return [(chunk_ids[i], scores[i]) for i in idx]
# =========================================================== /본인 작성 구간


def show(results, chunks, query):
    print(f'\n질의: {query}')
    print('-' * 78)
    for i, (cid, score) in enumerate(results[:TOP_K], 1):
        c = chunks[cid]
        body = ' '.join(c['text'].split())[:90]
        print(f'{i}. [{score:6.2f}] {c["location"]}')
        print(f'          p.{c["page"]}  {body}')
    if not results:
        print('  (결과 없음)')


def evaluate(path, run, chunks, label):
    """dev 평가셋으로 Hit@5 를 잰다. run(query) -> [(chunk_id, 점수)]"""
    rows = json.loads(Path(path).read_text(encoding='utf-8'))
    scored = [r for r in rows if r['type'] != 'no_answer']
    hit = n = 0
    rr = []
    skipped = []
    for r in scored:
        gold = {e['chunk_id'] for e in r['evidence'] if e.get('chunk_id')}
        if not gold:
            # 정답 청크가 없으면 채점 대상이 아니다. 0점이 아니라 '측정 불가'다.
            skipped.append(r['id'])
            continue
        n += 1
        ordered = [cid for cid, _ in run(r['question'])]
        # 정답 청크가 몇 위였나. Hit@5 는 1위와 5위를 똑같이 O 로 처리하므로
        # 순위를 같이 봐야 구성 간 차이가 보인다.
        pos = next((i for i, c in enumerate(ordered, 1) if c in gold), None)
        ok = bool(pos and pos <= TOP_K)
        hit += ok
        rr.append(1.0 / pos if pos else 0.0)
        print(f'  {"O" if ok else "X"}  {r["id"]}  {str(pos) if pos else "-":>3}위  {r["question"][:40]}')
    if skipped:
        print(f'\n채점 제외 {len(skipped)}건 (chunk_id 없음): {", ".join(skipped)}')
        print('  -> python src/link_evidence.py <평가셋> --write 를 먼저 돌릴 것')
    if n:
        mrr = sum(rr) / len(rr)
        print(f'\nHit@{TOP_K} = {hit}/{n}   MRR = {mrr:.3f}   ({label}, no_answer 제외)')
    else:
        print('\n채점 가능한 문항이 없다.')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('query', nargs='?')
    ap.add_argument('--eval')
    ap.add_argument('--index', default='data/index')
    ap.add_argument('--no-protect', action='store_true', dest='no_protect',
                    help='질문 쪽 비자 코드 보호도 끈다. 보호 OFF 색인과 짝으로만 쓸 것')
    ap.add_argument('--w-bm25', type=float, default=1.0, dest='w_bm25',
                    help='구성 B 에서 BM25 의 가중치. 1.0 이 원래 RRF')
    ap.add_argument('--config', default='bm25', choices=['bm25', 'A', 'B'],
                    help='bm25=BM25 단독(기준선), A=벡터 단독, B=BM25+벡터 RRF')
    a = ap.parse_args()

    load_env()
    bm25, chunk_ids, chunks, meta = load_index(a.index)
    pr = not a.no_protect
    # 색인과 질문의 전처리가 다르면 비교가 무의미하다. 섞어 쓰면 멈춘다.
    if meta.get('protect_visa_codes') is not None and meta['protect_visa_codes'] != pr:
        import sys as _s
        _s.exit(f"색인은 보호 {meta['protect_visa_codes']}, 질문은 보호 {pr} 다. "
                '질문과 문서에 같은 전처리를 써야 한다.')
    vecs, vmeta = load_vectors(a.index)
    model = os.environ.get('EMBEDDING_MODEL')
    print(f'색인 {meta["index_version"]} / 청크 {meta["n_chunks"]}개 / 구성 {a.config}')

    if a.config in ('A', 'B'):
        if vecs is None:
            sys.exit('벡터 색인이 없다. python src/build_vectors.py 를 먼저 돌릴 것')
        if not model:
            sys.exit('EMBEDDING_MODEL 이 없다. .env 를 확인할 것')
        if vmeta['embedding_model'] != model:
            sys.exit(f'색인은 {vmeta["embedding_model"]} 로 만들었는데 .env 는 {model} 다. '
                     '모델이 다르면 비교가 무의미하다')

    if a.config == 'bm25':
        run = lambda q: search_bm25(bm25, chunk_ids, q, protect=pr)
        label = 'BM25 단독'
    elif a.config == 'A':
        run = lambda q: search_vector(vecs, chunk_ids, q, model)
        label = f'구성 A 벡터 단독 ({model})'
    else:
        wb = a.w_bm25
        run = lambda q: rrf(search_bm25(bm25, chunk_ids, q, protect=pr),
                            search_vector(vecs, chunk_ids, q, model),
                            weights=[wb, 1.0], n=CANDIDATES)
        label = f'구성 B BM25+벡터 RRF (k={RRF_K}, w_bm25={wb})'

    if a.eval:
        evaluate(a.eval, run, chunks, label)
    elif a.query:
        show(run(a.query), chunks, a.query)
    else:
        ap.error('질의 또는 --eval 중 하나는 필요하다')


if __name__ == '__main__':
    main()
