"""二维码编码器自洽性测试：写进矩阵，再读回来，必须一模一样。

上一轮发现：原始数据码字是对的，但把我自己的矩阵反读回来却对不上。
这只有一种可能 —— 放置逻辑和读取逻辑对"哪些格子是数据"判断不一致。

这个脚本逐层定位：
  A. _interleave 的输出是否等于预期（数据段 + 纠错段）
  B. 放进矩阵再读回来，是否等于 _interleave 的输出
  C. 差在哪些格子（是不是功能图形区域被误当数据填了）

用法：.venv\\Scripts\\python.exe tools/selfcheck_qr.py
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


def main():
    payload = b"ABC"
    version = 1
    size = version * 4 + 17
    capacity, blocks, per_block, ec_per_block = myqr.VERSIONS_M[version]

    print(f"版本 {version}: 容量={capacity} 分块={blocks} 每块数据={per_block} 每块纠错={ec_per_block}")

    # --- A. 编码 + 交错 ---
    codewords, b, p = myqr._encode_data(payload, version)
    print(f"\nA. _encode_data -> {len(codewords)} 个码字: {codewords[:18]}")

    final = myqr._interleave(codewords, b, p, ec_per_block)
    print(f"   _interleave -> {len(final)} 个码字: {final}")

    # --- B. 放进矩阵再读回来 ---
    m = myqr._blank_matrix(size)
    reserved = [[False] * size for _ in range(size)]
    myqr._place_finder(m, reserved, 0, 0)
    myqr._place_finder(m, reserved, 0, size - 7)
    myqr._place_finder(m, reserved, size - 7, 0)
    myqr._place_alignment(m, reserved, version)
    myqr._place_timing(m, reserved)
    # 关键：格式信息区必须先保留，否则会被当成数据格
    myqr._reserve_format(reserved, size)

    data_cells = sum(1 for r in range(size) for c in range(size) if not reserved[r][c])
    print(f"\nB. 可用数据格数 = {data_cells}（码字需要 {len(final)}*8 = {len(final)*8} 位）")
    if data_cells != len(final) * 8:
        print(f"   ！！ 格数不符：多出 {data_cells - len(final)*8} 格")

    myqr._place_data(m, reserved, final)

    # --- C. 读回来 ---
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
                bits.append(m[row][c])
        col -= 2
        upward = not upward

    read_back = []
    for i in range(0, len(bits) - 7, 8):
        v = 0
        for bit in bits[i:i + 8]:
            v = (v << 1) | bit
        read_back.append(v)

    print(f"\nC. 读回 {len(read_back)} 个码字: {read_back}")
    if read_back == list(final):
        print("   ✅ 写入/读回一致")
    else:
        print("   ❌ 写入/读回不一致")
        n = min(len(read_back), len(final))
        diffs = [i for i in range(n) if read_back[i] != final[i]]
        print(f"      差异位置: {diffs}")
        for i in diffs[:8]:
            print(f"        [{i}] 写入={final[i]} 读回={read_back[i]}")

    # --- 找差异格子 ---
    if read_back != list(final):
        print("\nD. 差异格子定位：重新逐格对比写入的位与读出的位")
        # 重新放一次并记录每个格子写了什么
        m2 = myqr._blank_matrix(size)
        res2 = [[False] * size for _ in range(size)]
        myqr._place_finder(m2, res2, 0, 0)
        myqr._place_finder(m2, res2, 0, size - 7)
        myqr._place_finder(m2, res2, size - 7, 0)
        myqr._place_alignment(m2, res2, version)
        myqr._place_timing(m2, res2)
        myqr._reserve_format(res2, size)

        want = []
        for cw in final:
            for i in range(7, -1, -1):
                want.append((cw >> i) & 1)

        written = {}
        idx = 0
        upward = True
        col = size - 1
        while col > 0:
            if col == 6:
                col -= 1
                continue
            rows = range(size - 1, -1, -1) if upward else range(size)
            for row in rows:
                for c in (col, col - 1):
                    if res2[row][c]:
                        continue
                    written[(row, c)] = idx
                    idx += 1
            col -= 2
            upward = not upward

        # 找出「写入时跳过、但读回时被当成数据」或反过来的格子
        read_cells = []
        upward = True
        col = size - 1
        while col > 0:
            if col == 6:
                col -= 1
                continue
            rows = range(size - 1, -1, -1) if upward else range(size)
            for row in rows:
                for c in (col, col - 1):
                    if res2[row][c]:
                        continue
                    read_cells.append((row, c))
            col -= 2
            upward = not upward

        write_order = list(written.keys())
        if write_order == read_cells:
            print("   顺序一致 —— 问题不在格子顺序")
        else:
            print("   顺序不一致！")
            for i, (w, r) in enumerate(zip(write_order, read_cells)):
                if w != r:
                    print(f"     第 {i} 格: 写={w} 读={r}")
                    break

    return 0


if __name__ == "__main__":
    sys.exit(main())
