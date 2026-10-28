"""wenyanc bench —— 量出真实的语义密度与体积，不靠形容词。

对每个样例输出：
  原文 chars / 文言文 chars        -> 语义密度倍数
  原文 UTF-8 bytes                  -> 基线体积
  原文直接 lzma                     -> 对照组（同样算法压原文）
  文言文 GBK+lzma（.wy）            -> 本方案体积
  .wy 相对基线的倍数                -> 对外宣传的那个数
"""
from __future__ import annotations

import json
import os
import sys

from . import codec
from .translator import Translator, detect_lang

SAMPLE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples")


def bench_one(t: Translator, name: str, text: str, wenyan: str | None = None) -> dict:
    lang = detect_lang(text)
    if wenyan is None:
        wenyan = t.to_wenyan(text)
    if not wenyan:
        return {"sample": name, "lang": lang, "error": "empty translation"}

    m_src = codec.measure(text)
    m_wy = codec.measure(wenyan)
    ctrl = len(codec.encode(text, lang, algo="lzma", use_gbk=False))      # 同样算法压原文
    wy_gbk = len(codec.encode(wenyan, lang, algo="lzma", use_gbk=True))    # 本方案
    wy_utf8 = len(codec.encode(wenyan, lang, algo="lzma", use_gbk=False))

    return {
        "sample": name,
        "lang": lang,
        "src_chars": m_src["chars"],
        "src_utf8": m_src["utf8"],
        "wenyan_chars": m_wy["chars"],
        "density": round(m_src["chars"] / max(m_wy["chars"], 1), 2),
        "ctrl_lzma": ctrl,
        "wy_lzma_utf8": wy_utf8,
        "wy_size": wy_gbk,
        "vs_src": round(m_src["utf8"] / max(wy_gbk, 1), 2),
        "vs_ctrl": round(ctrl / max(wy_gbk, 1), 2),
        "wenyan": wenyan,
    }


def main(argv=None, files=None, golden: bool = False):
    argv = list(sys.argv[1:] if argv is None else argv)
    t = Translator()
    files = files or argv or sorted(
        os.path.join(SAMPLE_DIR, f) for f in os.listdir(SAMPLE_DIR)
        if f.endswith(".txt") and not f.endswith(".wenyan.txt")
    )
    rows = []
    for path in files:
        name = os.path.basename(path)
        with open(path, encoding="utf-8") as f:
            text = f.read().strip()
        wy = None
        if golden:
            wy_path = os.path.splitext(path)[0] + ".wenyan.txt"
            with open(wy_path, encoding="utf-8") as f:
                wy = f.read().strip()
        sys.stderr.write(f"[bench] {name} ...\n")
        sys.stderr.flush()
        row = bench_one(t, name, text, wy)
        rows.append(row)
        if "error" not in row:
            sys.stderr.write("  density %.2fx  size %.2fx vs src  %.2fx vs ctrl\n"
                             % (row["density"], row["vs_src"], row["vs_ctrl"]))

    ok = [r for r in rows if "error" not in r]
    print(json.dumps(rows, ensure_ascii=False, indent=2))

    out = os.path.join(os.path.dirname(SAMPLE_DIR), "bench_result.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    if ok:
        print("\n=== 汇总（%d/%d 段成功）===" % (len(ok), len(rows)))
        print(f"{'sample':22} {'lang':5} {'src':>6} {'wy':>6} {'den':>6} {'ctrl':>6} {'wy.wy':>7} {'x_src':>6} {'x_ctrl':>6}")
        for r in ok:
            print(f"{r['sample'][:22]:22} {r['lang']:5} {r['src_chars']:6} {r['wenyan_chars']:6} "
                  f"{r['density']:6.2f} {r['ctrl_lzma']:6} {r['wy_size']:7} {r['vs_src']:6.2f} {r['vs_ctrl']:6.2f}")
        print("\n平均：密度 %.2fx，相对原文 %.2fx，相对同算法直接压缩 %.2fx"
              % (sum(r["density"] for r in ok) / len(ok),
                 sum(r["vs_src"] for r in ok) / len(ok),
                 sum(r["vs_ctrl"] for r in ok) / len(ok)))
    print("\n结果写入 " + out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
