# Phase 2 SQLite 索引与检索原型报告

## 产物

- 候选数据库：`build/classics.sqlite`
- 文件大小：49.9 MiB
- SHA-256：`35316630ad2105cf9384376062f1c524994b63b633a75fbdd8b41130dbf21fc2`
- 可检索段落：53,800
- 明确排除的隔离段落：288
- 构建清单：`build/classics-index-manifest.json`（含数据库及全部索引输入 SHA-256）
- 索引：SQLite FTS5；预分词去重重叠二元字符组；运行时不加载全量 JSON。
- 数据库状态：`candidate`；Phase 1 发布闸门未通过前不得改称最终发布数据库。

## 性能

在本机构建后热文件缓存条件下，对12类查询各运行3次：

- CLI 内部检索中位数：13.116 ms
- CLI 内部检索 P95：53.582 ms
- 含 Python 进程启动的端到端中位数：873.888 ms
- 含 Python 进程启动的端到端 P95：1276.112 ms
- 路由/召回检查：24/24 通过

## 查询检查

| 场景 | 结果数 | 首条 | 指定作品是否召回 | 路由是否通过 |
|---|---:|---|---|---|
| suwen-core | 5 | `SW-000004` | 是 | 是 |
| lingshu-core | 5 | `LS-000157` | 是 | 是 |
| shanghan-core | 6 | `SHL-000054` | 是 | 是 |
| jingui-core | 5 | `JKY-000064` | 是 | 是 |
| nanjing-core | 3 | `NJ-000001` | 是 | 是 |
| wenbing-core | 2 | `WBTB-000175` | 是 | 是 |
| author-zhangjingyue | 2 | `COMMENTARY-NEIJING-LEIJING-000197` | 是 | 是 |
| author-wangbing | 2 | `COMMENTARY-SUWEN-WANGBING-007078` | 是 | 是 |
| author-youtaijing | 4 | `COMMENTARY-SHANGHAN-YOUYI-000003` | 是 | 是 |
| lineage-yetianshi | 2 | `LINEAGE-WENBING-YETIANSHI-000001` | 是 | 是 |
| cross-canon | 1 | `LS-000655` | 是 | 是 |
| traditional-query | 6 | `SHL-000056` | 是 | 是 |

## 质量边界

- 构建器只在 `citable_corpus_status=pass` 时建索引。
- 288条隔离段没有进入 `passages` 或 FTS，无法经普通检索、段落读取或上下文接口取得。
- CLI 只输出 `text_simplified` 作为显示/直接引文字段，不输出 `text_search`。
- 当前性能数据是开发机基准；目标 WorkBuddy 电脑仍须实机验收。
