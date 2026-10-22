"""诊断：为什么中继状态一直停在"重连中"。

直接连官方中继，逐秒打印状态，把真实原因逼出来。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import main  # noqa: E402

api = main.MollyPawAPI()
r = json.loads(api.relay_settings(json.dumps({"psk": "MollyPawDiag12345"})))
print("中继地址 =", r.get("url"))
print("密钥问题 =", r.get("psk_problems"))

mgr = api._ensure_relay()
print("启动前状态 =", mgr.status())
print("HAS_RELAY =", main.HAS_RELAY, " 导入错误 =", main.RELAY_IMPORT_ERROR or "(无)")

# 把 link 的日志打开，看它报什么
mgr.logger = lambda m: print(f"  [relay] {m}")

mgr.start()
for i in range(25):
    time.sleep(1)
    st = mgr.status()
    print("t=%2ds state=%-14s connected=%-5s" % (
        i + 1, st.get("state"), st.get("connected")))
    if st.get("connected"):
        print("=> 连上了")
        break
else:
    print("=> 25 秒仍未连上，看上面的 [relay] 日志找原因")

mgr.stop()
print("已停止")
