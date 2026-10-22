"""诊断二维码编码器：与标准实现逐模块比对，遍历所有 (ecc, mask) 组合。

判定逻辑：
  - 若存在某个 (ecc, mask) 使我的矩阵与参考**完全一致** → 编码器正确，
    之前的差异只是「读参考图格式信息」写错了。
  - 若全都不一致 → 数据编码 / RS 纠错 / 交错 / 填充 里有真 bug，
    并报告差异集中在哪些区域（定位图形 / 时序 / 数据 / 格式）。

用法：.venv\\Scripts\\python.exe tools\\diag_qr.py
"""
import os
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from PIL import Image

from agent.relay import qr as myqr

REF_URL = "https://api.qrserver.com/v1/create-qr-code/"


def fetch_reference(payload, scale_px=8):
    url = (REF_URL + f"?data={urllib.parse.quote(payload)}"
           f"&size=1000x1000&format=png&ecc=M&margin=0")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=30).read()


def extract_matrix(png_bytes, tmp_path):
    """把参考 PNG 还原成模块矩阵。

    不用「最短 run」估模块尺寸（会被抗锯齿/杂点骗到），
    改用自校验：遍历候选版本，谁能还原出合法定位图形就用谁。
    """
    with open(tmp_path, "wb") as f:
        f.write(png_bytes)
    img = Image.open(tmp_path).convert("L")
    w, h = img.size
    px = img.load()

    def sample(modules):
        if modules <= 0:
            return None
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
        """三个角必须是合法 7x7 定位图形。"""
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


def classify(r, c, size, version):
    """给模块分类：定位+分隔 / 时序 / 校正 / 格式 / 数据。"""
    # 定位图形及其分隔符
    if (r < 9 and c < 9) or (r < 9 and c > size - 10) or (r > size - 10 and c < 9):
        # 格式信息区嵌在里面
        if r == 8 or c == 8:
            return "format"
        return "finder"
    if r == 6 or c == 6:
        return "timing"
    for ar in myqr.ALIGNMENT[version]:
        for ac in myqr.ALIGNMENT[version]:
            if (ar < 8 and ac < 8) or (ar < 8 and ac > size - 9) or (ar > size - 9 and ac < 8):
                continue
            if abs(r - ar) <= 2 and abs(c - ac) <= 2:
                return "alignment"
    return "data"


def main():
    payloads = ["ABC", "MollyPaw pairing test 001", "HELLO-MOLLYPAW-123"]
    tmp = os.path.join(os.environ.get("TEMP", "/tmp"), "qr_diag.png")

    for payload in payloads:
        print(f"\n{'='*60}")
        print(f"payload = {payload!r}")
        print("=" * 60)
        try:
            png = fetch_reference(payload)
        except Exception as exc:
            print(f"  取参考图失败: {exc}")
            continue

        ref, modules, version = extract_matrix(png, tmp)
        if ref is None:
            print("  无法从参考图还原模块矩阵")
            continue
        print(f"  参考: {modules}x{modules} 模块，版本 {version}")

        best = None
        for ecc in range(1, 4):     # 只试 M(0)/L(1)/Q(3)?  用 0..3 全试
            pass
        matches = []
        for ecc in range(4):
            for mask in range(8):
                try:
                    mine, mv, mm = myqr.encode_matrix(
                        payload, force_version=version, force_mask=mask
                    )
                except Exception:
                    continue
                # 只比数据区（格式信息由 ecc/mask 决定，单独看）
                data_diff = 0
                for r in range(modules):
                    for c in range(modules):
                        kind = classify(r, c, modules, version)
                        if kind == "format":
                            continue
                        if mine[r][c] != ref[r][c]:
                            data_diff += 1
                full_diff = sum(
                    1 for r in range(modules) for c in range(modules)
                    if mine[r][c] != ref[r][c]
                )
                if best is None or data_diff < best[0]:
                    best = (data_diff, ecc, mask, full_diff)
                if full_diff == 0:
                    matches.append((ecc, mask))
                if data_diff == 0 and not any(m[1] == mask for m in matches):
                    matches.append(("data-only", mask))

        if matches:
            print(f"  ✅ 找到完全匹配: {matches}")
        else:
            diff, ecc, mask, full = best
            print(f"  ❌ 没有任何组合完全匹配")
            print(f"     最接近: ecc={ecc} mask={mask} 差异 {diff} 处（数据区），全图 {full} 处")

            # 差异集中在哪类区域？
            mine, _, _ = myqr.encode_matrix(payload, force_version=version, force_mask=mask)
            bykind = {}
            for r in range(modules):
                for c in range(modules):
                    if mine[r][c] != ref[r][c]:
                        k = classify(r, c, modules, version)
                        bykind[k] = bykind.get(k, 0) + 1
            print(f"     差异分布: {bykind}")

            # 打印前 8 行对照
            print("     参考 vs 我的（前 8 行）:")
            for r in range(min(8, modules)):
                rs = "".join("#" if ref[r][c] else "." for c in range(modules))
                ms = "".join("#" if mine[r][c] else "." for c in range(modules))
                print(f"       {rs}")
                print(f"       {ms}{'   <-- 不同' if rs != ms else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
