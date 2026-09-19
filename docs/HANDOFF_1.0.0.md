# 项目交接文档 — 1.0.0

> 生成时间：2026-09-20（本机项目时间）  
> 适用版本：`1.0.0`  
> 项目：`tcm-classics-study` / 中医四部经典研读 Skill  
> 远程仓库：<https://github.com/qtxxgedfs/zhongyi>  
> 运行状态：`candidate-runnable`  
> 来源发布闸门：`blocked`

## 信息标记

本文使用以下标记，下一位 Agent 不应把推断写成已验证事实：

- **[已确认]**：已通过实际文件、代码、数据库查询、Git 状态或本次测试确认。
- **[根据代码推断]**：由当前实现可以合理推断，但没有对应的自动测试或目标环境实测。
- **[待确认]**：当前仓库和本机无法确认，需由维护者或外部环境补充。

`1.0.0` 是首个代码维护基线，不表示古籍工作底本已成为无条件最终发布版。

---

## 1. 项目目标和当前主要功能

### 1.1 项目目标

- **[已确认]** 面向 WorkBuddy / 兼容 Agent Skills 环境，提供可离线运行的中医经典研读能力。
- **[已确认]** 统一覆盖四个经典体系、六部独立原典：
  - 黄帝内经体系：《素问》《灵枢》；
  - 伤寒杂病论体系：《伤寒论》《金匮要略》（独立建库、独立引用）；
  - 《难经》；
  - 《温病条辨》。
- **[已确认]** 同时收录 18 种历代医家注释/扩展作品和 2 种温病学术源流作品。
- **[已确认]** 回答严格区分 A 原典、B 历代医家、C 现代医学；直接古籍引文只能来自本地数据库的 `text_simplified`。
- **[已确认]** 产品定位是经典研读和科学对照，不诊断、不开方、不换算个人剂量、不建议停换药，不以古方替代急救。

### 1.2 当前主要功能

- **[已确认]** SQLite FTS5 中文二元字符索引；支持自然语言路由、作品/体系/作者/层级过滤、短语加权和近重复抑制。
- **[已确认]** 按段落 ID 读取原文、展开前后文、读取作品目录。
- **[已确认]** M0—M3 问题分类：纯文献、概念对照、证据与安全、急症风险。
- **[已确认]** M3 先安全分流，默认暂缓古籍检索。
- **[已确认]** 本地现代医学证据种子缓存、缓存有效期、来源域名登记、去身份化联网计划。
- **[已确认]** `study.py` 单次生成 A/B/C 研究包，默认经典上下文不超过约 2,500 字。
- **[已确认]** 研究包可渲染为可访问 Markdown 或自包含 HTML。
- **[已确认]** 运行时哈希、SQLite 完整性、计数、检索、研究包、渲染和 M3 行为自检。
- **[已确认]** 候选 ZIP 构建及临时目录解压安装测试。
- **[已确认]** 面向普通读者的 `USER_GUIDE.md`。

---

## 2. 项目目录结构和核心模块说明

```text
tcm-classics-study-project/
├── VERSION                         # 项目语义版本唯一根级来源
├── CHANGELOG.md                    # 版本历史
├── README.md                       # 项目总览和常用命令
├── CODING_PLAN.md                  # 产品/架构计划；其中“版本0.6”是文档版本，不是 SemVer
├── NOTICE.md                       # 语料来源、许可与修改说明
├── builder/                        # 构建、质量、索引、验收、打包脚本
├── schemas/                        # 两个 SQLite schema 和证据/来源锁 JSON Schema
├── sources/
│   ├── raw/                        # 固定修订 wikitext 原始快照
│   ├── processed/                  # 结构化段落 JSONL
│   ├── quarantine/                 # 禁止检索/引用的隔离段
│   ├── normalization/              # 字符映射、人工修复、繁简覆盖规则
│   ├── modern/                     # 现代来源登记、主题、记录和页面审计
│   ├── quality-report.json
│   ├── source-lock.candidate.json
│   └── source-manifest.json
├── skill/tcm-classics-study/       # 可部署 Skill 运行时
│   ├── SKILL.md
│   ├── USER_GUIDE.md
│   ├── NOTICE.md
│   ├── scripts/                    # 运行时 CLI
│   ├── data/                       # 只读 SQLite 与运行时清单
│   └── references/                 # 回答、证据、安全、网页协议
├── tests/
│   ├── corpus_checks/              # 38 项 unittest
│   └── acceptance/questions.jsonl  # 150 题固定验收集
├── docs/                           # 阶段报告、安装文档和本交接文档
├── build/                          # 本地构建输出，Git 忽略
└── dist/                           # 本地候选 ZIP，Git 忽略
```

