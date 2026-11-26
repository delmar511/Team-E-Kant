# 비자 코드 보호 규칙 검증 — 효과 없음

날짜: 2026-11-26 / 청크 1,815 / BM25 단독 구성
색인: `idx-v5` (보호 on) vs `idx-v5-noprotect` (보호 off, avg_tokens 97.0)

## 무엇을 쟀나

`src/tokenizer.py` 는 형태소 분석 전에 비자 코드(`[A-Za-z]-\d+(?:-\d+)?`)를
정규식으로 먼저 빼낸다. Kiwi 가 `E-7` 을 `E`/`-`/`7` 로 쪼개는 것을 막기 위해서다.
이 규칙이 실제로 점수를 올리는지 확인했다.

색인과 질문 **양쪽** 전처리를 함께 꺼야 한다. 한쪽만 끄면 비교가 무의미하므로
`retrieve.py` 가 색인 meta 의 `protect_visa_codes` 와 다르면 멈추게 해 두었다.

## 결과

| 조건 | dev Hit@5 | dev MRR | test Hit@5 | test MRR |
|---|---|---|---|---|
| 보호 on | 3/8 | **0.391** | 9/17 | 0.445 |
| 보호 off | 3/8 | 0.345 | **10/17** | **0.517** |

**두 평가셋이 반대 방향을 가리킨다.**

### 문항별 순위 변화 (test)

| 문항 | on | off | |
|---|---|---|---|
| TEST-004 | 20위 밖 | 2위 | off 승 |
| TEST-014 | 9위 | 1위 | off 승 |
| TEST-008 | 16위 | 7위 | off 승 |
| TEST-001 | 4위 | 9위 | on 승 |
| TEST-005 | 10위 | 19위 | on 승 |
| TEST-012 | 7위 | 9위 | on 승 |

일관된 패턴이 없다. 17문항에서 적중 1건 차이는 노이즈 범위로 본다.

## 가설이 빗나간 이유

당초 근거는 "코드가 쪼개지면 정확 일치가 붕괴한다" 였다. 논리는 맞지만
이 코퍼스에서는 전제가 성립하지 않는다. `D-2` 는 D-2 문서의 거의 모든 청크에
등장하므로 **IDF 가 낮아 BM25 점수에 거의 기여하지 않는다.** 보호하든 말든
순위를 움직일 힘이 없다. 보호 규칙이 값을 하려면 코드가 희귀하고 결정적이어야 한다.

## 결론

- 보호 규칙은 **유지한다.** 비용이 없고, 코드가 희귀한 질의에서는 여전히 옳은 처리다.
- 다만 **측정된 이득이 없으므로 성능 근거로 내세우지 않는다.**
- 최종 채택 구성은 A(벡터 단독)이고 A 는 토크나이저를 쓰지 않는다.
  이 실험은 채택하지 않은 부품에 대한 것이므로 최종 성능과 무관하다.

## 재현

```
python src/build_index.py --chunks data/chunks.jsonl --out data/index-noprotect \
    --version idx-v5-noprotect --no-protect
python src/retrieve.py --config bm25 --eval eval/eval-dev.json \
    --index data/index-noprotect --no-protect
python src/retrieve.py --config bm25 --eval eval/eval-test-quoted.json \
    --index data/index-noprotect --no-protect
```
