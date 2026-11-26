# -*- coding: utf-8 -*-
"""청크의 page 는 본문이 시작하는 쪽이어야 한다 (구간이 끝나는 쪽이 아니라)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "ingest"))
from chunk import MAXLEN, parse  # noqa: E402

DOC = """---
doc_id: DOC-T
title: 테스트
---
<!-- page: 10 -->
## 가. 첫 항목

첫 항목 본문은 10쪽에서 시작해서 다음 쪽으로 넘어간다
<!-- page: 11 -->
11쪽에 이어지는 본문
<!-- page: 12 -->
12쪽까지 이어지는 본문

## 나. 둘째 항목
<!-- page: 13 -->

둘째 항목 본문은 제목 다음 쪽 표시 뒤에 시작한다
"""


def _parse(tmp_path, text):
    p = tmp_path / "doc.md"
    p.write_text(text, encoding="utf-8")
    return parse(str(p))


def test_page_is_start_page_of_section(tmp_path):
    chunks = _parse(tmp_path, DOC)
    assert [c["page"] for c in chunks] == [10, 13]


def test_split_parts_get_their_own_start_page(tmp_path):
    line = "가" * 100
    body = "\n".join([line] * 10) + "\n<!-- page: 21 -->\n" + "\n".join([line] * 10)
    text = f"---\ndoc_id: DOC-T\ntitle: t\n---\n<!-- page: 20 -->\n## 긴 항목\n{body}\n"
    chunks = _parse(tmp_path, text)
    assert len(chunks) >= 2 and all(len(c["text"]) <= MAXLEN + len(line) + 1 for c in chunks)
    assert chunks[0]["page"] == 20
    assert chunks[-1]["page"] == 21
