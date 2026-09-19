# Phase 1 语料质量报告

生成时间：`2026-09-18T11:24:09+00:00`

## 结论

- 固定修订与原始哈希完整性：**pass**
- 结构完整性：**pass**
- 清洗与隔离检查：**pass-with-quarantine**
- 可引用语料未解字检查：**pass**
- 发布质量闸门：**blocked**

当前语料已经可以作为**固定修订的构建候选**继续索引和抽检；但发布质量闸门未通过时，
不得把候选来源锁称为最终无条件发布锁，也不得把工作底本称为唯一权威文本。

## 总量

- 来源：26 种
- 固定页面快照：973 页
- 纳入语料页面：938 页
- 全部段落：54088 条
- 可引用段落：53798 条
- 隔离段落：290 条
- 全部简体显示字符：3,434,734
- 隔离字符：5,842

## 完整性清单

| 来源 | 结构类型 | 预期/最低 | 观察值 | 状态 |
|---|---:|---:|---:|---:|
| `core-suwen` | chapter | 81/79 | 81 | pass |
| `core-lingshu` | chapter | 81/81 | 82 | pass |
| `core-shanghanlun` | chapter | 20/18 | 34 | pass |
| `core-jingui` | chapter | 25/22 | 31 | pass |
| `core-nanjing` | difficulty | 81/81 | 81 | pass |
| `core-wenbingtiaobian` | volume | 6/6 | 6 | pass |
| `commentary-suwen-wangbing` | volume | 24/24 | 24 | pass |
| `commentary-neijing-leijing` | volume | 32/32 | 32 | pass |
| `commentary-lingshu-zhangzhicong` | nonempty-corpus | —/1 | 1 | pass |
| `commentary-shanghan-chengwuji` | nonempty-corpus | —/1 | 1 | pass |
| `commentary-shanghan-fangyouzhi` | nonempty-corpus | —/1 | 1 | pass |
| `commentary-shanghan-yuchang` | nonempty-corpus | —/1 | 7 | pass |
| `commentary-shanghan-keqin` | nonempty-corpus | —/1 | 1 | pass |
| `commentary-shanghan-youyi` | nonempty-corpus | —/1 | 1 | pass |
| `commentary-jingui-xubin` | volume | 24/24 | 24 | pass |
| `commentary-jingui-youyi` | nonempty-corpus | —/1 | 1 | pass |
| `commentary-jingui-chenxiuyuan` | nonempty-corpus | —/1 | 1 | pass |
| `commentary-nanjing-huashou` | difficulty | 81/81 | 81 | pass |
| `commentary-nanjing-xudachun` | nonempty-corpus | —/1 | 1 | pass |
| `commentary-nanjing-jizhu` | nonempty-corpus | —/1 | 1 | pass |
| `commentary-wenbing-wangshixiong` | volume | 5/5 | 5 | pass |
| `commentary-wenbing-leifeng` | nonempty-corpus | —/1 | 1 | pass |
| `lineage-wenbing-yetianshi` | nonempty-corpus | —/1 | 1 | pass |
| `lineage-wenbing-xuexue` | nonempty-corpus | —/1 | 1 | pass |
| `commentary-suwen-zhangzhicong` | nonempty-corpus | —/1 | 1 | pass |
| `commentary-lingshu-danbo` | nonempty-corpus | —/1 | 1 | pass |

## 阻断发布的来源级风险

- `core-suwen`：core source has upstream 25%/50% quality category and lacks completed second-base collation
- `core-lingshu`：core source has upstream 25%/50% quality category and lacks completed second-base collation
- `core-shanghanlun`：core source has upstream 25%/50% quality category and lacks completed second-base collation
- `core-jingui`：core source has upstream 25%/50% quality category and lacks completed second-base collation
- `core-nanjing`：core source has upstream 25%/50% quality category and lacks completed second-base collation
- `core-wenbingtiaobian`：core work contains 2 quarantined unresolved semantic units
- `commentary-suwen-wangbing`：ProofreadPage contains 805 unproofread/problem pages

## 清洗与字符检查

硬错误包括残留模板/伪标签、HTML、Unicode 私用区、替换字符、图片路径和断裂的上下文链接。
缺字和HT/KT不会被静默删除：受影响的最小完整语义单元进入隔离库，检索字段置空，禁止引用；可引用语料必须为零未解字。