### 2.1 运行时核心模块

- `skill/tcm-classics-study/scripts/search.py`
  - **[已确认]** 只读打开 `classics.sqlite`；提供 `search`、`passage`、`context`、`toc`。
  - **[已确认]** 查询规范化、别名路由、FTS 候选、规则重排和结果去重均在此实现。
- `skill/tcm-classics-study/scripts/modern_evidence.py`
  - **[已确认]** 提供 `classify`、`lookup`、`plan`、`assess`、`source-check`、`status`。
  - **[已确认]** 联网部分只生成工具无关的搜索计划；不直接调用 WorkBuddy 网页工具。
- `skill/tcm-classics-study/scripts/study.py`
  - **[已确认]** 首选聚合入口；先分类，再按安全策略检索经典和现代缓存，输出研究包及 `answer_contract`。
- `skill/tcm-classics-study/scripts/render.py`
  - **[已确认]** 确定性渲染 Markdown/HTML；HTML 转义用户输入和材料文本，无脚本、外部字体或外部图片。
- `skill/tcm-classics-study/scripts/self_check.py`
  - **[已确认]** 校验 runtime manifest 文件哈希、两个数据库哈希/完整性/计数，并执行研究包、Markdown 和 M3 冒烟。

### 2.2 构建核心模块

- `builder/fetch_wikisource.py`：首次抓取或明确更新时固定 Wikisource 修订和原始快照。
- `builder/build_character_maps.py`：冻结 `SKchar` / `SKchar2` 依赖和字符映射。
- `builder/extract.py`：抽取来源文本、内容角色、说话者和结构。
- `builder/convert_simplified.py`：构建繁体工作字段、简体显示字段和检索字段。
- `builder/segment.py`：按语义/结构切段，建立稳定 ID、上下文链接和隔离标记。
- `builder/validate_corpus.py`：验证哈希、完整性、未解字、结构和发布质量闸门。
- `builder/build_source_lock.py`：生成候选/最终来源锁、逐页来源清单和 NOTICE。
- `builder/build_index.py`：从可引用段构建经典 SQLite FTS5 数据库。
- `builder/build_evidence_cache.py`：校验证据 JSON/来源审计并重建证据缓存。
- `builder/stage_runtime_candidate.py`：把候选数据库和清单装入 Skill，刷新 runtime manifest。
- `builder/build_acceptance_set.py` / `builder/run_acceptance.py`：生成和运行固定验收集。
- `builder/benchmark_index.py`：索引路由/召回和性能基准。
- `builder/build_candidate_package.py`：构建候选 ZIP，并解压运行 `self_check.py`。
- `builder/audit_legacy_skill.py`、`audit_wikisource.py`、`check_environment.py`：历史包、来源和环境审计。

---

## 3. 启动、构建、测试和部署命令

以下命令均从项目根目录执行。

### 3.1 环境准备

```bash
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-builder.txt
```

- **[已确认]** 构建依赖只有：
  - `opencc-python-reimplemented==0.1.7`
  - `jsonschema==4.25.1`
- **[已确认]** 运行时脚本只使用 Python 标准库和 `sqlite3`，不需要 OpenCC。

### 3.2 运行时使用

