# 검색 인터페이스 — 생성·에이전트 담당자용

작성: 서종찬 (문서·색인, 검색) | 2026-11-25
받는 사람: 김선규 (생성·에이전트)

검색은 돌아갑니다. 이 문서는 **그걸 어떻게 불러 쓰는지**만 적습니다.

---

## 1. 한 줄로 쓰는 법

```python
import sys
sys.path.insert(0, 'src')
import retrieve as R

R.load_env()
bm25, chunk_ids, chunks, _ = R.load_index()
vecs, _ = R.load_vectors()
model = os.environ['EMBEDDING_MODEL']

results = R.search_vector(vecs, chunk_ids, "어학연수생이 알바해도 되나요", model)
```

`results` 는 `[(chunk_id, 점수), ...]` 입니다. 상위 5개만 쓰시면 됩니다.

청크 본문과 출처는 `chunks` 사전에서 꺼냅니다.

```python
for cid, score in results[:5]:
    c = chunks[cid]
    c['text']       # 본문 (평균 350자)
    c['location']   # '유학(D-2) > 시간제취업 활동 허가 > 나. 대상'
    c['page']       # 38
    c['doc_title']  # '유학(D-2)'
    c['chunk_id']   # 'DOC-D2#a1b2c3d4e5'
```

---

## 2. 인용에 뭘 쓰면 되나

**`location` + `page` 를 그대로 쓰시면 됩니다.** 사람이 원문을 찾을 수 있는 형태로 만들어 뒀습니다.

```
근거: 유학(D-2) > 시간제취업 활동 허가 > 나. 대상 (매뉴얼 p.38)
```

`chunk_id` 는 평가 채점용입니다. 사용자에게 보여줄 필요는 없지만,
**어떤 청크를 근거로 썼는지는 결과에 남겨 주세요.** 평가표 5번에서
"검색 결과와 생성 결과가 이어지는가" 를 봅니다.

---

## 3. 구성 선택

| 함수 | 구성 | dev Hit@5 |
| --- | --- | --- |
| `R.search_bm25(bm25, chunk_ids, q)` | 어휘 검색만 | 4/8 |
| `R.search_vector(vecs, chunk_ids, q, model)` | **구성 A (현재 최선)** | **8/8** |
| `R.rrf(bm25결과, 벡터결과, weights=[w, 1.0])` | 구성 B | 7/8 |

**지금은 `search_vector` 를 쓰시면 됩니다.** 구성 B 는 현재 임베딩 모델
(`KURE-v1`)에서는 오히려 나쁩니다. 이유는 `results/runs/2026-11-25_rrf-weight-sweep.md`.

test 평가셋이 채워지면 다시 재서 최종 구성을 정합니다. **그때 바뀔 수 있습니다.**
그래서 구성을 코드에 하드코딩하지 말고 바꿔 끼울 수 있게 해 주세요.

---

## 4. 알아두실 것

**검색은 항상 5개를 돌려줍니다.** 질문과 무관해도 돌려줍니다.
점수가 낮아도 0개를 주지는 않습니다.

그래서 **"근거 없음" 판정은 검색이 아니라 그쪽에서 하셔야 합니다.**
평가셋에 `no_answer` 문항이 dev 2개 / test 3개 있습니다.
판정 기준(점수 임계값? LLM 판단?)은 정해지면 알려 주세요. 제가 점수 분포를 뽑아 드릴 수 있습니다.

**청크는 평균 350자, 최대 1,285자입니다.** 5개면 약 1,800자라
프롬프트에 다 넣어도 부담 없습니다.

**`location` 이 같은 청크가 여럿일 수 있습니다.** 매뉴얼이 같은 제목을
여러 번 쓰기 때문입니다. 두 번째부터는 `(2)`, `(3)` 이 붙습니다.

---

## 5. 환경

```powershell
pip install -r requirements.txt
pip install sentence-transformers     # KURE 쓰려면 필요. 2~3GB
```

`.env` 에 두 줄:

```
OPENAI_API_KEY=본인 키
EMBEDDING_MODEL=nlpai-lab/KURE-v1
```

색인을 직접 만들려면:

```powershell
python src/ingest/chunk.py "docs/corpus/*.md" > data/chunks.jsonl
python src/build_index.py
python src/build_vectors.py          # KURE 는 약 5분 30초
```

`data/chunks.jsonl` 은 레포에 있으니 첫 줄은 건너뛰어도 됩니다.
`data/index/` 는 레포에 없어서 직접 만드셔야 합니다 (20MB 넘어서 제외).

---

## 6. 막히면

검색 결과가 이상하면 이 두 개로 보세요.

```powershell
python src/retrieve.py --config A "질문"                      # 상위 5개 눈으로 확인
python src/retrieve.py --config A --eval eval/eval-dev.json   # 전체 채점
```

그래도 이상하면 질문과 기대한 근거를 알려 주세요. 제 쪽 문제일 수 있습니다.
