"""逐位对比格式信息区：参考图 vs 我的实现。

数据部分已经验证一致（码字完全相同），只剩格式信息区 4 个位对不上。
格式信息只有两处共 30 个位，全部打印出来看是哪几位、差在哪。

用法：.venv\\Scripts\\python.exe tools/diag_qr_format.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from agent.relay import qr as myqr
from tools.read_qr_reference import extract, fetch

# 格式信息两处副本的坐标（按 ISO 18004 §8.9，位序从 0 开始）
#
# 副本 1（左上）的位序：
#   位 0..5  → (8,0) (8,1) (8,2) (8,3) (8,4) (8,5)   沿第 8 行向右，跳过第 6 列
#   位 6     → (8,7)
#   位 7     → (8,8)
#   位 8     → (7,8)
#   位 9..14 → (5,8) (4,8) (3,8) (2,8) (1,8) (0,8)   沿第 8 列向上，跳过第 6 行
#   注意：位 9 对应 (5,8)，**不是** (5,8)→(0,8) 反过来。
#   之前写反了，导致副本1 有 4 个位对不上。
COPY1 = [
    (8, 0), (8, 1), (8, 2), (8, 3), (8, 4), (8, 5),
    (8, 7), (8, 8),
    (7, 8),
    (5, 8), (4, 8), (3, 8), (2, 8), (1, 8), (0, 8),
]
# 副本 2：右上（从右往左）+ 左下（从下往上）；坐标依赖 size，运行时展开
COPY2_B = [(-15 + i, 8) for i in range(8, 15)]


def bits_of(matrix, coords, size):
    out = []
    for (r, c) in coords:
        if c is None:
            c = size - 1
        if r < 0:
            r = size + r
        out.append(matrix[r][c])
    return out


def main():
    payload = "MollyPaw pairing test 001"
    tmp = os.path.join(os.environ.get("TEMP", "/tmp"), "qr_fmt.png")

    png = fetch(payload)
    ref, version = extract(png, tmp)
    if ref is None:
        print("参考图提取失败")
        return 1
    size = len(ref)
    print(f"参考: 版本 {version}, {size}x{size}")

    # 参考图的格式位
    c2a = [(8, size - 1 - i) for i in range(8)]
    c2b = [(size - 15 + i, 8) for i in range(8, 15)]
    ref1 = bits_of(ref, COPY1, size)
    ref2 = bits_of(ref, c2a, size) + bits_of(ref, c2b, size)

    print(f"\n参考 副本1 (左上) = {''.join(map(str, ref1))}")
    print(f"参考 副本2 (右上+左下) = {''.join(map(str, ref2))}")

    # 由参考的两个副本反推它实际用的 (ecc, mask)
    def decode(bits):
        val = 0
        for i, b in enumerate(bits):
            val |= (b & 1) << i
        val ^= 0b101010000010010
        data = val >> 10
        return (data >> 3) & 0b11, data & 0b111

    e1, m1 = decode(ref1)
    e2, m2 = decode(ref2)
    print(f"\n由副本1 反推: ecc码={e1} mask={m1}")
    print(f"由副本2 反推: ecc码={e2} mask={m2}")
    print("（ecc: L=1 M=0 Q=3 H=2）")

    # 我的实现：打印同样的位
    for ecc in (0, 1, 2, 3):
        for mask in (m1,):
            matrix, _v, _m = myqr.encode_matrix(
                payload, force_version=version, force_mask=mask
            )
            # 临时把 ecc 改掉重算格式信息
            myqr.ECC_INDICATOR_M = ecc
            matrix, _v, _m = myqr.encode_matrix(
                payload, force_version=version, force_mask=mask
            )
            my1 = bits_of(matrix, COPY1, size)
            my2 = bits_of(matrix, c2a, size) + bits_of(matrix, c2b, size)
            match1 = "✅" if my1 == ref1 else "❌"
            match2 = "✅" if my2 == ref2 else "❌"
            print(f"\n我的 (ecc={ecc}, mask={mask}):")
            print(f"  副本1 = {''.join(map(str, my1))}  {match1}")
            print(f"  副本2 = {''.join(map(str, my2))}  {match2}")
            if my1 != ref1:
                diff = [i for i in range(15) if my1[i] != ref1[i]]
                print(f"  副本1 差异位: {diff}")

    myqr.ECC_INDICATOR_M = 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
