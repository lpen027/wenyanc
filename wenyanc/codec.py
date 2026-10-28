"""codec —— 文言文文本 <-> .wy 字节流，无损。

为什么用通用压缩算法：文言文同字多、虚词重复率高、字表窄，
LZMA 的字典匹配天然吃这种冗余，不需要专用模型。

可选 GBK 双字节化：UTF-8 下每个汉字占 3 字节，GBK 占 2 字节，
直接砍掉 1/3 体积（生僻字自动回退 UTF-8）。

容器格式::

    magic  b"WY1\\0"                4
    algo   u8  0=raw 1=zlib 2=lzma  1
    flags  u8  bit0=gbk             1
    langl  u8                       1
    lang   langl bytes              变长
    rawlen u32 (文言文原始字节数)    4
    payload                         变长
"""
from __future__ import annotations

import lzma
import struct
import zlib

MAGIC = b"WY1\0"
FLAG_GBK = 1
ALGOS = {"raw": 0, "zlib": 1, "lzma": 2, "auto": 3}
ALGO_NAMES = {0: "raw", 1: "zlib", 2: "lzma"}


def _to_bytes(text: str, use_gbk: bool) -> tuple[bytes, int]:
    if use_gbk:
        try:
            return text.encode("gbk"), FLAG_GBK
        except UnicodeEncodeError:
            pass
    return text.encode("utf-8"), 0


def encode(text: str, lang: str = "zh", algo: str = "auto", use_gbk: bool = True) -> bytes:
    raw, flags = _to_bytes(text, use_gbk)
    if algo == "auto":
        # 小文本 lzma 的头部与字典开销不划算，直接比长度取小者
        cands = [("raw", raw), ("zlib", zlib.compress(raw, 9)),
                 ("lzma", lzma.compress(raw, preset=9 | lzma.PRESET_EXTREME))]
        algo, payload = min(cands, key=lambda kv: len(kv[1]))
        aid = ALGOS[algo]
    else:
        aid = ALGOS[algo]
        if algo == "raw":
            payload = raw
        elif algo == "zlib":
            payload = zlib.compress(raw, 9)
        elif algo == "lzma":
            payload = lzma.compress(raw, preset=9 | lzma.PRESET_EXTREME)
        else:
            raise ValueError(f"unknown algo {algo!r}")
    lang_b = lang.encode("utf-8")[:255]
    return (MAGIC + struct.pack("<BBBB", aid, flags, len(lang_b), 0)
            + lang_b + struct.pack("<I", len(raw)) + payload)


def decode(blob: bytes) -> tuple[str, str]:
    if blob[:4] != MAGIC:
        raise ValueError("not a .wy file")
    aid, flags, langl, _ = struct.unpack("<BBBB", blob[4:8])
    p = 8
    lang = blob[p:p + langl].decode("utf-8")
    p += langl
    (rawlen,) = struct.unpack("<I", blob[p:p + 4])
    p += 4
    payload = blob[p:]
    algo = ALGO_NAMES[aid]
    if algo == "raw":
        raw = payload
    elif algo == "zlib":
        raw = zlib.decompress(payload)
    else:
        raw = lzma.decompress(payload)
    if len(raw) != rawlen:
        raise ValueError("length mismatch: header says %d, got %d" % (rawlen, len(raw)))
    enc = "gbk" if flags & FLAG_GBK else "utf-8"
    return raw.decode(enc), lang


def measure(text: str) -> dict:
    """文本体积画像（用于对客展示）。"""
    gbk = None
    try:
        gbk = len(text.encode("gbk"))
    except UnicodeEncodeError:
        pass
    return {
        "chars": len(text),
        "utf8": len(text.encode("utf-8")),
        "gbk": gbk,
    }
