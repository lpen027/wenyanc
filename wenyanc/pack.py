"""pack —— 多条记忆打包成一个归档，共享一个压缩字典。

为什么不是每条约一个 zip：zip 每个成员约 105 字节头，几十条的头部开销就把
字典共享的收益吃光了。这里只留一个流：所有条目按序拼接后整体 LZMA 一次，
条目靠索引里的 (offset, length) 定位，取单条时整块解压再切。

格式::

    magic   b"WYP1"          4
    idxlen  u32
    idx     zlib(json)       紧凑索引（语言/来源做全局表，时间存 epoch）
    paylen  u32
    payload zlib|lzma(拼接流)

用途（对客演示的那条路）：
    pack 归档 -> search 按关键词取回原话 -> 原话塞进上下文
"""
from __future__ import annotations

import json
import lzma
import os
import struct
import time
import zlib

MAGIC = b"WYP1"


def _enc(text: str) -> tuple[bytes, int]:
    try:
        return text.encode("gbk"), 0
    except UnicodeEncodeError:
        return text.encode("utf-8"), 1


def _dec(raw: bytes, flag: int) -> str:
    return raw.decode("utf-8" if flag else "gbk")


def _table(lst: list, value) -> int:
    if value not in lst:
        lst.append(value)
    return lst.index(value)


def pack(entries, path: str, tags=None) -> dict:
    """entries: list[str] 或 list[dict(text=..., lang=..., tags=[...], ts=...)]"""
    norm = [{"text": e} if isinstance(e, str) else dict(e) for e in entries]

    stream = bytearray()
    rows = []
    langs, srcs, tagss = [], [], []
    ts0, prev_ts = 0, None
    for e in norm:
        text = e["text"].strip()
        raw, flag = _enc(text)
        ts = e.get("ts") or int(time.time())
        if isinstance(ts, str):
            try:
                ts = int(time.mktime(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")))
            except Exception:
                ts = int(time.time())
        ts = int(ts)
        if prev_ts is None:
            ts0, prev_ts = ts, ts
        rows.append([
            len(stream), len(raw), len(text), ts - prev_ts,
            _table(langs, e.get("lang", "zh")),
            _table(srcs, e.get("src", "")),
            _table(tagss, ",".join(e.get("tags") or (tags or []))),
            flag,
        ])
        prev_ts = ts
        stream += raw

    payload_l = lzma.compress(bytes(stream), preset=9 | lzma.PRESET_EXTREME)
    payload_z = zlib.compress(bytes(stream), 9)
    algo, payload = ("lzma", payload_l) if len(payload_l) <= len(payload_z) else ("zlib", payload_z)

    head = {
        "v": 3,
        "algo": algo,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "count": len(rows),
        "stream_bytes": len(stream),
        "ts0": ts0,
        "langs": langs,
        "srcs": srcs,
        "tags": tagss,
        "rows": rows,
    }
    idx = zlib.compress(json.dumps(head, ensure_ascii=False, separators=(",", ":")).encode(), 9)
    with open(path, "wb") as f:
        f.write(MAGIC + struct.pack("<I", len(idx)) + idx
                + struct.pack("<I", len(payload)) + payload)

    total = os.path.getsize(path)
    return {
        "path": path,
        "algo": algo,
        "entries": len(rows),
        "stream_bytes": len(stream),
        "payload_bytes": len(payload),
        "index_bytes": len(idx),
        "total_bytes": total,
        "index_pct": round(100.0 * len(idx) / max(total, 1), 1),
    }


def _raw_head(path: str) -> dict:
    with open(path, "rb") as f:
        if f.read(4) != MAGIC:
            raise ValueError("not a .wypack archive")
        (idxlen,) = struct.unpack("<I", f.read(4))
        return json.loads(zlib.decompress(f.read(idxlen)).decode("utf-8"))


def read_head(path: str) -> dict:
    """还原成好用的形态：entries 是 dict 列表，id 是稳定的 nNNN。"""
    h = _raw_head(path)
    ents = []
    ts = h["ts0"]
    for i, r in enumerate(h["rows"]):
        off, ln, chars, dts, li, si, ti, flag = r
        ts += dts
        ents.append({
            "id": "n%03d" % i,
            "lang": h["langs"][li],
            "src": h["srcs"][si],
            "tags": [t for t in h["tags"][ti].split(",") if t],
            "chars": chars,
            "off": off, "len": ln, "flag": flag,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts)),
        })
    out = {k: v for k, v in h.items() if k != "rows"}
    out["entries"] = ents
    return out


def _stream(path: str, head: dict) -> bytes:
    with open(path, "rb") as f:
        f.seek(4)
        (idxlen,) = struct.unpack("<I", f.read(4))
        f.seek(idxlen, 1)
        (paylen,) = struct.unpack("<I", f.read(4))
        payload = f.read(paylen)
    if head.get("algo", "lzma") == "zlib":
        return zlib.decompress(payload)
    return lzma.decompress(payload)


def get(path: str, entry_id, head: dict | None = None, stream: bytes | None = None) -> dict:
    head = head or read_head(path)
    want = str(entry_id)
    if want.isdigit():
        want = "n%03d" % int(want)
    for e in head["entries"]:
        if e["id"] == want:
            stream = stream if stream is not None else _stream(path, head)
            return {**e, "text": _dec(stream[e["off"]:e["off"] + e["len"]], e["flag"])}
    raise KeyError(entry_id)


def all_entries(path: str, head: dict | None = None) -> list[dict]:
    head = head or read_head(path)
    stream = _stream(path, head)
    return [{**e, "text": _dec(stream[e["off"]:e["off"] + e["len"]], e["flag"])}
            for e in head["entries"]]


def unpack(path: str, outdir: str) -> list[str]:
    os.makedirs(outdir, exist_ok=True)
    written = []
    for e in all_entries(path):
        fn = os.path.join(outdir, "%s.txt" % e["id"])
        with open(fn, "w", encoding="utf-8") as f:
            f.write(e["text"])
        written.append(fn)
    return written


def search(path: str, keywords, head: dict | None = None, stream: bytes | None = None,
           mode: str = "any") -> list[dict]:
    """关键词命中，按命中数、再按时间倒序。

    mode="any"（默认）：命中任一即返回，多命中的排前面——演示时要的是"能捞到"。
    mode="all"：全部命中才算——要精确时用。

    刻意做成朴素的子串匹配：对"把原话取回来"这件事足够，且没有训练依赖。
    """
    keywords = [k.strip() for k in keywords if k.strip()]
    if not keywords:
        return []
    head = head or read_head(path)
    stream = stream if stream is not None else _stream(path, head)
    need = len(keywords) if mode == "all" else 1
    hits = []
    for e in head["entries"]:
        text = _dec(stream[e["off"]:e["off"] + e["len"]], e["flag"])
        body = text + " " + " ".join(e["tags"]) + " " + e["src"]
        n = sum(1 for k in keywords if k in body)
        if n >= need:
            hits.append({**e, "text": text, "score": n})
    hits.sort(key=lambda x: (x["score"], x["ts"]), reverse=True)
    return hits
