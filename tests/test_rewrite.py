# -*- coding: utf-8 -*-
"""src/optimize/rewrite.py: 용어 치환, 약호 보존, 비정상 출력 거부, build_rewrite_prompt. API 호출 없음."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from optimize.rewrite import build_rewrite_prompt, rewrite_query, TERMS


# ---------------------------------------------------------------------------
# 용어 사전 치환 (llm_fn=None)
# ---------------------------------------------------------------------------

def test_dict_rewrite_replaces_known_colloquial_terms():
    q = "어학당 학생이 알바하려면 어떻게 해야 하나요?"
    out = rewrite_query(q)
    assert "알바" not in out
    assert "시간제취업" in out
    assert "어학연수(D-4)" in out


def test_dict_rewrite_replaces_areubaeiteu():
    q = "아르바이트 허가를 받으려면?"
    out = rewrite_query(q)
    assert "아르바이트" not in out
    assert "시간제취업" in out


def test_dict_rewrite_replaces_visa_extension_phrasing():
    q = "비자 연장 신청은 어디서 하나요?"
    out = rewrite_query(q)
    assert "비자 연장" not in out
    assert "체류기간 연장허가" in out


def test_dict_rewrite_no_change_for_already_correct_terms():
    q = "D-2 체류기간 연장허가 제출서류는?"
    out = rewrite_query(q)
    assert out == q  # 이미 매뉴얼 용어 — 치환 없음


# ---------------------------------------------------------------------------
# 비자 약호 보존
# ---------------------------------------------------------------------------

def test_visa_code_preserved_through_dict_rewrite():
    """D-2-2, D-4-1 같은 체류자격 약호는 치환하지 않는다."""
    for code in ("D-2", "D-2-2", "D-4-1", "D-4"):
        q = f"{code} 비자 연장 조건은?"
        out = rewrite_query(q)
        assert code in out, f"{code} 가 리라이트 결과에서 사라짐: {out!r}"


# ---------------------------------------------------------------------------
# LLM 리라이터 경로 (llm_fn 주입)
# ---------------------------------------------------------------------------

def test_llm_rewrite_result_is_returned():
    """llm_fn 이 정상 한 줄을 돌려주면 그것이 결과가 된다."""
    def good_llm(prompt):
        return "D-4 어학연수 시간제취업 허가 요건"

    out = rewrite_query("어학당 학생 알바 허가 조건", llm_fn=good_llm)
    assert out == "D-4 어학연수 시간제취업 허가 요건"


def test_llm_rewrite_empty_output_raises():
    def empty_llm(prompt):
        return ""

    with pytest.raises(ValueError):
        rewrite_query("질문", llm_fn=empty_llm)


def test_llm_rewrite_too_long_output_raises():
    def verbose_llm(prompt):
        return "길고 " * 300

    with pytest.raises(ValueError):
        rewrite_query("짧은 질문", llm_fn=verbose_llm)


def test_llm_rewrite_exception_propagates():
    """llm_fn 이 예외를 던지면 그대로 전파한다 (agent 가 fallback 처리)."""
    def broken_llm(prompt):
        raise RuntimeError("API 호출 실패")

    with pytest.raises(RuntimeError, match="API 호출 실패"):
        rewrite_query("질문", llm_fn=broken_llm)


# ---------------------------------------------------------------------------
# build_rewrite_prompt 에 정답·근거가 없어야 한다
# ---------------------------------------------------------------------------

def test_build_rewrite_prompt_contains_question_only():
    """리라이트 프롬프트에 expected_facts / evidence 같은 정답표가 들어가면 안 된다."""
    q = "D-4 시간제취업 요건은?"
    prompt = build_rewrite_prompt(q)
    assert q in prompt
    # 정답표 키워드가 프롬프트에 없어야 한다
    assert "expected_facts" not in prompt
    assert "evidence" not in prompt
    assert "chunk_id" not in prompt


def test_build_rewrite_prompt_instructs_manual_terminology():
    """프롬프트가 매뉴얼 용어로 바꾸라는 지시를 담고 있어야 한다."""
    prompt = build_rewrite_prompt("질문")
    assert "매뉴얼" in prompt
    assert "검색 질의" in prompt
