# Team-E-Kant: 체류민원 매뉴얼 Knowledge Agent

출입국 체류민원 담당자가 「체류민원 자격별 안내 매뉴얼」(법무부, 2026. 11. 판, 795쪽)에서 요건·제출서류·예외를 찾을 때,
원문 위치가 붙은 근거로 답하거나 근거가 없으면 "근거 없음"을 안내하는 RAG 에이전트.
평가 범위는 D-2(유학)·D-4(일반연수)이고, 색인은 매뉴얼 전체다.

| 문서 | 내용 |
|---|---|
| [docs/problem.md](docs/problem.md) | 사용자·업무 문제·오답 위험·성공 기준 (결과 전에 고정) |
| [docs/document_index.md](docs/document_index.md) | 문서 목록 (ID·쪽 범위·출처·이용 조건) |
| [docs/conversion_notes.md](docs/conversion_notes.md) | PDF 변환·정제 규칙과 수정 이력 |
| [docs/design.md](docs/design.md) | 청킹·검색·재정렬 설계 |
| [docs/retrieval-interface.md](docs/retrieval-interface.md), [docs/answer-interface.md](docs/answer-interface.md) | 모듈 간 인터페이스 |
| [eval/README.md](eval/README.md) | 평가셋 스키마·개발/평가 분리 원칙 |
| [results/runs/](results/runs/) | 실행별 원본 기록과 측정 메모 |

## 구성

| 구성 | 검색 | 설정 |
|---|---|---|
| A | 벡터 단독 | [configs/A.toml](configs/A.toml) |
| B | BM25(kiwi 형태소) + 벡터, RRF(k=60) 결합 | [configs/B.toml](configs/B.toml) |
| C | B 후보 20개를 cross-encoder(`BAAI/bge-reranker-v2-m3`)로 재정렬 → 상위 5개를 프롬프트에 | [configs/C.toml](configs/C.toml) |
| C+cache | C + 정확 일치 답변 캐시 (버전·사용자 범위 키, TTL) | [configs/C_cache.toml](configs/C_cache.toml) |
| C+rewrite | C + 질의 리라이트 (실패 시 원질문) | [configs/C_rewrite.toml](configs/C_rewrite.toml) |

생성 모델·프롬프트·컨텍스트 한도는 A/B/C 공통([configs/base.toml](configs/base.toml)), 실행 시 `config.check_shared_settings` 로 검사한다.

## 설치