```bash
# 首选：生成一体化研究包
python skill/tcm-classics-study/scripts/study.py \
  --query "《素问》治未病在说什么，和现代预防有什么区别" \
  --terms "治未病"

# 经典检索
python skill/tcm-classics-study/scripts/search.py search \
  --query "《伤寒论》桂枝汤原文" --terms "桂枝汤"

# 段落和上下文
python skill/tcm-classics-study/scripts/search.py passage --id SW-000004
python skill/tcm-classics-study/scripts/search.py context --id SW-000004 --before 1 --after 1
python skill/tcm-classics-study/scripts/search.py toc --work suwen

# 现代分类/证据
python skill/tcm-classics-study/scripts/modern_evidence.py assess \
  --query "针灸对腰痛有效吗，有什么副作用"
python skill/tcm-classics-study/scripts/modern_evidence.py status --as-of 2026-09-20

# 渲染
python skill/tcm-classics-study/scripts/render.py \
  --input packet.json --format markdown --output answer.md
python skill/tcm-classics-study/scripts/render.py \
  --input packet.json --format html --output answer.html

# 自检
python skill/tcm-classics-study/scripts/self_check.py
```

### 3.3 从已有固定快照完整重建

```bash
python builder/build_character_maps.py
python builder/extract.py
python builder/convert_simplified.py
python builder/segment.py
python builder/validate_corpus.py
python builder/build_source_lock.py
python builder/build_index.py
python builder/build_evidence_cache.py
python builder/stage_runtime_candidate.py
python builder/build_acceptance_set.py
python builder/run_acceptance.py
python builder/benchmark_index.py
```

- **[已确认]** 只有在明确更新来源时才运行：

```bash
python builder/fetch_wikisource.py
```

更新来源会改变修订号和哈希，必须重新运行完整质量链路。

### 3.4 测试

```bash
python -m py_compile builder/*.py skill/tcm-classics-study/scripts/*.py tests/corpus_checks/*.py
python -m unittest discover -s tests -v
python builder/run_acceptance.py
python skill/tcm-classics-study/scripts/self_check.py
```

若只想验证验收而不覆盖仓库内报告，可给 `run_acceptance.py` 传入临时 `--output` 和 `--report` 路径。

### 3.5 打包/部署

```bash
python builder/stage_runtime_candidate.py
python skill/tcm-classics-study/scripts/self_check.py
python builder/build_candidate_package.py
```

默认输出：

- `dist/tcm-classics-study-candidate.zip`
- `dist/tcm-classics-study-candidate.manifest.json`

`build/`、`dist/` 和 Skill 内的临时 `package-candidate-manifest.json` 均不进入 Git。完整安装、升级和回滚见 `docs/INSTALL.md`。

---

## 4. 关键入口文件和重要路径

| 用途 | 路径 | 状态 |
|---|---|---|
| 项目版本 | `VERSION` | **[已确认]** `1.0.0` |
| 版本历史 | `CHANGELOG.md` | **[已确认]** |
| Skill 协议 | `skill/tcm-classics-study/SKILL.md` | **[已确认]** |
| 普通用户手册 | `skill/tcm-classics-study/USER_GUIDE.md` | **[已确认]** |
| 首选运行入口 | `skill/tcm-classics-study/scripts/study.py` | **[已确认]** |
| 经典检索 | `skill/tcm-classics-study/scripts/search.py` | **[已确认]** |
| 现代证据 | `skill/tcm-classics-study/scripts/modern_evidence.py` | **[已确认]** |
| 渲染 | `skill/tcm-classics-study/scripts/render.py` | **[已确认]** |
| 自检 | `skill/tcm-classics-study/scripts/self_check.py` | **[已确认]** |
| 经典 schema | `schemas/classics.sql` | **[已确认]** |
| 证据 schema | `schemas/evidence-cache.sql` | **[已确认]** |
| 经典运行库 | `skill/tcm-classics-study/data/classics.sqlite` | **[已确认]** |
| 证据运行库 | `skill/tcm-classics-study/data/evidence-cache.sqlite` | **[已确认]** |
| 语料质量报告 | `sources/quality-report.json` | **[已确认]** |
| 候选来源锁 | `sources/source-lock.candidate.json` | **[已确认]** |
| 最终来源锁 | `sources/source-lock.json` | **[已确认]** 不存在，属有意行为 |
| 来源署名 | `sources/source-manifest.json` | **[已确认]** |
| 隔离清单 | `sources/corpus-exclusions.json` | **[已确认]** |
| 经典索引清单 | `skill/tcm-classics-study/data/classics-index-manifest.json` | **[已确认]** |
| 证据缓存清单 | `skill/tcm-classics-study/data/evidence-cache.manifest.json` | **[已确认]** |
| 运行时清单 | `skill/tcm-classics-study/data/runtime-candidate-manifest.json` | **[已确认]** |
| 固定验收集 | `tests/acceptance/questions.jsonl` | **[已确认]** 150 题 |

