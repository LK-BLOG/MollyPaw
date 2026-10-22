"""检查二维码生成能力（不想引入新依赖）。"""
import importlib
import sys

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

for name in ("qrcode", "segno", "pyqrcode", "PIL", "cv2"):
    try:
        mod = importlib.import_module(name)
        ver = getattr(mod, "__version__", "?")
        print(f"  {name}: 有（{ver}）")
    except ImportError:
        print(f"  {name}: 无")

print()
try:
    from PIL import Image, ImageDraw  # noqa: F401
    print("Pillow 可用 —— 可以自己画二维码矩阵，不需要新依赖")
except ImportError as exc:
    print(f"Pillow 不可用: {exc}")
