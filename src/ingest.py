"""
문서 로딩 -> 정제 -> 청킹 -> chunks.jsonl

담당: 서종찬 | 평가표 3번 (문서 처리·메타데이터)
실행: python src/ingest.py --corpus docs/corpus --out data/chunks.jsonl

[의도적으로 본문을 비워뒀습니다. 아래 순서대로 직접 구현하세요.]

할 일
-----
1. docs/corpus/*.md 를 읽는다
   - frontmatter(doc_id, title, version, source, license, collected_at)를 파싱
   - python-frontmatter 패키지 사용

2. 조항 단위로 자른다
   - '## 제N조' 를 경계로 분할
   - 조항이 임베딩 입력 한도를 넘으면 항(①②③) 단위로 다시 분할

3. 각 청크에 메타데이터를 붙인다
   - 문서 frontmatter 값을 모든 청크에 상속
   - location 은 '제46조 제1항' 형태로 채점자가 원문을 열 수 있게

4. chunk_id 를 결정적으로 만든다
   - 랜덤 UUID 금지. 같은 입력 -> 같은 ID 여야 gold_chunks 가 안 깨진다
   - 위치 기반(doc_id + 조항번호) 또는 내용 해시 중 하나를 골라 design.md 에 기록

5. jsonl 로 저장한다

검증 (반드시)
------------
- 모든 청크가 chunk_id / doc_id / location 을 가지는지 확인하고, 없으면 에러를 낸다
- 두 번 실행해 파일 해시가 같은지 확인한 로그를 results/ 에 남긴다
"""


def load_documents(corpus_dir):
    """마크다운 + frontmatter 를 읽어 문서 목록을 돌려준다."""
    raise NotImplementedError


def split_into_chunks(document):
    """문서 하나를 조항 단위 청크 목록으로 자른다."""
    raise NotImplementedError


def make_chunk_id(doc_id, location, text):
    """결정적 chunk_id 를 만든다. 같은 입력 -> 같은 출력."""
    raise NotImplementedError


def validate(chunks):
    """주소 3종(chunk_id/doc_id/location) 누락 여부를 검사한다."""
    raise NotImplementedError


if __name__ == "__main__":
    raise NotImplementedError