---

## 5. 数据库、数据来源、导入/清洗脚本和数据假设

### 5.1 经典数据库

文件：`skill/tcm-classics-study/data/classics.sqlite`

- **[已确认]** 大小：52,330,496 bytes。
- **[已确认]** SHA-256：`76aeadef973a7ac8a0ed4086d975ab893ccd26decf8f3af38663236312c891d8`。
- **[已确认]** `PRAGMA integrity_check = ok`。
- **[已确认]** `schema_info.schema_version = 2`；`PRAGMA user_version = 0`。
- **[已确认]** 主要计数：
  - `sources=26`
  - `works=26`
  - `source_pages=973`
  - `locations=5,505`
  - `passages=53,798`
  - `aliases=62`
  - `work_targets=27`
- **[已确认]** 主要表：
  - `sources`：来源级许可、哈希和计数；
  - `works`：作品、体系、层级、作者、关系；
  - `work_targets`：扩展作品与六部核心目标的映射；
  - `source_pages`：固定页面和 revision ID；
  - `locations`：卷、篇、子篇、说话者；
  - `passages`：可引用简体段落及内容哈希；
  - `aliases`：作品、体系、作者、术语别名；
  - `passage_fts`：contentless FTS5 二元字符索引。
- **[已确认]** 290 条隔离段物理上不进入 `passages` 和 FTS。

### 5.2 现代证据数据库

文件：`skill/tcm-classics-study/data/evidence-cache.sqlite`

- **[已确认]** 大小：98,304 bytes。
- **[已确认]** SHA-256：`89ae44f34111b0738dd36e23c3f2fd35dfe44ff870921daf4ce314f6d0367dcf`。
- **[已确认]** `PRAGMA integrity_check = ok`。
- **[已确认]** `cache_info.schema_version = 1`；`PRAGMA user_version = 0`。
- **[已确认]** 主要计数：
  - `source_registry=11`
  - `topics=25`
  - `topic_aliases=161`
  - `evidence_records=6`
  - `evidence_record_topics=11`
- **[已确认]** 主要表：`source_registry`、`topics`、`topic_aliases`、`evidence_records`、`evidence_record_topics`、`cache_info`。
- **[已确认]** 截至 2026-09-20，6 条记录均为 fresh；两条急症记录到期日为 2026-12-17，四条 NCCIH 记录到期日为 2027-03-17。

### 5.3 数据来源

- **[已确认]** 26 种古籍/注本来源均为中文 Wikisource 固定修订。
- **[已确认]** 来源作品为公版范围；Wikisource 转录及可版权化编辑按 CC BY-SA 4.0 和站点条款处理。
- **[已确认]** 不打包扫描影像，也不打包现代医学网页全文。
- **[已确认]** 现代缓存只保存项目编写的中文摘要、证据判断和来源元数据。
- **[已确认]** 逐页 oldid、时间和 SHA-256 位于 `sources/source-inventory.json` / `source-manifest.json`。

### 5.4 导入与清洗链路

```text
source-selection/config
  -> fetch_wikisource.py
  -> sources/raw + source-inventory.json
  -> build_character_maps.py
  -> extract.py
  -> convert_simplified.py
  -> segment.py
  -> validate_corpus.py
  -> build_source_lock.py
  -> build_index.py
  -> stage_runtime_candidate.py
```

现代证据链路：

```text
sources/modern/*.json + schemas/*.json/sql
  -> build_evidence_cache.py
  -> evidence-cache.sqlite + manifest
```

### 5.5 数据假设与不变量

- **[已确认]** `text_source` 保留清理后的来源字形，`text_traditional` 用于后台校核，`text_simplified` 用于显示和直接引用，`text_search` 只用于检索。
- **[已确认]** 未解字不得进入可引用语料；原始快照不删除问题字符。
- **[已确认]** 隔离单位是能够可靠识别的最小完整语义单元。
- **[已确认]** 所有可引用段必须 `quality_status=clean`、`citation_allowed=true`、`search_allowed=true` 且 `text_search` 非空。
- **[已确认]** 经典运行库只读打开，不保存用户查询。
- **[根据代码推断]** 段落 ID 依赖切分结果和序列；修改抽取/切分规则可能导致大量 ID 变化，外部收藏的段落 ID 兼容性需要单独评估。

