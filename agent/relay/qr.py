"""MollyPaw — 极简二维码编码器（零依赖）。

为什么自己写：系统里没有 qrcode/segno，而为了显示一个配对码去装一个
新依赖不划算。算法是公开标准（ISO/IEC 18004），实现清楚就行。

支持范围（够配对码用，不追求全规格）：
  - 字节模式（byte mode）
  - 纠错等级 M
  - 版本 1..6（最多 108 个数据码字，足够装下 MP1.<44>.<32> 的配对码）
  - 自动选版本、自动选最优掩码

不支持：数字/字母数字模式、版本 7+、版本信息块、结构化追加。
这些配对码都用不到，硬塞进来只会增加出错面。

验证方式：tools/verify_qr.py 用 Edge 内置的 BarcodeDetector 把生成的图
解回来，比对原文 —— 自己写的编码器必须能被标准解码器读懂才算数。
"""
import io

# ---------------------------------------------------------------------------
# 版本参数（仅纠错等级 M）
# ---------------------------------------------------------------------------
# (数据码字总数, 分块数, 每块数据码字, 每块纠错码字)
# 版本 1..6 在等级 M 下每块大小相同，所以分块逻辑很简单。
VERSIONS_M = {
    1: (16, 1, 16, 10),
    2: (28, 1, 28, 16),
    3: (44, 1, 44, 26),
    4: (64, 2, 32, 18),
    5: (86, 2, 43, 24),
    6: (108, 4, 27, 16),
}

MAX_VERSION = 6

# 余位（remainder bits）：ISO/IEC 18004 规定某些版本在最后一个码字之后
# 还有几个不属于任何码字的空位，用 0 填充。表格：
#   版本 1      : 0
#   版本 2..6   : 7
#   版本 7..13  : 0
#   版本 14..20 : 3
#   版本 21..27 : 4
#   版本 28..34 : 3
#   版本 35..40 : 0
# 所以「可用数据格数」= 码字位数 + 余位数。少了这一项，
# 版本 2 会算成差 7 格，看起来像 bug（实际是规范如此）。
REMAINDER_BITS = {1: 0, 2: 7, 3: 7, 4: 7, 5: 7, 6: 7}

# 每个版本的校正图形中心坐标
ALIGNMENT = {
    1: [],
    2: [6, 18],
    3: [6, 22],
    4: [6, 26],
    5: [6, 30],
    6: [6, 34],
}

ECC_INDICATOR_M = 0b00  # 等级 M 在格式信息里的两位


def _size(version):
    return version * 4 + 17


# ---------------------------------------------------------------------------
# GF(256) 运算（Reed-Solomon 用）
# ---------------------------------------------------------------------------

_PRIM = 0x11D
_EXP = [0] * 512
_LOG = [0] * 256


def _init_tables():
    x = 1
    for i in range(255):
        _EXP[i] = x
        _LOG[x] = i
        x <<= 1
        if x & 0x100:
            x ^= _PRIM
    for i in range(255, 512):
        _EXP[i] = _EXP[i - 255]


_init_tables()


def _gf_mul(a, b):
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _rs_generator(degree):
    """生成多项式 (x - a^0)(x - a^1)...(x - a^(degree-1))。"""
    poly = [1]
    for i in range(degree):
        new = [0] * (len(poly) + 1)
        for j, coef in enumerate(poly):
            new[j] ^= coef
            new[j + 1] ^= _gf_mul(coef, _EXP[i])
        poly = new
    return poly


def _rs_encode(data, ec_len):
    """对 data 做 RS 纠错编码，返回 ec_len 个纠错码字。"""
    gen = _rs_generator(ec_len)
    remainder = list(data) + [0] * ec_len
    for i in range(len(data)):
        coef = remainder[i]
        if coef == 0:
            continue
        for j in range(len(gen)):
            remainder[i + j] ^= _gf_mul(gen[j], coef)
    return remainder[len(data):]


# ---------------------------------------------------------------------------
# 位流
# ---------------------------------------------------------------------------


class _Bits:
    def __init__(self):
        self.bits = []

    def put(self, value, length):
        for i in range(length - 1, -1, -1):
            self.bits.append((value >> i) & 1)

    def __len__(self):
        return len(self.bits)


