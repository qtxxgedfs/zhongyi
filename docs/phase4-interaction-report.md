# Phase 4 回答协议与交互原型报告

## 状态

Phase 4 已形成可运行闭环。`study.py` 在一次调用中先完成M0—M3安全分级，再按需要检索A原典、B历代医家和C现代证据，并输出受字符预算约束的研究包。`render.py` 可把研究包确定性渲染为可访问Markdown或独立HTML。两个脚本已进入运行时清单；研究包、Markdown渲染和M3暂缓古籍检索也已进入 `self_check.py`。

## 单调用研究包

```bash
python scripts/study.py --query "《素问》治未病在说什么，和现代预防有什么区别" --terms "治未病"
```

输出包含：

- `safety_first`：M3是否必须先分流；
- `classification`：M0—M3级别、理由和主题；
- `A_core`：只含原典层；
- `B_physicians`：只含注家和学术源流层；
- `C_modern`：有效缓存及去身份化联网计划；
- `answer_contract`：允许引用的段落ID、现代记录ID和回答边界；
- `context_budget`：默认不超过2500个经典文本字符。

M3默认不检索古籍，避免急症问题被古方材料带偏。只有先呈现急救分流后，才可通过明确选项另作纯文献讨论。

## 两种渲染

### accessible-markdown

- 固定“一句话结论 → 🟩A原典 → 🟧B医家 → 🟦C现代医学”；
- 原文、来源和限制独立换行；
- 不支持颜色时仍可依靠A/B/C、图标和标题辨识；
- 直接引文完全来自研究包中的 `text_simplified`。

### accessible-cards HTML

- 正文18px、来源16px、行高1.75；
- 浅色底、深色字和明显边框；
- 无动画、渐变、阴影、外部字体、脚本或外部图片；
- 针对窄屏调整内边距和字号；
- 用户文本经过HTML转义。

命令：

```bash
python scripts/render.py --input packet.json --format markdown --output answer.md
python scripts/render.py --input packet.json --format html --output answer.html
```

渲染器只负责忠实展示检索材料和结构化证据，不自行生成诊断、处方或未经来源支持的解释。WorkBuddy可以在 `answer_contract` 约束下增加明确标记的“AI研读解释”，但不能改写直接引文。

## 来源回查

经典结果现在同时提供：

- 简体页面标题；
- 固定修订号；
- 带 `oldid` 的固定Wikisource链接；
- 段落ID和内容哈希。

现代记录提供机构、标题、日期、URL、核验日期、有效期和页面内容哈希。

## 自动验证

- Phase 4独立测试：5/5通过，并已纳入自动回归；
- 运行时自检：研究包、Markdown渲染和M3暂缓古籍检索均通过；
- 150题固定验收中的M0—M3分类和M3安全检查均通过。

## 使用方部署事项

以下事项由使用方在目标环境处理，不作为代码完成条件：

- 按WorkBuddy实际能力配置网页工具；不支持HTML时使用Markdown。
- 按具体设备和用户偏好确认字号、信息密度及默认渲染格式；当前样式已满足既定自动可访问性指标。
