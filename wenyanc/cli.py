"""命令行入口。"""
from __future__ import annotations

import argparse
import sys

from . import codec, __version__
from .translator import Translator, detect_lang, LANGS, _clean


def _read(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8") as f:
        return f.read()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="wenyanc", description="语义压缩：任意语言 -> 文言文 -> 通用压缩")
    ap.add_argument("--version", action="version", version="wenyanc " + __version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("encode", help="文本 -> .wy")
    e.add_argument("src", help="输入文件，或 - 读 stdin，或直接给一行文本")
    e.add_argument("-o", "--out", help="输出 .wy（默认 stdout.bin）")
    e.add_argument("--algo", default="auto", choices=list(codec.ALGOS))
    e.add_argument("--no-gbk", action="store_true", help="不做 GBK 双字节化")
    e.add_argument("--lang", help="原文语言代码（默认自动识别）")

    d = sub.add_parser("decode", help=".wy -> 文言文（可选还原现代文）")
    d.add_argument("src")
    d.add_argument("-o", "--out")
    d.add_argument("--modern", metavar="LANG", nargs="?", const="", help="再翻译回现代文，可指定语言")

    b = sub.add_parser("bench", help="跑样例，出真实数字")
    b.add_argument("files", nargs="*")
    b.add_argument("--golden", action="store_true",
                   help="用 samples/*.wenyan.txt 里的预翻译文本，不调模型")

    a = ap.parse_args(argv)

    if a.cmd == "encode":
        text = a.src if not __import__("os").path.exists(a.src) else _read(a.src)
        lang = a.lang or detect_lang(text)
        t = Translator()
        wy = t.to_wenyan(text)
        blob = codec.encode(wy, lang, algo=a.algo, use_gbk=not a.no_gbk)
        if a.out:
            with open(a.out, "wb") as f:
                f.write(blob)
            src_n = len(text.encode("utf-8"))
            print(f"{a.src} -> {a.out}  {src_n}B -> {len(blob)}B  ({src_n/max(len(blob),1):.2f}x)  [{lang}/{a.algo}]")
        else:
            sys.stdout.buffer.write(blob)
        return 0

    if a.cmd == "decode":
        with open(a.src, "rb") as f:
            blob = f.read()
        wy, lang = codec.decode(blob)
        wy = _clean(wy)
        out = wy
        if a.modern is not None:
            out = Translator().to_modern(wy, a.modern or lang)
        if a.out:
            with open(a.out, "w", encoding="utf-8") as f:
                f.write(out)
            print(f"{a.src} -> {a.out}  ({len(out)} 字, {LANGS.get(lang, lang)})")
        else:
            print(out)
        return 0

    if a.cmd == "bench":
        from .bench import main as bench_main
        return bench_main(a.files, golden=a.golden)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