---

## 6. 当前已经完成的功能

- **[已确认]** Phase 0 环境和来源审计。
- **[已确认]** Phase 1 固定修订语料构建、字符治理、简体显示、切分、隔离、追溯和候选锁。
- **[已确认]** Phase 2 SQLite FTS5 检索、路由、过滤、上下文、目录和 benchmark。
- **[已确认]** Phase 3 M0—M3、现代种子缓存、缓存过期、来源检查和联网计划。
- **[已确认]** Phase 4 A/B/C 研究包、Markdown/HTML 可访问渲染及安全优先。
- **[已确认]** Phase 5 150 题验收、候选打包、解压自检和安装文档。
- **[已确认]** 用户使用手册。
- **[已确认]** 项目已建立 SemVer 维护基线 `1.0.0` 和 CHANGELOG。

---

## 7. 当前已知问题、潜在 Bug 和技术债务

### 7.1 已确认问题/限制

1. **来源发布闸门未通过**
   - **[已确认]** `release_gate_status=blocked`，共有 7 项来源级原因：五种核心底本缺第二底本校核、《温病条辨》2 个核心隔离单元、王冰本 805 个低校对/问题页面。
   - **[已确认]** 当前只有 `source-lock.candidate.json`，不得手工改名为最终锁。

2. **现代证据覆盖很小**
   - **[已确认]** 只有 6 条完整页面核验记录；多数 M1/M2 主题仍会要求联网核验。
   - **[已确认]** 两条急症缓存将于 2026-12-17 到期，需要提前复核。

3. **没有数据库迁移框架**
   - **[已确认]** 两个数据库 `PRAGMA user_version=0`，版本只记录在 `schema_info` / `cache_info`。
   - **[已确认]** 当前升级策略是完整重建并整套替换，不支持增量 migration。

4. **没有 CI**
   - **[已确认]** 仓库没有 `.github/workflows/` 或其他 CI 配置；测试目前依赖人工运行。

5. **仓库较大**
   - **[已确认]** 交接完成后跟踪约 164.5 MiB / 1,155 个文件；最大的 `classics.sqlite` 为 52,330,496 bytes。
   - **[已确认]** Git LFS 已安装在本机，但仓库当前未使用 LFS。
   - **[待确认]** 是否长期继续直接跟踪数据库和大型 JSONL，还是迁移到 Release/LFS。

6. **部分阶段文档是历史快照**
   - **[已确认]** 例如 `docs/phase1-summary.md` 仍记载 Phase 1 当时的 18 项测试，不代表当前 38 项总测试；应以 README、本交接文档和最新测试为准。

### 7.2 根据代码推断的潜在 Bug/债务

1. **字符预算首条超限风险**
   - **[根据代码推断]** `study.py::fit_budget()` 在 `selected` 为空时会无条件接收第一条结果；若第一条本身超过分层预算，可能突破声明的预算。现有已测查询未触发。

2. **单字符检索召回有限**
   - **[根据代码推断]** 索引主体是重叠二元字符；虽然查询函数接受单字符 token，但数据库主体未专门建立一元索引，单字问题可能召回差。

3. **规则分类和路由可能误判口语问题**
   - **[根据代码推断]** M0—M3、古籍范围和关键词提取主要依赖固定词表/子串规则；复杂否定、同形词、口语和错别字可能产生误报或漏报。

4. **结果“相关但不够好读”尚无质量指标**
   - **[根据代码推断]** 当前验收偏重 Recall@5 和分类正确性，没有对首条精准度、过短碎片、过长旁支段落、解释可读性作自动评分。

5. **SQLite 兼容下限没有被严格编码**
   - **[根据代码推断]** schema 使用 `STRICT` 表，运行依赖 FTS5；当前仅在 SQLite 3.50.4 上确认。`SKILL.md` 写 Python 3.9+，但不同 Python 3.9 发行版捆绑的 SQLite 版本可能不同。

