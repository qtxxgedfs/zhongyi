# 中医四部经典研读 Skill

面向 WorkBuddy 的古典医籍研读与现代医学对照项目。产品范围、技术路线和验收要求见 [`CODING_PLAN.md`](CODING_PLAN.md)。

## 当前状态

- **代码版本：`1.0.0`**，版本规则与历史见 `VERSION` 和 `CHANGELOG.md`。
- **Phase 0：已完成**，见 `docs/phase0-summary.md`。
- **Phase 1 构建流水线：已完成；发布质量闸门：未通过**，见 `docs/phase1-summary.md` 和 `docs/phase1-quality-report.md`。
- **Phase 2 索引与检索：已完成候选版**，已生成可审计的本地 SQLite FTS5 索引和检索 CLI。
- **Phase 3 现代医学证据层：已完成首个可运行版**，见 `docs/phase3-modern-evidence-report.md`。
- **Phase 4 回答与渲染：已完成**，单调用研究包可输出可访问 Markdown 或自包含 HTML。
- **Phase 5 功能验收：已通过**，150题、280/280项检查通过；候选包可用构建脚本生成到 `dist/`。
- 已固定26种作品、973个页面修订，938页进入语料；共54,088条结构化段落，其中53,798条可引用、290条隔离（另丢弃3条纯标点格式碎片）。
- 原始哈希和结构完整性检查通过；可引用语料未解字为零，清洗状态为 `pass-with-quarantine`。
- 因五种核心底本尚未完成第二底本校核、《温病条辨》仍有2个核心隔离单元、王冰本805页低校对等级，当前只生成 `sources/source-lock.candidate.json`；**没有生成最终 `source-lock.json`**。

按当前交付范围，代码实现、自动测试、功能验收、运行时自检和候选包构建已经完成。WorkBuddy导入适配及具体用户设备验证由使用方处理，不作为代码完成条件。面向普通读者的使用说明见 [`USER_GUIDE.md`](skill/tcm-classics-study/USER_GUIDE.md)。

`skill/tcm-classics-study/` 现在是可离线运行和安装测试的 **`candidate-runnable` 候选版**，经典数据库和现代证据种子缓存均已装入。它仍不是最终无条件发布版，不能绕过质量闸门把候选锁改名为最终来源锁。

主要产物：

- `sources/source-inventory.json`：逐页修订、角色、原始路径和 SHA-256
- `sources/raw/`：固定修订 wikitext 快照
- `sources/processed/`：来源文本、繁体工作字段、简体显示字段和检索字段
- `sources/quarantine/`：保留但禁止搜索、禁止引用的未解语义单元
- `sources/corpus-exclusions.json`：逐条隔离原因、位置和修订来源
- `sources/completeness-manifest.json`：26种作品的结构完整性清单
- `sources/quality-report.json`：机器可读质量闸门结果
- `sources/source-lock.candidate.json`：被质量闸门阻断的候选来源锁
- `sources/source-manifest.json`、`NOTICE.md`：逐页署名追溯和许可说明
- `build/classics.sqlite`：约49.9 MiB 的候选运行时索引，只含53,798条可引用段落
- `build/classics-index-manifest.json`：数据库哈希、输入哈希、计数和索引算法
- `skill/tcm-classics-study/data/classics.sqlite`：已装入Skill的候选经典索引
- `skill/tcm-classics-study/scripts/search.py`：检索、段落读取、上下文和目录 CLI
- `skill/tcm-classics-study/data/evidence-cache.sqlite`：25个主题、6条完整页面核验记录的现代证据种子缓存
- `skill/tcm-classics-study/scripts/modern_evidence.py`：M0—M3分类、缓存读取、联网计划和来源检查
- `skill/tcm-classics-study/scripts/study.py`：首选单调用入口，生成A/B/C分层研究包
- `skill/tcm-classics-study/scripts/render.py`：可访问Markdown和自包含HTML渲染
- `skill/tcm-classics-study/scripts/self_check.py`：运行时数据库、哈希、计数、研究包、渲染和M3分流自检
- `skill/tcm-classics-study/USER_GUIDE.md`：面向普通读者的大字友好使用手册
- `tests/acceptance/questions.jsonl`、`build/acceptance-results.json`：150题固定验收集及结果

## 重建 Phase 1 语料

先安装构建依赖：

```bash
python -m pip install -r requirements-builder.txt
```

已有快照时，从字符映射开始重建：

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
python -m unittest discover -s tests -v
python builder/run_acceptance.py
python builder/benchmark_index.py
```

首次或明确需要更新来源时才运行 `builder/fetch_wikisource.py`。抓取与审计脚本带缓存、限速和重试；更新会改变修订号与哈希，必须重新走完整质量流程。

候选索引检索示例：

```bash
python skill/tcm-classics-study/scripts/search.py search \
  --query "《素问》治未病怎么说" --terms "治未病"
python skill/tcm-classics-study/scripts/search.py context \
  --id SW-000004 --before 1 --after 1
python skill/tcm-classics-study/scripts/modern_evidence.py assess \
  --query "针灸对腰痛有效吗，有什么副作用"
python skill/tcm-classics-study/scripts/study.py \
  --query "《素问》治未病在说什么，和现代预防有什么区别" --terms "治未病"
python skill/tcm-classics-study/scripts/render.py \
  --input packet.json --format markdown --output answer.md
python skill/tcm-classics-study/scripts/self_check.py
```

性能和召回结果见 `docs/phase2-index-report.md`，现代证据层见 `docs/phase3-modern-evidence-report.md`，安装、升级和回滚见 `docs/INSTALL.md`。当前38项自动测试全部通过，固定验收集150题、280/280项检查通过。

构建并解压自检候选包：

```bash
python builder/build_candidate_package.py
```

生成的 `dist/tcm-classics-study-candidate.zip` 仍是 `candidate-runnable` 候选版，不代表文本发布质量闸门已经解除。

## 目录约定

- `skill/`：最终进入用户 ZIP 的最小运行时内容
- `builder/`：抓取、转换、切分、建索引和发布工具，不进入普通用户包
- `sources/raw/`：固定修订版繁体来源快照，不向最终用户界面展示
- `sources/processed/`：结构化和简体处理结果
- `sources/cache/`：可删除的网络审计缓存
- `docs/`：来源、环境、性能和发布报告
- `tests/`：语料、检索、安全与渲染验收

## 安全定位

本项目用于经典研读、学术比较和现代医学证据对照，不提供个体诊断、辨证处方、剂量换算或停换药建议。
