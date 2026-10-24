"""自动更新 / 版本比较的单元测试。

不联网：只测纯逻辑 + 用假 JSON 喂 _pick_release。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import updater
from agent.version import APP_VERSION, is_newer, version_tuple


def test_version_tuple_parses_segments():
    assert version_tuple("0.0.0.2.1") == (0, 0, 0, 2, 1)
    assert version_tuple("v1.2.3") == (1, 2, 3)
    assert version_tuple("") == (0,)


def test_is_newer_handles_different_lengths():
    # 长度不同时按补 0 比较 —— 0.0.0.2 与 0.0.0.2.1 必须能区分
    assert is_newer("0.0.0.2.1", "0.0.0.2")
    assert not is_newer("0.0.0.2", "0.0.0.2.1")
    assert not is_newer("0.0.0.2.0", "0.0.0.2.0")


def test_app_version_is_semverish():
    parts = APP_VERSION.split(".")
    assert all(p.isdigit() for p in parts)
    assert len(parts) >= 4


def _release(tag, assets, draft=False, body="notes"):
    return {
        "tag_name": tag,
        "draft": draft,
        "body": body,
        "assets": [
            {"name": name, "size": 1024, "browser_download_url": "https://x/" + name}
            for name in assets
        ],
    }


def test_pick_release_prefers_highest_version():
    releases = [
        _release("beta-0.0.0.2.0", ["MollyPaw.exe"]),
        _release("beta-0.0.0.2.1", ["MollyPaw.exe"]),
        _release("beta-0.0.0.2.2", ["MollyPaw.exe"]),
    ]
    picked = updater._pick_release(releases)
    assert picked["version"] == "0.0.0.2.2"
    assert picked["asset"]["name"] == "MollyPaw.exe"


def test_pick_release_skips_drafts_and_assetless():
    releases = [
        _release("beta-0.0.0.9.9", ["MollyPaw.exe"], draft=True),
        _release("beta-0.0.0.8.8", ["source.zip"]),
        _release("beta-0.0.0.2.1", ["MollyPaw.exe"]),
    ]
    picked = updater._pick_release(releases)
    assert picked["version"] == "0.0.0.2.1"


def test_pick_release_empty_returns_none():
    assert updater._pick_release([]) is None
    assert updater._pick_release(None) is None


def test_swap_bat_contains_expected_commands(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "download_dir", lambda: str(tmp_path))
    bat = updater._swap_bat(r"C:\app\MollyPaw.exe",
                            r"C:\tmp\MollyPaw-new.exe", 1234)
    text = open(bat, "r", encoding="utf-8").read()
    assert "tasklist" in text
    assert "MollyPaw.exe.old" in text
    assert "start" in text
    assert bat.endswith("apply_update.bat")
