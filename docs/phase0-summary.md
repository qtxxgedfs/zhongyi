# Phase 0 完成摘要

## 状态

**Phase 0：环境、旧包与来源审计已完成。** 可以进入 Phase 1 的固定修订版抓取、文本治理和 `source-lock.json` 构建。

## 已完成

- [x] 建立项目、Skill、builder、schema、sources、tests 和 docs 骨架。
- [x] 验证当前开发机 Python 3.14.1、SQLite 3.50.4、FTS5 与 trigram 可用。
- [x] 验证 Wikisource、WHO 脚本访问；记录本机 Python 直连 PubMed 的证书链问题及安全降级策略。
- [x] 记录产品方确认的 WorkBuddy 网页搜索与网页读取能力。
- [x] 审计旧 ZIP 的规模、索引结构、查询速度和过长输出问题。
- [x] 建立六部原典和扩展作品候选清单。
- [x] 自动核验 Wikisource 页面、修订号、页面长度和子页面数量。
- [x] 完成作品级选择调整，形成6种原典、20种扩展/源流，共26种作品的暂定首版范围。
- [x] 建立 source-lock JSON Schema 与 SQLite schema 草案。
- [x] 建立初版 Skill 安全、回答和现代证据协议。
- [x] 运行9项 Phase 0 自动测试，全部通过。

## 关键发现

1. 旧版检索每次解析6.27MB JSON并遍历10,926条记录；全层示例查询中位耗时约1.29—1.38秒，输出可达约19—26KB。
2. 六部原典均有可定位的Wikisource候选，但《伤寒论》《素问》《灵枢》等页面明确存在低校订率或繁简转换风险，不能未经检查直接称为权威定本。
3. 原计划三种作品未在Wikisource发现全文：马莳两种《注证发微》、叶霖《增订温病条辨》。
4. 程林《金匮要略直解》的自动搜索结果实际是周扬俊《金匮玉函经二注》，已阻止错误归属。
5. Wikisource普通《类经》入口不完整，已改为有49个子页的《类经（四库全书本）》候选。
6. Kanripo《类经》看似完整，但单仓库未声明许可证；在许可未明确前不作为发布来源。
7. 当前机器Python直连PubMed存在本地证书链错误；不会关闭TLS校验，现代层优先走WorkBuddy网页能力。

## 首版作品调整

- 马莳《黄帝内经素问注证发微》 → 张志聪《黄帝内经素问集注》。
- 马莳《黄帝内经灵枢注证发微》 → 丹波元简《灵枢识》。
- 程林《金匮要略直解》 → 首版排除，不用其他作者作品冒名替代。
- 叶霖《增订温病条辨》 → 延期；首版保留王士雄、雷丰及叶天士、薛雪源流材料。

详见 [`source-selection-review.md`](source-selection-review.md)。

## 下一阶段入口

Phase 1 首先实施：

1. 枚举每种入选作品实际使用的根页和子页；
2. 固定所有修订号，而不是只记录根页；
3. 下载繁体wikitext/HTML快照并计算SHA-256；
4. 建立篇卷完整性清单；
5. 清理模板、伪标签、私用区字符和明显乱码；
6. 区分经文、注文、校语和按语；
7. 生成简体阅读字段和检索字段；
8. 通过质量检查后生成最终 `source-lock.json`。

## 相关文件

- `../CODING_PLAN.md`
- `environment-report.md`
- `legacy-skill-audit.md`
- `wikisource-source-audit.md`
- `source-selection-review.md`
- `../sources/source-candidates.json`
- `../sources/source-selection.json`
- `../schemas/source-lock.schema.json`
- `../schemas/classics.sql`
