# NOTICE — 中医四部经典研读语料

## 状态

当前为可运行的固定修订候选；质量精修尚未完成，不得称为最终无条件发布底本。

本产品所用的是**工作底本**，不是无异文、无错误的唯一权威文本。语料包含
26 种作品、973 个固定页面快照。逐页标题、链接、固定修订号、
访问时间和 SHA-256 见 `sources/source-manifest.json`（候选Skill内为
`data/source-manifest.json`）。

## Wikisource 文本

- 来源网站：中文维基文库（Wikisource）
- 网站使用条款：https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use/en
- 文本再利用许可：https://creativecommons.org/licenses/by-sa/4.0/
- 原古籍作品属于公版范围；维基文库转录文本及其可版权化编辑按 CC BY-SA 4.0
  署名—相同方式共享条件处理。
- 固定修订链接同时指向页面历史和贡献者记录，构成逐页署名追溯入口。

## 本项目所作修改

本项目对固定 wikitext 快照进行模板展开、版式标记清理、缺字模板解析、Unicode
规范化、繁简转换、医学字符阅读规范化、说话者/内容角色标注和检索字段生成。
所有人工字符修复均记录在 `sources/normalization/manual-character-repairs.json`；
繁简阅读覆盖规则记录在 `sources/normalization/conversion-overrides.json`。含未解字的最小完整语义单元保留在隔离库中，但检索字段置空，禁止搜索和引用；隔离清单见 `sources/corpus-exclusions.json`。

## 现代医学来源

`data/evidence-cache.sqlite` 只保存本项目撰写的中文证据摘要、结构化判断和来源元数据，不保存NCCIH、CDC、NHS等网站的网页全文。来源标题、机构、日期、URL、页面核验日期和抓取内容哈希用于追溯，不表示外部网页采用与古籍语料相同的许可。在线使用仍须遵守各来源网站条款。

## 不包含的内容

本项目不打包 Wikisource、互联网档案馆或其他机构的扫描影像，也不打包现代医学来源网页全文。扫描影像和外部网页可能有独立权利和使用条件，不能因文字或事实可引用而推定其他内容可打包。

## 相同方式共享

分发含 Wikisource 衍生文本的版本时，应同时保留本 NOTICE、逐页来源清单、修改
说明和 CC BY-SA 4.0 链接，并按相同许可证提供受该许可证约束的衍生文本部分。
