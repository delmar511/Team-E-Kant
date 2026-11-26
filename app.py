"""Team-E-Kant Knowledge Agent — Streamlit UI.

실행: streamlit run app.py
"""
import os
import sys
import traceback

import streamlit as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import config as cfg_mod
from agent import run_agent
from answer.generator import ClaudeLLM, make_answer_llm, make_rewrite_llm
from optimize.cache import AnswerCache
from optimize.rewrite import build_rewrite_prompt, rewrite_query
from search_adapter import make_retriever

# ---------------------------------------------------------------------------
# 구성 선택 목록
# ---------------------------------------------------------------------------
CONFIG_OPTIONS = {
    "A": "configs/A.toml",
    "B": "configs/B.toml",
    "C": "configs/C.toml",
    "C+cache": "configs/C_cache.toml",
    "C+rewrite": "configs/C_rewrite.toml",
}

RETRIEVAL_MODE_LABEL = {
    "vector": "vector",
    "hybrid": "hybrid",
    "hybrid_rerank": "hybrid+rerank",
}


# ---------------------------------------------------------------------------
# 캐시된 리소스
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def _load_config(name: str):
    path = CONFIG_OPTIONS[name]
    return cfg_mod.load_config(path)


@st.cache_resource(show_spinner=False)
def _make_retriever(name: str):
    c = _load_config(name)
    return make_retriever(c)


# ---------------------------------------------------------------------------
# 사이드바
# ---------------------------------------------------------------------------
st.set_page_config(page_title="비자 지식 에이전트", layout="wide")
st.title("비자 지식 에이전트")

with st.sidebar:
    st.header("구성")
    cfg_name = st.selectbox("구성 선택", list(CONFIG_OPTIONS.keys()), index=2)

    # 설정 로드 및 오류 처리
    cfg_ok = True
    cfg = None
    manifest_error = None
    try:
        cfg = _load_config(cfg_name)
    except cfg_mod.ConfigError as e:
        st.error(f"설정 오류: {e}")
        cfg_ok = False

    if cfg is not None:
        try:
            cfg_mod.check_index_manifest(cfg)
        except cfg_mod.ConfigError as e:
            st.warning(f"⚠️ 인덱스 불일치: {e}")
            manifest_error = str(e)
            cfg_ok = False

    if cfg is not None:
        mode_label = RETRIEVAL_MODE_LABEL.get(cfg.retrieval.mode.value, cfg.retrieval.mode.value)
        opt_kind = cfg.optimization.kind.value
        badge_parts = [cfg_name, mode_label]
        if opt_kind != "none":
            badge_parts.append(opt_kind)
        st.success(" · ".join(badge_parts))

# ---------------------------------------------------------------------------
# API 키 확인
# ---------------------------------------------------------------------------
api_key = os.getenv("ANTHROPIC_API_KEY", "")
api_key_missing = not api_key.strip()

if api_key_missing:
    st.error("ANTHROPIC_API_KEY 환경 변수가 설정되지 않았습니다. .env 파일을 확인하세요.")

# ---------------------------------------------------------------------------
# 세션 상태: 캐시 인스턴스
# ---------------------------------------------------------------------------
if "answer_cache" not in st.session_state:
    st.session_state.answer_cache = {}  # cfg_name -> AnswerCache


def _get_cache(name: str, ttl_s: int) -> AnswerCache:
    if name not in st.session_state.answer_cache:
        st.session_state.answer_cache[name] = AnswerCache(ttl_seconds=ttl_s)
    return st.session_state.answer_cache[name]


# ---------------------------------------------------------------------------
# 질문 입력
# ---------------------------------------------------------------------------
submit_disabled = not cfg_ok or api_key_missing

with st.form("question_form"):
    question = st.text_input(
        "질문",
        placeholder="예: 비자 연장 신청에 필요한 서류는 무엇인가요?",
        disabled=submit_disabled,
    )
    submitted = st.form_submit_button("질문하기", disabled=submit_disabled)

if not submitted or not question.strip():
    st.stop()

# ---------------------------------------------------------------------------
# 에이전트 호출
# ---------------------------------------------------------------------------
try:
    retriever = _make_retriever(cfg_name)
    llm_fn = make_answer_llm(cfg)

    cache = None
    rewrite_fn = None
    versions = None

    opt = cfg.optimization.kind.value
    if opt == "cache":
        ttl = cfg.optimization.cache.ttl_s
        cache = _get_cache(cfg_name, ttl)
        versions = cfg_mod.build_versions(cfg)
    elif opt == "rewrite":
        rewrite_llm = make_rewrite_llm(cfg)

        def rewrite_fn(prompt: str) -> str:  # noqa: F811
            from answer.generator import as_reply
            return as_reply(rewrite_llm(prompt)).text

    with st.spinner("검색 중…"):
        result = run_agent(
            question,
            cfg,
            retriever,
            llm_fn=llm_fn,
            rewrite_fn=rewrite_fn,
            cache=cache,
            versions=versions,
            user_scope="public",
        )
