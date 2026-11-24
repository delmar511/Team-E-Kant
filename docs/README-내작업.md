# 서종찬 작업 안내

> 담당: 문서·색인 / 검색·재정렬 (평가표 3·4·5번)

## 실행 순서

```bash
cp .env.example .env            # 키 입력
pip install -r requirements.txt

python src/ingest.py      --corpus docs/corpus --out data/chunks.jsonl
python src/build_index.py --chunks data/chunks.jsonl --index-version idx-v1
```

## 내 산출물 체크리스트

- [ ] `src/ingest.py` / `src/build_index.py` — 2단계 분리, 설정 외부화 **(3)**
- [ ] 청크 검증 — 주소 3종 누락 0건 출력 **(3)**
- [ ] 재생성 2회 로그 — 해시 동일 **(3, 11)**
- [ ] `docs/document_index.md` — 출처·이용조건·버전·원문위치 **(3, 10)**
- [ ] 토크나이저 보호 규칙 on/off 비교 실험 **(4)**
- [ ] `docs/design.md` — RRF 근거, 후보 수, 중복 제거 규칙 **(4)**
- [ ] 실행 기록에 `before_rerank` / `after_rerank` 배열 **(5)**

## 일정

| 시점 | 할 일 | 완료선 |
|---|---|---|
| 2일차 오전 | 청킹, chunk_id 결정성 | `chunks.jsonl` 생성 |
| **2일차 오후** | 색인, 검증, **gold_chunks 채우기** | **평가셋 버전 고정 커밋** |
| 2일차 말 | 구성 A | dev 10문항 검색 결과 출력 |
| 3일차 오전 | 토크나이저 + BM25, 보호 규칙 실험 | on/off Hit@5 비교 |
| 3일차 오후 | RRF 결합 → 구성 B | A/B 비교 가능 |
| 3일차 말 | 구성 C 연결 확인 | 전후 순위 기록 저장 |

## 브랜치

```
feat/ingest-index       2일차 — 청킹·색인
feat/hybrid-retrieval   3일차 — 토크나이저·BM25·RRF
```

기능 단위로 나눠 PR을 올린다. 발제가 "기능 브랜치·PR·리뷰"를 요구하고,
평가표 11번이 개인별 PR 링크를 증빙으로 본다.