def _encode_data(data, version):
    """字节模式编码：模式指示符 + 长度 + 数据 + 终止符 + 填充。"""
    capacity, blocks, per_block, _ec = VERSIONS_M[version]
    total_bits = capacity * 8

    bits = _Bits()
    bits.put(0b0100, 4)                 # 字节模式
    # 版本 1..9 的字符计数指示符是 8 位
    bits.put(len(data), 8)
    for byte in data:
        bits.put(byte, 8)

    if len(bits) > total_bits:
        raise ValueError("data too large for version")

    # 终止符（最多 4 个 0）
    remaining = total_bits - len(bits)
    bits.put(0, min(4, remaining))

    # 补齐到字节边界
    while len(bits) % 8:
        bits.put(0, 1)

    # 填充码字 0xEC / 0x11 交替
    codewords = []
    for i in range(0, len(bits.bits), 8):
        value = 0
        for bit in bits.bits[i:i + 8]:
            value = (value << 1) | bit
        codewords.append(value)

    pad = [0xEC, 0x11]
    index = 0
    while len(codewords) < capacity:
        codewords.append(pad[index % 2])
        index += 1

    return codewords, blocks, per_block


def _interleave(codewords, blocks, per_block, ec_per_block):
    """分块 -> 各自 RS -> 交错。"""
    data_blocks = []
    ec_blocks = []
    for b in range(blocks):
        chunk = codewords[b * per_block:(b + 1) * per_block]
        data_blocks.append(chunk)
        ec_blocks.append(_rs_encode(chunk, ec_per_block))

    out = []
    for i in range(per_block):
        for block in data_blocks:
            out.append(block[i])
    for i in range(ec_per_block):
        for block in ec_blocks:
            out.append(block[i])
    return out


# ---------------------------------------------------------------------------
# 矩阵
# ---------------------------------------------------------------------------


def _blank_matrix(size):
    return [[None] * size for _ in range(size)]


def _place_finder(m, reserved, row, col):
    """7x7 定位图形 + 分隔符。"""
    size = len(m)
    for r in range(-1, 8):
        for c in range(-1, 8):
            rr, cc = row + r, col + c
            if not (0 <= rr < size and 0 <= cc < size):
                continue
            reserved[rr][cc] = True
            if 0 <= r <= 6 and 0 <= c <= 6:
                edge = r in (0, 6) or c in (0, 6)
                core = 2 <= r <= 4 and 2 <= c <= 4
                m[rr][cc] = 1 if (edge or core) else 0


def _place_alignment(m, reserved, version):
    centers = ALIGNMENT[version]
    size = len(m)
    for r in centers:
        for c in centers:
            # 跳过与定位图形重叠的三个角
            if (r < 8 and c < 8) or (r < 8 and c > size - 9) or (r > size - 9 and c < 8):
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    rr, cc = r + dr, c + dc
                    reserved[rr][cc] = True
                    edge = max(abs(dr), abs(dc))
                    m[rr][cc] = 0 if edge == 1 else 1


def _place_timing(m, reserved):
    size = len(m)
    for i in range(8, size - 8):
        if not reserved[6][i]:
            m[6][i] = 1 if i % 2 == 0 else 0
            reserved[6][i] = True
        if not reserved[i][6]:
            m[i][6] = 1 if i % 2 == 0 else 0
            reserved[i][6] = True


