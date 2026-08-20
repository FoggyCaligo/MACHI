from __future__ import annotations

import pytest

from MK4.tools.file_navigation_tools import FileNavigationToolSuite


@pytest.mark.asyncio
async def test_file_tree_defaults_to_depth_three_and_broad_limit(tmp_path) -> None:
    for index in range(30):
        path = tmp_path / f"dir_{index}" / "nested" / "leaf.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(index), encoding="utf-8")

    suite = FileNavigationToolSuite(workspace_root=tmp_path)
    result = await suite._tree({"root": "."})

    assert result["ok"] is True
    assert result["depth"] == 3
    assert result["truncated"] is False
    paths = {entry["path"] for entry in result["entries"]}
    assert "dir_0/nested/leaf.txt" in paths
    assert "dir_29/nested/leaf.txt" in paths


@pytest.mark.asyncio
async def test_truncated_file_tree_is_not_a_successful_absence_check(tmp_path) -> None:
    for index in range(25):
        (tmp_path / f"item_{index:02d}").mkdir()

    suite = FileNavigationToolSuite(workspace_root=tmp_path)
    result = await suite._tree({"root": ".", "depth": 1, "limit": 10})

    assert result["ok"] is False
    assert result["error"] == "tree_truncated"
    assert result["truncated"] is True
    assert result["recovery"]["absence_is_unproven"] is True
    assert result["recovery"]["next_tools"] == ["file_tree", "file_search"]
    assert result["recovery"]["suggested_limit"] > 10
    assert "does NOT prove" in result["message"]
    assert "Do not conclude" in result["message"]


@pytest.mark.asyncio
async def test_complete_file_tree_remains_successful(tmp_path) -> None:
    (tmp_path / "MK4").mkdir()
    (tmp_path / "IDEA1").mkdir()

    suite = FileNavigationToolSuite(workspace_root=tmp_path)
    result = await suite._tree({"root": ".", "depth": 1, "limit": 100})

    assert result["ok"] is True
    assert result["truncated"] is False
    paths = {entry["path"] for entry in result["entries"]}
    assert "MK4" in paths
