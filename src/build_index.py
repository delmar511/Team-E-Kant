# -*- coding: utf-8 -*-
"""chunks.jsonl -> BM25 색인

담당: 서종찬 | 평가표 3·4번
실행: python src/build_index.py --chunks data/chunks.jsonl --out data/index --version idx-v1

청킹과 파일을 나눈 이유
--------------------
청킹은 싸고 자주 돌린다. 여기는 나중에 임베딩 API 를 전량 호출해서 비싸다.
합쳐두면 청킹 오타 하나 고칠 때마다 임베딩 비용이 다시 나간다.
"""
import argparse
import datetime
import json
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tokenizer import tokenize                      # noqa: E402

from rank_bm25 import BM25Okapi                     # noqa: E402


def load_chunks(path):
    """chunks.jsonl 을 읽고 주소 3종이 다 있는지 검사한다."""
    rows = []
    with open(path, encoding='utf-8') as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            for key in ('chunk_id', 'doc_id', 'location'):
                if not r.get(key):
                    raise ValueError(f'{path}:{n} 에 {key} 가 없다')
            rows.append(r)
    if not rows:
        raise ValueError(f'{path} 가 비어 있다')
    return rows


# ============================================================ 본인 작성 구간
def build_bm25(chunks):
    """청크 목록 -> (BM25Okapi 색인, 토큰화된 문서 목록)

    할 일
    -----
    1. 각 청크의 'text' 를 tokenize() 에 넣어 토큰 목록으로 바꾼다.
       tokenize 는 위에서 이미 import 돼 있다.
       결과는 '리스트의 리스트' 가 된다:
           [['E-7','비자','연장'], ['학사','과정'], ...]

    2. BM25Okapi(그 리스트의 리스트) 로 색인을 만든다.
       k1, b 는 기본값을 쓴다. 바꾸려면 design.md 에 근거를 남길 것.

    3. (색인, 토큰화된_문서_목록) 두 개를 돌려준다.
       토큰 목록도 저장해야 나중에 '이 청크가 왜 걸렸나' 를 추적할 수 있다.

    힌트: 1번은 리스트 컴프리헨션 한 줄이면 된다.
    """
    tokenized = [tokenize(c['text']) for c in chunks]
    bm25 = BM25Okapi(tokenized)

    return bm25, tokenized

# =========================================================== /본인 작성 구간


def save(out_dir, bm25, tokenized, chunks, version):
    """색인과 설정을 함께 저장한다.

    설정을 같이 남겨야 '이 검색 결과가 어떤 색인에서 나왔나' 를 역추적할 수 있다.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    with open(out / 'bm25.pkl', 'wb') as f:
        pickle.dump({'bm25': bm25, 'tokenized': tokenized}, f)

    # 검색 결과(순번)를 chunk_id 로 되돌리기 위한 순서 보존 목록
    with open(out / 'chunk_ids.json', 'w', encoding='utf-8') as f:
        json.dump([c['chunk_id'] for c in chunks], f, ensure_ascii=False)

    meta = {
        'index_version': version,
        'built_at': datetime.datetime.now().isoformat(timespec='seconds'),
        'n_chunks': len(chunks),
        'n_docs': len({c['doc_id'] for c in chunks}),
        'tokenizer': 'kiwipiepy + 비자코드 보호',
        'bm25': 'rank_bm25.BM25Okapi (k1/b 기본값)',
        'avg_tokens': round(sum(len(t) for t in tokenized) / len(tokenized), 1),
    }
    with open(out / 'meta.json', 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--chunks', default='data/chunks.jsonl')
    ap.add_argument('--out', default='data/index')
    ap.add_argument('--version', default='idx-v1')
    a = ap.parse_args()

    chunks = load_chunks(a.chunks)
    print(f'청크 {len(chunks)}개 읽음. 토큰화 중... (1~2분 걸린다)')
    bm25, tokenized = build_bm25(chunks)
    meta = save(a.out, bm25, tokenized, chunks, a.version)
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
