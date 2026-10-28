# wenyanc · 文言压缩

**把任何主流语言译成文言文，再交给普通压缩算法。** 文言文是人类实际用过的书面语里语义密度最高的一种：同样的事实，字符数只有现代英语的五分之一左右。密度上来之后，剩下的工作交给 LZMA 就够了——文言文字表窄、同字重复多，正是字典压缩最擅长吃的东西。

This is a *semantic* compressor: it is lossy by design (it drops wording, not facts), and it is reversible in bytes (`.wy` decodes to exactly the Classical Chinese that was stored).

```
English / 日本語 / français / español / 中文  ──▶  文言文  ──▶  .wy (LZMA + GBK)
                                                     ▲
                                              a codec, not a model
```

## 实测（真实跑出来的，不是估算）

5 段样例，每段 300–1300 字符，内容含人名、数字、日期、因果。文言文译文见 `samples/*.wenyan.txt`（可用 `--golden` 离线复现），压缩 `lzma preset 9e` + GBK 双字节化。

| sample | lang | 原文 char | 文言 char | 语义密度 | 同算法压原文 | 本方案 .wy | 对原文 | 对直接压缩 |
|---|---|---|---|---|---|---|---|---|
| en.txt | en | 1240 | 270 | 4.59× | 818 B | 542 B | 2.29× | 1.51× |
| es.txt | es | 1040 | 198 | 5.25× | 694 B | 418 B | 2.55× | 1.66× |
| fr.txt | fr | 1046 | 219 | 4.78× | 726 B | 446 B | 2.40× | 1.63× |
| ja.txt | ja | 417 | 221 | 1.89× | 774 B | 454 B | 2.61× | 1.70× |
| zh.txt | zh | 329 | 264 | 1.25× | 754 B | 526 B | 1.73× | 1.43× |
| **均值** | | | | **3.55×** | | | **2.32×** | **1.59×** |

复现：`python -m wenyanc bench --golden`（结果同时写入 `bench_result.json`）。

两点诚实的读法：

- **拼音文字收益最大**（英/西/法 4.6–5.3×），因为这几个语言的字符密度本来就低。
- **现代汉语收益最小**（1.25×），因为汉字已经替你压过一轮了；但它的绝对体积依旧最小。日语 1.89× 里已经不含任何假名。
- 注意"对直接压缩"只有 1.4–1.7×：文言文省下的信息冗余，有相当一部分普通压缩器自己也能吃掉。真正的差额来自"字符变少"这一步，而这一步是有损的。

## 用法

```bash
pip install -e .

# 文本 -> .wy（默认 lzma + GBK 双字节化）
wenyanc encode samples/en.txt -o doc.wy

# .wy -> 文言文
wenyanc decode doc.wy

# .wy -> 还原成原文语言
wenyanc decode doc.wy --modern en

# 跑样例出数字
wenyanc bench
```

默认后端是本地 ollama（`http://127.0.0.1:11434`，模型 `qwen3:8b`）。换模型/端点直接继承 backend：

```python
from wenyanc.translator import Translator, OllamaBackend
from wenyanc import codec

t = Translator(OllamaBackend(model="qwen3:8b", url="http://127.0.0.1:11434"))
wy = t.to_wenyan("The pump failed at 03:20 on 12 May; the seal was replaced on the 14th.")
blob = codec.encode(wy, "en", algo="lzma")
assert codec.decode(blob)[0] == wy
```

翻译结果按 `(model, mode, lang, prompt, text)` 哈希缓存到 `~/.cache/wenyanc/`，重复跑不重复烧算力。

## 容器格式

```
magic  "WY1\0"                   4
algo   u8  0=raw 1=zlib 2=lzma   1
flags  u8  bit0 = GBK payload    1
langl  u8                        1
lang   utf-8, 变长
rawlen u32                       4
payload                          变长
```

`rawlen` 是文言文的原始字节数，解压后校验长度，任何截断都会报错而不是静默出错。

## 为什么用普通压缩算法

文言文的统计特征对通用压缩极其友好：

- 字表窄（常用字约 3000），单字重复率高；
- 无空格、无大小写、无词形变化，没有"同一概念多种写法"；
- 高频虚词（之、而、也、者、以、其）形成长距离重复，LZMA 的字典天然吃到。

所以这里没有自研编码器，只有 `lzma` + 一个可选的 GBK 双字节化（UTF-8 每字 3 字节 → GBK 2 字节，直接砍掉 1/3；生僻字自动回退 UTF-8）。

## 局限（别拿去存合同）

- **有损**：丢的是措辞、语气、冗余交代，不是事实。但文言文本身歧义性高，反向翻译一定会有细微漂移。
- **依赖 LLM**：翻译一步慢（本地 8B 约 15–20 秒/段），且质量随模型波动；`/no_think` 之外仍偶发输出英文单词。
- **数字与专名最脆**：提示词里强制"数字转汉字"，但模型仍可能把 `3.8%` 写成"三成八"这类误读。
- **短文本会变大**：`.wy` 头部 8 字节 + LZMA 头，300 字符以下往往"压完更胖"（实测一句 96 B → 126 B）。建议 ≥300 字符再用。
- **不可压缩已压缩的东西**：代码、日志、JSON 收益极小，甚至可能变大。

## 关于"10× 上下文"

常被拿来对比的是"把整段历史塞进上下文"的做法：实测一轮 3 万 tokens 起步，随对话线性增长，撞到上限就得压缩、压缩就丢细节。本项目本身只压文本，不扩容上下文——但如果把它当作记忆/检索层的最后一步（原文已经检索出来、只需要塞进窗口），就能用固定预算承担越来越长的历史，这一层才是那个数量级的来源。

## Roadmap

- [ ] 更多语种样例（ko / ru / ar / pt）与语言检测的置信度
- [ ] backend：OpenAI 兼容 / vLLM
- [ ] 文言文 → 字表编码（把 ~3000 常用字映射到 1.5 字节），替代 GBK
- [ ] 增量压缩：一句话只存与旧记忆的差异

## License

MIT.
