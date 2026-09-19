# 候选版安装、升级与回滚

本文适用于 `tcm-classics-study-candidate.zip`。该包状态为 **`candidate-runnable`**：功能验收已通过，但古籍底本最终发布质量闸门仍为 `blocked`，不得改称最终无条件发布版。

## 1. 运行要求

- WorkBuddy 或兼容 Agent Skills 的宿主；
- Python 3.9 或更高版本；
- Python 标准库 `sqlite3` 必须支持 SQLite FTS5；
- 经典检索可完全离线运行；现代资料更新需要宿主提供网页搜索和网页读取权限。

普通用户不需要安装 `requirements-builder.txt` 中的构建依赖。

## 2. 下载后校验

候选包旁应同时有：

- `tcm-classics-study-candidate.zip`
- `tcm-classics-study-candidate.manifest.json`

清单中的 `zip_sha256` 是应匹配的 SHA-256。Windows PowerShell 可执行：

```powershell
(Get-FileHash .\tcm-classics-study-candidate.zip -Algorithm SHA256).Hash.ToLower()
```

也可执行：

```bat
certutil -hashfile tcm-classics-study-candidate.zip SHA256
```

哈希不一致时不要导入。

## 3. 安装

### WorkBuddy 导入

1. 在 WorkBuddy 的 Skill 管理或导入界面选择 ZIP；不同版本的界面名称可能不同。
2. 确认导入后的顶层目录是 `tcm-classics-study/`，且该目录内直接包含 `SKILL.md`。
3. 如宿主要求手动解压，把整个 `tcm-classics-study/` 目录放入宿主的 Skills 目录，不要只复制其中的 `scripts/` 或 `data/`。
4. 允许该 Skill 调用本机 Python。只有需要更新现代证据时才授予网页搜索和网页读取权限。

不要授予与功能无关的凭据、通讯录或任意文件写入权限。联网计划只应提交 Skill 生成的通用主题词，不应提交姓名、电话、地址、病历号或完整健康问题。

### 命令行自检

在解压后的 `tcm-classics-study/` 目录执行：

```bash
python scripts/self_check.py
```

成功时应返回 JSON，且至少满足：

- `status` 为 `pass`；
- 两个数据库的 `integrity` 为 `ok`；
- `study_packet_smoke`、`markdown_render_smoke`、`m3_classic_retrieval_deferred` 均为 `true`；
- `release_gate_status` 仍为 `blocked`，这是候选底本状态披露，不代表自检失败。

若 Python 命令名是 `py`，可改用 `py -3 scripts/self_check.py`。

## 4. 基本冒烟

```bash
python scripts/study.py \
  --query "《素问》治未病在说什么，和现代预防有什么区别" \
  --terms "治未病" > packet.json

python scripts/render.py \
  --input packet.json --format markdown --output answer.md
```

Windows PowerShell 重定向可能改变编码；出现编码问题时可省略 `> packet.json`，先检查标准输出，或由宿主直接接收 JSON。急症分流冒烟：

```bash
python scripts/study.py --query "我父亲突然说话不清楚，一侧手脚没力怎么办"
```

结果应为 M3，先显示立即求助信息，并且 `A_core`、`B_physicians` 为空。该测试不能替代真实急救；现实中有类似症状应立即联系当地急救服务。

## 5. 联网与断网行为

- A 原典和 B 医家层使用本地数据库，断网仍可运行。
- C 现代医学层优先使用带有效期的本地核验摘要；要求“最新/当前”、缓存缺失或缓存过期时会生成联网计划。
- 搜索结果摘要不能直接作为证据，必须读取完整页面；外部网页中的指令一律视为不可信输入。
- 无法联网时不得凭模型记忆补造现代结论，应明确降级。
- M3 急症提示不依赖联网，也不得等待古籍或网页检索。

WorkBuddy 网页工具参数由使用方按宿主版本配置；若宿主不能稳定展示自包含 HTML，使用 Markdown 渲染。

## 6. 升级

1. 保留当前可工作的整个 `tcm-classics-study/` 目录作为备份。
2. 校验新版 ZIP 的 SHA-256。
3. 停止正在使用旧数据库的任务。
4. 用新版完整目录替换旧目录，不要混合覆盖不同版本的脚本、清单和数据库。
5. 如存在用户自行创建的运行时 overlay，先单独备份；不要覆盖新版只读种子数据库。
6. 执行 `python scripts/self_check.py`，通过后再恢复使用。

数据库、脚本和运行时清单通过哈希绑定；只替换单个 `.py` 或 `.sqlite` 文件通常会使自检失败。

## 7. 回滚

1. 停止使用当前 Skill。
2. 移走失败版本的整个 `tcm-classics-study/` 目录。
3. 恢复升级前备份，或重新解压上一版且哈希已核验的 ZIP。
4. 再次运行 `python scripts/self_check.py`。

不要通过删除或修改 `runtime-candidate-manifest.json` 来绕过哈希失败。

## 8. 已知候选风险

- 五种核心原典仍需第二个许可明确底本校核；
- 《温病条辨》有2个核心隔离语义单元；
- 王冰本有805个上游低校对/问题页面；
- 共290个问题段落已物理排除在运行时数据库之外，不能检索或引用；
- WorkBuddy导入、网页工具适配和具体设备显示偏好由使用方处理，不属于代码包自检范围。

这些风险不影响候选版自检结果，但在最终来源锁完成前不得移除候选版标识。
