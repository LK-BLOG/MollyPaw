"""Shared data directory resolution for MollyPaw.

All persistent data (config, conversations, memory, skills) lives under a
single directory so upgrades and reinstalls never touch user data.

Frozen (PyInstaller):  %APPDATA%\\MollyPaw
Dev (python main.py):  PROJECT_ROOT/data
Test / 隔离运行:        MOLLYPAW_DATA_DIR 环境变量指定的目录

**MOLLYPAW_DATA_DIR 存在的理由（血泪教训）**：
测试曾经直接构造 AgentCore，而 AgentCore 会 save_config()，
结果把开发者的真 data/config.json 覆盖成了测试夹具的假数据。
任何测试都必须在 import 前把这个环境变量指到临时目录 ——
见 tests/conftest.py 的 autouse fixture。
"""
import os
import sys

ENV_DATA_DIR = "MOLLYPAW_DATA_DIR"


def data_dir() -> str:
    """Return the root data directory, creating it if needed.

    优先级：MOLLYPAW_DATA_DIR > frozen 的 %APPDATA%\\MollyPaw > 项目内 data/
    """
    override = os.environ.get(ENV_DATA_DIR)
    if override:
        base = os.path.abspath(override)
    elif getattr(sys, 'frozen', False):
        base = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'MollyPaw')
    else:
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
    os.makedirs(base, exist_ok=True)
    return base


def is_isolated() -> bool:
    """当前是否跑在隔离数据目录下（测试环境）。"""
    return bool(os.environ.get(ENV_DATA_DIR))


def config_path() -> str:
    return os.path.join(data_dir(), 'config.json')


def conversations_dir() -> str:
    d = os.path.join(data_dir(), 'conversations')
    os.makedirs(d, exist_ok=True)
    return d


def memory_dir() -> str:
    d = os.path.join(data_dir(), 'memory')
    os.makedirs(d, exist_ok=True)
    return d


def skills_dir() -> str:
    d = os.path.join(data_dir(), 'skills')
    os.makedirs(d, exist_ok=True)
    return d