def _place_format(m, reserved, mask):
    """格式信息：5 位数据 + 10 位 BCH，再异或掩码 0x5412。

    位序是 QR 规范里最容易写错的细节（ISO/IEC 18004 §8.9）。
    它一共放两份，两份的**走法完全不同**：

      副本 A（左上，沿"列 8"向上 + 沿"行 8"向左）：
        位 0..5   → (0,8) (1,8) (2,8) (3,8) (4,8) (5,8)
        位 6      → (7,8)          跳过第 6 行（时序）
        位 7      → (8,8)
        位 8      → (8,7)          跳过第 6 列（时序）
        位 9..14  → (8,5) (8,4) (8,3) (8,2) (8,1) (8,0)

      副本 B（右上 + 左下）：
        位 0..7   → (8,size-1) (8,size-2) ... (8,size-8)
        位 8..14  → (size-7,8) (size-6,8) ... (size-1,8)

    之前把 A 的"行/列"写反了（把列 8 的位放到行 8 上），
    导致与标准实现比对时恰好 4 个位对不上。
    """
    size = len(m)
    data = (ECC_INDICATOR_M << 3) | mask

    # BCH(15,5)，生成多项式 0b10100110111
    rem = data << 10
    gen = 0b10100110111
    for i in range(14, 9, -1):
        if (rem >> i) & 1:
            rem ^= gen << (i - 10)
    bits = ((data << 10) | rem) ^ 0b101010000010010

    def bit(i):
        return (bits >> i) & 1

    def put(r, c, i):
        m[r][c] = bit(i)
        reserved[r][c] = True

    # --- 副本 A：左上 ---
    for i in range(6):
        put(i, 8, i)          # 位 0..5 沿第 8 列向下
    put(7, 8, 6)              # 位 6，跳过第 6 行
    put(8, 8, 7)              # 位 7
    put(8, 7, 8)              # 位 8，跳过第 6 列
    for i in range(9, 15):
        put(8, 14 - i, i)     # 位 9..14 → 列 5,4,3,2,1,0

    # --- 副本 B：右上（沿第 8 行从右往左）---
    for i in range(8):
        put(8, size - 1 - i, i)

    # --- 副本 B：左下（沿第 8 列从下往上）---
    for i in range(8, 15):
        put(size - 15 + i, 8, i)

    # 固定暗模块
    m[size - 8][8] = 1
    reserved[size - 8][8] = True


def _reserve_format(reserved, size):
    """把格式信息占用的格子标记为保留（内容稍后再填）。

    必须**在填数据之前**调用。之前是填完数据才放格式信息，
    结果格式区没被 reserved，被当成数据格填了 31 位，
    数据位全部错位 —— 这就是与标准实现比对不上的根因。
    """
    # 左上角的格式信息（含暗模块）
    for i in range(9):
        reserved[8][i] = True
        reserved[i][8] = True
    # 右上角
    for i in range(8):
        reserved[8][size - 1 - i] = True
    # 左下角
    for i in range(8):
        reserved[size - 1 - i][8] = True
    # 固定暗模块
    reserved[size - 8][8] = True


def _place_data(m, reserved, codewords):
    """从右下角开始之字形填数据，跳过第 6 列（时序）。

    调用前必须先调用 _reserve_format，否则格式区会被当成数据填。
    如果码字位数没铺满所有可填格，剩余格子显式写 0 ——
    否则矩阵里会留 None，后面的掩码和罚分计算全崩。
    """
    size = len(m)
    bits = []
    for cw in codewords:
        for i in range(7, -1, -1):
            bits.append((cw >> i) & 1)

    index = 0
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
                m[row][c] = bits[index] if index < len(bits) else 0
                index += 1
        col -= 2
        upward = not upward

    # 兜底：任何仍是 None 的格子补 0，保证矩阵只含 0/1
    for r in range(size):
        for c in range(size):
            if m[r][c] is None:
                m[r][c] = 0


