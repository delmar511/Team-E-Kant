# -*- coding: utf-8 -*-
"""RAGAS 기반 RAG 평가 (실험용, 역할 7).

기존 실행 기록(records.jsonl)을 RAGAS 형식으로 변환해
LLMContextRecall, Faithfulness, FactualCorrectness 를 계산한다.
LLM judge 는 Anthropic Claude (ANTHROPIC_API_KEY 필요).

사용:
    python experiments/ragas_eval.py results/runs/<...>.records.jsonl \\
        --eval eval/eval-dev.json \\
        [--out results/ragas/<이름>.json] \\
        [--model claude-haiku-5-5]

no_answer 문항은 제외한다 (RAGAS 지표 정의에 맞지 않음).
답변이 없는 오류 건(retrieval_error, model_error 등)도 제외한다.
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "experiments"))

from _common import load_questions  # noqa: E402
from schemas import RunRecord, RunKind, Status  # noqa: E402

RAGAS_DIR = ROOT / "results" / "ragas"

# RAGAS 가 출력하는 진행 로그를 줄임
os.environ.setdefault("RAGAS_DO_NOT_TRACK", "true")


def load_records(paths: list[Path]) -> list[RunRecord]:
    out = []
    for p in paths:
        with open(p, encoding="utf-8") as f:
            out += [RunRecord.model_validate_json(line) for line in f if line.strip()]
    return [r for r in out if r.run_kind is not RunKind.WARMUP]


def build_samples(records: list[RunRecord], questions: list[dict]) -> list[dict]:
    """RunRecord 목록 → RAGAS SingleTurnSample 입력용 딕셔너리 목록.

    반환 각 항목:
        question_id, config_name, user_input, response,
        retrieved_contexts (청크 본문 리스트), reference (expected_facts 합치기)
    """
    q_index = {q["question_id"]: q for q in questions}
    samples = []
    skipped = {"no_answer": 0, "error": 0, "missing": 0, "no_context": 0}

    for r in records:
        q = q_index.get(r.question_id)
        if q is None:
            skipped["missing"] += 1
            continue
        if not q["answerable"]:
            skipped["no_answer"] += 1
            continue
        if r.response.status.is_error or r.response.status is Status.NO_EVIDENCE:
            skipped["error"] += 1
            continue
        if not r.candidates:
            skipped["no_context"] += 1
            continue

        contexts = [c.chunk.text for c in r.candidates if c.chunk.text]
        reference = " ".join(q.get("expected_facts") or [])
        if not reference:
            skipped["no_context"] += 1
            continue

        samples.append({
            "question_id": r.question_id,
            "config_name": r.config_name,
            "run_id": r.run_id,
            "user_input": r.question,
            "response": r.response.answer or "",
            "retrieved_contexts": contexts,
            "reference": reference,
        })

    total = sum(skipped.values())
    if total:
        detail = ", ".join(f"{k} {v}" for k, v in skipped.items() if v)
        print(f"[ragas_eval] 제외: {detail} ({total}건)")
    print(f"[ragas_eval] 평가 대상: {len(samples)}건")
    return samples


_JUDGE_PROMPTS = {
    "context_recall": """\
주어진 참고 답변(reference)의 각 문장이 검색된 문맥(contexts)으로부터 추론 가능한지 판단하라.

[참고 답변]
{reference}

[검색된 문맥]
{contexts}

각 문장을 검토하고, 문맥으로부터 근거를 찾을 수 있으면 1, 없으면 0으로 평가하라.
마지막 줄에 반드시 다음 형식으로 최종 점수(0.0~1.0)를 출력하라:
SCORE: <숫자>""",

    "faithfulness": """\
주어진 답변(answer)의 각 주장이 검색된 문맥(contexts)에 의해 뒷받침되는지 판단하라.

[답변]
{answer}

[검색된 문맥]
{contexts}

각 주장을 검토하고, 문맥에서 지지되면 1, 지지되지 않으면 0으로 평가하라.
마지막 줄에 반드시 다음 형식으로 최종 점수(0.0~1.0)를 출력하라:
SCORE: <숫자>""",

    "context_precision": """\
주어진 질문(question)에 대한 참고 답변(reference)을 고려할 때,
검색된 문맥(contexts) 중 관련 있는 문맥이 상위에 위치하는지 판단하라.

[질문]
{question}

[참고 답변]
{reference}

[검색된 문맥 (순서대로)]
{contexts}

