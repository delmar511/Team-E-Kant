# 테스트 과정 및 결과 — `feat/section-expand-threadsafe-corpus-e2-f5`

**날짜:** 2026-11-26  
**평가셋:** eval-v0.1 (dev 10문항 / test 20문항)  
**LLM:** gpt-6-luna @ medium  
**색인:** idx-v4

---

## 변경 내용 요약

이 브랜치에서 추가·수정된 사항:

- **섹션 확장(Section Expansion)**: 검색된 청크 주변 섹션을 함께 넘겨 LLM 컨텍스트를 보강
- **스레드 안전성(Thread Safety)**: 병렬 실행 시 경합 조건 수정
- **코퍼스 완성(E2/F5)**: 미색인 문서 추가 및 idx-v4 재생성
- `eval-test.json` chunk_id 재매핑 (idx-v4 기준, 208개 body 청크 ID 갱신)

---

## 테스트 절차

### 1단계 — Dev 튜닝 평가 (무료, dummy LLM)

```
python experiments/run_experiment.py \
  --configs A B C \
  --eval eval/eval-dev.json \
  --kind dev
```

| 구성 | Hit@5 | 답변 | 응답 시간 중앙값 |
|------|-------|------|-----------------|
| A    | 8/8   | 10/10 | 2.46초 |
| B    | 7/8   | 10/10 | 2.35초 |
| C    | 6/8   | 10/10 | 18.66초 |

→ 구성별 차이 확인. 색인·파이프라인 정상 동작.

### 2단계 — Core 본 평가 (gpt-6-luna)

```
python experiments/run_experiment.py \
  --configs A B C \
  --eval eval/eval-test.json \
  --kind core \
  --llm openai
```

결과 파일: `results/runs/2026-11-26_154902_core_A-B-C.{records,trace}.jsonl`

---

## 최종 평가 결과 (eval-test.json, 20문항)

| 구성 | Hit@5 (분모 16) | answered | no_evidence | no_answer 판정 | 응답 시간 중앙값 |
|------|----------------|----------|-------------|---------------|-----------------|
| **A** (vector) | **8/16 = 50%** | 14 | 6 | 3/3 ✓ | 5.85초 |
| **B** (RRF/hybrid) | **6/16 = 38%** | 12 | 8 | 3/3 ✓ | 4.21초 |
| **C** (reranker) | **8/16 = 50%** | 14 | 6 | 3/3 ✓ | 20.88초 |

> Hit@5 분모가 16인 이유: TEST-013의 `evidence.chunk_id`가 없어 측정 불가 (1문항 제외)  
> `no_answer` 자동 판정(참고용)은 3구성 모두 3/3 완벽

### 구성별 Hit/Miss 패턴 (Config A 기준)

| 문항 | 유형 | Hit@5 | 비고 |
|------|------|-------|------|
| TEST-001 | direct | ✅ | |
| TEST-002 | direct | ❌ | gold DOC-D2#85e4296b7c 미검색 |
| TEST-003 | direct | ❌ | gold DOC-D10 계열 — E계열 청크가 상위 차지 |
| TEST-004 | direct | ❌ | 섹션 확장으로 gold 근접 도달했으나 Top5 미진입 |
| TEST-005 | direct | ❌ | gold DOC-D4 3개 중 하나도 Top5 미진입 |
| TEST-006 | direct | ✅ | |
| TEST-007 | direct | ✅ | |
| TEST-008 | direct | ✅ | |
| TEST-009 | direct | ✅ | |
| TEST-010 | (경고) | ✅ | type 필드 오류 — 아래 이슈 참조 |
| TEST-011 | paraphrase | ❌ | 표현 변형, gold DOC-D2#20b4b050be 미검색 |
| TEST-012 | paraphrase | ❌ | gold DOC-D2#79eeda1ada 미검색 |
| TEST-013 | paraphrase | — | chunk_id 없어 측정 불가 |
| TEST-014 | confusable | ✅ | |
| TEST-015 | confusable | ✅ | |
| TEST-016 | confusable | ❌ | gold DOC-D2#85e4296b7c 미검색 |
| TEST-017 | confusable | ❌ | 섹션 확장으로 gold 포함됐으나 초기 Top5 밖 |
| TEST-018 | no_answer | — | (Hit@5 해당 없음) |
| TEST-019 | no_answer | — | (Hit@5 해당 없음) |
| TEST-020 | no_answer | — | (Hit@5 해당 없음) |

