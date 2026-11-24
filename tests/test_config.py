"""Tests for src/config.py. Run: pytest tests/test_config.py"""

import json
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from config import (  # noqa: E402
    ConfigError, build_versions, check_index_manifest, check_shared_settings,
    index_version, load_config,
)


@pytest.fixture
def repo(tmp_path):
    """A throwaway repo with the real configs and a dummy prompt template."""
    shutil.copytree(REPO / "configs", tmp_path / "configs")
    tpl = tmp_path / "src/answer/templates/answer_v1.txt"
    tpl.parent.mkdir(parents=True)
    tpl.write_text("Answer using only the context.\n{context}\n{question}", encoding="utf-8")
    return tmp_path


def load(repo, name):
    return load_config(repo / "configs" / name)


def edit(repo, name, old, new):
    p = repo / "configs" / name
    text = p.read_text(encoding="utf-8")
    assert old in text, f"{old!r} not in {name}"
    p.write_text(text.replace(old, new), encoding="utf-8")


def test_all_shipped_configs_load(repo):
    for name in ["A.toml", "B.toml", "C.toml", "C_cache.toml", "C_rewrite.toml"]:
        load(repo, name)


def test_extends_merges_child_over_parent(repo):
    c = load(repo, "C.toml")
    assert c.retrieval.mode.value == "hybrid_rerank"
    assert c.retrieval.fusion.rrf_k == 60          # inherited from B
    assert c.generation.temperature == 0.0         # inherited from base


def test_core_configs_share_settings(repo):
    check_shared_settings([load(repo, n) for n in ["A.toml", "B.toml", "C.toml"]])


def test_shared_settings_violation_detected(repo):
    a, b = load(repo, "A.toml"), load(repo, "B.toml")
    edit(repo, "B.toml", 'name = "B"', 'name = "B"\n\n[generation]\ntemperature = 0.7')
    with pytest.raises(ConfigError, match="generation"):
        check_shared_settings([a, load(repo, "B.toml")])
    check_shared_settings([a, b])  # originals still fine


def test_versions_are_deterministic(repo):
    v1, v2 = build_versions(load(repo, "C.toml")), build_versions(load(repo, "C.toml"))
    assert v1 == v2


def test_retrieval_version_differs_across_configs(repo):
    vs = [build_versions(load(repo, n)) for n in ["A.toml", "B.toml", "C.toml", "C_cache.toml"]]
    assert len({v.retrieval_config_version for v in vs}) == 4
    assert len({v.index_version for v in vs}) == 1   # same chunks for all


def test_chunk_setting_change_changes_index_version(repo):
    before = index_version(load(repo, "A.toml"))
    edit(repo, "base.toml", "chunk_size = 800", "chunk_size = 600")
    assert index_version(load(repo, "A.toml")) != before


def test_template_edit_changes_prompt_version(repo):
    before = build_versions(load(repo, "A.toml")).prompt_version
    (repo / "src/answer/templates/answer_v1.txt").write_text("changed", encoding="utf-8")
    assert build_versions(load(repo, "A.toml")).prompt_version != before


def test_gate_change_changes_answer_version(repo):
    before = build_versions(load(repo, "C.toml")).answer_config_version
    edit(repo, "base.toml", "params = {}", "params = { threshold = 0.3 }")
    assert build_versions(load(repo, "C.toml")).answer_config_version != before


def test_source_file_hash_added_to_doc_version(repo):
    assert build_versions(load(repo, "A.toml")).doc_version == "MAN-STAY-YYMMDD"
    raw = repo / "data/raw/manual.pdf"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"%PDF fake")
    assert build_versions(load(repo, "A.toml")).doc_version.startswith("MAN-STAY-YYMMDD+")


@pytest.mark.parametrize("name, old, new, msg", [
    ("B.toml", 'name = "B"', 'name = "A"', "must use mode"),
    ("A.toml", "top_k = 5", "top_k = 3", "top_k"),
    ("B.toml", "bm25_k = 20", "", "needs bm25_k"),
    ("C.toml", 'model = "TBD"\ninput_k = 20', 'model = "x"\ninput_k = 99', "input_k"),
    ("C.toml", 'name = "C"', 'name = "C"\n\n[optimization]\nkind = "cache"\n'
               '[optimization.cache]\nttl_s = 1', "optimization must be off"),
    ("base.toml", "chunk_overlap = 100", "chunk_overlap = 900", "chunk_overlap"),
    ("base.toml", "max_context_chunks = 5", "max_context_chunks = 9", "max_context_chunks"),
])
def test_invalid_configs_rejected(repo, name, old, new, msg):
    edit(repo, name, old, new)
    target = "C.toml" if name == "C.toml" else ("B.toml" if name == "B.toml" else "A.toml")
    with pytest.raises(ConfigError, match=msg):
        load(repo, target)


def test_unknown_key_rejected(repo):
    edit(repo, "A.toml", "top_k = 5", "top_k = 5\ntopk = 5")
    with pytest.raises(ConfigError):
        load(repo, "A.toml")


def test_circular_extends_rejected(repo):
    edit(repo, "base.toml", "[docs]", 'extends = "A.toml"\n\n[docs]')
    with pytest.raises(ConfigError, match="circular"):
        load(repo, "A.toml")


def test_stale_index_manifest_detected(repo):
    cfg = load(repo, "A.toml")
    idx = repo / "index"
    idx.mkdir()
    (idx / "manifest.json").write_text(json.dumps({"index_version": "idx-old"}))
    with pytest.raises(ConfigError, match="stale index"):
        check_index_manifest(cfg)
    (idx / "manifest.json").write_text(json.dumps({"index_version": index_version(cfg)}))
    check_index_manifest(cfg)
