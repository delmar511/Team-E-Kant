"""
chunks.jsonl -> BM25 색인 + 벡터 저장소

담당: 서종찬(BM25) / 벡터는 담당자와 분담 | 평가표 3·4번
실행: python src/build_index.py --chunks data/chunks.jsonl --index-version idx-v1

[의도적으로 본문을 비워뒀습니다.]

왜 ingest 와 파일을 나눴나
------------------------
ingest 는 싸고 자주 돌린다. 여기는 임베딩 API 를 전량 호출해서 비싸다.
합쳐두면 청킹 오타 하나 고칠 때마다 임베딩 비용이 다시 나간다.

할 일
-----
1. chunks.jsonl 을 읽는다
2. BM25 색인을 만든다
   - 토크나이징은 tokenizer.py 를 쓴다 (보호 토큰 + Kiwi)
   - rank-bm25 의 BM25Okapi 사용, k1/b 는 기본값 유지
3. 벡터 저장소를 만든다
   - 문서 10개 규모면 전수 탐색으로 충분. ANN 인덱스는 불필요
4. 설정을 함께 저장한다
   - 임베딩 모델명, 청크 수, index_version, 생성 일시
   - 나중에 '이 결과가 어떤 색인에서 나왔나' 를 역추적할 수 있어야 한다
"""


def build_bm25(chunks):
    raise NotImplementedError


def build_vector_store(chunks):
    raise NotImplementedError


if __name__ == "__main__":
    raise NotImplementedError