---

## 알려진 문제

**1. TEST-010 type 경고**

`eval-test.json`의 `type` 필드가 아직 `"false_premise"`로 남아있어 로더가 경고를 출력함.
평가 README 변경 기록(2026-11-26)에는 `"direct"`로 수정 예정이었으나 JSON 파일에 미반영.

```
[평가셋 경고] 알 수 없는 type: TEST-010
```

→ `eval/eval-test.json` TEST-010의 `"type"` 값을 `"direct"`로 수정 필요.

**2. TEST-013 chunk_id 미설정**

`evidence.chunk_id`가 `null`이어서 Hit@5 측정 불가. 해당 문항은 분모에서 제외됨.

```
[평가셋 경고] 답변 가능 문항인데 evidence.chunk_id 없음 → Hit@5 측정 불가: TEST-013
```

→ 팀원 원문 대조 후 `chunk_id` 채우기 필요 (eval README 6절).

---

## 다음 단계

- [ ] `eval/eval-test.json` TEST-010 `type` → `"direct"` 수정
- [ ] TEST-013 `chunk_id` 원문 대조 후 채우기
- [ ] miss 패턴 분석: DOC-D10 계열(TEST-003), 표현 변형 쿼리(TEST-011/12)에서 반복 실패 → 쿼리 리라이터(`C_rewrite`) 실험 검토

---

# 추가 검토 — 서종찬 (2026-11-26)

## 요약

**위 측정은 틀리지 않았다. 다만 정답지가 틀려 있었다.**
같은 평가셋(`eval-test.json`)으로는 내 쪽에서도 똑같이 **A 8/16** 이 나왔고,
틀린 문항까지 완전히 일치했다. 색인(idx-v4 vs idx-v5)과 파이프라인
(`run_experiment.py` vs `retrieve.py`)이 다른데도 같은 결과가 나왔으므로
**재현성에는 문제가 없다.**

```
태환님 A 실패   002 003 004 005 011 012 016 017
서종찬 A 실패   002 003 004 005 011 012 016 017   (eval-test.json 기준, 동일)
```

## 정답지가 왜 틀렸나

`eval-test.json` 의 `chunk_id` 는 내가 쓴 `src/link_evidence.py` 가 만든 값이다.
이 스크립트는 근거의 `quote` 를 코퍼스 본문에서 찾아 청크를 특정하는데,
**test 근거에는 `quote` 키가 아예 없었다.**

```python
quote = ev.get('quote', '')     # 키가 없으면 ''
for frag in fragments(quote):   # fragments('') -> ['']
    if frag in chunk_text:      # '' in 아무문자열 -> 항상 True
```

빈 문자열이 모든 청크와 매칭에 성공해 1,815개 전부가 후보가 됐고,
같은 쪽으로 좁힌 뒤 **첫 번째 청크**가 정답으로 박혔다. 질문은 한 번도 읽히지 않았다.
근거 32건 전부가 이렇게 생성됐다. 상세: `2026-11-26_eval-test-gold-bug.md`.

입력이 없으면 멈췄어야 했다. 조용히 다른 방식으로 넘어간 것이 사고의 핵심이다.
지금은 `quote` 없이 기본 모드로 돌리면 종료코드 1로 멈추게 고쳤다.

## 정답지를 고친 뒤 — A 15/17

박태환이 근거 32건에 `quote` 를 채워주어 `eval/eval-test-quoted.json` 으로 다시 연결했다.
`quote` 모드 연결 결과: ok 25 / spans_multiple 2 / partial 5 / **not_found 0**.
**원본 정답지와 32건 중 25건(78%)이 달랐다.**

| 평가셋 | 색인 | 구성 A |
| --- | --- | --- |
| eval-test.json (버그) | idx-v4 | 8/16 |
| eval-test.json (버그) | idx-v5 | 8/16 — MRR 0.345 |
| **eval-test-quoted.json** | idx-v5 | **15/17 — MRR 0.774** |

위 보고서에서 실패로 잡힌 8문항이 정답지를 고치자 전부 상위로 들어왔다.

