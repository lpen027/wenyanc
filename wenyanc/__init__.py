"""wenyanc —— 语义压缩：任意语言 → 文言文 → 通用压缩算法。

分层：
  translator  任意语言 <-> 文言文（可插拔 LLM 后端，默认本地 ollama）
  codec       文本 <-> 字节（无损，通用压缩：lzma/zlib，可选 GBK 双字节化）
"""
__version__ = "0.1.0"
