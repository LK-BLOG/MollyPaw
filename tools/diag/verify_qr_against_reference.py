"""用标准实现生成的二维码做逐模块比对，验证自己的编码器。

思路：从 api.qrserver.com 取同一段文本的标准 QR（那是独立实现），
把 PNG 还原成 0/1 模块矩阵，再让我自己的编码器**强制用同样的
版本和掩码**生成矩阵，逐位比对。

为什么要强制版本+掩码：QR 对同一段文本有多个合法输出（版本和掩码
都可以不同）。不固定这两项就没法逐位比，只能比"能否解码"——
而我没有独立的解码器。

逐位比对比"看着像"强得多：它同时验证了
  数据编码 / RS 纠错 / 分块交错 / 之字形填充 / 掩码变换 / 格式信息
任何一环写错都会在这里逐位暴露。

用法：.venv\\Scripts\\python.exe tools\\verify_qr_against_reference.py
"""
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from PIL import Image

from agent.relay import qr as myqr

PASS, FAIL = [], []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  [PASS] {name}")
    else:
        FAIL.append((name, detail))
        print(f"  [FAIL] {name} :: {detail}")


def fetch_reference(payload, size=1000):
    url = ("https://api.qrserver.com/v1/create-qr-code/"
           f"?data={urllib.parse.quote(payload)}&size={size}x{size}&format=png&ecc=M&margin=0")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=30).read()


def extract_matrix(png_bytes, tmp_path):
    """把参考 PNG 还原成模块矩阵。

    不靠"最短 run"估模块尺寸（会被抗锯齿骗到，330px 图会误判成版本 78），
    改用自校验：遍历候选版本，谁能还原出合法定位图形就用谁。
    """
    with open(tmp_path, "wb") as f:
        f.write(png_bytes)
    img = Image.open(tmp_path).convert("L")
    w, h = img.size
    px = img.load()

    def sample(modules):
        m = []
        for r in range(modules):
            row = []
            for c in range(modules):
                x = int((c + 0.5) * w / modules)
                y = int((r + 0.5) * h / modules)
                row.append(0 if px[min(x, w - 1), min(y, h - 1)] > 128 else 1)
            m.append(row)
        return m

    def finder_ok(m):
        n = len(m)
        for (r0, c0) in ((0, 0), (0, n - 7), (n - 7, 0)):
            if m[r0][c0] != 1 or m[r0 + 1][c0 + 1] != 0 or m[r0 + 2][c0 + 2] != 1:
                return False
            if m[r0 + 3][c0 + 3] != 1 or m[r0 + 6][c0 + 6] != 1:
                return False
        return True

    for version in range(1, 7):
        modules = version * 4 + 17
        m = sample(modules)
        if finder_ok(m):
            return m, modules, version
    return None, 0, 0


def read_format(matrix):
    """从左上角读出格式信息的 15 位，解析出纠错等级和掩码。"""
    size = len(matrix)
    bits = []
    # 按 ISO 18004 的位序收集（位 0 = LSB）
    coords = [(8, 0), (8, 1), (8, 2), (8, 3), (8, 4), (8, 5), (8, 7), (8, 8),
              (7, 8), (5, 8), (4, 8), (3, 8), (2, 8), (1, 8), (0, 8)]
    for (r, c) in coords:
        bits.append(matrix[r][c])
    value = 0
    for i, b in enumerate(bits):
        value |= (b & 1) << i
    value ^= 0b101010000010010
    data = value >> 10
    ecc = (data >> 3) & 0b11
    mask = data & 0b111
    return ecc, mask


def main():
    import urllib.parse  # noqa: F401  (fetch_reference 用)

    # 用混合大小写+空格的文本，保证标准实现也走字节模式
    # （纯大写+数字会被标准实现改走"字母数字模式"，跟字节模式本就不同，
    #   那种差异不算我的 bug，所以不拿来做逐模块比对）
    payloads = [
        "MollyPaw pairing test 001",
        "mollypaw-online",
        "Hello Molly 2026",
    ]

    tmp = os.path.join(os.environ.get("TEMP", "/tmp"), "qr_ref.png")

    for payload in payloads:
        print(f"\n=== {payload!r} ===")
        try:
            png = fetch_reference(payload)
        except Exception as exc:
            check(f"取参考图 {payload[:16]!r}", False, str(exc))
            continue

        ref, modules, version = extract_matrix(png, tmp)
        if ref is None:
            check(f"{payload[:16]} 能从参考图还原矩阵", False, "采样失败")
            continue
        ecc, mask = read_format(ref)
        print(f"  参考图: {modules}x{modules} 模块 (版本 {version})")
        print(f"  格式信息: 纠错等级码={ecc} 掩码={mask}")

        if not (1 <= version <= myqr.MAX_VERSION):
            check(f"{payload[:16]} 版本在支持范围", False, f"版本 {version}")
            continue

        # 我的编码器强制用同样的版本和掩码
        mine, mv, mm = myqr.encode_matrix(payload, force_version=version, force_mask=mask)
        check(f"{payload[:16]} 我的版本与参考一致", mv == version, f"{mv} vs {version}")

        diff = []
        for r in range(modules):
            for c in range(modules):
                if mine[r][c] != ref[r][c]:
                    diff.append((r, c))
        check(f"{payload[:16]} 逐模块完全一致", not diff,
              f"有 {len(diff)} 处不同，前 10 个: {diff[:10]}")

        if diff:
            print("      参考 vs 我的（前 12 行）:")
            for r in range(min(12, modules)):
                rs = "".join("#" if ref[r][c] else "." for c in range(modules))
                ms = "".join("#" if mine[r][c] else "." for c in range(modules))
                mark = "" if rs == ms else "  <-- 不同"
                print(f"        {rs}   {ms}{mark}")

    print("\n" + "=" * 56)
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    for name, detail in FAIL:
        print(f"  FAIL: {name} :: {detail}")
    print("=" * 56)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
