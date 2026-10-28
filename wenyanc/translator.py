"""语言 <-> 文言文 翻译层。

后端可插拔，默认本地 ollama（http://127.0.0.1:11434）。
所有翻译结果按 (backend, mode, lang, text) 哈希缓存，重复跑不重复烧算力。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.request

CACHE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "wenyanc")

# 语言代码 -> 人类可读名（反向翻译时用）
LANGS = {
    "zh": "现代汉语",
    "en": "English",
    "ja": "日本語",
    "ko": "한국어",
    "fr": "français",
    "de": "Deutsch",
    "es": "español",
    "ru": "русский",
    "ar": "العربية",
    "pt": "português",
}

_TO_WENYAN = """你是文言文压缩器。把用户输入改写成尽可能简短的古文/文言文，要求：
1. 保留全部事实：人名、地名、机构、数字、日期、因果、条件、否定、程度、指代关系。
2. 允许删虚词、改语序、用单音节词，不可删信息。
3. 数字、单位、百分比一律译成汉字（3.8% -> 三点八分，2024 -> 二〇二四，1.8 秒 -> 一点八秒），勿用"成""percent"等；不可留英文单词。
4. 日期写成"五月十二日"式，时刻写成"三时二十分"式，勿用卯时、时辰等传统纪时；年份写"二〇二四年"。
5. 不用典故，不押韵，不加解释，不加"译文"等字样。
6. 只输出文言文本身，不要任何前后缀。
/no_think"""

_TO_MODERN = """把用户给的文言文翻译成{lang}，要求：
1. 忠实还原事实与因果，不要扩写。
2. 只输出译文，不要任何前后缀。
/no_think"""


_LATIN_HINTS = {
    "fr": ("é", "è", "ê", "à", "ç", "œ", " les ", " des ", " une ", " est ", " pour ", " que "),
    "de": ("ß", "ä", "ö", "ü", " der ", " die ", " und ", " nicht ", " ist ", " eine "),
    "es": ("ñ", "¿", "¡", " el ", " la ", " los ", " por ", " para ", " una ", " que "),
    "pt": ("ã", "õ", " não ", " uma ", " dos ", " das ", " para ", " com "),
    "it": (" gli ", " della ", " sono ", " che ", " per ", " una "),
}


def detect_lang(text: str) -> str:
    """按 Unicode 脚本粗判主语言（够用即可，不作学术用途）。"""
    counts = {"cjk": 0, "hangul": 0, "kana": 0, "cyrillic": 0, "arabic": 0, "latin": 0}
    for ch in text:
        o = ord(ch)
        if 0x3040 <= o <= 0x30FF:
            counts["kana"] += 1
        elif 0x4E00 <= o <= 0x9FFF:
            counts["cjk"] += 1
        elif 0xAC00 <= o <= 0xD7AF:
            counts["hangul"] += 1
        elif 0x0400 <= o <= 0x04FF:
            counts["cyrillic"] += 1
        elif 0x0600 <= o <= 0x06FF:
            counts["arabic"] += 1
        elif ch.isalpha():
            counts["latin"] += 1
    top = max(counts, key=counts.get) if any(counts.values()) else "latin"
    if top != "latin":
        return {"kana": "ja", "cjk": "zh", "hangul": "ko",
                "cyrillic": "ru", "arabic": "ar"}[top]
    # 拉丁字母：看变音符号与高频功能词
    low = " " + text.lower() + " "
    best, score = "en", 0
    for code, hints in _LATIN_HINTS.items():
        s = sum(low.count(h) for h in hints)
        if s > score:
            best, score = code, s
    return best


class OllamaBackend:
    def __init__(self, model: str = "qwen3:8b", url: str = "http://127.0.0.1:11434", timeout: int = 300):
        self.model = model
        self.url = url.rstrip("/")
        self.timeout = timeout

    def complete(self, prompt: str) -> str:
        body = json.dumps({
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": 2000},
        }).encode()
        req = urllib.request.Request(
            self.url + "/api/generate", data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            data = json.loads(r.read().decode())
        return data.get("response", "").strip()


_META_LEAKS = ("译文如下", "译文：", "文言文：", "以下是", "Here is", "Translation:")
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.S)


def _clean(out: str) -> str:
    out = _THINK_BLOCK.sub("", out)
    out = out.replace("<think>", "").replace("</think>", "")
    lines = [ln.strip() for ln in out.strip().splitlines() if ln.strip()]
    cleaned = []
    for ln in lines:
        for m in _META_LEAKS:
            if ln.startswith(m):
                ln = ln[len(m):].lstrip("：: 　")
                break
        if ln:
            cleaned.append(ln)
    txt = "".join(cleaned)
    return txt.strip().strip("「」\"'“”")


class Translator:
    def __init__(self, backend=None):
        self.backend = backend or OllamaBackend()
        os.makedirs(CACHE_DIR, exist_ok=True)

    def _cached(self, mode: str, lang: str, text: str, fn, prompt: str = ""):
        salt = prompt or ""
        key = hashlib.sha256(f"{getattr(self.backend,'model','?')}|{mode}|{lang}|{salt}|{text}".encode()).hexdigest()[:32]
        path = os.path.join(CACHE_DIR, key + ".json")
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    return json.load(f)["out"]
            except Exception:
                pass
        out = fn()
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"mode": mode, "lang": lang, "in": text, "out": out,
                       "model": getattr(self.backend, "model", "?")}, f, ensure_ascii=False)
        return out

    def to_wenyan(self, text: str) -> str:
        prompt = f"{_TO_WENYAN}\n\n原文：\n{text}"
        return self._cached("to_wenyan", "-", text,
                            lambda: _clean(self.backend.complete(prompt)), prompt)

    def to_modern(self, wenyan: str, lang: str = "zh") -> str:
        prompt = f"{_TO_MODERN.format(lang=LANGS.get(lang, lang))}\n\n{wenyan}"
        return self._cached("to_modern", lang, wenyan,
                            lambda: _clean(self.backend.complete(prompt)), prompt)
