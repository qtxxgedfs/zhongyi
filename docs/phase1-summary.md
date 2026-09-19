# Phase 1 完整语料构建摘要

## 状态

Phase 1 的固定修订抓取、正文抽取、字符治理、繁简转换、结构切分、完整性检查和来源锁生成器已经完成。

**发布质量闸门仍为 `blocked`。** 因此当前产物是
`sources/source-lock.candidate.json`，而不是最终 `sources/source-lock.json`。
这一区分是有意的：固定修订成功不等于文本质量已经达到可发布门槛。

## 构建规模

| 项目 | 数量 |
|---|---:|
| 独立作品 | 26 |
| 原典 | 6 |
| 扩展/源流 | 20 |
| 固定页面快照 | 973 |
| 纳入语料页面 | 938 |
| 结构化段落 | 54,088 |
| 可引用段落 | 53,798 |
| 隔离段落 | 290 |
| 丢弃的纯标点格式碎片 | 3 |
| 简体显示字符 | 3,434,734 |
| 隔离字符 | 5,842 |
| 原始 wikitext | 约15 MB |
| 结构化 JSONL | 约87 MB |

973页中包括王冰本通过 `<pages>` 引用后冻结的805个 ProofreadPage 页面。只保存和处理文字；扫描影像没有打包。

## 已完成工作

### 1. 页面和修订冻结

`builder/fetch_wikisource.py` 已完成：

- 枚举根页、子页和实际转录页；
- 按作品配置排除《类经》图翼、附翼等非目标范围；
- 固定每一个页面的修订号、修订时间和源站 SHA-1；
- 保存 UTF-8 wikitext；
- 计算页面级及作品聚合 SHA-256；
- 冻结 ProofreadPage 的实际页面依赖。

逐页结果见 `sources/source-inventory.json`，快照见 `sources/raw/`。

### 2. 缺字和私用区治理

`builder/build_character_maps.py` 固定了 `SKchar`、`SKchar2` 模板/模块依赖，并生成可审计字符映射：

- 使用代码：183个；
- 映射文件：`sources/normalization/skchar-map.json`；
- 依赖锁：`sources/normalization/source-dependencies.json`；
- 人工修复：`sources/normalization/manual-character-repairs.json`。

已记录的人工私用区修复：

- 《金匮要略》三个连续 PUA 字修为“㽲”；
- 《难经》PUA 字修为“啘”。

无法确认的缺字没有静默删除，而是保留于隔离库；其检索字段置空，禁止搜索和引用。

### 3. 正文抽取和说话者

`builder/extract.py` 处理了：

- MediaWiki 模板、链接、HTML、`noinclude`、伪标签和图片路径；
- `SK notes`、`雙行註文`、`SKchar`、`SKchar2`、`属性：`等来源格式；
- 经文、注文、新校正、校语、序文、学术源流和问答说话者；
- 《难经集注》的吕广、丁德用、杨玄操、虞庶、滑寿等署名；
- 无法可靠自动拆分的注本采用 `mixed`，不冒认成原典或某位医家独立发言。

四库无标点文本按源页逻辑行保留边界；王冰扫描页则保留页面级来源追溯。

### 4. 三类文本字段

`builder/convert_simplified.py` 使用固定版本
`opencc-python-reimplemented==0.1.7` 生成：

- `text_source`：清理后的来源字形；
- `text_traditional`：后台繁体工作字段；
- `text_simplified`：前端简体阅读字段；
- `text_search`：去标点和检索规范化字段。

中医阅读规范例外记录在
`sources/normalization/conversion-overrides.json`，包括五藏/五脏、六府/六腑、荣卫/营卫及医疗语境中“寫/泻”的上下文处理。前端直接引文只能使用 `text_simplified`，不能引用 `text_search`。

### 5. 可引用段落

`builder/segment.py` 生成稳定段落 ID、前后段 ID、可引用前后段 ID、卷篇、说话者、来源页、修订号、原始页哈希和内容哈希。超长段落在标点边界附近切分，最大700字符，并保留 `segment_group_id` 和分段序号。

未解字所在的最小完整语义单元标记为 `quality_status=quarantined`、`citation_allowed=false`、`search_allowed=false`，并把 `text_search` 置空。当前290个隔离段只占5,842字符；可引用语料中未解字为零。

