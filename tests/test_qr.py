"""MollyPaw — 二维码编码器测试。

自己写的编码器（agent/relay/qr.py）必须被**独立实现**验证过才算数，
光"看着像二维码"没有意义。

验证链条（三层，都在这里）：
  1. 结构自检：矩阵尺寸 / 定位图形 / 只含 0/1
  2. 自洽性：写进矩阵再读回来，码字必须一模一样，且数据格数 == 码字位数
  3. 与标准实现比对：从 api.qrserver.com 取标准 QR（独立实现），
     指定同版本同掩码后**逐模块比对**

第 3 层是网络依赖，用 pytest.mark.network 标记，默认跑但允许跳过。
（必须联网时用 `-m "not network"` 排除。）

这两层一起抓出过两个真 bug：
  - 格式信息区没有在填数据前 reserved → 数据位整体错位 31 位
  - 格式信息副本 A 的行/列写反 → 4 个位对不上
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.relay import crypto as C
from agent.relay import qr


# --------------------------------------------------------------------------
# 1. 结构自检
# --------------------------------------------------------------------------


def test_matrix_size_matches_version():
    for payload in ("A", "Hello Molly", "x" * 40, "y" * 90):
        matrix, version, mask = qr.encode_matrix(payload)
        assert len(matrix) == len(matrix[0]) == version * 4 + 17


def test_matrix_contains_only_bits():
    matrix, _, _ = qr.encode_matrix("Hello Molly 2026")
    assert all(v in (0, 1) for row in matrix for v in row)


def test_mask_in_valid_range():
    _, _, mask = qr.encode_matrix("Hello")
    assert 0 <= mask <= 7


def test_finder_patterns_correct():
    """三个角的 7x7 定位图形必须正确。"""
    matrix, _, _ = qr.encode_matrix("Hello Molly")
    n = len(matrix)
    for (r0, c0) in ((0, 0), (0, n - 7), (n - 7, 0)):
        # 外框全黑
        for i in range(7):
            assert matrix[r0][c0 + i] == 1
            assert matrix[r0 + 6][c0 + i] == 1
            assert matrix[r0 + i][c0] == 1
            assert matrix[r0 + i][c0 + 6] == 1
        # 次圈全白
        for i in range(1, 6):
            assert matrix[r0 + 1][c0 + i] == 0
            assert matrix[r0 + 5][c0 + i] == 0
        # 中心 3x3 全黑
        for r in range(2, 5):
            for c in range(2, 5):
                assert matrix[r0 + r][c0 + c] == 1


def test_timing_patterns_alternate():
    matrix, version, _ = qr.encode_matrix("Hello Molly 2026")
    n = len(matrix)
    for i in range(8, n - 8):
        expected = 1 if i % 2 == 0 else 0
        assert matrix[6][i] == expected, f"水平时序第 {i} 列"
        assert matrix[i][6] == expected, f"垂直时序第 {i} 行"


def test_version_selection_grows_with_payload():
    small, v_small, _ = qr.encode_matrix("A")
    big, v_big, _ = qr.encode_matrix("z" * 90)
    assert v_small <= v_big


def test_payload_too_large_raises():
    with pytest.raises(ValueError):
        qr.encode_matrix("x" * 500)


def test_force_version_and_mask_are_honoured():
    matrix, version, mask = qr.encode_matrix("Hello", force_version=3, force_mask=5)
    assert version == 3
    assert mask == 5
    assert len(matrix) == 3 * 4 + 17


# --------------------------------------------------------------------------
# 2. 自洽性（写入 / 读回）
# --------------------------------------------------------------------------


def _read_codewords(matrix, version, mask):
    """按规范之字形读回码字（反掩码）。"""
    size = len(matrix)
    reserved = [[False] * size for _ in range(size)]
    m = qr._blank_matrix(size)
    qr._place_finder(m, reserved, 0, 0)
    qr._place_finder(m, reserved, 0, size - 7)
    qr._place_finder(m, reserved, size - 7, 0)
    qr._place_alignment(m, reserved, version)
    qr._place_timing(m, reserved)
    qr._reserve_format(reserved, size)

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
                # 功能图形区不反掩码
                if mask_bit(row, c):
                    bit ^= 1
                bits.append(bit)
        col -= 2
        upward = not upward

    out = []
    for i in range(0, len(bits) - 7, 8):
        value = 0
        for b in bits[i:i + 8]:
            value = (value << 1) | b
        out.append(value)
    return out


@pytest.mark.parametrize("payload", ["ABC", "Hello Molly 2026", "mollypaw"])
def test_data_capacity_is_exact(payload):
    """可用数据格数必须**正好**等于 码字数 × 8。

    这条抓出过最严重的一个 bug：格式信息区没有在填数据前 reserved，
    于是多算了 31 个格，数据位从第一个字开始就整体错位。

    注意版本要用 encode_matrix 实际选中的那个（pick_version 对边界
    长度的判断和 _encode_data 的填充逻辑算的是同一件事，但比对时
    必须以实际产出为准）。
    """
    matrix, version, _mask = qr.encode_matrix(payload)
    _cap, blocks, per_block, ec_per_block = qr.VERSIONS_M[version]
    codewords, _b, _p = qr._encode_data(payload.encode("utf-8"), version)
    final = qr._interleave(codewords, blocks, per_block, ec_per_block)

    size = version * 4 + 17
    reserved = [[False] * size for _ in range(size)]
    m = qr._blank_matrix(size)
    qr._place_finder(m, reserved, 0, 0)
    qr._place_finder(m, reserved, 0, size - 7)
    qr._place_finder(m, reserved, size - 7, 0)
    qr._place_alignment(m, reserved, version)
    qr._place_timing(m, reserved)
    qr._reserve_format(reserved, size)

    cells = sum(1 for r in range(size) for c in range(size) if not reserved[r][c])
    # 规范另有 0~7 个"余位"（REMAINDER_BITS），不属于任何码字
    expected = len(final) * 8 + qr.REMAINDER_BITS[version]
    assert cells == expected, (
        f"版本 {version}: 可用数据格 {cells}，"
        f"码字需要 {len(final) * 8} 位 + 余位 {qr.REMAINDER_BITS[version]} = {expected}"
    )


@pytest.mark.parametrize("payload", ["ABC", "Hello Molly 2026", "mollypaw-online"])
def test_write_read_roundtrip(payload):
    """放进矩阵再读回来，码字必须完全一致。"""
    matrix, version, mask = qr.encode_matrix(payload)
    _cap, blocks, per_block, ec_per_block = qr.VERSIONS_M[version]
    codewords, _b, _p = qr._encode_data(payload.encode("utf-8"), version)
    final = qr._interleave(codewords, blocks, per_block, ec_per_block)

    read_back = _read_codewords(matrix, version, mask)
    assert read_back[:len(final)] == list(final)


def test_encoded_codewords_match_reference_expected():
    """'ABC' 在版本 1 下的数据码字（独立实现也给出这串）。"""
    codewords, _b, _p = qr._encode_data(b"ABC", 1)
    assert codewords[:12] == [64, 52, 20, 36, 48, 236, 17, 236, 17, 236, 17, 236]


def test_reed_solomon_output_is_stable():
    """RS 纠错码字必须稳定（改错会立刻发现）。"""
    codewords, _b, _p = qr._encode_data(b"ABC", 1)
    final = qr._interleave(codewords, 1, 16, 10)
    assert len(final) == 26
    assert final[16:] == [39, 66, 60, 248, 208, 211, 30, 10, 147, 64]


# --------------------------------------------------------------------------
# 3. 与标准实现比对（联网）
# --------------------------------------------------------------------------


@pytest.mark.network
def test_matches_standard_implementation_module_by_module():
    """从独立服务取标准 QR，逐模块比对。

    这是最强的一条：同一个版本、同一个掩码下，
    我的矩阵必须与标准实现**逐位相同**。
    格式信息、掩码变换、数据编码、RS、交错、之字形填充全在里面。
    """
    import urllib.parse
    import urllib.request

    from PIL import Image

    payload = "MollyPaw pairing test 001"
    url = ("https://api.qrserver.com/v1/create-qr-code/"
           f"?data={urllib.parse.quote(payload)}&size=1000x1000&format=png&ecc=M&margin=0")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        png = urllib.request.urlopen(req, timeout=30).read()
    except Exception as exc:
        pytest.skip(f"取标准参考图失败（网络问题）: {exc}")

    import tempfile

    tmp = os.path.join(tempfile.gettempdir(), "qr_ref_test.png")
    with open(tmp, "wb") as f:
        f.write(png)
    img = Image.open(tmp).convert("L")
    w, h = img.size
    px = img.load()

    def sample(modules):
        out = []
        for r in range(modules):
            row = []
            for c in range(modules):
                x = int((c + 0.5) * w / modules)
                y = int((r + 0.5) * h / modules)
                row.append(0 if px[min(x, w - 1), min(y, h - 1)] > 128 else 1)
            out.append(row)
        return out

    def finder_ok(m):
        n = len(m)
        for (r0, c0) in ((0, 0), (0, n - 7), (n - 7, 0)):
            if m[r0][c0] != 1 or m[r0 + 1][c0 + 1] != 0 or m[r0 + 2][c0 + 2] != 1:
                return False
        return True

    ref = None
    version = 0
    for v in range(1, 7):
        m = sample(v * 4 + 17)
        if finder_ok(m):
            ref, version = m, v
            break
    assert ref is not None, "无法从参考图还原模块矩阵"

    size = len(ref)
    # 参考图用的掩码：试所有掩码，能解出原文的那个就是
    from tools.diag.read_qr_reference import deinterleave, decode_payload
    ref_mask = None
    for mask in range(8):
        cws = _read_codewords(ref, version, mask)
        data, _err = decode_payload(cws, version)
        if data is not None and data.decode("utf-8", errors="replace") == payload:
            ref_mask = mask
            break
    assert ref_mask is not None, "无法确定参考图的掩码"

    mine, mv, mm = qr.encode_matrix(payload, force_version=version, force_mask=ref_mask)
    assert mv == version

    diff = [(r, c) for r in range(size) for c in range(size) if mine[r][c] != ref[r][c]]
    assert not diff, f"与标准实现有 {len(diff)} 处不同，前 10 个: {diff[:10]}"


# --------------------------------------------------------------------------
# 配对码
# --------------------------------------------------------------------------


def test_pairing_code_roundtrip():
    seed = os.urandom(C.PAIR_SEED_LEN)
    room = "0123456789abcdef0123456789abcdef"
    code = C.make_pairing_code(seed, room)
    parsed_seed, parsed_room = C.parse_pairing_code(code)
    assert parsed_seed == seed
    assert parsed_room == room


def test_pairing_code_tolerates_whitespace():
    """用户从聊天软件粘贴过来常带空格换行。"""
    seed = os.urandom(C.PAIR_SEED_LEN)
    room = "f" * 32
    code = C.make_pairing_code(seed, room)
    messy = f"  {code[:10]}\n{code[10:]}\n  "
    parsed_seed, parsed_room = C.parse_pairing_code(messy)
    assert parsed_seed == seed
    assert parsed_room == room


def test_pairing_code_rejects_garbage():
    for bad in ("", "hello", "MP1.", "MP1.abc", "MP2.x.y", "MP1.!!!.zz"):
        with pytest.raises(ValueError):
            C.parse_pairing_code(bad)


def test_pairing_code_rejects_wrong_token_length():
    short = C.b64e(os.urandom(16))
    with pytest.raises(ValueError):
        C.parse_pairing_code(f"MP1.{short}.{'a' * 32}")


def test_pairing_code_png_is_declared():
    """配对码必须能被编码成 PNG（供二维码显示）。"""
    seed = os.urandom(C.PAIR_SEED_LEN)
    code = C.make_pairing_code(seed, "0" * 32)
    png = qr.make_png(code)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 200