각 문맥이 질문 답변에 유용한지 평가하고, 상위에 유용한 문맥이 많을수록 높은 점수를 준다.
마지막 줄에 반드시 다음 형식으로 최종 점수(0.0~1.0)를 출력하라:
SCORE: <숫자>""",
}


def _extract_score(text: str) -> float | None:
    import re
    m = re.search(r"SCORE:\s*([0-9]*\.?[0-9]+)", text or "")
    if not m:
        return None
    v = float(m.group(1))
    return max(0.0, min(1.0, v))


def run_ragas(samples: list[dict], model: str) -> list[dict]:
    """RAGAS 지표를 Anthropic SDK 직접 호출로 계산한다 (RAGAS 비동기 러너 우회)."""
    import anthropic
    import time
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")

    client = anthropic.Anthropic()

    def judge(prompt: str) -> float | None:
        for attempt in range(3):
            try:
                msg = client.messages.create(
                    model=model,
                    max_tokens=4096,
                    messages=[{"role": "user", "content": prompt}],
                )
                texts = [b.text for b in msg.content if type(b).__name__ == "TextBlock"]
                if not texts:
                    types = [type(b).__name__ for b in msg.content]
                    raise ValueError(f"텍스트 블록 없음 — 반환된 블록: {types}")
                return _extract_score(texts[-1])
            except Exception as e:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                else:
                    print(f"[judge 실패] {e}")
                    return None

    out = []
    total = len(samples)
    for i, s in enumerate(samples, 1):
        contexts_text = "\n---\n".join(s["retrieved_contexts"][:5])
        scores: dict[str, float | None] = {}
        for metric, tmpl in _JUDGE_PROMPTS.items():
            prompt = tmpl.format(
                question=s["user_input"],
                answer=s["response"],
                reference=s["reference"],
                contexts=contexts_text,
            )
            scores[metric] = judge(prompt)
        row = {k: v for k, v in s.items() if k != "retrieved_contexts"}
        row.update(scores)
        out.append(row)
        print(f"  [{i:2d}/{total}] {s['question_id']} ({s['config_name']}) "
              + " | ".join(f"{k} {v:.2f}" if v is not None else f"{k} -"
                           for k, v in scores.items()))
    return out


def render_report(rows: list[dict], sources: list[str]) -> str:
    import statistics

    def avg(key):
        vals = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
        return f"{statistics.mean(vals):.3f}" if vals else "N/A"

    by_config: dict[str, list[dict]] = {}
    for r in rows:
        by_config.setdefault(r["config_name"], []).append(r)

    metric_keys = ["context_recall", "faithfulness", "context_precision"]

    lines = [
        "# RAGAS 평가 결과",
        "",
        f"- 실행 기록: {', '.join(Path(s).name for s in sources)}",
        f"- 평가 건수: {len(rows)}건 (no_answer·오류 제외)",
        "- 지표: ContextRecall, Faithfulness, ContextPrecision (Anthropic Claude judge)",
        "",
        "## 구성별 평균",
        "",
        "| 구성 | 건수 | context_recall | faithfulness | context_precision |",
        "|---|---|---|---|---|",
    ]
    for config, rs in sorted(by_config.items()):
        vals = [f"{statistics.mean([r[k] for r in rs if isinstance(r.get(k), (int, float))]):.3f}"
                if any(isinstance(r.get(k), (int, float)) for r in rs) else "N/A"
                for k in metric_keys]
        lines.append(f"| {config} | {len(rs)} | {' | '.join(vals)} |")

    lines += [
        "",
        "## 전체 평균",
        "",
        "| context_recall | faithfulness | context_precision |",
        "|---|---|---|",
        f"| {avg('context_recall')} | {avg('faithfulness')} | {avg('context_precision')} |",
        "",
    ]
    return "\n".join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(description="RAGAS 기반 RAG 평가")
    p.add_argument("records", nargs="+", help="results/runs/*.records.jsonl")
    p.add_argument("--eval", required=True, help="eval/eval-dev.json 또는 eval/eval-test.json")
    p.add_argument("--model", default="claude-haiku-5-5", help="Anthropic 모델 ID (기본: claude-haiku-5-5)")
    p.add_argument("--out", help="결과 JSON 저장 경로 (없으면 results/ragas/ 에 자동 저장)")
    a = p.parse_args(argv)

    questions = load_questions(a.eval)
    records = load_records([Path(r) for r in a.records])
    if not records:
        raise SystemExit("[ragas_eval] 평가할 실행 기록이 없습니다.")

    samples = build_samples(records, questions)
    if not samples:
        raise SystemExit("[ragas_eval] 평가 대상 샘플이 없습니다 (no_answer 또는 오류 건만 있음).")

    print(f"[ragas_eval] LLM judge: {a.model} — RAGAS 실행 중...")
    rows = run_ragas(samples, a.model)

    report = render_report(rows, a.records)
    print(report)

    out_path = Path(a.out) if a.out else RAGAS_DIR / (Path(a.records[0]).name.replace(".records.jsonl", ".ragas.json"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    out_path.with_suffix(".md").write_text(report, encoding="utf-8")
    print(f"[ragas_eval] 저장: {out_path} (+ .md)")


if __name__ == "__main__":
    main()
