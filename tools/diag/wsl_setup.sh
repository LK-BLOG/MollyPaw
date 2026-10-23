#!/bin/bash
# 在 WSL (Arch) 里装齐测试依赖。
set -e
sudo pacman -S --needed --noconfirm \
  python-pytest \
  python-websockets \
  python-cryptography \
  python-websocket-client
python3 - <<'PY'
import pytest, websockets, cryptography, websocket
print("deps ok")
PY
