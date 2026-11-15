"""設計書のエラーIDと障害対応手順書の対応の検査（TC-DOC-01）。

詳細設計書（03_詳細設計.md）4.1 節に出てくる ERR-xxx が、障害対応手順書（07_障害対応手順書.md）の
4 章の見出しと 7 章のエラーID対応表にすべて載っていること、手順書と他の文書に設計書に無い ERR が無いことを確かめる。
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
DESIGN = DOCS / "03_詳細設計.md"
RUNBOOK = DOCS / "07_障害対応手順書.md"
ERR = re.compile(r"ERR-\d{3}")


def _chapters(text: str) -> dict[str, str]:
    """「## N. 見出し」ごとに本文を分ける。キーは章番号。"""
    parts = re.split(r"^## ", text, flags=re.M)
    chapters = {}
    for part in parts[1:]:
        m = re.match(r"(\d+)\.", part)
        if m:
            chapters[m.group(1)] = part
    return chapters


def test_tc_doc_01_runbook_covers_all_error_ids():
    design_ids = set(ERR.findall(DESIGN.read_text(encoding="utf-8")))
    assert design_ids, "詳細設計書にエラーIDが見つかりません"

    runbook = RUNBOOK.read_text(encoding="utf-8")
    chapters = _chapters(runbook)
    headings = set(re.findall(r"^### 4\.\d+ (ERR-\d{3}) ", chapters["4"], flags=re.M))
    table_ids = set(re.findall(r"^\| (ERR-\d{3}) \|", chapters["7"], flags=re.M))

    assert design_ids - headings == set(), f"4 章に見出しが無いエラーID: {sorted(design_ids - headings)}"
    assert design_ids - table_ids == set(), f"7 章の表に無いエラーID: {sorted(design_ids - table_ids)}"

    # 手順書・他の設計書・README に、設計書に無いエラーIDを書いていないこと
    for path in [*DOCS.glob("*.md"), ROOT / "README.md"]:
        unknown = set(ERR.findall(path.read_text(encoding="utf-8"))) - design_ids
        assert unknown == set(), f"{path.name} に設計書に無いエラーID: {sorted(unknown)}"
