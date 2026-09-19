# Phase 0 环境验证报告

> 检查时间：2026-09-18T08:41:42+00:00  
> 范围：当前开发/构建机器；发布前还要在父亲实际使用的电脑运行 `self_check.py`。

## 本地运行能力

- 操作系统：`Windows-11-10.0.26200-SP0`
- Python：`3.14.1 (tags/v3.14.1:57e0d17, Dec  2 2025, 14:05:07) [MSC v.1944 64 bit (AMD64)]`
- Python最低版本（3.9）：通过
- SQLite：`3.50.4`
- SQLite FTS5：通过
- SQLite trigram tokenizer：通过
- 用户级 WorkBuddy Skills 目录：`C:\Users\wangx\.workbuddy\skills`（当前不存在）

结论：当前机器可以开发和运行预构建 SQLite FTS5/trigram 检索。正式版仍保留不依赖 trigram tokenizer 的预生成字符词项方案，以兼容较旧的目标环境。

## 网络探测（仅脚本直连）

| 地址 | 结果 | HTTP/错误 | 耗时 |
|---|---|---|---:|
| https://zh.wikisource.org/ | 通过 | 200 | 1223 ms |
| https://pubmed.ncbi.nlm.nih.gov/ | 失败 | URLError: <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate in certificate chain (_ssl.c:1081)> | 685 ms |
| https://www.who.int/ | 通过 | 200 | 484 ms |

当前 Python 直连 PubMed 如出现本地证书链错误，不得通过关闭 TLS 校验绕过。运行时优先使用已确认稳定的 WorkBuddy 网页搜索/网页读取能力；结构化 PubMed 适配器需在目标环境单独验证证书链，失败时安全降级。

## WorkBuddy 能力结论

- 产品方已确认：网页搜索和网页读取能力稳定可用。
- 旧版 Skill 已在 WorkBuddy 成功使用，并使用内联可视化卡片协议，说明可视化路径具备实际可用基础。
- 本编码环境不能直接调用父亲 WorkBuddy 会话中的具体网页工具或渲染器，因此 Phase 3/4 仍需适配实际工具参数并做实机验收。
- 经典检索不能依赖网络；现代层超时或断网不得阻塞原典与医家层。

## Phase 0 结论

1. Python 与 SQLite 检索技术路线可行。
2. FTS5 和 trigram 在当前机器可用，但发布版需要兼容性自检和回退路径。
3. Wikisource 与 WHO 当前脚本直连可用。
4. 现代证据优先走 WorkBuddy 网页能力；PubMed 结构化直连属于增强项，不能成为单点依赖。
