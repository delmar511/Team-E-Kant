# 응답·실험 인터페이스 — 검색·스키마 담당자용

작성: 김선규 (응답·최적화, 실험) | 2026-11-25
받는 사람: 서종찬 (검색), 박태환 (스키마·설정·지표)

`docs/retrieval-interface.md` 에 대한 답장입니다. 생성 쪽이 검색과 스키마를 **어떻게 쓰는지**, 그리고 **맞춰야 할 것**을 적습니다.

---

## 1. 흐름

```
질문 → (캐시) → (리라이트) → 검색 → 근거 판정 → 생성 → 인용 검사 → schemas.AgentResponse
```

| 파일 | 내용 |
| --- | --- |
| `src/agent.py` | `run_agent(question, cfg, retriever, llm_fn, ...)` → `AgentResult(response, candidates, trace)` |
| `src/search_adapter.py` | `retrieve.py` 함수를 `[retrieval] mode` 로 골라 `retrieve(query) -> list[RetrievedCandidate]` 로 묶음 |
| `src/answer/prompt.py` + `templates/answer_v1.txt` | 프롬프트. 청크마다 `chunk_id` 와 위치(`location (p.N)`)를 붙이고 원문은 이스케이프 |
| `src/answer/generator.py` | Claude 호출 (JSON 구조화 출력), 형식 오류 1회 재요청, 토큰 수 기록 |
| `src/answer/evidence_gate.py` | `[evidence_gate] method` 대로 근거 부족 판정 |
| `src/answer/citation_check.py` | 모델에 주지 않은 청크 인용은 `invalid_citation_ids` 로 분리, 답변에 `[검증 실패: ID]` 표시 |
| `src/optimize/cache.py`, `rewrite.py` | `C_cache` / `C_rewrite` 구성에서만 켜짐 |
| `experiments/run_experiment.py` | 구성 × 문항 실행, `RunRecord` JSONL 기록 |

status 는 `schemas.Status` 5개를 그대로 씁니다. 검색·생성 오류는 예외로 던지지 않고 응답으로 돌려 분모에 넣습니다.

## 2. 실행

```powershell
pip install -r requirements.txt
python -m pytest tests                                                                  # API 호출 없음
python experiments/run_experiment.py --configs A B --eval eval/eval-dev.json --stub     # 색인 없이 리허설
python experiments/run_experiment.py --configs A B --eval eval/eval-dev.json            # 실제 검색 + 더미 생성 (무료)
python experiments/run_experiment.py --configs A B --eval eval/eval-dev.json --llm claude   # 실제 생성 (비용 발생)
```

결과는 `results/runs/<시각>_<이름>.records.jsonl` (`RunRecord`) 과 `.trace.jsonl` (분석용) 두 개입니다.
`.env` 에 `ANTHROPIC_API_KEY`, `EMBEDDING_MODEL` 이 필요합니다. 생성 effort 는 `LLM_EFFORT` (기본 `medium`).

---

## 3. 서종찬님께

1. **구성 C**: 재정렬기가 생기면 `search_adapter.py` 의 `hybrid_rerank` 분기를 채우거나, `retrieve(query, config)` 단일 진입점을 주시면 그걸 부르게 바꾸겠습니다. 지금 C 는 `ConfigError` 를 냅니다.
2. **RRF 가중치**: `rrf(weights=...)` 로 BM25 가중치를 튜닝하셨는데 `config.FusionConfig` 에 가중치 칸이 없어 지금은 동등 가중치(1.0)로 부릅니다. 쓰실 거면 박태환님과 칸을 추가해 주세요.
3. **색인 위치**: `base.toml` 은 `index_dir = "index"` 인데 실제 색인은 `data/index` 입니다. 어댑터는 `data/index` 를 씁니다. `config.check_index_manifest()` 가 찾는 `manifest.json` 도 `build_index.py` 는 `meta.json` 으로 씁니다.
4. **`build_vectors.py` 의존성**: KURE(로컬 모델)만 써도 26행 `from openai import APIStatusError` 때문에 `openai` 가 없으면 실패합니다.
   `requirements.txt` 에 `openai`, `sentence-transformers` 를 넣거나 import 를 OpenAI 분기 안으로 옮겨 주세요.
5. **근거 없음 점수 분포**: 기본 판정은 `model_judgment` 입니다. 점수 게이트(`score_threshold`/`both`)를 쓸지 dev 결과를 보고 정하겠습니다. 그때 A·B 점수 분포를 부탁드립니다.

## 4. 박태환님께

1. **`schemas.AgentResponse` 에 칸 제안**: `no_evidence_reason`, `context_chunk_ids`(모델에 실제로 넣은 청크), `rewrite_fallback`. 지금은 `extra="forbid"` 라 `.trace.jsonl` 에 따로 씁니다.
2. **`config.GenerationConfig`**:
   - `temperature` 는 Claude Opus 5.5 에서 400 오류라 API 로 보내지 않습니다. 칸을 빼거나 무시한다고 적어 주세요.
   - 대신 `effort` (`low`~`max`) 칸이 필요합니다. 지금은 `.env` 의 `LLM_EFFORT` 라 `answer_config_version` 에 안 잡힙니다.
3. **평가셋 형식과 `schemas.EvalItem` 불일치**:
   - 실제 `evidence` 는 `{page, section, quote, chunk_id, chunk_ids_all}`, 스키마는 `{doc_id, location, excerpt, chunk_id, required}` 입니다. 그래서 `EvalItem` 으로 검증하면 실패해 실험은 느슨한 로더(`experiments/_common.py`)를 씁니다.
   - `no_answer` 문항(DEV-009, DEV-010)에 참고 근거가 들어 있는데 `EvalItem` 은 `no_answer` 의 `evidence` 를 빈 배열로 요구합니다.
4. **Hit@5 정답**: `evidence[].chunk_id` 만 씁니다 (서종찬님 `evaluate()` 와 같음). `chunk_ids_all` 은 다른 자격 문서 청크가 섞여 있어 자격 혼동을 정답으로 칠 수 있어 뺐습니다.
5. **`tests/test_config.py` 5개 실패**: `config.py` 오류 메시지가 한글로 바뀌었는데 테스트는 영어 문구(`circular`, `stale index` 등)를 찾습니다. 제 변경 전부터 실패합니다.
6. **지표·채점표**: `metrics.py` 는 박태환님 담당이라 옮기지 않았습니다. `records.jsonl` 을 읽어 주시면 되고, 실행 직후 확인용 요약(상태 수, Hit@5, 응답 시간 중앙값)은 `run_experiment.py` 가 출력합니다.
