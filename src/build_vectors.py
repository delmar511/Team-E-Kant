# -*- coding: utf-8 -*-
"""chunks.jsonl -> 벡터 색인 (구성 A·B 용)

담당: 서종찬 | 평가표 4번
실행: python src/build_vectors.py

BM25 색인과 파일을 나눈 이유
-------------------------
임베딩은 API 를 전량 호출해서 돈과 시간이 든다. 청킹을 고칠 때마다
다시 돌리면 비용이 반복된다. 그래서 따로 두고 필요할 때만 돌린다.

비용
----
청크 1,646개 / 본문 약 53만자. text-embedding-3-large 기준 $0.1 내외.
모델을 바꾸면 전량 다시 호출해야 하므로 팀 합의 후에 바꾼다.
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import numpy as np
from openai import APIStatusError

sys.path.insert(0, str(Path(__file__).resolve().parent))

BATCH = 96          # 한 번에 보낼 청크 수. 요청당 토큰 상한을 넉넉히 피한다
MAX_RETRY = 5


def load_env(path='.env'):
    """python-dotenv 없이도 돌도록 직접 읽는다."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())


def slug(model):
    """모델명을 파일명으로 쓸 수 있게 바꾼다."""
    return re.sub(r'[^A-Za-z0-9._-]+', '-', model)


def load_chunks(path):
    rows = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def embed_text(c):
    """임베딩에 넣을 문자열.

    본문만 넣으면 '신청서, 여권, 수수료' 같은 청크가 어느 자격의 것인지
    알 수 없다. 경로를 앞에 붙여 맥락을 준다. BM25 와 달리 벡터는
    긴 맥락을 넣어도 토큰 수로 점수가 깎이지 않는다.
    """
    return f"{c['location']}\n\n{c['text']}"


def is_local(model):
    """허깅페이스 모델 이름은 'org/name' 꼴이다. OpenAI 모델명엔 / 가 없다."""
    return '/' in model


def embed_local(chunks, model):
    """sentence-transformers 로 내 컴퓨터에서 임베딩한다.

    KURE-v1 은 bge-m3 를 한국어로 추가 학습한 모델이다(1024차원).
    처음 돌리면 모델을 내려받으므로 시간이 걸린다.
    """
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer(model)
    texts = [embed_text(c) for c in chunks]
    a = m.encode(texts, batch_size=16, show_progress_bar=True,
                 normalize_embeddings=True, convert_to_numpy=True)
    return a.astype(np.float32)


def embed_all(client, chunks, model):
    vecs = []
    for i in range(0, len(chunks), BATCH):
        batch = [embed_text(c) for c in chunks[i:i + BATCH]]
        for attempt in range(MAX_RETRY):
            try:
                r = client.embeddings.create(model=model, input=batch)
                vecs.extend(d.embedding for d in r.data)
                break
            except APIStatusError as e:
                # 다시 보내도 결과가 같은 오류는 즉시 멈춘다.
                # 모델명 오타(404)로 5번 기다리는 건 시간 낭비다.
                if e.status_code in (400, 401, 403, 404):
                    sys.exit(f'재시도해도 소용없는 오류다. 설정을 확인할 것.\n  {e}')
                if attempt == MAX_RETRY - 1:
                    raise
                wait = 2 ** attempt
                print(f'  재시도 {attempt + 1}/{MAX_RETRY} ({wait}초): {e}')
                time.sleep(wait)
            except Exception as e:                      # 네트워크 등 일시 오류
                if attempt == MAX_RETRY - 1:
                    raise
                wait = 2 ** attempt
                print(f'  재시도 {attempt + 1}/{MAX_RETRY} ({wait}초): {e}')
                time.sleep(wait)
        done = min(i + BATCH, len(chunks))
        print(f'  {done}/{len(chunks)}', end='\r', flush=True)
    print()
    a = np.array(vecs, dtype=np.float32)
    # 코사인 유사도를 내적으로 계산하기 위해 미리 정규화해 둔다
    a /= np.linalg.norm(a, axis=1, keepdims=True)
    return a


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--chunks', default='data/chunks.jsonl')
    ap.add_argument('--out', default='data/index')
    ap.add_argument('--model', default=None, help='없으면 .env 의 EMBEDDING_MODEL')
    a = ap.parse_args()

    load_env()
    model = a.model or os.environ.get('EMBEDDING_MODEL')
    if not model:
        sys.exit('EMBEDDING_MODEL 이 없다. .env 에 적거나 --model 로 넘길 것')
    if not is_local(model) and not os.environ.get('OPENAI_API_KEY'):
        sys.exit('OPENAI_API_KEY 가 없다. .env 를 확인할 것')

    chunks = load_chunks(a.chunks)
    print(f'청크 {len(chunks)}개를 {model} 로 임베딩한다.')
    t0 = time.time()
    if is_local(model):
        vecs = embed_local(chunks, model)
    else:
        from openai import OpenAI
        vecs = embed_all(OpenAI(), chunks, model)

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tag = slug(model)
    np.save(out / f'vectors_{tag}.npy', vecs)
    # 기본 모델은 vectors.npy 로도 둬서 기존 명령이 그대로 돌게 한다
    if model == os.environ.get('EMBEDDING_MODEL'):
        np.save(out / 'vectors.npy', vecs)
        (out / 'vectors_meta.json').write_text(json.dumps({
            'embedding_model': model, 'n_chunks': len(chunks),
            'dim': int(vecs.shape[1]), 'normalized': True,
        }, ensure_ascii=False, indent=2), encoding='utf-8')
    (out / f'vectors_{tag}.meta.json').write_text(json.dumps({
        'embedding_model': model,
        'n_chunks': len(chunks),
        'dim': int(vecs.shape[1]),
        'normalized': True,
        'embed_input': 'location + 본문',
        'built_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'elapsed_sec': round(time.time() - t0, 1),
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'shape': list(vecs.shape), 'model': model,
                      'elapsed_sec': round(time.time() - t0, 1)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
