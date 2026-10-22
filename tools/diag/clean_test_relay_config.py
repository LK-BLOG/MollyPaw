"""清掉诊断/演示脚本写进 config.json 的测试用 relay 配置。"""
import io, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
from agent.paths import config_path
TEST_PSKS = {"MollyPawDiag12345", "MollyPawVerify123", "MollyPawStrong123",
             "MollyPawCliDemo99", "MollyPawCliTest99"}
path = config_path()
if not os.path.exists(path):
    print("没有 config.json"); sys.exit(0)
cfg = json.load(io.open(path, encoding="utf-8"))
relay = cfg.get("relay")
if not isinstance(relay, dict):
    print("没有 relay 字段"); sys.exit(0)
psk = relay.get("psk", "")
if psk in TEST_PSKS or psk.startswith("MollyPaw"):
    print("清掉测试用 relay 配置")
    cfg.pop("relay", None)
    json.dump(cfg, io.open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("已清理")
else:
    print("看起来是用户自己的配置，保留")
