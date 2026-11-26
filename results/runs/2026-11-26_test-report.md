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
