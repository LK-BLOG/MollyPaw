"""诊断：弱密钥保存为什么返回 ok:false。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault("MOLLYPAW_DATA_DIR",
                      os.path.join(os.environ.get("TEMP", "/tmp"), "mp-diag"))

import main

api = main.MollyPawAPI()
print("controller      =", api.service.controller)

try:
    print("relay_settings  =", api.relay_settings(json.dumps({"psk": "abc"})))
except Exception:
    import traceback
    traceback.print_exc()

print("--- 直接看 RelayManager.set_config ---")
try:
    mgr = api._ensure_relay()
    print("mgr.config =", mgr.config)
    st = mgr.set_config(psk="abc")
    print("set_config ->", st)
except Exception:
    import traceback
    traceback.print_exc()

print("--- 再看 relay_settings ---")
print(api.relay_settings(json.dumps({"psk": "abc"})))
