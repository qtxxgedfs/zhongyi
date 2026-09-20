# 项目交接 — 1.1.1

> 版本/发布标签：`1.1.1` / `v1.1.1`；分支：`main`。
> 远程：`https://github.com/qtxxgedfs/zhongyi.git`。
> 运行状态：`candidate-runnable`；来源发布闸门：`blocked`。本版为自`v1.1.0`后的PATCH修复；交接收尾不再修改功能代码、原始语料、段落ID或数据库结构。

## 1. 本次交付

- 修复自然语言指定医家/书籍被代表段落误触发全库回退，以及注文“原文/怎么说”被强求原典命中的问题。
- 医家别名归并、完整注书名识别、硬范围与排除对象、多对象召回及覆盖检查。
- 一般范围题单列范围外备选；出处核对题保留披露后的软回退。不再要求提示读者“可能记混”。
- 查询扩展保留引号原句、关注点、比较双方；经文转引不再占注文名额。
- A/B共享预算、上下文锚点优先、已检得未展示与未检得区分、最终引用白名单与覆盖一致。
- Markdown/HTML明确为材料预览，关系标签中文化，空层省略；更新协议、使用与安装文档。

详细根因、实现和验收预期调整见 [`1.1.1-refinement-report.md`](1.1.1-refinement-report.md)。上版语料与来源审计交接仍见 [`HANDOFF_1.1.0.md`](HANDOFF_1.1.0.md)。

## 2. 已验证基线

- 编译：31个Python文件通过。
- 单测：70/70（新增22项精修回归）。
- 固定验收：150题、280/280。
- 自然问法：主结果/备选首条50/50；范围行为、澄清、结果质量均60/60。
- 连续追问：10组30轮，锚点10/10。
- Benchmark：24/24，内部检索P95为53.582 ms。
- 自检、SQLite完整性和候选ZIP临时解压安装测试通过；交接时Git暂存树的独立导出也通过70/70单测、280/280固定验收、60题自然验收及自检（未跳过测试）。
- 全套测试需要 `requirements-builder.txt`；仅运行Skill需要Python 3.9+及标准库SQLite FTS5。新检出没有 `build/`，4项索引测试会跳过；构建索引或将产品经典库及其清单复制到该目录后可运行全部70项。

## 3. 数据与包

- 26作品、54,088结构化段、53,800可引用、288隔离；六部核心隔离为0。
- 现代证据25主题、6条核验记录。
- 经典库SHA-256：`35316630ad2105cf9384376062f1c524994b63b633a75fbdd8b41130dbf21fc2`。
- 证据库SHA-256：`89ae44f34111b0738dd36e23c3f2fd35dfe44ff870921daf4ce314f6d0367dcf`。
- `dist/tcm-classics-study-candidate.zip` 为本地1.1.1候选包（不入Git），配套外部manifest包含ZIP哈希；升级须整包替换，不能混用旧脚本与新清单。
- 两个SQLite是公开古籍和核验摘要组成的产品运行时数据，不是用户数据库备份；无用户表或会话日志表。

## 4. 宿主接入要点

- 保留schema v2和既有CLI；`study.py`新增 `--no-route-fallback`。
- 搜索层 `alternative_results` 对应研究包 `source_alternatives`；必须与指定范围材料分开展示，不替代指定医家观点。
- `scope_coverage`逐对象报告 `matched`、`not-found`、`not-displayed`、`not-displayed-budget`；缺项时不得宣称比较完成。
- `quality_policy.budget_omitted`列出已检得但未展示的ID。`primary_passage_id`为空时先解释原因，不把未展示锚点冒充可引用材料。
- `--anchor-id`只做全文/前后文展开，不保存隐式会话状态；新比较应显式提交条文关键词。
- 渲染器是材料预览，不生成白话解释。宿主仍按 `answer_contract`组织最终研读。
- `speaker_type=quoted_core`仅为注书转引经文；不能因来自某医家著作就当作该医家独立观点。

## 5. 回归注意事项

- 所有60道自然题均断言冲突标记，默认false。
- NQ033/035/037/038按确认的新协议改为检查单列备选，题内保留调整说明；不能恢复“无依据则自动换人”的旧预期。
- `tests/corpus_checks/test_refinement_runtime.py`包含不传人工terms的反馈案例、两/三医家比较、注书名、否定限定、关注点、预算、引用及渲染检查。
- 关键入口：`skill/tcm-classics-study/scripts/{search,study,render,self_check}.py`；查询规则在 `skill/tcm-classics-study/data/query-rules.json`；回答协议在 `skill/tcm-classics-study/references/answer-policy.md`。
- 修改运行时文件后重新执行 `builder/stage_runtime_candidate.py`，再跑全套测试、两套验收、benchmark、自检、`builder/build_candidate_package.py`。
- **字节完整性：** `.gitattributes` 对 `sources/**` 和 `skill/tcm-classics-study/**` 使用 `-text`，保留哈希绑定文件的现有LF/CRLF字节。不要批量转换换行或撤销该属性；清单哈希必须与Git实际存储、检出的字节一致。

## 6. 不变的边界

直接引文只取数据库 `text_simplified` 或连续子串；隔离段禁止检索引用；A/B/C分层及M3优先不变。未改原始快照、未新增最终来源锁，来源阻断仍按1.1.0交接处理。WorkBuddy目标设备验证及白话解释人工评审尚需使用方完成。

`.env`、密钥、缓存、`build/`、`dist/`、临时目录、数据库备份、`memo.md`、`TASK_CHECKPOINT.md`不得提交。已检查远程现行树及可达历史，未发现禁推文件或高置信凭据；发布提交由 `v1.1.1` 标签定位（`git log -1 v1.1.1`）。

## 7. 下一阶段

- 功能精修已完成，优先由使用方验证WorkBuddy实际展示、网页接入和生成式白话解释质量；确定性渲染通过不代表这些人工评审已完成。
- 文本质量线仍有6项来源级阻断：五部核心待全量第二见证校勘，王冰本805页低校对等级及混合分层问题。按已确认计划暂缓时，不重建、不伪造最终来源锁。
- 无数据库增量迁移框架；变更采用整套重建、验收和整包回滚。接手先运行 `python skill/tcm-classics-study/scripts/self_check.py`，再依据任务查看精修报告及1.1.0交接中的来源边界。