| 来源 | 全部段落 | 可引用 | 隔离 | 硬错误 | 隔离警告数 | 主要说话者类型 |
|---|---:|---:|---:|---:|---:|---|
| `core-suwen` | 1228 | 1228 | 0 | 0 | 0 | dialogue:1197, core_text:31 |
| `core-lingshu` | 862 | 862 | 0 | 0 | 0 | dialogue:780, core_text:78, textual_collation:4 |
| `core-shanghanlun` | 205 | 205 | 0 | 0 | 0 | core_text:147, dialogue:58 |
| `core-jingui` | 295 | 295 | 0 | 0 | 0 | core_text:134, textual_collation:86, dialogue:75 |
| `core-nanjing` | 83 | 83 | 0 | 0 | 0 | core_text:83 |
| `core-wenbingtiaobian` | 239 | 237 | 2 | 0 | 2 | core_text:221, dialogue:18 |
| `commentary-suwen-wangbing` | 14170 | 14146 | 24 | 0 | 31 | commentary:7145, quoted_core:5040, textual_collation:1310, dialogue:675 |
| `commentary-neijing-leijing` | 19021 | 19019 | 2 | 0 | 2 | commentary:9840, quoted_core:8120, dialogue:1061 |
| `commentary-lingshu-zhangzhicong` | 1568 | 1521 | 47 | 0 | 55 | mixed:1210, commentary:356, preface:2 |
| `commentary-shanghan-chengwuji` | 278 | 263 | 15 | 0 | 27 | commentary:210, mixed:68 |
| `commentary-shanghan-fangyouzhi` | 359 | 325 | 34 | 0 | 48 | mixed:334, commentary:18, preface:7 |
| `commentary-shanghan-yuchang` | 1341 | 1341 | 0 | 0 | 0 | commentary:1341 |
| `commentary-shanghan-keqin` | 211 | 208 | 3 | 0 | 6 | mixed:176, commentary:33, preface:2 |
| `commentary-shanghan-youyi` | 179 | 177 | 2 | 0 | 10 | commentary:179 |
| `commentary-jingui-xubin` | 3066 | 3064 | 2 | 0 | 2 | quoted_core:1564, commentary:1457, dialogue:45 |
| `commentary-jingui-youyi` | 199 | 193 | 6 | 0 | 10 | mixed:133, commentary:63, preface:3 |
| `commentary-jingui-chenxiuyuan` | 245 | 244 | 1 | 0 | 1 | mixed:222, commentary:23 |
| `commentary-nanjing-huashou` | 83 | 83 | 0 | 0 | 0 | commentary:83 |
| `commentary-nanjing-xudachun` | 59 | 58 | 1 | 0 | 2 | mixed:45, commentary:14 |
| `commentary-nanjing-jizhu` | 946 | 943 | 3 | 0 | 3 | commentary:917, quoted_core:24, preface:5 |
| `commentary-wenbing-wangshixiong` | 316 | 314 | 2 | 0 | 2 | commentary:316 |
| `commentary-wenbing-leifeng` | 211 | 206 | 5 | 0 | 5 | commentary:211 |
| `lineage-wenbing-yetianshi` | 18 | 18 | 0 | 0 | 0 | lineage:18 |
| `lineage-wenbing-xuexue` | 15 | 15 | 0 | 0 | 0 | lineage:15 |
| `commentary-suwen-zhangzhicong` | 7309 | 7260 | 49 | 0 | 67 | commentary:3716, mixed:3591, preface:2 |
| `commentary-lingshu-danbo` | 1582 | 1490 | 92 | 0 | 105 | mixed:936, commentary:646 |

## 已知高风险

- 王冰本 ProofreadPage 的低校对等级按页面计入，不因抽取成功而降级为普通警告。
- 核心《素问》《灵枢》《伤寒论》等上游低质量标记，需要第二许可明确底本的差异检查或人工抽检记录。
- `mixed` 表示自动规则不能可靠区分原文与注文；前端必须如实显示，不得自动冒认作者。
- `text_source`、`text_traditional` 仅用于后台校核；用户直接引文必须使用 `text_simplified`。
