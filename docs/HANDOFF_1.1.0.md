# 项目交接 — 1.1.0

> 分支：`main`  
> 运行状态：`candidate-runnable`  
> 来源发布闸门：`blocked`  
> 工作底本定位：可追溯候选，不是无异文、无错误的权威定本

## 1. 本版交付

- 自然问法支持：任务词清理、口语与记忆残片扩展、精确/关键词/宽松字符召回、原典优先重排。
- 结果治理：短残片与弱相关抑制、核心引文优先、全文和前后文展开、来源记混软回退。
- 统一研读协议：只保留一种标准深度；A原典、B医家、C现代医学严格分层，无依据时不凑层。
- 连续追问：以 `primary_passage_id` / `study.py --anchor-id` 显式承接，不保存隐式会话状态。
- 《温病条辨》两处影像确认缺字已修订，`WBTB-000004`、`WBTB-000209` ID不变并恢复检索引用。
- 完成五部核心第二见证代表篇章试校、王冰本分层试跑及CText《灵枢》少量人工参考。

## 2. 当前数据与产物

| 项目 | 当前值 |
|---|---:|
| 作品 / 固定页面 / 纳入页面 | 26 / 973 / 938 |
| 结构化 / 可引用 / 隔离段落 | 54,088 / 53,800 / 288 |
| 六部核心隔离段 | 0 |
| 现代证据核验记录 | 6 |
| 经典运行时数据库 SHA-256 | `35316630ad2105cf9384376062f1c524994b63b633a75fbdd8b41130dbf21fc2` |
| 现代证据数据库 SHA-256 | `89ae44f34111b0738dd36e23c3f2fd35dfe44ff870921daf4ce314f6d0367dcf` |

运行时数据库位于 `skill/tcm-classics-study/data/`，是离线Skill产品数据，不是用户数据库备份。两个SQLite的 `integrity_check` 均为 `ok`。

## 3. 已验证基线

- Python编译检查：通过。
- `unittest`：48/48通过。
- 固定验收：150题、280/280项通过。
- 自然问法：60题；首条可接受50/50，来源记混恢复10/10，结果质量60/60。
- 连续追问：10组、30轮；上下文锚点10/10。
- Benchmark：12场景、24/24；内部检索P95为36.913 ms。
- 运行时自检：通过；经典库和证据库完整性均为 `ok`。
- 候选ZIP已通过临时目录解压安装测试；`dist/` 为本地构建产物，不进入Git。

## 4. 不可破坏的边界

- 古籍直接引文只能来自数据库 `text_simplified` 或其连续子串 `core_quote`。
- 隔离段不得进入索引、检索或回答；不得为凑数量展示弱相关或残缺材料。
- A原典、B医家、C现代医学必须分层；M3问题必须先安全分流。
- 原始固定快照不因人工校字而覆盖；修订证据写入 `sources/normalization/`。
- 未经影像或可靠底本支持，不按语义顺畅度裁改异文。
- Kanripo 当前只作候选比较见证，不复制全文进项目或发布包，不称正式第二底本。
- 不生成最终 `sources/source-lock.json`，除非质量报告的发布闸门真实通过。

## 5. 尚未解除的发布阻断

质量报告当前有6项来源级阻断：

1. 《素问》《灵枢》《伤寒论》《金匮要略》《难经》尚未完成全量、逐项留痕的第二见证校勘；
2. 王冰本纳入的805页均为ProofreadPage等级0/1，且王冰注与“新校正”无法可靠自动重分层。

Kanripo 的组织级许可声明尚未证明明确覆盖各文本仓库转录；固定提交可保证复现，但不能证明电子转录链独立。详细证据见 Phase 7 报告。

## 6. 关键文件

- 检索规则：`skill/tcm-classics-study/data/query-rules.json`
- 检索与研读：`skill/tcm-classics-study/scripts/search.py`、`study.py`、`render.py`
- 回答协议：`skill/tcm-classics-study/references/answer-policy.md`
- 自然问法验收：`tests/natural/`、`builder/run_natural_acceptance.py`
- 影像校字：`sources/normalization/passage-text-corrections.json`
- 第二见证审计：`sources/collation/second-witness-candidates.json`、`pilot-results.json`
- 阶段报告：`docs/phase6-usability-report.md`、`docs/phase7-second-witness-pilot-report.md`、`docs/phase7-ctext-lingshu-reference-report.md`
- 质量与来源：`sources/quality-report.json`、`sources/source-lock.candidate.json`、`sources/source-manifest.json`

## 7. Git与本地文件边界

- `.env`、密钥、证书、数据库备份、`build/`、`dist/`、缓存、临时文件均由 `.gitignore` 排除。
- `memo.md` 和 `TASK_CHECKPOINT.md` 是本地用户/会话文件，不得提交。
- 仓库及候选提交文件已做高置信凭据扫描，未发现API Key、Token、私钥或带凭据URL。
- 原始扫描、Kanripo临时克隆、CText页面正文和 `09医藏-0869部.zip` 均未进入仓库或发布包。

## 8. 下一阶段建议

当前功能与数据清理阶段可视为完成。若继续来源质量线，优先顺序为：

1. 《灵枢》；
2. 《金匮要略》；
3. 《难经》（SBCK主比较、WYG第三见证）；
4. 《素问》（只抽经文）；
5. 《伤寒论》（按条文锚点比较）。

每次语料变更后依次运行：`segment.py`、`validate_corpus.py`、`build_source_lock.py`、`build_index.py`、`stage_runtime_candidate.py`、完整测试、两套验收、benchmark、自检和候选包安装测试。
