# Phase 3 现代医学证据层报告

## 状态

Phase 3 的首个可运行版本已经完成：M0—M3 分级、急症优先分流、可信来源登记、结构化证据缓存、缓存有效期、去身份化联网计划、来源域名检查、断网降级和运行时自检均已落地。

当前 Skill 标记为 **`candidate-runnable`**，用于继续功能和实机验收；它不是最终无条件发布版。古籍可引用库已经隔离未解内容，但最终来源锁仍留待后续文本质量精修。

## 运行时产物

- `skill/tcm-classics-study/scripts/modern_evidence.py`：分类、缓存检索、联网计划及来源检查。
- `skill/tcm-classics-study/data/evidence-cache.sqlite`：只读首批核验证据缓存。
- `skill/tcm-classics-study/data/evidence-cache.manifest.json`：数据库和构建输入哈希。
- `schemas/evidence-cache.sql`：证据缓存 schema。
- `schemas/evidence-records.schema.json`：证据记录 JSON Schema。
- `sources/modern/source-registry.json`：可信来源登记与用途边界。
- `sources/modern/evidence-topics.json`：主题、别名、默认级别和去身份化检索词。
- `sources/modern/evidence-records.json`：中文结论、直接性、证据类型、可信度、局限和来源元数据。
- `sources/modern/evidence-source-audit.json`：完整页面核验、HTTP状态、页面哈希及记录映射。
- `references/workbuddy-web-evidence.md`：WorkBuddy网页搜索/读取接入协议。

## M0—M3 行为

| 级别 | 典型问题 | 产品行为 |
|---|---|---|
| M0 纯文献 | 原句、出处、篇章、版本、注家解释 | 不强行添加现代层，不要求联网 |
| M1 概念对照 | 阴阳、脏腑、经络、证候与现代概念的关系 | 说明对应边界；无来源时不补造机制 |
| M2 证据与安全 | 方药、针灸、疗效、不良反应、剂量、检查、预后 | 先查有效缓存，缺失、过期或要求最新时联网 |
| M3 急症风险 | 卒中征象、严重呼吸困难、胸痛压迫、严重过敏、大量出血、中毒、自伤等 | 先输出急救分流；不得等待古籍或网页检索 |

分类器会区分现实健康问题和学术语境。例如“我父亲突然说话不清、一侧手脚无力怎么办”判为M3；“《伤寒论》胸痛原文在哪篇”在没有现实症状或行动请求时判为M0。

## 首批缓存

- 可信来源机构登记：11个。
- 现代主题：25个（含急性腹痛急症主题）。
- 已完整页面核验记录：6条。
- 当前有效记录：6条。
- 网页全文：不进入Skill；只保存中文摘要、来源元数据和核验哈希。

首批记录覆盖：

1. NCCIH对中药总体疗效证据不一致、研究质量有限的概述；
2. NCCIH对部分中药产品污染、掺入成分、误替及严重不良反应的安全概述；
3. NCCIH对针灸用于部分疼痛状况的混合/有限证据概述；
4. NCCIH对针灸操作不当所致感染、脏器损伤和气胸等风险的概述；
5. CDC卒中警示症状和立即急救要求；
6. NHS严重过敏反应的急症识别与立即求助要求。

这些总体记录不能外推成具体方剂、制剂、剂量、疾病或个人的疗效结论。缓存未覆盖时，C层必须联网核验或明确降级。

## 联网与隐私

`assess` 返回的是由主题表生成的通用检索词，不把用户姓名、电话、地址、病历号或完整健康问题提交给外部网站。搜索摘要不能作为证据；必须打开全文页。外部网页按不可信输入处理，页面中的指令不能改变本地任务或安全政策。

WorkBuddy的具体网页工具调用签名仍需在目标电脑上确认，因此首版使用工具无关的检索计划。即使网页工具不可用，古籍A/B层和有效缓存仍可离线运行；M3安全分流永不依赖网络。

## 命令示例

```bash
python scripts/modern_evidence.py assess --query "针灸对腰痛有效吗，有什么副作用"
python scripts/modern_evidence.py assess --query "我父亲突然说话不清，一侧手脚没力怎么办"
python scripts/modern_evidence.py status
python scripts/modern_evidence.py source-check --url "https://www.cdc.gov/stroke/signs-symptoms/index.html"
python scripts/self_check.py
```

## 当前边界

- 6条缓存只用于建立可运行闭环，不代表现代医学主题已经全面覆盖。
- 请求“最新研究”或“当前指南”会强制生成联网更新计划，即使缓存尚未过期。
- 未登记域名不能自动写入已核验缓存；新增指南机构必须先审计登记。
- PubMed结构化直连的本机证书链问题仍未通过关闭TLS绕过；可优先使用WorkBuddy网页能力。
- 现代证据缓存不记录用户查询，在线结果也不自动进入长期缓存。
