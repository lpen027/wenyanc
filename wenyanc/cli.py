"""命令行入口。"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

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

    p = sub.add_parser("pack", help="多条记忆打包成一个归档（共享压缩字典）")
    p.add_argument("out", help="输出 .wypack")
    p.add_argument("files", nargs="*", help="文本文件，一个文件一条记忆")
    p.add_argument("--dir", help="扫描目录下所有 .txt（排除 *.wenyan.txt 的重复项可自行控制）")
    p.add_argument("--tag", action="append", default=[], help="给本次全部条目加标签，可重复")

    u = sub.add_parser("unpack", help="归档 -> 单个文本文件")
    u.add_argument("src")
    u.add_argument("-o", "--out", required=True, help="输出目录")

    l = sub.add_parser("list", help="列出归档里的条目")
    l.add_argument("src")
    l.add_argument("--json", action="store_true")

    s = sub.add_parser("search", help="按关键词取回原话")
    s.add_argument("src")
    s.add_argument("keywords", nargs="+")
    s.add_argument("-n", "--limit", type=int, default=5)
    s.add_argument("--all", action="store_true", help="要求全部关键词都命中（默认任一命中即返回，多命中优先）")

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

    if a.cmd == "pack":
        from . import pack as P
        files = list(a.files)
        if a.dir:
            import glob
            files += sorted(glob.glob(os.path.join(a.dir, "*.txt")))
        if not files:
            ap.error("pack 需要文件或 --dir")
        entries = []
        for f in files:
            try:
                txt = _read(f).strip()
            except OSError as exc:
                print(f"跳过 {f}: {exc}", file=sys.stderr)
                continue
            if not txt:
                continue
            entries.append({"text": txt, "lang": detect_lang(txt),
                            "tags": a.tag, "src": os.path.basename(f),
                            "ts": time.strftime("%Y-%m-%dT%H:%M:%S",
                                                time.localtime(os.path.getmtime(f)))})
        info = P.pack(entries, a.out)
        print("打包 %d 条 -> %s" % (info["entries"], a.out))
        print("  文言文流 %d B, 压缩后 %d B (%s), 索引 %d B, 总计 %d B (索引占 %.1f%%)"
              % (info["stream_bytes"], info["payload_bytes"], info["algo"],
                 info["index_bytes"], info["total_bytes"], info["index_pct"]))
        return 0

    if a.cmd == "unpack":
        from . import pack as P
        written = P.unpack(a.src, a.out)
        print("解出 %d 条 -> %s" % (len(written), a.out))
        return 0

    if a.cmd == "list":
        from . import pack as P
        head = P.read_head(a.src)
        if a.json:
            print(json.dumps(head, ensure_ascii=False, indent=2))
        else:
            print("%s  条目 %d  流 %d B  建于 %s"
                  % (a.src, head["count"], head["stream_bytes"], head["created"]))
            for e in head["entries"]:
                print("  %-14s %-4s %5d 字  %s  %s"
                      % (e["id"], e["lang"], e["chars"], e["ts"], ",".join(e["tags"])))
        return 0

    if a.cmd == "search":
        from . import pack as P
        hits = P.search(a.src, a.keywords, mode="all" if a.all else "any")
        if not hits:
            print("无命中：" + " ".join(a.keywords))
            return 0
        for h in hits[:a.limit]:
            print("--- %s  %s  %d 字" % (h["id"], h["ts"], h["chars"]))
            print(h["text"])
        print("\n命中 %d 条，显示 %d 条" % (len(hits), min(len(hits), a.limit)))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