Python **3.11 이상** (설정 로더가 `tomllib` 사용).

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # ANTHROPIC_API_KEY, OPENAI_API_KEY, EMBEDDING_MODEL 채우기
pytest -q                # API 호출 없음
```

임베딩(`nlpai-lab/KURE-v1`)과 재정렬기(`BAAI/bge-reranker-v2-m3`)는 로컬 모델이다 (`sentence-transformers`, 첫 실행 시 각 약 2GB 내려받음, GPU 없어도 동작).
`.env` 에 `EMBEDDING_MODEL=nlpai-lab/KURE-v1` 를 넣는다.

**Windows**: 스크립트가 한글을 출력하므로 콘솔 기본 인코딩(cp1252/cp949)에서는 `UnicodeEncodeError` 로 멈춘다.
실행 전에 UTF-8 모드를 켠다: PowerShell `$env:PYTHONUTF8=1`, Git Bash `export PYTHONUTF8=1`
(영구 설정: `setx PYTHONUTF8 1` 후 터미널 재시작).

## 색인 재생성

`docs/corpus/*.md`(변환 결과)와 `data/chunks.jsonl`(청크)은 저장소에 있다. 색인(`data/index/`)은 커밋하지 않으므로 직접 만든다.

```bash
python src/ingest/chunk.py docs/corpus/*.md > data/chunks.jsonl   # 청크를 다시 만들 때만
python src/build_index.py                                          # BM25 -> data/index/ (1~2분)
python src/build_vectors.py --model nlpai-lab/KURE-v1              # 벡터 -> data/index/ (CPU 에서 수십 분)
python src/retrieve.py --config B --eval eval/eval-dev.json        # 검색만 점검 (Hit@5)
```

청크를 다시 만들면 `chunk_id` 가 바뀔 수 있다. 그때는 평가셋 근거를 다시 연결한다:
`python src/link_evidence.py eval/eval-dev.json --write` (원문 발췌 `quote` 로 청크를 찾는다).
`data/chunks.jsonl` 내용이 바뀌면 `index_version` 이 바뀌어 이전 캐시 답변은 재사용되지 않는다.

PDF 에서 다시 변환하려면 poppler(`pdftotext`)가 필요하다 ([requirements.txt](requirements.txt) 상단, [docs/conversion_notes.md](docs/conversion_notes.md)).

## 실행

```bash
# 무료 리허설: 색인·API 없이 더미 검색기와 더미 생성기
python experiments/run_experiment.py --configs A B --eval eval/eval-dev.json --stub

# 개발셋 튜닝 (실제 검색 + Claude 생성, 비용 발생)
python experiments/run_experiment.py --configs A B --eval eval/eval-dev.json --llm claude --kind dev

# 본 평가 60건: A/B/C x 최종 평가 20문항 x 1회 (평가셋 고정 후 1회만)
python experiments/run_experiment.py --configs A B C --eval eval/eval-test.json --llm claude --kind core

# 최적화 분기: 리라이트 20건 / 캐시 15건 (5문항 x 미적중·적중·버전 변경 후)
python experiments/run_experiment.py --configs C_rewrite --eval eval/eval-test.json --llm claude --kind branch
python experiments/run_cache_experiment.py --eval eval/eval-test.json --llm claude
```

결과는 `results/runs/<시각>_<이름>.records.jsonl`(실행마다 질문·구성·버전·후보 점수·답변·인용·시간·상태)과
`.trace.jsonl`(근거 없음 사유, 모델에 넣은 청크, Hit@5)로 남는다. 오류도 기록해 분모에 포함하고, 재실행은 `--kind retry` 로 따로 남긴다.

## 채점과 지표

```bash
# 1) 사람이 채울 채점표 (호출 오류는 0점으로 미리 채움)
python experiments/metrics.py sheet results/runs/<...>.records.jsonl --eval eval/eval-test.json
# 2) 채점표를 채우고 교차 검토 (reviewer 는 scorer 와 달라야 함)
# 3) 구성별 표: Hit@5, 근거 전체 회수@5, 정답 충족, 근거 적합, 근거 없음 대응, 호출 성공, 오류·timeout, 응답 시간 평균·중앙값·n
python experiments/metrics.py report results/runs/<...>.records.jsonl --eval eval/eval-test.json \
       --scores results/scores/<...>.scores.csv --out results/report_core.md
```

Hit@5 는 채점표가 아니라 검색 후보에서 계산한다. 검색 오류는 0, 결과가 5개 미만이면 있는 결과로 판정한다.

## 보안·데이터

- 공개 공공 문서만 사용, 개인정보 없음. 이용 조건은 [docs/document_index.md](docs/document_index.md).
- `.env`(API 키)는 커밋하지 않는다. 원본 PDF·색인·가상환경도 커밋하지 않는다 ([.gitignore](.gitignore)).
- 검색된 문서 내용은 프롬프트에서 데이터로 표시·이스케이프하며, 문서 속 지시는 따르지 않는다.
- 캐시 키에 사용자 범위(`user_scope`)와 문서·색인·모델·프롬프트·검색 설정 버전이 들어간다. 캐시는 프로세스 메모리에만 있다.

## 한계

작은 평가셋(개발 10 / 최종 20문항)과 한 판의 매뉴얼에 대한 검증이다. 실제 업무 소요시간은 측정하지 않았으므로 시간 절감을 주장하지 않는다.
공개 배포·보안 인증·서비스 수준을 달성했다고 주장하지 않는다.