逐作品结果见 `sources/processed/<source-id>/passages.jsonl`；隔离库见 `sources/quarantine/passages.jsonl`，逐条披露见 `sources/corpus-exclusions.json`。

### 6. 完整性、清洗和许可追溯

`builder/validate_corpus.py` 的当前结果：

- 原始快照哈希：`pass`；
- 结构完整性：`pass`；
- 清洗硬错误：未检出；
- 可引用语料未解字检查：`pass`；
- 清洗状态：`pass-with-quarantine`；
- 发布质量闸门：`blocked`。

`builder/build_source_lock.py` 生成：

- `sources/source-lock.candidate.json`；
- `sources/source-manifest.json`；
- `NOTICE.md`；
- `skill/tcm-classics-study/NOTICE.md`。

来源清单保留逐页固定修订链接（`oldid`）、访问时间和 SHA-256。古籍作品为公版范围；Wikisource 转录按站点条款及 CC BY-SA 4.0 处理。扫描影像不进入包。

## 当前7项来源级阻断原因

### 核心底本需第二底本校核

以下五种核心来源存在上游25%或50%质量标记，且尚未完成另一许可明确底本的自动差异检查和人工抽检：

- `core-suwen`
- `core-lingshu`
- `core-shanghanlun`
- `core-jingui`
- `core-nanjing`

《温病条辨》当前未因第二底本事项被阻断，但因核心正文仍有2个隔离语义单元而继续阻断发布。

### 王冰本低校对等级

- `commentary-suwen-wangbing`：805个 ProofreadPage 页面为低校对/问题等级；其中795页为等级1、10页为等级0。其缺字单元已经隔离，但低校对风险仍单独阻断。

### 已隔离、当前不再污染可引用语料的缺字或疑似乱码

当前共检出35个显式缺字标记、342个 `HT/KT` 旧转录占位符和1处界面文字混入：

- `commentary-neijing-leijing`：2个显式缺字；
- `commentary-jingui-xubin`：2个未确认 `SKchar`；
- `commentary-suwen-wangbing`：31个显式缺字/空字符模板（另有低校对页阻断）；
- 14种来源含342个 `HT/KT` 占位符：`core-wenbingtiaobian`、灵枢张志聪本、成无己本、方有执本、柯琴本、伤寒尤怡本、金匮尤怡本、陈修园本、徐大椿本、《难经集注》、《温热经纬》、《时病论》、素问张志聪本及《灵枢识》；
- `commentary-nanjing-jizhu`：1处“滚动条”界面文字混入。

`HT/KT` 在不同上下文中代表的原字并不相同，不能全局替换，必须逐条查扫描或可靠版本。医家扩展中的未解单元已完整披露并隔离，不再单独阻断；核心《温病条辨》的2个隔离单元仍阻断发布。

完整段落、示例和计数见 `sources/quality-report.json` 及
`docs/phase1-quality-report.md`。

## 测试

当前执行：

```text
python -m py_compile builder/*.py tests/corpus_checks/*.py
python -m unittest discover -s tests -v
```

结果：18项测试全部通过。测试覆盖26种作品、973页哈希、938页纳入状态、普通及可引用段落链接、700字符上限、可引用语料零未解字、290条隔离披露、模板/HTML/替换字符/PUA 清理、人工字符修复、医学“寫/泻”阅读转换、逐页署名清单及“候选锁不得冒充最终锁”。

## 下一步

1. 后续按 `memo.md` 记录，对含缺字或疑似乱码的隔离文本逐条查看扫描并形成有依据的人工修复记录。
2. 为五种高风险核心来源找到许可明确的第二工作底本，生成自动差异提示，并抽检高频名篇、方剂和随机段落。
3. 对王冰本确定取舍：完成足够的逐页抽检/校对，或换用质量和许可均合格的文本；不能把805页低校对状态降格为普通提示。
4. 重跑完整流水线；只有 `release_gate_status=pass` 时，构建器才允许生成最终 `sources/source-lock.json`。
5. Phase 2 的 SQLite 索引原型已经完成；质量消项可与后续开发并行，但任何可安装发布包必须等待最终来源锁。
