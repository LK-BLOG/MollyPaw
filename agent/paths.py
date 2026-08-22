"""Shared data directory resolution for MollyPaw.

All persistent data (config, conversations, memory, skills) lives under a
single directory so upgrades and reinstalls never touch user data.

Frozen (PyInstaller):  %APPDATA%\MollyPaw
Dev (python main.py):  PROJECT_ROOT/data
"""
import os
import sys


def data_dir() -> str:
    """Return the root data directory, creating it if needed."""
    if getattr(sys, 'frozen', False):
        base = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'MollyPaw')
    else:
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
    os.makedirs(base, exist_ok=True)
    return base


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

