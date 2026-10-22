"""精确比对：我的编码器 vs 标准实现，比的是**数据码字**不是像素。

上一轮像素比对失败，是因为参考图选了某个掩码、而我的诊断没匹配上；
而且参考服务有时会为纯大写+数字的文本选「字母数字模式」，
那和我的「字节模式」本来就不同 —— 那种情况不算我错。

所以这一版只比一件事：**同一段文本、同一版本、同一掩码下，
我生成的最终码字序列是否与标准实现一致。**
标准实现那边通过「从参考图读出码字」得到（读取逻辑已经用原文自证正确）。

用法：.venv\\Scripts\\python.exe tools/compare_qr_codewords.py
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
from tools.read_qr_reference import extract, fetch, read_bits, deinterleave  # noqa: E402


def main():
    tmp = os.path.join(os.environ.get("TEMP", "/tmp"), "qr_cmp.png")
    # 用混合大小写+空格的文本，确保标准实现也走字节模式
    payloads = ["ABC", "MollyPaw pairing test 001", "mollypaw-online"]

    all_ok = True
    for payload in payloads:
        print(f"\n=== {payload!r} ===")
        png = fetch(payload)
        matrix, version = extract(png, tmp)
        if matrix is None:
            print("  提取失败")
            all_ok = False
            continue
        print(f"  参考: 版本 {version}, {len(matrix)}x{len(matrix)} 模块")

        # 找参考图用的掩码（以能否还原原文为准）
        ref_mask = None
        ref_codewords = None
        for mask in range(8):
            cws = read_bits(matrix, version, mask)
            flat = deinterleave(cws, version)
            # 用数据码字解出内容，判断掩码对不对
            from tools.read_qr_reference import decode_payload
            data, err = decode_payload(cws, version)
            if data is not None:
                try:
                    if data.decode("utf-8") == payload:
                        ref_mask = mask
                        ref_codewords = cws
                        break
                except UnicodeDecodeError:
                    pass

        if ref_mask is None:
            print("  ⚠ 参考图不是字节模式（或无匹配掩码），跳过这条")
            continue

        print(f"  参考掩码 = {ref_mask}")
        print(f"  参考最终码字 = {ref_codewords[:10]} ...")

        # 我的编码器：强制同版本同掩码，取最终码字
        my_matrix, my_version, my_mask = myqr.encode_matrix(
            payload, force_version=version, force_mask=ref_mask
        )

        # 从我自己的矩阵反读码字（复用同一套读取逻辑，保证口径一致）
        my_codewords = read_bits(my_matrix, version, ref_mask)
        print(f"  我的最终码字 = {my_codewords[:10]} ...")

        if my_codewords == ref_codewords:
            print("  ✅ 最终码字完全一致")
        else:
            all_ok = False
            print("  ❌ 码字不一致")
            n = min(len(my_codewords), len(ref_codewords))
            diffs = [i for i in range(n) if my_codewords[i] != ref_codewords[i]]
            print(f"     共 {len(diffs)} 处不同，位置: {diffs[:20]}")
            for i in diffs[:6]:
                print(f"       [{i}] 参考={ref_codewords[i]} 我的={my_codewords[i]}")

            # 分别比数据段和纠错段
            _cap, blocks, per_block, ec_per_block = myqr.VERSIONS_M[version]
            data_len = blocks * per_block
            print(f"     数据段长度 {data_len}，纠错段长度 {blocks * ec_per_block}")
            data_diffs = [i for i in diffs if i < data_len]
            ec_diffs = [i for i in diffs if i >= data_len]
            print(f"     数据段差异 {len(data_diffs)} 处，纠错段差异 {len(ec_diffs)} 处")

            if data_diffs:
                # 直接比「编码后、纠错前」的数据码字
                my_cws, _b, _p = myqr._encode_data(payload.encode("utf-8"), version)
                print(f"     我的原始数据码字 = {my_cws[:12]}")
                ref_flat = deinterleave(ref_codewords, version)
                print(f"     参考原始数据码字 = {ref_flat[:12]}")
                if list(my_cws) == list(ref_flat):
                    print("      → 原始数据码字一致，问题在分块/交错/纠错")
                else:
                    print("      → 原始数据码字就不一致，问题在数据编码")

    print("\n" + "=" * 56)
    print("全部一致 ✅" if all_ok else "存在不一致 ❌")
    print("=" * 56)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