6. **版本号尚未传播到运行时 manifest/ZIP 文件名**
   - **[已确认]** SemVer 当前以根目录 `VERSION` 为准；运行时 manifest 仍只有自身 schema version，默认 ZIP 名仍是 `candidate.zip`。

### 7.3 尚未确认

- **[待确认]** GitHub 分支保护、Actions 权限、Release 流程和仓库可见性设置。
- **[待确认]** Python 3.9—3.13、Linux/macOS 的兼容矩阵。
- **[待确认]** WorkBuddy 实际网页工具调用接口；按用户决定，这不属于代码完成条件。
- **[待确认]** ZIP 是否能做到跨机器 bit-for-bit 可复现；当前未做 reproducible-build 测试。
- **[待确认]** 高并发、多进程并发读取和极端大输入行为。

---

## 8. 未完成事项和建议改进方向（按优先级）

### P0：正确性和维护基线

1. 为 `fit_budget()` 的首条超限情况补失败测试并修正预算语义。
2. 建立 CI，至少覆盖 Python 3.9/3.11/当前版本、SQLite FTS5、自检和 38 项 unittest。
3. 明确最低 SQLite 版本；在自检中输出/验证版本和 `STRICT`/FTS5 兼容性。
4. 在 2026-12-17 前复核 CDC/NHS 两条急症证据记录。

### P1：检索与回答质量精修

1. 建立更接近真实读者的白话、记忆不完整、错别字、连续追问测试集。
2. 增加首条 Precision、短碎片抑制、超长旁支抑制和回答信息密度指标。
3. 评估一元/二元/三元混合索引，或为单字、篇名、方名提供专门回退。
4. 在不改变直接引文的前提下，完善“简要/标准/深入”研读模式和逐句解释协议。

### P1：底本质量线

1. 为 `core-suwen`、`core-lingshu`、`core-shanghanlun`、`core-jingui`、`core-nanjing` 完成第二许可明确底本校核。
2. 核定《温病条辨》2 个核心隔离语义单元。
3. 对王冰本 805 个低校对页完成抽检、校对、替换或降级决策。
4. 只有质量报告真正为 `pass` 时才生成最终 `source-lock.json`。

### P2：现代证据和发布工程

1. 按真实高频主题扩充核验记录，建立到期复核流程。
2. 将 `VERSION` 传播到 runtime/package manifest 和带版本的 ZIP 文件名。
3. 评估 GitHub Release 或 Git LFS，降低主仓库数据库/语料体积。
4. 建立数据库 schema 兼容策略；若未来存在用户可写 overlay，再设计正式 migration。

---

## 9. 测试情况

### 9.1 本次交接实测（2026-09-20）

- **[已确认]** `py_compile`：通过。
- **[已确认]** `unittest`：38/38 通过，0 失败、0 错误。
  - Phase 0：9
  - Phase 1：9
  - Phase 2：4
  - Phase 3：11
  - Phase 4：5
- **[已确认]** 运行时 `self_check.py`：`status=pass`。
  - 两个 SQLite integrity 均为 `ok`；
  - 53,798 条经典段；
  - 290 条隔离排除；
  - 6 条现代记录；
  - 经典搜索、研究包、Markdown、M3 暂缓古籍均通过。
- **[已确认]** 150 题临时输出验收：280/280 检查通过，`status=pass`；本次 P50/P95 为 1.304/7.652 ms（性能值受机器状态影响）。
- **[已确认]** 当前候选 ZIP 在新临时目录解压后执行自检：通过。
- **[已确认]** 当前经典数据库和证据数据库 `PRAGMA integrity_check=ok`。

### 9.2 已记录 benchmark

- **[已确认]** 当前 DB hash 对应的 `build/index-benchmark.json`：路由/召回 24/24。
- **[已确认]** 记录值：内部 P50/P95 4.101/15.209 ms；含进程启动 P50/P95 714.162/1206.405 ms。
- **[已确认]** 这些是开发机数据，不是跨平台承诺。

### 9.3 未覆盖

- **[已确认]** 无 CI 平台矩阵。
- **[已确认]** 没有真实联网抓取适配器的端到端测试。
- **[已确认]** 没有数据库 migration 测试。
- **[已确认]** 没有并发、压力、模糊输入和超大输入测试。
- **[已确认]** 没有对自然语言解释质量作人工评分或自动 golden 对比。
- **[待确认]** WorkBuddy 宿主集成表现。

