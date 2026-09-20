---
name: tcm-classics-study
description: 研读《素问》《灵枢》《伤寒论》《金匮要略》《难经》《温病条辨》，区分原典、历代医家与现代医学证据。用于原文定位、释义、注家比较、跨经典比较和科学证据对照；不用于诊断、开方或剂量建议。
compatibility: WorkBuddy；运行时需要 Python 3.9+ 和标准库 sqlite3，经典检索离线可用，现代证据层需要网页搜索/读取能力。
---

# 中医四部经典研读

> 开发状态：功能验收通过的可运行候选版。经典数据库、现代证据缓存、单调用研究包和两种渲染器均已装入 Skill；最终来源锁仍待后续精修，因此暂不标记为正式发布版。

产品必须遵守以下不变量：

1. 原典、历代医家和现代医学严格分层。
2. 直接引文只能来自本地检索结果，不凭模型记忆补引。
3. 有合理现代医学对应时默认核验现代资料；纯字词、篇章、版本问题不硬凑现代层。
4. 网络失败不阻塞原典和医家层。
5. 不提供个体诊断、处方、剂量换算、停换药或以古方替代急救的建议。
6. 隔离段落不在运行时数据库中；不得绕过索引读取或引用隔离文本。
7. 对话输出遵守“宁缺毋滥”：不为凑数展示弱相关、过短、残缺或不能独立解释的材料；一条准确材料优于多条泛主题材料。
8. 只采用一种标准研读深度，不识别或切换“简要/深入”模式；用户需要更多内容时通过下一轮追问展开。

## 首选运行入口

优先用一次调用生成受安全规则和上下文预算约束的 A/B/C 研究包：

```bash
python scripts/study.py --query "用户原问题"
```

`--terms` 可省略；只有已经确认明确原句时才提供1—3个经典词组。运行顺序固定为：

1. 先完成现代分级；M3 立即返回安全分流，并默认暂缓古籍检索。
2. 非M3问题检索 A原典和 B历代医家；M0通常省略C层。
3. M1—M3使用有效缓存，缓存不足时返回去身份化联网计划。
4. 严格按研究包的 `answer_contract` 完成标准研读：一句话主旨、核心引文、逐句白话、3—5个关键词，以及有直接依据时的医家异同。
5. 默认只展示 `core_quote`；`text_simplified` 保留为可核对的完整段落。没有高质量医家材料时省略B层，没有合理现代对应时省略C层。

研究包可确定性渲染为可访问Markdown或自包含HTML的**材料预览**。渲染器不生成本题主旨或白话解释；宿主仍须按 `answer_contract` 完成研读，不把通用提示当作“一句话主旨”：

```bash
python scripts/render.py --input packet.json --format markdown --output answer.md
python scripts/render.py --input packet.json --format html --output answer.html
```

若宿主不能稳定展示HTML，默认使用Markdown。不得把完整健康问题或个人信息原样提交给外部搜索；若 `online_search_plan.required=true`，遵守 `references/workbuddy-web-evidence.md`。

## 分步工具与本地经典检索协议

需要单独检查分类或缓存时使用：

```bash
python scripts/modern_evidence.py assess --query "用户原问题"
```

数据库路径为 `data/classics.sqlite`。

通常直接提交用户原问题，由运行时规则提取1—3个高价值经典词组、识别口语改写并抑制任务套话；已经确认原句时才额外提供 `--terms`：

```bash
python scripts/search.py search --query "用户原问题" --terms "词组一,词组二"
```

需要限定时使用 `--work suwen|lingshu|shanghanlun|jingui|nanjing|wenbingtiaobian`（也接受完整作品ID）、`--layers core,commentary,lineage` 或 `--author 姓名`。自然语言点名医家、字号及完整注书名也能限定范围。“只看/只查/只在”、排除对象及CLI显式范围是硬约束，不扩展到其他来源。

指定范围有直接材料时不得因全库代表段落不同而回退。一般指定范围题的 `alternative_results`（研究包为 `source_alternatives`）只能作为单独标注实际出处的备选，不能替代指定医家观点。只有出处核对问法允许软回退；`route_resolution.conflict_detected=true` 仅表示用了范围外出处，不表示证明用户记错。先客观说明指定范围和范围外分别检得什么，不作责备或静默换人。可用 `--no-route-fallback` 禁止备选和软回退。

默认只保留A—C级相关候选，并抑制数量、缺文标记、“方见上”等短残片；匹配等级只是词句覆盖，不代表整问已被回答。`needs_clarification.required=true` 时按提示收窄范围，不用弱结果填满配额。

比较题必须逐项核对 `scope_coverage`：`not-found` 是未检得，`not-displayed` / `not-displayed-budget` 是限额或预算未展示，均不能宣称完成全部比较。默认医家名额可扩至覆盖三位等明确对象，总条数仍受 `--limit-total` 控制。`quality_policy.budget_omitted` 列出已检得但因预算未展示的段落，不能改称“未检得”。主ID为空时不要冒称已展示锚点。

注书转引经文（`speaker_type=quoted_core`）不占医家注文名额；显式上下文读取可保留，但只能标为转引经文，不能当作医家自己的观点。

查看连续上下文：

```bash
python scripts/search.py context --id PASSAGE-ID --before 1 --after 1
```

连续追问“上一条/前后文”时，宿主从上一研究包读取 `answer_contract.primary_passage_id`，再调用：

```bash
python scripts/study.py --query "用户追问" --anchor-id PASSAGE-ID
```

`--anchor-id` 专用于全文/前后文展开，不用于另一次医家比较或新主题搜索；换医家时应提交包含条文关键词的新查询。锚点超预算时应增加 `--character-budget` 后重试，不用邻段替代。Skill 不保存隐式会话状态或原始查询日志。只可把结果中的 `text_simplified` 或其连续子串 `core_quote` 作为直接引文。回答必须同时保留 `title`、`author`、卷篇、页面标题和固定 `source_revision_id`；不得把检索规范化文本写成引文。

## 现代证据使用

- 只引用 `cache.records` 中 `citation_recommended=true` 的缓存记录。
- 缓存记录必须同时展示结论方向、直接性、证据类型、可信度、局限、来源和核验日期。
- 请求最新进展、缓存缺失或已过期时，按 `online_search_plan` 联网；搜索摘要不能作证据。
- 断网不阻塞A/B层；M2无有效缓存时明确说明未能核验，不凭记忆补结论。
- 现代对应不得把证候、脏腑、经络等直接等同于现代疾病或解剖结构。

逐句解释、关键词、医家分歧和“宁缺毋滥”细则见 `references/answer-policy.md`。详细政策见 `references/`；正式发布标记仍须等待后续文本质量精修和最终来源锁。
