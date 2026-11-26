# 기여 내역 (contributions.md)

> 평가표 **11번**(협업·재현·시연)의 증빙.
> 역할별 담당자, 코드 기여·실행 검증·리뷰 근거를 연결한다.

---

## 팀원

| 이름 | GitHub ID | 담당 역할 |
|---|---|---|
| 박태환 | delmar511 | 문제·평가 설계, 스키마·설정, 통합·재현 |
| 서종찬 | SJC / acdc234-git | 문서·색인, 검색·재정렬 |
| 김선규 | ilmae322 / ilmae-322 | 응답·최적화, 실험·분석 |

---

## 역할별 기여 내역

### 1. 문제·평가 설계 담당 — 박태환

| 항목 | 근거 |
|---|---|
| 사용자·업무 문제·오답 위험·성공 기준 사전 합의 | `docs/problem.md` (PR #1) |
| 평가셋 30문항(dev 10 / test 20) 설계, 정답·근거 확인, 개발/평가 분리 유지 | `eval/dev.json`, `eval/test.json` (PR #1), 정답지 버그 검토 (commit a5bab41) |
| 평가 지표 정의 (Hit@5, 정답 충족, 근거 적합, 무근거 안내) | `src/schemas.py`, `src/config.py`, 평가 기준 `docs/problem.md` |

**주요 커밋·PR:**
- PR #1 — 문제 정의, 평가셋 초안, 공통 스키마 및 설정 로더 추가 (`d49ee1a`)
- commit `029b25c` — testresult1 (테스트 실행 검증)
- PR #16 — Streamlit 앱 OpenAI 제공자로 전환 (`6212308`)

---

### 2. 문서·색인 담당 — 서종찬

| 항목 | 근거 |
|---|---|
| PDF → Markdown 변환, 본문 2단 표 처리, 머리글·바닥글 제거 | `src/ingest/pdf_to_md.py`, `docs/conversion_notes.md` (PR #2) |
| 청킹: 제목 경로 단위, chunk_id 내용 해시, 원문 위치(page·location) 연결 | `src/ingest/chunk.py`, `design.md` |
| 코퍼스 완성(37개 자격), 변환 오류 수정, 재청킹(L5→L6) | PR #2, #4, #9, #17 |
| 토크나이저 구현 (`4265b15`) | `src/tokenizer.py` |
| BM25 검색 구현, 임베딩 모델 비교, 벡터 검색 + RRF 결합 | `src/build_index.py`, `src/retrieve.py` (PR #5) |
| 가중 RRF + 하이브리드 검색 개선, 평가셋 근거 chunk_id 링커 | PR #5 (`cc498fa`, `7fe58c2`, `cd00d93`) |
| link_evidence facts 모드, 평가 측정 (BM25 단독·구성 A/B 비교) | PR #13, #15 (`0c39961`, `8bfcd64`, `1b8357b`) |
| 검색 인터페이스 인수인계 문서 (`docs/retrieval-interface.md`) | commit `781a439` |

**검증:**
- BM25·벡터 검색기 각각 출력 후 점수 척도 차이 확인 (`results/runs/2026-11-25_bm25-baseline.md`, `results/runs/2026-11-25_config-A-vector.md`, `results/runs/2026-11-25_config-B-rrf.md`)
- 임베딩 비교 (`results/runs/2026-11-25_embedding-compare.md`)
- RRF 가중치 스윕 (`results/runs/2026-11-25_rrf-weight-sweep.md`)

---

### 3. 응답·최적화·실험 담당 — 김선규

| 항목 | 근거 |
|---|---|
| 응답 생성·에이전트·실험 실행 팀 구조 연결 | `src/agent.py`, `src/answer/`, PR #6, #7 (`4567010`) |
| 실행 기록 보강(즉시 기록, run_id 시각, API 키 점검, effort 기록) | commit `000ee68` |
| 구성 C 재정렬기(`BAAI/bge-reranker-v2-m3`), 지표·채점표, 캐시 검증 15건 | `src/rerank.py`, PR #8 (`12e761b`) |
| 캐시 구현 (`src/optimize/cache.py`), 쿼리 리라이트 (`src/optimize/rewrite.py`) | PR #8 |
| RAGAS 평가 스크립트 및 dev 베이스라인 결과 | `experiments/ragas_eval.py`, PR #17 (`5fb1e58`) |
| 근거 판정(`src/answer/evidence_gate.py`), 인용 검사(`src/answer/citation_check.py`) | 응답 생성 PR |
| 응답·실험 인터페이스 문서 (`docs/answer-interface.md`) | 2026-11-25 |

**검증:**
- dev 10문항 정상·근거 없음·오류 흐름 검증
- 캐시 미적중→적중→버전 변경 15건 기록
- RAGAS dev 베이스라인 (`results/ragas/2026-11-26_172732_dev_A-B-C.ragas.json`)

---

### 4. 통합·재현 담당 — 전원

| 항목 | 담당 | 근거 |
|---|---|---|
| README 재실행 절차 검증 | 박태환 | 각 PR 머지 전 재실행 확인 |
| 평가 기준 교차 검토 | 전원 | commit `a5bab41` (정답지 버그 발견·검토) |
| `.env.example`, `.gitignore` (API 키 미포함) 점검 | 박태환 | PR #1 |
| 색인 재생성 가능 여부 확인 | 서종찬 | `docs/conversion_notes.md`, `docs/design.md` |
| Streamlit 인터페이스 (질문·답변·근거·오류 확인) | 박태환 | PR #16 |
| 제출 태그 (`ax1-project3-submit`) | 박태환 | 최종 제출 전 생성 예정 |

---

## PR 목록

| PR | 제목 | 머지 담당 | 작성자 |
|---|---|---|---|
| #1 | 문제 정의, 평가셋 초안, 공통 스키마 및 설정 로더 | 박태환 | 박태환 |
| #2 | feat/corpus-ingest — 체류민원 매뉴얼 34개 자격 변환 + 청킹 | 서종찬(acdc234-git) | 서종찬 |
| #4 | feat/corpus-annex-fixes — 변환 오류 4종 수정 + 663쪽 이후 추가 | 서종찬(acdc234-git) | 서종찬 |
| #5 | feat/bm25-index — BM25·벡터 검색·RRF 결합 | 서종찬(acdc234-git) | 서종찬 |
| #6 | feat/answer-agent — 응답 생성·에이전트·실험 실행 연결 | 김선규(ilmae322) | 김선규 |
| #7 | feat/answer-agent — 실행 기록 보강 + dev 결과 | 김선규(ilmae322) | 김선규 |
| #8 | feat/rerank-metrics-cache — 구성 C, 지표, 캐시 15건 | 박태환 | 박태환 |
| #9 | fix/corpus-rechunk-l5 — 전체 코퍼스 MD 정제 및 청크 재생성 | 김선규(ilmae322) | 서종찬 |
| #10 | feat/rerank-metrics-cache (추가) | 박태환 | 박태환 |
| #12 | feat/section-expand-threadsafe-corpus-e2-f5 | 박태환 | 박태환 |
| #13 | feat/link-evidence-facts-mode — link_evidence facts 모드 | 서종찬(acdc234-git) | 서종찬 |
| #14 | feat/test1 — testresult1 | 박태환 | 박태환 |
| #15 | feat/link-evidence-facts-mode (추가) | 서종찬(acdc234-git) | 서종찬 |
| #16 | feat/openai-provider-support — Streamlit OpenAI 전환 | 박태환 | 박태환 |
| #17 | fix/corpus-rechunk-l6 + RAGAS 평가 스크립트 | 김선규(ilmae322) | 김선규 |

---

## 개인별 최종 확인 항목

| 항목 | 박태환 | 서종찬 | 김선규 |
|---|---|---|---|
| 코드 직접 작성·수정 | ✓ (스키마, 설정, 실험 실행, Streamlit) | ✓ (ingest, 검색, 재정렬) | ✓ (응답, 에이전트, 캐시, RAGAS) |
| 원본 실행·결과 검증 | ✓ | ✓ (검색 기록 runs/) | ✓ (캐시 15건, RAGAS) |
| 타인 PR 리뷰 참여 | ✓ (정답지 버그 검토 등) | ✓ | ✓ |
| 본인 설계·한계 설명 가능 | ✓ | ✓ | ✓ |
