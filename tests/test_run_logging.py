"""experiments/_common.py 기록: 한 줄씩 바로 쓰기, 덮어쓰기 금지."""
import json

import pytest

from _common import JsonlWriter, out_paths


def test_rows_survive_a_crash_mid_run(tmp_path):
    p = tmp_path / "run.records.jsonl"
    with pytest.raises(RuntimeError):
        with JsonlWriter(p) as w:
            w.write({"run_id": "r1"})
            w.write({"run_id": "r2"})
            raise RuntimeError("59번째 문항에서 실패")
    assert [json.loads(l)["run_id"] for l in p.read_text(encoding="utf-8").splitlines()] == ["r1", "r2"]


def test_existing_file_is_never_overwritten(tmp_path):
    p = tmp_path / "run.records.jsonl"
    p.write_text("old\n", encoding="utf-8")
    with pytest.raises(FileExistsError):
        with JsonlWriter(p):
            pass
    assert p.read_text(encoding="utf-8") == "old\n"


def test_out_paths_returns_stamp_for_run_ids(monkeypatch, tmp_path):
    import _common
    monkeypatch.setattr(_common, "RUNS_DIR", tmp_path)
    stamp, rec, trace = out_paths("dev_A")
    assert len(stamp) == 14 and stamp.isdigit()
    assert rec.name.endswith("_dev_A.records.jsonl") and trace.name.endswith("_dev_A.trace.jsonl")