def _apply_mask(m, reserved, mask):
    size = len(m)
    out = [row[:] for row in m]
    for r in range(size):
        for c in range(size):
            if reserved[r][c]:
                continue
            if mask == 0:
                inv = (r + c) % 2 == 0
            elif mask == 1:
                inv = r % 2 == 0
            elif mask == 2:
                inv = c % 3 == 0
            elif mask == 3:
                inv = (r + c) % 3 == 0
            elif mask == 4:
                inv = (r // 2 + c // 3) % 2 == 0
            elif mask == 5:
                inv = (r * c) % 2 + (r * c) % 3 == 0
            elif mask == 6:
                inv = ((r * c) % 2 + (r * c) % 3) % 2 == 0
            else:
                inv = ((r + c) % 2 + (r * c) % 3) % 2 == 0
            if inv:
                out[r][c] ^= 1
    return out


def _penalty(m):
    """ISO/IEC 18004 的四条掩码罚分规则。分数越低越好。"""
    size = len(m)
    score = 0

    # 规则 1：同色连续 >= 5
    for line in list(m) + [list(col) for col in zip(*m)]:
        run = 1
        for i in range(1, size):
            if line[i] == line[i - 1]:
                run += 1
            else:
                if run >= 5:
                    score += 3 + (run - 5)
                run = 1
        if run >= 5:
            score += 3 + (run - 5)

    # 规则 2：2x2 同色块
    for r in range(size - 1):
        for c in range(size - 1):
            v = m[r][c]
            if v == m[r][c + 1] == m[r + 1][c] == m[r + 1][c + 1]:
                score += 3

    # 规则 3：出现 1:1:3:1:1 的定位图形样式
    pattern_a = [1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0]
    pattern_b = [0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1]
    for line in list(m) + [list(col) for col in zip(*m)]:
        for i in range(size - 10):
            seg = line[i:i + 11]
            if seg == pattern_a or seg == pattern_b:
                score += 40

    # 规则 4：黑色比例偏离 50%
    dark = sum(sum(row) for row in m)
    ratio = dark * 100 // (size * size)
    score += 10 * (abs(ratio - 50) // 5)

    return score


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------


def pick_version(data_len):
    for version in range(1, MAX_VERSION + 1):
        capacity = VERSIONS_M[version][0]
        # 4 位模式 + 8 位长度 = 12 位；能装下的字节数 = capacity - 2
        if data_len <= capacity - 2:
            return version
    raise ValueError(f"data too long ({data_len} bytes) for version <= {MAX_VERSION}")


def encode_matrix(data, force_version=None, force_mask=None):
    """把文本/字节编码成 0/1 矩阵（未加安静区）。

    force_version / force_mask 用于测试：允许强制指定版本与掩码，
    这样才能和标准实现生成的参考图做**逐模块比对**
    （同一段文本有多个合法输出，不固定这两项就没法逐位比）。
    """
    if isinstance(data, str):
        data = data.encode("utf-8")
    version = force_version if force_version else pick_version(len(data))
    capacity, blocks, per_block, ec_per_block = VERSIONS_M[version]

    codewords, blocks, per_block = _encode_data(data, version)
    final = _interleave(codewords, blocks, per_block, ec_per_block)

    size = _size(version)
    m = _blank_matrix(size)
    reserved = [[False] * size for _ in range(size)]

    _place_finder(m, reserved, 0, 0)
    _place_finder(m, reserved, 0, size - 7)
    _place_finder(m, reserved, size - 7, 0)
    _place_alignment(m, reserved, version)
    _place_timing(m, reserved)
    # 必须先把格式信息区保留出来，再填数据 —— 顺序反了数据位会错位
    _reserve_format(reserved, size)
    _place_data(m, reserved, final)

    if force_mask is not None:
        candidate = _apply_mask(m, reserved, force_mask)
        _place_format(candidate, [row[:] for row in reserved], force_mask)
        return candidate, version, force_mask

    # 选罚分最低的掩码
    best = None
    for mask in range(8):
        candidate = _apply_mask(m, reserved, mask)
        _place_format(candidate, [row[:] for row in reserved], mask)
        score = _penalty(candidate)
        if best is None or score < best[0]:
            best = (score, candidate, mask)

    return best[1], version, best[2]


def matrix_to_png(matrix, scale=8, border=4, dark=(58, 42, 26), light=(255, 248, 240)):
    """把矩阵渲染成 PNG 字节。默认用品牌色（摩尼黑 / 米白）。"""
    from PIL import Image

    size = len(matrix)
    total = (size + border * 2) * scale
    img = Image.new("RGB", (total, total), light)
    pixels = img.load()
    for r in range(size):
        for c in range(size):
            if not matrix[r][c]:
                continue
            y0 = (r + border) * scale
            x0 = (c + border) * scale
            for y in range(y0, y0 + scale):
                for x in range(x0, x0 + scale):
                    pixels[x, y] = dark
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_png(data, scale=8, border=4):
    matrix, _version, _mask = encode_matrix(data)
    return matrix_to_png(matrix, scale=scale, border=border)