| 문항 | 버그 정답지 | 확정 정답지 |
| --- | --- | --- |
| TEST-002 | 7위 | **1위** |
| TEST-004 | 20위 밖 | **2위** |
| TEST-005 | 20위 밖 | **1위** |
| TEST-011 | 20위 밖 | **1위** |
| TEST-012 | 20위 밖 | **1위** |
| TEST-016 | 20위 밖 | **1위** |
| TEST-017 | 7위 | **1위** |
| TEST-003 | 15위 | 15위 (유일하게 진짜 실패) |

"gold DOC-D2#85e4296b7c 미검색" 같은 분석은 그 gold 자체가 버그로 박힌 값이므로
실패 원인 분석으로 쓸 수 없다.

## 위 보고서의 다음 단계 2건은 해결됐다

- **TEST-010 `type`** — `eval-test-quoted.json` 에서 정리됨
- **TEST-013 `chunk_id`** — `quote` 로 연결됨 (유학(D-2) > 시간제취업 > (3) 장소변경)

## 재정렬(C)이 dev 에서 손해다

dev 정답지는 `quote` 36건이 모두 채워져 있어 신뢰할 수 있다.
그 위에서 두 사람이 독립적으로 같은 값을 얻었다.

| 구성 | 태환님 dev | 서종찬 dev | 응답 시간 중앙값 |
| --- | --- | --- | --- |
| A | 8/8 | 8/8 | 2.46초 |
| B | 7/8 | 7/8 (w=1.0) | 2.35초 |
| C | **6/8** | — | **18.66초** |

C 는 A 보다 2건 낮고 **7.6배 느리다.**
다만 C 는 B 를 앞단으로 쓰는데 B 가 이미 A 보다 낮다.
**A 를 앞단으로 한 C 는 아직 재지 않았다.** 이것을 재기 전에는 재정렬 자체의
문제인지 앞단의 문제인지 가를 수 없다.

판단 기준은 상위 5 순서가 아니라 **후보 20개 안에 정답이 있는 비율(Hit@20)** 이다.
재정렬은 후보를 다시 줄 세울 뿐 새로 찾아오지 않기 때문이다.
이를 재려고 `src/retrieve.py` 에 `--top-k` 를 추가했다.

## BM25 를 섞는 것이 손해다 (구성 B)

| 구성 | dev Hit@5 | dev MRR | test Hit@5 | test MRR |
| --- | --- | --- | --- | --- |
| BM25 단독 | 3/8 | 0.391 | 9/17 | 0.445 |
| **A 벡터 단독** | **8/8** | **0.792** | **15/17** | **0.774** |
| B 혼합 w=1.0 | 7/8 | 0.597 | 13/17 | 0.679 |
| B 혼합 w=0.5 | 7/8 | 0.766 | — | — |
| B 혼합 w=0.3 | 7/8 | 0.745 | — | — |

**BM25 의 적중은 벡터 적중의 부분집합이다.** test 에서 BM25 가 맞힌 9문항이
모두 벡터 적중 15문항에 포함된다. 추가로 건지는 것이 없고 잘 찾던 것을 밀어내기만 한다.
원인은 코퍼스 구조로 본다 — 39개 문서가 모두 같은 절 구조라 "제출서류" 같은 어휘에
변별력이 없다. 상세: `2026-11-26_bm25-vs-vector.md`.

가중치 조정은 dev 에서만 했다. test 로 손잡이를 돌리면 과적합이다.

## 색인 버전을 고정해야 한다

```
태환님 보고서   idx-v4,  1,881 청크
현재 main      idx-v5,  1,815 청크
```

`chunk_id` 는 본문 해시라 **청킹이 바뀌면 ID 가 바뀐다.** 바뀔 때마다 정답지를
재매핑해야 하고, 그 재매핑이 이번 사고의 출발점이었다.
팀 전체가 같은 색인 버전을 쓰고, 바꿀 때는 정답지 재연결을 `quote` 로만 하는 것이 안전하다.

## 요청

**`eval/eval-test-quoted.json` 으로 다시 돌려주세요.** 이 파일은 이 브랜치에 있고
`main` 에는 아직 없습니다. 지금까지 main 만 받으셨다면 확정 정답지를 가진 적이 없습니다.

```
python experiments/run_experiment.py --configs A B C --eval eval/eval-test-quoted.json --kind core --llm openai
```
