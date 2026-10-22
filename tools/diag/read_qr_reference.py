"""从参考图里把数据位读出来，看能否还原原文。

这是判断"到底谁错了"的关键一步：
  - 如果能从参考图还原出原文 → 参考图提取正确，错在我的编码器。
  - 如果还原不出来 → 我的提取（采样）有问题，先修提取再谈比对。

只实现「读取」这一小段（字节模式 + 等级 M + 版本 1..6），
不实现纠错解码 —— 数据正确时 RS 校验位不该用上。

用法：.venv\\Scripts\\python.exe tools/read_qr_reference.py
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


def fetch(payload, size=1000):
    url = (REF_URL + f"?data={urllib.parse.quote(payload)}"
           f"&size={size}x{size}&format=png&ecc=M&margin=0")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=30).read()


def extract(png, tmp_path):
    with open(tmp_path, "wb") as f:
        f.write(png)

    img = Image.open(tmp_path).convert("L")
    w, h = img.size
    px = img.load()

    def finder_ok(m):
        n = len(m)
        for (r0, c0) in ((0, 0), (0, n - 7), (n - 7, 0)):
            if m[r0][c0] != 1 or m[r0 + 6][c0 + 6] != 1:
                return False
            if m[r0 + 1][c0 + 1] != 0 or m[r0 + 5][c0 + 5] != 0:
                return False
            if m[r0 + 3][c0 + 3] != 1:
                return False
        return True

    for version in range(1, 7):
        n = version * 4 + 17
        m = [[0] * n for _ in range(n)]
        for r in range(n):
            for c in range(n):
                x = int((c + 0.5) * w / n)
                y = int((r + 0.5) * h / n)
                m[r][c] = 0 if px[min(x, w - 1), min(y, h - 1)] > 128 else 1
        if finder_ok(m):
            return m, version
    return None, 0


def build_reserved(version):
    """算出哪些位置是功能图形（不参与数据）。"""
    size = version * 4 + 17
    reserved = [[False] * size for _ in range(size)]
    m = myqr._blank_matrix(size)

    myqr._place_finder(m, reserved, 0, 0)
    myqr._place_finder(m, reserved, 0, size - 7)
    myqr._place_finder(m, reserved, size - 7, 0)
    myqr._place_alignment(m, reserved, version)
    myqr._place_timing(m, reserved)
    # 格式信息 + 暗模块的位置
    for i in range(9):
        reserved[8][i] = True
        reserved[i][8] = True
    for i in range(8):
        reserved[8][size - 1 - i] = True
    for i in range(8):
        reserved[size - 1 - i][8] = True
    reserved[size - 8][8] = True
    return reserved, size


def read_bits(matrix, version, mask):
    """按之字形读出数据位，返回码字列表。"""
    reserved, size = build_reserved(version)

    # 先反掩码
    def mask_bit(r, c):
        if mask == 0:
            return (r + c) % 2 == 0
        if mask == 1:
            return r % 2 == 0
        if mask == 2:
            return c % 3 == 0
        if mask == 3:
            return (r + c) % 3 == 0
        if mask == 4:
            return (r // 2 + c // 3) % 2 == 0
        if mask == 5:
            return (r * c) % 2 + (r * c) % 3 == 0
        if mask == 6:
            return ((r * c) % 2 + (r * c) % 3) % 2 == 0
        return ((r + c) % 2 + (r * c) % 3) % 2 == 0

    bits = []
    upward = True
    col = size - 1
    while col > 0:
        if col == 6:
            col -= 1
            continue
        rows = range(size - 1, -1, -1) if upward else range(size)
        for row in rows:
            for c in (col, col - 1):
                if reserved[row][c]:
                    continue
                bit = matrix[row][c]
                if mask_bit(row, c):
                    bit ^= 1
                bits.append(bit)
        col -= 2
        upward = not upward

    codewords = []
    for i in range(0, len(bits) - 7, 8):
        value = 0
        for b in bits[i:i + 8]:
            value = (value << 1) | b
        codewords.append(value)
    return codewords


def deinterleave(codewords, version):
    """把交错的数据码字还原成原始顺序。"""
    _cap, blocks, per_block, ec_per_block = myqr.VERSIONS_M[version]
    data_blocks = [[] for _ in range(blocks)]
    # 数据码字：逐列取
    idx = 0
    for i in range(per_block):
        for b in range(blocks):
            if idx < len(codewords):
                data_blocks[b].append(codewords[idx])
                idx += 1
    # 按块顺序拼回
    flat = []
    for b in range(blocks):
        flat.extend(data_blocks[b])
    return flat


def decode_payload(codewords, version):
    """从数据码字解出字节模式的内容。"""
    flat = deinterleave(codewords, version)
    bits = []
    for cw in flat:
        for i in range(7, -1, -1):
            bits.append((cw >> i) & 1)

    pos = 0

    def take(n):
        nonlocal pos
        v = 0
        for _ in range(n):
            if pos < len(bits):
                v = (v << 1) | bits[pos]
            pos += 1
        return v

    mode = take(4)
    if mode != 0b0100:
        return None, f"模式不是字节模式（0b{mode:04b}）"
    length = take(8)
    data = bytes(take(8) for _ in range(length))
    return data, None


def main():
    tmp = os.path.join(os.environ.get("TEMP", "/tmp"), "qr_read.png")
    payloads = ["ABC", "MollyPaw pairing test 001", "HELLO-MOLLYPAW-123"]

    for payload in payloads:
        print(f"\n=== {payload!r} ===")
        png = fetch(payload)
        matrix, version = extract(png, tmp)
        if matrix is None:
            print("  提取失败")
            continue
        print(f"  提取出 {len(matrix)}x{len(matrix)} 模块，版本 {version}")

        found = False
        for mask in range(8):
            cws = read_bits(matrix, version, mask)
            data, err = decode_payload(cws, version)
            if data is None:
                continue
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                continue
            if text == payload:
                print(f"  ✅ mask={mask} 还原出原文: {text!r}")
                print(f"     数据码字前 12 个: {cws[:12]}")
                found = True
                break
            else:
                print(f"     mask={mask} 解出 {text[:40]!r}（不匹配）")

        if not found:
            print("  ❌ 无法从参考图还原原文 —— 说明我的提取/读取有问题")

    return 0


if __name__ == "__main__":
    sys.exit(main())