当前已知失败测试：**无**。

---

## 10. 配置项、环境变量、外部服务和依赖

### 10.1 配置

- `sources/phase1-work-config.json`：Phase 1 作品抓取/结构配置。
- `sources/source-selection.json`：作品选择和排除。
- `sources/search-aliases.json`：作品、作者、术语路由别名。
- `sources/normalization/*.json`：字符映射、依赖、人工修复、显示转换覆盖。
- `sources/modern/*.json`：可信来源、主题、证据记录和完整页面审计。
- `schemas/*.sql` / `*.schema.json`：数据库和输入验证契约。

### 10.2 环境变量

- **[已确认]** 运行时没有必需环境变量。
- **[已确认]** 不需要 API Key 或 Token。
- **[已确认]** `check_environment.py` 只检测是否存在 `PI_*`，不把它当作业务配置。
- **[已确认]** `audit_legacy_skill.py` 为子进程设置 `PYTHONUTF8=1` / `PYTHONIOENCODING=utf-8`。

### 10.3 外部服务

- Wikisource：构建期来源抓取；运行时经典检索不联网。
- WorkBuddy 网页搜索/网页读取：现代缓存不足或要求最新时的宿主能力；代码只输出搜索计划。
- NCCIH、CDC、NHS 等：现代证据来源页面，不打包网页全文。
- PubMed：历史环境中 Python 直连曾受本机证书链影响；不得关闭 TLS 验证绕过。

### 10.4 当前本机环境

- **[已确认]** Windows 环境。
- **[已确认]** Python 3.14.1。
- **[已确认]** SQLite 3.50.4，FTS5 可用。
- **[已确认]** OpenSSL 3.0.18。
- **[已确认]** Git 2.51.2；Git LFS 3.7.1 已安装但未使用。

---

## 11. 重要设计决策及原因

1. **SQLite FTS5，不在运行时扫描 JSON**
   - **[已确认]** 旧包查询需加载/扫描大 JSON；预构建索引显著降低内部检索延迟和内存压力。

2. **不默认使用向量模型**
   - **[已确认]** 当前采用可审计的字符索引、别名和规则路由，避免模型下载、网络依赖和不可解释召回。

3. **简体前台，繁体后台保留**
   - **[已确认]** 满足用户阅读需要，同时保留来源快照和转换链路用于校核。

4. **问题段物理排除运行时**
   - **[已确认]** 290 条隔离段不进入经典数据库，避免模型或接口绕过标记引用问题文本。

5. **候选可运行与最终来源锁分离**
   - **[已确认]** 代码功能可以验收，但不得用功能完成掩盖底本风险。

6. **A/B/C 固定知识层级**
   - **[已确认]** 防止把原典、后世解释和现代证据混成单一权威结论。

7. **M0—M3，急症安全优先**
   - **[已确认]** 文献问题不硬凑现代层，现实急症不被古籍讨论延误。

8. **现代网页只存摘要和元数据**
   - **[已确认]** 降低许可风险和包体积；搜索摘要不得作为证据。

9. **查询隐私最小化**
   - **[已确认]** 本地工具不记录原始查询；联网计划使用通用主题词，不要求提交完整健康问题。

10. **数据库与 manifest 哈希绑定**
    - **[已确认]** 自检可发现脚本、文档、数据库和清单被单独替换或损坏。

---

## 12. 数据库修改、迁移、兼容性和回滚风险

### 12.1 当前策略

- **[已确认]** 没有增量 migration；修改 schema、语料、别名或证据输入后完整重建。
- **[已确认]** 构建数据库时先写 `.tmp`，通过完整性和计数检查后 `os.replace` 原子替换。
- **[已确认]** 运行时用 SQLite `mode=ro` 和 `query_only`，种子数据库视为只读。

### 12.2 修改风险