except Exception:
    with st.expander("오류 상세 (클릭하여 열기)", expanded=True):
        st.code(traceback.format_exc(), language="python")
    st.stop()

resp = result.response
candidates = result.candidates

# ---------------------------------------------------------------------------
# 리라이트 / 캐시 배지
# ---------------------------------------------------------------------------
if resp.rewritten_query:
    st.info(f"리라이트된 질문: {resp.rewritten_query}")

if resp.cache_hit:
    st.markdown('<span style="background:#1a7f3c;color:#fff;padding:2px 8px;border-radius:4px;font-size:0.8em">캐시 적중</span>', unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# 답변 표시
# ---------------------------------------------------------------------------
status = resp.status.value
invalid_set = set(resp.invalid_citation_ids)

if status == "answered":
    st.markdown(f"""<div style="background:#e8f4fd;border-left:4px solid #1a73e8;padding:12px 16px;border-radius:4px;margin-bottom:8px">{resp.answer}</div>""", unsafe_allow_html=True)
    with st.expander(f"근거 청크 ({len(resp.cited_chunk_ids)}개)"):
        for cid in resp.cited_chunk_ids:
            cand = next((c for c in candidates if c.chunk.chunk_id == cid), None)
            warn = " ⚠️" if cid in invalid_set else ""
            if cand:
                st.markdown(f"**{cid}**{warn} · {cand.chunk.location.label()}")
                st.caption(cand.chunk.text[:200])
            else:
                st.markdown(f"**{cid}**{warn}")
            st.divider()

elif status == "no_evidence":
    st.info(resp.answer or "관련 근거를 찾을 수 없습니다.")
    if candidates:
        with st.expander(f"근거 청크 ({len(resp.cited_chunk_ids)}개)"):
            for cid in resp.cited_chunk_ids:
                cand = next((c for c in candidates if c.chunk.chunk_id == cid), None)
                if cand:
                    st.markdown(f"**{cid}** · {cand.chunk.location.label()}")
                    st.caption(cand.chunk.text[:200])
                    st.divider()

else:
    st.error(f"[{status}] {resp.error_message or '알 수 없는 오류'}")

# ---------------------------------------------------------------------------
# 검색 후보 상세 (디버그)
# ---------------------------------------------------------------------------
if candidates:
    cited_set = set(resp.cited_chunk_ids)
    with st.expander("검색 후보 상세"):
        import pandas as pd

        rows = []
        for c in candidates:
            rows.append({
                "rank": c.rank,
                "chunk_id": c.chunk.chunk_id,
                "source": c.source.value,
                "score": round(c.score, 4),
                "rank_before_rerank": c.rank_before_rerank,
                "location": c.chunk.location.label(),
                "preview": c.chunk.text[:100],
            })
        df = pd.DataFrame(rows)

        def _highlight(row):
            color = "background-color:#d4edda" if row["chunk_id"] in cited_set else ""
            return [color] * len(row)

        st.dataframe(df.style.apply(_highlight, axis=1), use_container_width=True)

# ---------------------------------------------------------------------------
# 지연·사용량 푸터
# ---------------------------------------------------------------------------
lat = resp.latency
usage = resp.usage

metrics = []
metrics.append(("전체 (ms)", lat.total_ms))
if lat.retrieval_ms is not None:
    metrics.append(("검색 (ms)", lat.retrieval_ms))
if lat.rerank_ms is not None:
    metrics.append(("재정렬 (ms)", lat.rerank_ms))
if lat.generation_ms is not None:
    metrics.append(("생성 (ms)", lat.generation_ms))
if lat.cache_lookup_ms is not None:
    metrics.append(("캐시조회 (ms)", lat.cache_lookup_ms))
if lat.rewrite_ms is not None:
    metrics.append(("리라이트 (ms)", lat.rewrite_ms))
metrics.append(("모델 호출", usage.model_calls))
metrics.append(("입력 토큰", usage.input_tokens))
metrics.append(("출력 토큰", usage.output_tokens))

cols = st.columns(len(metrics))
for col, (label, value) in zip(cols, metrics):
    col.metric(label, value)