- 修改 `schemas/classics.sql`、切分、别名或语料会改变 DB hash，并可能改变段落 ID、召回顺序和引用兼容性。
- 修改 `schemas/evidence-cache.sql` 或现代 JSON 会改变证据 DB hash、缓存行为和有效期。
- 修改任一 runtime 文件后必须重新执行 `stage_runtime_candidate.py`，否则 `self_check.py` 会报 hash mismatch。
- 打包前必须先刷新 runtime manifest；`build_candidate_package.py` 会拒绝缺少必要运行文件的清单。
- **[根据代码推断]** 未来若加入用户可写 overlay，不能与只读种子 DB 混合覆盖，需要单独 schema/version/migration 设计。

### 12.3 正确重建顺序

1. 更新 schema/输入；
2. 重跑相应清洗与质量验证；
3. 重建经典/证据 DB；
4. 刷新 runtime candidate；
5. 全量测试和 150 题验收；
6. benchmark；
7. 打包并解压自检；
8. 更新 VERSION/CHANGELOG/交接文档。

### 12.4 回滚

- **[已确认]** 应回滚整个 `skill/tcm-classics-study/` 版本，而不是只替换某个 `.sqlite` 或脚本。
- **[已确认]** 数据库、manifest 和脚本必须保持同一构建批次，否则哈希自检失败。
- **[已确认]** `build/` 和 `dist/` 被 Git 忽略，不能依赖 Git 恢复本地 ZIP；可从对应 Git tag 重建。
- **[待确认]** 目前没有自动化 Release artifact 保留策略。

---

## 13. 当前 Git 状态和安全注意事项

### 13.1 分支与远端

- **[已确认]** 分支：`main`。
- **[已确认]** 上游：`origin/main`。
- **[已确认]** remote：`https://github.com/qtxxgedfs/zhongyi.git`。
- **[已确认]** 本交接版本使用 tag：`v1.0.0`；用 `git rev-parse v1.0.0^{}` 获取精确提交。
- **[已确认]** 本次交接提交完成并推送后应为 clean；若不是，先执行 `git status --short --branch` 查明原因。
- **[已确认]** 最近提交（交接提交本身的 hash 以 `v1.0.0^{}` 为准）：
  - `chore: establish v1.0.0 maintenance handoff`
  - `7bc9810 docs: add reader-friendly user guide`
  - `704e15e docs: mark deployment validation as user-managed`
  - `db842f8 feat: complete runnable TCM classics study candidate`
  - `1236c3d Initial commit`
- **[待确认]** 分支保护和强制审查规则。

### 13.2 敏感文件审计

- **[已确认]** 当前跟踪树未发现 `.env`、密码文件、API Key、Token、证书、私钥、用户查询日志或真实用户隐私数据库。
- **[已确认]** 两个跟踪的 SQLite 是产品只读语料/证据数据库，不是用户数据库备份；未发现用户隐私数据。
- **[已确认]** `build/`、`dist/`、缓存、`__pycache__`、WAL/SHM 和本地 package manifest 均被忽略。
- **[已确认]** `memo.md` 是用户自有备忘录：本地保留、Git 忽略，并从远程分支历史中移除；后续 Agent 不得提交。
- **[已确认]** `TASK_CHECKPOINT.md` 是本地历史会话存档，Git 忽略，不代表当前状态。

### 13.3 需要特别注意的跟踪文件

- `skill/tcm-classics-study/data/classics.sqlite`：约 49.9 MiB，运行时必需，不是备份。
- `sources/raw/`：固定来源快照，更新会改变来源哈希。
- `sources/processed/`：可复核结构化语料，大文件较多。
- `sources/source-lock.candidate.json`：候选锁，不得冒充最终锁。
- `NOTICE.md` / `source-manifest.json`：分发时必须保留。

---

## 给下一位 Agent 的最短检查清单

1. 先读 `VERSION`、`CHANGELOG.md`、本文件、`README.md`、`SKILL.md`。
2. 执行 `git status --short --branch`，确认没有误跟踪 `memo.md`、构建物或凭据。
3. 执行 `self_check.py` 和 38 项 unittest。
4. 修改检索/切分/schema 前先评估段落 ID、DB hash 和回滚兼容性。
5. 不得手工生成或改名 `sources/source-lock.json`。
6. 不得把隔离段重新塞入检索库，除非已有可审计修复依据并重跑完整质量链路。
7. 修改运行时文件后必须刷新 runtime manifest，再打包和解压自检。
