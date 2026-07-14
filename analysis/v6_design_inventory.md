# 《革命街没有尽头》V6 设计资产清单

> 任务范围：盘点 `_legacy_v6/` 全部源码（6 个 `.ts`）+ 4 份契约文档 + 44 张有效美术资产，为 AI 原生重构提供完整资产清单。
> 输出基准日期：2026-07-14（任务执行日）。
> 阅读范围：`app/*.ts`、`docs/*.md`、`public/art*/` 下所有 PNG。**未修改任何 v6 源代码**，仅做读取与归档。

---

## 0. 元数据与阅读须知

| 项目 | 实测值 | 任务简报声称 | 备注 |
| --- | --- | --- | --- |
| 故事 TS 体积 | 68 KB（1372 行） | 68 KB / 25 幕 | 一致 |
| 互动 TS 体积 | 42 KB | 42 KB | 一致 |
| 美术 PNG 总数（disk） | 44（不含 `og.png` 与 4 个 SVG） | 49 | 简报数据与磁盘不一致；实际可清点 44 张艺术图，加 1 张 `og.png` 合计 45 张 PNG |
| 文档 .md | 4 | 4 | 一致 |
| 测试文件 | 0（V6 项目根无 `*.test.*` / `*.spec.*`） | 10 | 简报数据与磁盘不一致；V6 文档自报"60 项测试基线 / V6 新增 15 项"指测试用例（cases），不是测试文件 |
| 互动条目数 | 15（`interactionCatalog` 长度） | 15 | 一致 |
| 共鸣条目数 | 3（photo / email / gaze） | 3 | 一致 |
| 主轴 | 3（speak / keep / survive） | 3 | 一致 |
| 演示码 | 5（`G1N-DEMO-*`） | 5 | 一致 |

> **重要前置说明**：
> 1. 任务简报提及"v0.1 PRD"与"经验教训四项问题"，但项目仓库下未发现对应的 `docs/design/`、`docs/decisions/`、`AGENTS.md`、`CLAUDE.md` 等文件（已用 `glob` 与 `Get-ChildItem -Recurse` 确认）。下文"AI 原生重构评估"章节依据任务简报提供的四项标准与四类"必须废弃"清单来执行；未对 v6 源码做规范性裁断。
> 2. V6 内部存在两处可被测出的不一致：①V4 美术清单自称"旧资源 14 张"，实际 `art/ + art-v2/ + art-v3/` 共 20 张；②V5 契约说"放映机两段不计分"，但 V6 互动表给 `projector-repair` 标 `memoryGain: 7` 且 `isCore: true`。两者均记录在第八节。

---

## 1. 故事资产

### 1.1 五个历史锚点（不可改写端点）

V6 通过"V5 契约第 1 节"与 `story.ts` 中各 `chapter.kind = "chapter"` 场景的 `body[0]` 共同确立，五个锚点即"宏观端点锁定 + 微观动作由玩家书写"的固定骨架。

| # | 时间 | 地点 | 核心事件 | 对应场景 / 来源 |
| --- | --- | --- | --- | --- |
| 锚点 1 | 2009 年夏 | 德黑兰大学纪律委员会 | 莱拉遭到处分，失去继续深造资格，出版社撤回工作邀请 | `story.ts: scene "after-gate"`，`art: /art-v4/university-gate-expulsion.png` |
| 锚点 2 | 2009—2010 | 德黑兰出租屋 → 圣何塞（卡姆兰所在） | 莱拉决定离开，嫁给姨妈介绍的软件工程师卡姆兰 | `story.ts: scene "kamran"`（视频通话→她主动给姨妈回电话），`art: /art-v4/video-call-kamran.png` |
| 锚点 3 | 2010 年 | 德黑兰国际机场 | 与阿拉什在出发大厅时钟下告别，行李箱轮子把她推向安检 | `story.ts: scene "echo-three"`，`art: /art-v4/airport-clock-goodbye.png` |
| 锚点 4 | 2011—2021 | 圣何塞 ↔ 德黑兰 | 莱拉成为本地化外包译员，卡姆兰冲洗黑白照片；阿拉什留在德黑兰陪伴父亲维修铺、玛丽亚姆记录流星 | `story.ts: scene "two-cities"`（蒙太奇，3 帧艺术） |
| 锚点 5 | 十三年后（≈2024） | 伊斯坦布尔卡拉柯伊老咖啡馆 | 与阿拉什重逢，咖啡馆翻开发黄诗集，两张同版毕业照对齐，路口再次分开 | `story.ts: scene "gaze" + "book" + "crossroads"`，`art: /art-v5/istanbul-reunion-aged.png` + `/art-v5/poetry-book-photo-close.png` + `/art-v5/istanbul-crossroads-aged.png` |

> 锚点不可被玩家的选择改写；玩家书写的不是"是否离开"，而是"怎样表达 / 怎样处理证据 / 怎样告别"。

### 1.2 25 幕命名与五章分组

V6 主线保留 25 幕（V6 契约第 2 节：`保留 25 幕主线`）。下表由 `story.ts` 中所有 `kind ∈ {chapter, narrative, montage, choice, echo, resonance}` 的 19 个活动场景 + 5 章首页 + 1 个开篇序章 photo 场景归并得到。**注**：V6 实际场景对象数 ≠ 25，但 V5/V6 文档用"幕"统计连续叙事节拍（蒙太奇节拍计 3 幕，回响计 1 幕，选项不计幕数），最终叙事节拍合计 25。

| 章节 | 幕编号 | 场景 ID | 场景名 | kind | 地点 / 年份 | 艺术文件 |
| --- | --- | --- | --- | --- | --- | --- |
| 序章 | 第 01 幕 | `photo` | 一张照片 | resonance | 伊斯坦布尔 · 十三年后 | `art-v5/istanbul-cafe-photo-close.png` |
| 第一章 · 革命街上的恋人 | 第 02 幕 | `chapter-one` | 革命街上的恋人（章首页） | chapter | 德黑兰 · 2008 | `art-v4/university-gate-autumn.png` |
| | 第 03 幕 | `campus` | 文学课与地下室放映机 | narrative | 德黑兰大学 / 革命街 | `art-v3/tehran-literature-class.png` |
| | 第 04 幕 | `choice-one` | 停电后的地下室（第一次保存） | choice | 旧书店地下室 | `art-v4/underground-projector-close.png` |
| | 第 05 幕 | `echo-one` | 雨、屋顶与一台旧放映机 | echo | 德黑兰屋顶 | `art-v3/tehran-rooftop.png` |
| | 第 06 幕 | `promise` | 毕业照那天 | narrative | 毕业合影现场 | `art-v5/graduation-photo-day.png` |
| 第二章 · 知识变成证据 | 第 07 幕 | `chapter-two` | 知识变成证据（章首页） | chapter | 德黑兰 · 2009 | `art-v4/student-publication-room.png` |
| | 第 08 幕 | `publication` | 学生宿舍 / 大学广场 | narrative | 学生宿舍 | `art-v4/student-publication-room.png` |
| | 第 09 幕 | `choice-two` | 大学纪律委员会（第二次保存） | choice | 纪律委员会问话室 | `art-v4/dorm-search-night.png` |
| | 第 10 幕 | `echo-two` | 没有提高声音的问话 | echo | 纪律委员会档案室 | `art-v3/discipline-committee.png` |
| | 第 11 幕 | `after-gate` | 大学铁门外 | narrative | 大学铁门 | `art-v4/university-gate-expulsion.png` |
| 第三章 · 只有一个人能够离开 | 第 12 幕 | `chapter-three` | 只有一个人能够离开（章首页） | chapter | 德黑兰 · 2010 | `art-v3/tehran-airport-departure.png` |
| | 第 13 幕 | `small-room` | 蒙太奇·出租屋 | montage | 出租屋 | `art-v3/tehran-rental-room.png` |
| | 第 14 幕 | `one-year` | 出租屋 · 凌晨 | narrative | 出租屋 · 凌晨 | `art-v3/tehran-rental-room.png` |
| | 第 15 幕 | `kamran` | 圣何塞 / 德黑兰 | narrative | 视频通话 | `art-v4/video-call-kamran.png` |
| | 第 16 幕 | `choice-three` | 德黑兰屋顶 · 最后一夜（第三次保存） | choice | 德黑兰屋顶 | `art-v4/final-rooftop-night.png` |
| | 第 17 幕 | `echo-three` | 国际出发 · 天亮以前 | echo | 德黑兰机场 | `art-v4/airport-clock-goodbye.png` |
| 第四章 · 两个城市 | 第 18 幕 | `chapter-four` | 两个城市（章首页） | chapter | 圣何塞 / 德黑兰 · 2011—2021 | `art-v5/san-jose-arrival-2011.png` |
| | 第 19 幕 | `two-cities` | 蒙太奇 · 两个城市 | montage | 圣何塞 ↔ 德黑兰 | `art-v4/localization-office.png` + `maryam-telescope-rooftop.png` + `art-v3/san-jose-apartment.png` |
| | 第 20 幕 | `email` | 没有回复的邮件（共鸣） | resonance | 圣何塞 · 凌晨 | `art-v4/email-delete-night.png` |
| | 第 21 幕 | `last-email` | 删除以后 | narrative | 圣何塞公寓 | `art-v4/email-delete-night.png` |
| 第五章 · 伊斯坦布尔重逢 | 第 22 幕 | `chapter-five` | 伊斯坦布尔重逢（章首页） | chapter | 十三年后 | `art-v2/istanbul-cafe.png` |
| | 第 23 幕 | `gaze` | 重逢视线（共鸣） | resonance | 卡拉柯伊老咖啡馆 | `art-v5/istanbul-reunion-aged.png` |
| | 第 24 幕 | `book` | 诗集与桌面 | narrative | 同一咖啡馆 | `art-v5/poetry-book-photo-close.png` |
| | 第 25 幕 | `crossroads` | 终章 · 另一个故事 | narrative | 伊斯坦布尔街头 | `art-v5/istanbul-crossroads-aged.png` |

**叙事节拍说明**：
- 25 幕 = 1 序章 + 5 章首页 + 19 个活动场景；
- `montage` 在 V5 契约中按节拍计幕（"小房间"3 拍 / "两个城市"3 拍）；
- 三个 `choice` 场景在 V5 契约中**不计入幕数**，但与 `echo`、`resonance` 共同形成"输入—回响—代价"三段节拍。

### 1.3 三轴定义（说出 / 留住 / 活下去）

来自 `story.ts: axisNames` + `axisExplanations` + V5 契约第 2.1 节。具体语义与文案如下：

| 轴（id） | 中文 | 内部语义（一句话） | 通关后轴解释 | 主要场景角色 |
| --- | --- | --- | --- | --- |
| `speak` | 说出 | 把爱、责任和真相说出口——写进纸张的"理想" | "把爱、责任和真相说出口——它后来被称作理想。" | 写诗 / 供词 / 坦白 |
| `keep` | 留住 | 让一个吻、一本书和共同未来留在手里——能被感知的"爱情" | "让一个吻、一本书和共同未来留在手里——它后来被称作爱情。" | 接吻 / 拒绝告发 / 再问一条共同的路 |
| `survive` | 活下去 | 先保护自己，再承担离开后的生活——能继续行动的"生存" | "先保护自己，再承担离开后的生活——它后来被称作生存。" | 先行离开 / 说出名字换取减轻 / 只说航班 |

**首轮规则**（V5 契约第 5 节）：
- 首轮不显示 `speak/keep/survive` 标签，不显示精确分数（`emptyScores` 保持 `{0,0,0}`）；
- 结尾电影尾声不因主轴数值差异改写为"最优解"，混合尾声基调句固定为"她没有让一种记忆替另外两种作证"。

### 1.4 六次输入的完整列表（3 主 + 3 共鸣）

| 类别 | # | 场景 | 主动作 / 共鸣操作 | 文案（label） | 轴 / 不计分 | 三个选项 |
| --- | --- | --- | --- | --- | --- | --- |
| 主动作 | 1 | `choice-one`（地下室停电） | 选卡片 | "看不见画面，故事也不会消失" | `speak / keep / survive` | 送他一首诗 / 主动吻他 / 先行离开 |
| 主动作 | 2 | `choice-two`（纪律委员会） | 选卡片 | "谁和你一起做的？" | `speak / keep / survive` | 只承认自己 / 拒绝告发 / 说出名字 |
| 主动作 | 3 | `choice-three`（最后一夜） | 选卡片 | "把卡姆兰、婚姻、机票、害怕与仍然爱他一次说完？" | `speak / keep / survive` | 把一切一次说完 / 再问一条共同的路 / 只说航班已经确定 |
| 共鸣 | 1 | `photo`（序章） | 物件拖放 / 翻面 / 收回 | "把照片放在哪里？" | **不计分** | 正面朝上 / 反面朝上 / 收回包里 |
| 共鸣 | 2 | `email`（第四章） | 写入 → 删除 | "写下一句，再亲手删除" | **不计分** | "我记得地下室的味道" / "那本诗集还在吗" / "我现在过得很好" |
| 共鸣 | 3 | `gaze`（第五章） | 画面焦点移动 | "她先把视线停在哪里？" | **不计分** | 手与白发 / 发黄的诗集 / 时钟与机场方向 |

> 六次输入包含三种不同操作语法：**并列选卡**（3×主）、**物件拖放 + 持续删除**（photo + email）、**画面焦点**（gaze）。V5 契约第 2.2 节特别要求"玩家不应把体验概括为'点六次三选一'"。

### 1.5 AI 原生重构评估（故事资产）

| 类别 | 评估 | 说明 |
| --- | --- | --- |
| **可直接复用** | 五个历史锚点（不可改写端点） | 锚点是叙事骨架，AI 重构应保留；可作为"世界状态硬约束"，由 AI agent 守护 |
| **可直接复用** | 25 幕主线、3 轴定义 | 幕数与轴名稳定，AI 重构的 prompt 与测评仍可基于这套语义 |
| **可直接复用** | 共鸣物件的三种操作语法（拖放 / 删除 / 焦点） | 三种语法在 V5 契约已明确要求"不能压成三选一"，AI 重构可基于同样约束设计 LLM 驱动的随机化 |
| **需要重构** | 序章 photo 共鸣在 V6 仍"以三选卡片呈现" | V5 契约第 2.2 节要求 photo 必须有"正面朝上 / 反面朝上 / 收回包里"三个放置区域与拖放支持；当前 `scene "photo"` 的 `resonances` 仍是并列卡片；AI 重构应直接落到 DOM 拖放 / 点击放置 |
| **需要重构** | `chapterEnd` 显式挂在 `promise / after-gate / echo-three / last-email / crossroads` 5 个场景 | 这与 V6 契约第 3 节"五个有叙事用途的互动"不完全对齐——V6 把章末结算挂到 5 个不同形态的场景（narrative / narrative / echo / narrative / narrative），导致"互动 1 = choice + 互动 2 = choice + 互动 3 = choice"加上 12 个 explorer 的结构与文档"3+3+3+3+3=15"在表述上略有错位，AI 重构应统一为"每章 = 1 主选择 + 1 共鸣（按章分配） + 1 可选线索探索" |
| **需要重构** | 25 幕的"幕"含义模糊 | 实际 19 个 `Scene.kind ∈ {narrative, montage, choice, echo, resonance}` 加上 5 个 `chapter` 加上 1 个 `prologue photo` = 25 个对象，但 V5 文档用"节拍"计幕（蒙太奇 3 拍，echo 1 拍，choice 不计）。AI 重构应明确"幕 = 单一时间锚点下的连续叙事节拍"，避免 LLM 在编排时混淆 |
| **必须废弃** | V5 文档"前两段放映机不计分" vs V6 互动表 `projector-repair` `memoryGain: 7` | V5 文档明确说放映机两段"只负责建立手感与亲密，不成为隐藏的第七次测评"，但 V6 在 progression.ts 给了 7 分。这是 V6 内部矛盾，AI 重构应明确以"前置手感"为定位，**不进入显影度计算** |
| **必须废弃** | `confirm: 25 幕固定端点和免费完整结局不因显影度、权益或礼包而改变` 与 V6 互动奖励 / 章节包挂钩 | 当 `memoryGain` 实际计算章节满额时（21/21/20/19/19 = 100），免费完整结局被默认 0 显影度下的 `base` 档覆盖——但 V6 契约第 4 节要求 0–20 也能"看见基础选择与免费完整结局"，而 0 显影度下若 `interactionCatalog` 没有完成第 1 章的 `first-memory-action`，就没有 `axisValues` 写进 `endings.mixed` 的判定，结局语调是 `mixed`，与"基础结局"不冲突——**但** AI 重构应让"0 显影度也获得完整结局"成为显式代码路径，避免 LLM 误判"必须先完成一定互动" |

---

## 2. 互动资产

### 2.1 15 个互动的位置、类型、操作方式、显影度增量

下表为 `app/progression.ts: interactionCatalog` 的 15 条完整条目。表中"操作语法"由 V5 契约第 2.2 节 + `kind` 字段 + `steps` 字段共同确认。

| ID | 章 | sceneId | kind | 标题 | requirement | 核心玩法 | 操作语法 | memoryGain | 显影线索 | 收藏品 | 与四项问题的对应 |
| --- | --- | --- | --- | --- | --- | --- | --- | ---: | --- | --- | --- |
| `photo-placement` | 1 | `photo` | photo | 安放毕业照 | required | 拖动 / 翻面 / 收回 | 拖拽 + 落点区 | 5 | `two-identical-prints`（两次冲洗） | `leila-graduation-photo`（女生毕业照） | 世界状态✓ 人物认知✓ 可用行动✓（后续 gaze 决定焦点） 未来回响✓（"gaze 场景路由到 photo.farEcho"） |
| `projector-repair` | 1 | `campus` | projector | 修好旧放映机 | required (isCore) | 两阶段修理 + 共同影像辨认 | 焦距校准 + 错位画面回正 | **7** | `projector-toolbox-note`（工具箱里的折痕 / "我到了"） | `underground-film-ticket`（地下放映会电影票） | 世界状态✓（齿轮咬合 / 灯泡亮） 人物认知✓（共同记忆被认出） 可用行动⚠（V5 说不计分） 未来回响✓（`first-do-not-let-go`） |
| `first-memory-action` | 1 | `choice-one` | choice | 停电后的第一个动作 | required | 主选择卡 | 三选一卡片 | 6 | `first-do-not-let-go`（第一次"别松手"） | — | 全部满足，**主轴核心** |
| `publication-clues` | 2 | `publication` | explore | 检查刊物桌面 | optional | 三个有用途的物件 | 三步触觉探查 | 5 | `maziya-last-note`（玛兹雅页边字） | `publication-margin`（刊物页边） | 世界状态✓（找到失踪学生报道） 人物认知⚠（校方证据） 可用行动✗（未影响后续选择） 未来回响✗ |
| `names-decision` | 2 | `choice-two` | choice | 是否告发同伴 | required (isCore) | 主选择卡 | 三选一卡片 | 7 | `twenty-eight-names`（问话记录） | — | 全部满足，**主轴核心** |
| `discipline-record` | 2 | `echo-two` | explore | 翻看纪律记录 | optional | 把三处记录按时间排好 | 时间排序 | 6 | `maziya-fixed-future`（玛兹雅的后来） | `discipline-stamp`（纪律委员会印章拓片） | 世界状态✓ 人物认知✓ 可用行动✗（不能改写结果） 未来回响✗ |
| `departure-packing` | 3 | `small-room` | explore | 整理离开前的桌面 | optional | 钥匙 / 复健单 / 护照申请 | 依次翻看 | 5 | `three-directions`（三个方向） | `rental-room-key`（出租屋钥匙） | 世界状态✓（看清三个方向） 人物认知✓ 可用行动⚠ 未来回响✗ |
| `last-night-truth` | 3 | `choice-three` | choice | 完成最后一夜 | required | 主选择卡 | 三选一卡片 | 7 | `sealed-flight-envelope`（装着航班的信封） | — | 全部满足，**主轴核心** |
| `airport-goodbye` | 3 | `echo-three` | silence | 握住，然后松开 | required (isCore) | 听广播→松开 | 按住画面 + 时序操作 | 5 | `unsent-arrival`（未发送的"我到了"） | `one-way-luggage-tag`（单程行李牌） | 世界状态✓（行李过线） 人物认知✓（"我到了"草稿） 可用行动⚠（不可改） 未来回响✓（远期回响） |
| `dual-city-objects` | 4 | `two-cities` | combine | 对齐两座城市 | optional | 底片编号 + 流星日期 | 组合拖放 | 5 | `parallel-date`（同一天） | `parallel-date-card`（双城日期卡） | 世界状态✓（同一天被发现） 人物认知✓ 可用行动✗ 未来回响✗ |
| `email-draft` | 4 | `email` | email | 处理未发送邮件 | required (isCore) | 写入→删除 | 邮件编辑器 + 显式点击 | 7 | `deleted-draft-shadow`（删除后的残影） | — | 世界状态✓（光标节拍） 人物认知✓ 可用行动⚠ 未来回响✓ |
| `receipt-memory-combination` | 4 | `last-email` | combine | 把草稿与照片收在一起 | optional | 未发送草稿 + 雾中高速公路底片 | 组合叠放 | 4 | — | `draft-shadow`（未发送邮件残影） | 世界状态✓（贴上冰箱） 人物认知✓ 可用行动✗ 未来回响✗ |
| `reunion-gaze` | 5 | `gaze` | gaze | 决定第一眼 | required | 视线移动 | 画面热点 / 焦点 | 5 | `arrival-finally`（终于抵达） | — | 世界状态✓（焦点转移） 人物认知✓ 可用行动⚠（只影响镜头） 未来回响✓（仅终止镜头） |
| `photo-pairing` | 5 | `book` | combine | 对齐两张相同照片 | required (isCore) | 把两张照片放进同一取景框 | 组合对齐 | 6 | — | `paired-graduation-photos`（两张同版毕业照） | 世界状态✓（两张照片对齐） 人物认知✓（同一站位 / 不同磨损） 可用行动⚠ 未来回响✓ |
| `final-crossroad` | 5 | `crossroads` | silence | 走到路中央 | required | 握住→穿过→松开 | 按住 + 释放 | 5 | `last-do-not-let-go`（最后一次"别松手"） | — | 世界状态✓（绿灯结束前放手） 人物认知✓ 可用行动⚠ 未来回响✓ |

**汇总**：

- `required` = 10 项（photo-placement / projector-repair / first-memory-action / names-decision / last-night-truth / airport-goodbye / email-draft / reunion-gaze / photo-pairing / final-crossroad）
- `optional` = 5 项（publication-clues / discipline-record / departure-packing / dual-city-objects / receipt-memory-combination）
- `isCore` = 5 项（projector-repair / names-decision / airport-goodbye / email-draft / photo-pairing）——每章 1 个
- `memoryGain` 合计 = `5+7+6+5+7+6+5+7+5+5+7+4+5+6+5 = 85` 分
- `chapterContract.completionMemory` 合计 = `5 × 3 = 15` 分
- **首轮必满额（仅完成 required + 章末结算）= 5×(photo+projector+choice+choice+email+gaze+airport+final) + 章末**：
  - 公式：`sum(required.memoryGain) + 5×3 = (5+7+6)+(7)+(7+5)+(7+5)+(5) + 15 = 18+7+12+12+5+15 = 69`
  - **这是首轮不可能满分 100 的关键原因**：V6 把"15 个互动"分成 required 10 项 + optional 5 项；首轮仅完成 required 即得 69 分；满分 100 需要完成全部 15 项 + 5 章结算 = `85+15 = 100`。

### 2.2 6 个共鸣互动（照片 / 邮件 / 视线）的特殊处理

V5 契约第 2.2 节明确："共鸣不计入三轴得分，但会改变措辞、镜头、物件、声音与结尾组合。它们不能再复用普通三选一卡片。"

| 共鸣 ID | 操作语法差异化 | 感官确认 | 远期回响（farEcho） | 结尾镜头（endingFragment） | 与三项主选择的差异 |
| --- | --- | --- | --- | --- | --- |
| `photo` | 拖放 / 翻面 / 收回（V5 明确要求） | "糖罐旁留出一个刚好够照片的位置" / "纸面擦过桌布，只剩日期朝向灯光" / "帆布包的拉链合上" | "男生翻开诗集时，里面那张同版毕业照也正面朝上；两张照片隔着桌面再次对齐" | "桌上那张照片始终正面朝上；年轻的他们替现在的两个人完成了最后一次对视" | 唯一**带收藏品 + 线索**的共鸣；操作上**真物件**而非卡片 |
| `email` | 邮件编辑器 + 显式删除按钮 | "点下删除前，光标又闪了两次" / "她在问号后停了一分钟" / "这句话是真的，只是不完整" | "门被推开时，雨水和热灯泡的气味一起进来；她先认出那个被删除过的夜晚" | "她曾写下地下室潮湿的纸张和热灯泡气味，后来删掉了；重逢时，那气味仍先于对白回来" | 唯一**不要求玩家在场景中拼出句式**——三句是"作者预设文本"，玩家只选 + 删除 |
| `gaze` | 画面焦点 / 热点 | "十三年先落在指节和鬓角" / "书页的颜色比记忆更诚实" / "四十分钟后，机场班车不会等她" | "最后的焦点停在他放开茶杯的手上 / 越过人群，落在他臂弯里的旧诗集上 / 停在绿灯和机场方向牌上" | 与 farEcho 同义——**视线只决定最终镜头，不在下一幕重复成回响**（V5 契约第 3 节硬约束） | 唯一**不进入 futureEchoRoutes** 的共鸣（V6 `futureEchoRoutes.gaze` 把"choice-one + email"作为未来的两条回响来源） |

**未来回响路由表**（V6 `futureEchoRoutes`，每个场景最多 2 条）：

| 目标场景 | 来源 1 | 来源 2 |
| --- | --- | --- |
| `gaze`（伊斯坦布尔重逢视线） | `choice-one.farEcho` | `email.farEcho` |
| `book`（诗集与桌面） | `photo.farEcho` | `choice-two.farEcho` |
| `crossroads`（路口） | `choice-three.farEcho` | （空，第二条预留） |

### 2.3 AI 原生重构评估（互动资产）

| 类别 | 评估 | 说明 |
| --- | --- | --- |
| **可直接复用** | 15 互动 = 5 章 × 3 的结构 | 这是 V6 反复确认的硬约束，AI 重构保留章节 / 互动 1:3 比例 |
| **可直接复用** | 三个 `isCore` 互动（`projector-repair` / `names-decision` / `airport-goodbye` / `email-draft` / `photo-pairing`） | 每章一个核心，符合 V5 契约第 2 节"1 项核心玩法 + 1 次有代价的主选择 + 1 个情绪峰值" |
| **可直接复用** | 共鸣的三种操作语法（拖放 / 删除 / 焦点） | V5 契约明确要求"不能压成三选一"，AI 重构应直接落到 LLM 驱动的物件操作 |
| **需要重构** | `first-memory-action` 的 sceneId = `choice-one` 与 `choice-one` 自身是同一个对象 | 当前实现里 `choice-one` 既作为"主选择"又被 `completeInteraction('first-memory-action')` 调用，等于**主选择同时被记两次**。AI 重构应拆分"主选择 = choice-one / 共鸣 = photo-placement"，移除冗余的 `first-memory-action` 互动 ID |
| **需要重构** | `projector-repair` 标 `memoryGain: 7` + `isCore: true`，但 V5 契约第 2.2 节明确"不计分 / 不成为隐藏第七次测评" | V6 内部矛盾；AI 重构应把放映机改为"前置手感"（不计分，仅建立共同记忆的感官基线） |
| **需要重构** | `gaze` 互动不进入 `futureEchoRoutes` 作为自身来源 | 视线自身**只能**决定最终镜头（V5 契约第 3 节硬约束："视线只改变最终镜头，不在下一幕重复成一条回响"），AI 重构应让 LLM 在生成 endingFragment 时**直接消费** gaze 字段，而不是路由到后续场景 |
| **需要重构** | `futureEchoRoutes.crossroads` 只有 1 条 `choice-three` 回响 | V5 契约第 3 节允许"最多 2 条"，当前未填满。AI 重构应补一条（如 `gaze.farEcho` 或 `photo.farEcho`）让路口有"主线 + 共鸣"双收束 |
| **必须废弃** | `gaze` 没有 collectible | 三个共鸣里**只有 gaze 不给收藏品**——`photo` 给毕业照、`email` 在 `receipt-memory-combination` 给未发送邮件残影。AI 重构应让"视线第一眼"也产生收藏品（如"重逢时手心握过的糖纸"）以维持"6 个共鸣物件都进镜头"的视觉承诺 |
| **必须废弃** | 凝视热点如果只是 UI 操作，不算改变世界 | 任务简报明确："凝视热点如果只是 UI 操作不算"。V6 `reunion-gaze` 当前仅移动焦点 + 改 endingFragment，不改变任何人物 / 物件 / 世界状态——按四项问题核验，**不满足"改变世界状态 / 改变人物认知 / 改变可用行动"三条**。AI 重构必须让 gaze 真正影响后续选择：例如"看白发后"才能在 `crossroads` 触发"也许我们只是老了"的回响，而"看时钟"触发"今晚飞回圣何塞" |

---

## 3. 物件母题

V6 中所有"物件"在 `story.ts` 的 `object` 字段、`interactionCatalog` 的 `collectible.motif` 字段、以及 `MainOption.motif` 字段中三处定义。下表汇总五大物件母题。

| 物件 | 核心语义 | 归属变化 | 出现场景（`object` 字段） | 出现互动 / 选择 | 是否带"canonical" |
| --- | --- | --- | --- | --- | --- |
| **毕业照** | 共同青春的唯一物证，跨十三年"同站位 + 不同磨损" | 序章：莱拉保存一张（`leila-graduation-photo`）→ 第六幕：两人各持一张同版（"照片要冲两张吗？"）→ 第五章：诗集里那张（男生持有）+ 桌上 / 帆布包（莱拉持有） | `photo`（序章 resonance） / `promise`（第六章 narrative） / `book`（第五章 narrative） | `photo-placement`（放置） / `photo-pairing`（对齐两张） | 是（`/art-v5/canonical-graduation-photo.png` 唯一母版） |
| **诗集** | 沉默 / 拒绝告发 / 被保管的纸页 | 第一章男生把诗集藏在工具盒 → 第二章"拒绝告发"选项的 `motif` → 第五章作为重逢关键证据 | `choice-two.book`（拒绝告发选项的 motif）/ `echo-one` / `book` | `names-decision.book`（拒绝告发） / `reunion-gaze.book`（看诗集） | 否（诗集本身是抽象物件，画面以咖啡馆桌面 + 发黄书页呈现） |
| **名单** | 证据 / 调查 / 同伴的姓名 | 第二章序曲：刊物末页 + 玛兹雅失踪 → `echo-two` 翻看纪律记录 → "说出名字"选项的笔迹 | `publication` / `echo-two` / `choice-two.burn`（说出名字的 motif = 笔迹） | `publication-clues` / `discipline-record` / `names-decision.burn` | 否（名单通过蓝铅笔太阳、刊物页边、印章拓片三个替身出现） |
| **车票** | 共同未来 / 退路 / 离开的物证 | 第一章"先行离开"选项的 motif = 电影票 → 第三章"再问一条共同的路"选项的 motif = 两张车票 → 第三章章末"未发送的'我到了'" | `campus`（电影票出现在故事） / `choice-one.leave` / `choice-three.escape` / `echo-three` | `first-memory-action.leave` / `last-night-truth.escape` / `airport-goodbye` | 否（公交票是抽象物件，画面以"未发送'我到了'"草稿 + 单程行李牌呈现） |
| **邮件** | 未说出口的句子 / 残影 | 第四章：圣何塞凌晨邮件编辑器（`email` 共鸣） → `last-email`：删除后 + 卡姆兰照片（"雾里高速公路"） | `email`（resonance） / `last-email`（narrative） | `email-draft`（共鸣操作） / `receipt-memory-combination`（组合草稿 + 照片） | 否（邮件草稿以光标节拍呈现；实物是卡姆兰的底片） |

**物件之间的交叉**：

- 毕业照 ↔ 诗集：第五章 `book` 场景中"男生翻开诗集，里面是他保存的那张毕业照"——**两个母题在同一取景框**；
- 诗集 ↔ 名单：第二章 `choice-two.book` 拒绝告发 → 远期回响"诗集里仍夹着那张处分通知"——**诗集成了名单的容器**；
- 车票 ↔ 邮件：第三章 `last-night-truth.conceal` 只说航班 → 远期回响"路口，她先说卡姆兰正在等她；十三年前留在信封里的名字终于抵达街上"——**车票（信封）↔ 邮件（未寄出）共享同一个语义层**；
- 毕业照 ↔ 视线：第五章 `reunion-gaze.hands` → endingFragment"停在他放开茶杯的手上"，与毕业照里"他用指节压住要合上的书页"互文——**毕业照"按住的指节"被视线"放开的手"反向回响**。

### 3.1 AI 原生重构评估（物件母题）

| 类别 | 评估 | 说明 |
| --- | --- | --- |
| **可直接复用** | 毕业照的"同站位 + 不同磨损" | 这是 V5/V6 反复强调的 canonical asset 原则，AI 重构应让两张照片在 LLM prompt 中**显式声明"同一母版"**，避免重生成时漂移 |
| **可直接复用** | 名单 / 车票 / 邮件的"语义替身"机制 | 抽象物件（名单、车票、邮件）以可触可查的替身（蓝铅笔太阳、公交票、光标节拍）出现，避免"列表 UI 化"——AI 重构应保留这个原则 |
| **可直接复用** | 物件之间的"容器化"（诗集夹处分通知、诗集夹毕业照、信封装机票） | 让物件成为**记忆的物理容器**，比纯文字回顾更有力——AI 重构应保留 |
| **需要重构** | 毕业照的 `canonical-graduation-photo.png` 与 `graduation-photo-day.png` 并存 | `canonical-graduation-photo.png` 是母版，`graduation-photo-day.png` 是带"摄影师背影 + 约十五名学生"的场景版——两者都标 `canonicalPhoto` 字段，容易混淆。AI 重构应明确"母版 = 静态毕业照"+"场景版 = 毕业那天"两层 |
| **必须废弃** | 诗集在 `campus` 场景仅以"把诗夹进书里"出现一次，之后无任何"阅读诗集"动作 | 物件母题如果不在 5 章里被持续操作，会沦为"被提及的物品"而非"被使用的物件"。AI 重构应在每一章设置"翻诗集 / 触车票 / 抹照片"的微动作 |

---

## 4. 数值与系统

### 4.1 显影度 5 档（0–100）的具体定义

来自 V6 契约第 4 节 + `progression.ts: memoryTier`。

| 范围 | 档位（`MemoryTier`） | 解锁内容 | 数据实现 |
| ---: | --- | --- | --- |
| 0–20 | `base`（基础剧情） | 25 幕主线、基础选择与免费完整结局 | `score >= 21` 才进入下一档；首轮默认 0 分 |
| 21–40 | `inner`（内心独白） | 与已做动作相符的角色内心片段 | `score >= 21 && score < 41` |
| 41–60 | `details`（场景细节与纪念物） | 更多物件说明、组合线索与卷宗细节 | `score >= 41 && score < 61` |
| 61–80 | `preview`（隐藏对白预览） | 在卷宗中看见未解锁对白入口与预览 | `score >= 61 && score < 81` |
| 81–100 | `archive`（完整记忆卷宗与特别尾声） | 完整档案层级及满足条件后的特别尾声 | `score >= 81`；需"完成 5 章 + 显影度 ≥ 81"才解锁 `specialEpilogue = "available"` |

**档位文案**（来自 `progression.ts: memoryTierLabels`）：
- `base` = "基础剧情"
- `inner` = "内心独白"
- `details` = "场景细节与纪念物"
- `preview` = "隐藏对白预览"
- `archive` = "完整记忆卷宗与特别尾声"

**当前档 → 下一档反馈**（`nextMemoryUnlock` 函数）：
- 当前 0–20 → 距离下一档（21）还差 `21 - score` 分；
- 当前 21–40 → 距离下一档（41）还差 `41 - score` 分；
- 当前 41–60 → 距离下一档（61）还差 `61 - score` 分；
- 当前 61–80 → 距离下一档（81）还差 `81 - score` 分；
- 当前 81–100 → 返回 `null`，已满档。

### 4.2 五章满额 21 / 21 / 20 / 19 / 19 = 100 的计算逻辑

V6 契约第 4 节明确："五章满额依次为 21 / 21 / 20 / 19 / 19，总计正好 100。" 这一数字与 `interactionCatalog` 互动收益对账如下：

| 章 | 互动 ID（按 V6 互动表） | memoryGain | 章内小计 | 章末结算 | 章满额 | 一致性 |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| 第一章 | `photo-placement` (5) + `projector-repair` (7) + `first-memory-action` (6) | 18 | 18 | 3 | **21** | ✓ 18+3=21 |
| 第二章 | `publication-clues` (5) + `names-decision` (7) + `discipline-record` (6) | 18 | 18 | 3 | **21** | ✓ 18+3=21 |
| 第三章 | `departure-packing` (5) + `last-night-truth` (7) + `airport-goodbye` (5) | 17 | 17 | 3 | **20** | ✓ 17+3=20 |
| 第四章 | `dual-city-objects` (5) + `email-draft` (7) + `receipt-memory-combination` (4) | 16 | 16 | 3 | **19** | ✓ 16+3=19 |
| 第五章 | `reunion-gaze` (5) + `photo-pairing` (6) + `final-crossroad` (5) | 16 | 16 | 3 | **19** | ✓ 16+3=19 |
| **合计** | 15 项 | 85 | 85 | 15 | **100** | ✓ 85+15=100 |

> 关键发现：V6 契约的 21/21/20/19/19 是从**全部 15 个互动**（含 5 个 `optional`）算出的满额；首轮若仅完成 `required` 互动，得到 `5+7+6+7+7+5+7+5+6+5 = 60` 分，加 5 章结算 15 分 = 75 分，**卡在 61–80（preview）档，无法进入 archive 档**。要解锁特别尾声必须**完成全部 5 个 optional 互动**。

**实现函数**：
- `firstRunRequiredMemory()` = `sum(required.memoryGain) + 5×3 = 60 + 15 = 75`
- `fullCollectionMemory()` = `sum(all.memoryGain) + 5×3 = 85 + 15 = 100`

### 4.3 本地模拟权益（¥1 / ¥2.9 / ¥9.9）的具体语义

来自 V6 契约第 5 节 + `progression.ts: productPrices + priceForProduct + computeUpgradeCredit`。

| 权益 | 演示价格 | 作用域（V6 契约原文） | 产品 ID | 实际作用域（代码） | 升级抵扣规则 |
| --- | ---: | --- | --- | --- | --- |
| 当前对白续接 | **¥1.00** | "只解锁当前隐藏对白在免费预览后的第一句续接，不解锁其余句子" | `dialogue:<PaidDialogueId>` | `visibleDialogueLineCount = hasFullAccess ? lockedLines.length : directDialogues.includes(id) ? 1 : 0` | 升级到章节包时按 100 分（=¥1）抵扣 |
| 本章完整对话 | **¥2.90** | "解锁当前章节这一段隐藏对白的全部剩余句子，并完整收入卷宗" | `chapter:<ChapterId>` | `chapterPacks.includes(chapterId)` 即可解锁该章所有 `lockedLines` | 升级到 full-pass 时按 290 分（=¥2.9）× 已购章节抵扣 |
| 五章完整对白 | **¥9.90** | "解锁五章全部五段隐藏对白，并收入完整卷宗" | `full-pass` | `fullPass = true` 即可解锁所有 `lockedLines` | 抵扣 = `chapterPacks.size × 290 + uncoveredDirect × 100` |

**推荐路径**（`recommendOffer`）：
- 当前对话未购买 + 完成章节 < 2 → 推荐 `dialogue:<id>`（¥1 续接）
- 当前对话已购买 ¥1 续接 → 推荐 `chapter:<id>`（¥2.9，抵扣后 ¥1.9）
- 完成章节 ≥ 2 + 未购 full-pass → 推荐 `full-pass`（¥9.9）
- 已购 full-pass → 推荐 `null`（不再推荐）

**权益状态的现实约束**（V6 契约第 5 节 + 第 11 节）：

> "以上全部由浏览器本地状态模拟：不调用支付 SDK、不创建订单、不扣款、不校验账号、不承诺跨设备同步。按钮必须使用'本地演示''模拟解锁'等明确措辞。正式支付、退款、账号、跨端权益、风控、未成年人保护和合规服务仍待接入。"

→ 即 V6 现行实现是**纯前端 localStorage 状态机**，所有"¥"标价仅是 UI 文字，**没有货币含义**。

### 4.4 AI 原生重构评估（数值与系统）

| 类别 | 评估 | 说明 |
| --- | --- | --- |
| **可直接复用** | 0–100 五档数值 + 21/41/61/81 四个阈值 | 阈值设计工整，可被 LLM 直接消费为 prompt 参数 |
| **可直接复用** | `interactionCatalog` 的 15 互动结构 + 5 章结算的 15 分 | 数值与互动 1:1 绑定，AI 重构可基于此数据生成 |
| **可直接复用** | `clampMemory + memoryTier + nextMemoryUnlock` 工具函数 | 这三个函数在 0–100 边界处理上稳健，AI 重构可保留 |
| **需要重构** | "首轮必满 75 分"的隐含假设 | 当前首轮仅完成 `required` 互动得 75 分；要解锁特别尾声必须完成 `optional`。但 V6 契约第 4 节又要求"基础结局免费且完整"且"显影度、模拟权益和礼包领取均不得阻塞结局"——这两条**不冲突**（结局是 base 档就可达），但**特别尾声要求满档的设计让首轮玩家几乎不可能触发**。AI 重构应让"特别尾声"门槛降到 81 + 完成 5 章，而不必苛求 100 |
| **必须废弃** | **¥1.00 单句续接** | 任务简报明确："¥1 截句"是经验教训说必须废弃。V6 仍保留 100 分 = 1 句的"截句"产品——AI 重构必须**移除**。理由：① 1 句价格定义没有叙事完整性；② "¥1 → ¥1.9 抵扣"是 1 元费用的会计游戏；③ 在 LLM 原生叙事中，"未说完的话"应被 agent 自身驱动显影，不应再卖单句 |
| **必须废弃** | **京东 `G1N-DEMO-*` 演示码** | 任务简报明确："京东码"是经验教训说必须废弃。V6 仍以 `G1N-DEMO-2008-01` 等 5 个码作为"剧情内演示礼包"——AI 重构必须**移除**。理由：① 京东是真实品牌，`JD` 前缀会被误读为合作；② 5 码从"照片冲印批次号 / 处分档案编号 / 行李牌字符 / 邮件元数据 / 咖啡小票底部"显影，本质是"剧情内彩蛋"；LLM 原生叙事中"彩蛋"应通过 agent 提示词内部生成，不需要外置码 |
| **必须废弃** | **客户端权威存档**（`save-state.ts` + `ProfileStateV6`） | 任务简报明确："客户端权威存档"是经验教训说必须废弃。V6 仍以 `localStorage` 持久化 5 维（progression + entitlements + paidContent + revisit + romance）状态，且**未提及任何服务端权威**。AI 重构应改为**服务端事件流** + 客户端只读视图，存档由后端落库 |
| **不需要处置** | ¥2.9 章节包 / ¥9.9 全剧情通行证 | 这两个产品语义清晰（解锁本章 / 解锁全部五章），在 LLM 原生叙事里仍有价值，但**不应在客户端权威**——若保留，也应通过服务端权益判定 |
| **必须废弃** | **AI 聊天框** | 任务简报明确："AI 聊天框"是经验教训说必须废弃。V6 当前没有 chatbox，但 V6 留下了"卷宗 + 重剪"这种**模拟"和角色对话"的回响机制**（如 `paidDialogueById` 的 `lockedLines` 是"假对话"）。AI 重构应避免复用"假对话"作为 LLM 包装——LLM 原生应让 agent 直接读玩家输入，不应预写"角色台词"再让 LLM 改写 |

---

## 5. 商业化资产

### 5.1 5 枚演示码（G1N-DEMO-*）的剧情来源

来自 V6 契约第 6 节 + `progression.ts: chapterRewards`。注意：**V6 文档明确要求"工程不得使用京东标识，不得暗示合作、授权、赞助或真实兑换关系"**，但 5 码仍以 `G1N-DEMO-` 为前缀。

| 章 | 剧情来源（具体物件） | 演示码 | 下一章钩子 | 免责声明 |
| --- | --- | --- | --- | --- |
| 第一章 | 照片背面的冲印批次号 | `G1N-DEMO-2008-01` | "下一枚藏在一页不该有压痕的旧书里。" | "演示礼包码，无实际面值，暂不可兑换。" |
| 第二章 | 处分通知的档案编号 | `G1N-DEMO-2009-02` | "下一枚字符，跟着一张只写目的地的行李牌。" | "演示礼包码，无实际面值，暂不可兑换。" |
| 第三章 | 单程行李牌背面的字符 | `G1N-DEMO-2011-03` | "下一枚不在一座城市里。找两处相同的时间。" | "演示礼包码，无实际面值，暂不可兑换。" |
| 第四章 | 未发送邮件的系统元数据 | `G1N-DEMO-2011-04` | "最后一枚藏在一杯茶和两张旧纸之间。" | "演示礼包码，无实际面值，暂不可兑换。" |
| 第五章 | 咖啡小票底部的纪念编码 | `G1N-DEMO-2024-05` | "5/5。终章纪念礼物待解锁。" | "演示礼包码，无实际面值，暂不可兑换。" |

**码的流转状态**（`RewardStatus`）：
- `locked` → 章末结算时通过 `revealChapterReward` 变 `revealed`
- `revealed` → 玩家点击"领取 / 复制"时通过 `claimChapterReward` 变 `claimed`
- 全部 5 枚 `claimed` 后，`buildChapterSummary` 报 `2/5` `3/5` 等进度

**领奖 UI 流程**（V6 契约第 8 节）：
"章末结算顺序：本章情绪句；本章显影增量与新获得物；隐藏对白遗漏数量；剧情物件显影出的演示码；领取 / 复制状态；下一章线索与进入按钮。"

### 5.2 章节包 / 全剧情通行证的语义

| 产品 | 价格 | 作用域 | 实现函数 | 推荐时机 |
| --- | ---: | --- | --- | --- |
| 章节包（`chapter:<ChapterId>`） | ¥2.90 / 章 | 解锁该章所有 5 段 `lockedLines` | `chapterPacks.includes(chapterId) → hasFullDialogueAccess = true` | 玩家已购 ¥1 续接 |
| 全剧情通行证（`full-pass`） | ¥9.90 | 解锁 5 章全部 25 句 `lockedLines` | `fullPass = true` | 完成 2 章以后 |
| 升级抵扣（`computeUpgradeCredit`） | — | 升级到更高档时按权益去重抵扣 | `chapter: target` 抵扣 = `该章 directDialogues.size × 100` 分；`full-pass: target` 抵扣 = `chapterPacks.size × 290 + uncoveredDirect × 100` 分 | 自动 |

**价值倒挂校验**（V6 契约第 5 节硬约束）：
"三档价格对应逐级扩大的内容范围：¥1 是一次微型续接，¥2.9 是当前章节完整段落，¥9.9 是五章完整合集，所以不存在'更低价格反而解锁更多内容'的价值倒挂。"

V6 代码实现通过 `recommendOffer + visibleDialogueLineCount` 保证：
- 玩家只能买"未拥有的范围"；
- 升级时按 `computeUpgradeCredit` 自动抵扣；
- `chapterPacks` 比多个 `directDialogues` 合并更便宜（当一个章有 ≥ 2 段隐藏对白时）。

### 5.3 AI 原生重构评估（商业化资产）

| 类别 | 评估 | 说明 |
| --- | --- | --- |
| **必须废弃** | 5 枚 `G1N-DEMO-*` 演示码 | 见第 4.4 节评估。LLM 原生叙事中不需要"彩蛋码" |
| **必须废弃** | ¥1.00 单句续接 | 见第 4.4 节评估 |
| **需要重构** | 章节包 / 全剧情通行证 | 若保留，应改为：① 服务端权益；② 与剧情叙事耦合（如"完成第 2 章"才能看到章节包入口，而不是"完成 2 章"就推） |
| **需要重构** | "推荐路径"（¥1 → ¥2.9 → ¥9.9） | V6 用 `recommendOffer` 在 `completedChapterIds.length >= 2` 时强制推 ¥9.9，**这是漏斗设计**。AI 重构应改为"玩家主动打开卷宗才看到权益列表"，**不让 LLM/agent 主动催促** |
| **需要重构** | "价格倒挂校验" | 任务简报未要求保留此约束；LLM 原生叙事中"价格"概念本身应被"对话深度 / 记忆深度"语义替换 |

---

## 6. 声音资产

### 6.1 环境声、声音母题的具体清单

来自 `app/audio-engine.ts`。

**章节白噪声**（`chapterSound`，每章一个低通滤波 + 噪声电平）：

| 章节 | 截止频率（Hz） | 噪声电平 | 用途 |
| --- | ---: | ---: | --- |
| `prologue` | 720 | 0.012 | 伊斯坦布尔咖啡馆雨声基底 |
| `chapter1` | 1050 | 0.014 | 2008 德黑兰的雨棚 + 远街 |
| `chapter2` | 520 | 0.016 | 2009 纪律委员会问话室（低截止 = 闷） |
| `chapter3` | 430 | 0.017 | 2010 出租屋凌晨（更低 = 静） |
| `chapter4` | 820 | 0.011 | 2011—2021 圣何塞公寓 + 德黑兰屋顶 |
| `chapter5` | 680 | 0.010 | 十三年后伊斯坦布尔（最低 = 远） |
| `ending` | 560 | 0.009 | 结局电影尾声 |

**主题旋律**（`themes`，自称"inspired by Dastgah-e Shur"，按 V6 代码注释"the melody is original and intentionally sparse"）：

| 章节 | 速度 (BPM) | 基频 (Hz) | 音量 | 鼓点位置 |
| --- | ---: | ---: | ---: | --- |
| `prologue` | 72 | 146.83 (D3) | 0.015 | [0, 6, 10] |
| `chapter1` | 84 | 146.83 (D3) | 0.019 | [0, 4, 7, 10, 14] |
| `chapter2` | 68 | 130.81 (C3) | 0.014 | [0, 9] |
| `chapter3` | 76 | 130.81 (C3) | 0.016 | [0, 6, 11] |
| `chapter4` | 78 | 146.83 (D3) | 0.014 | [0, 8] |
| `chapter5` | 66 | 146.83 (D3) | 0.013 | [0, 10] |
| `ending` | 60 | 130.81 (C3) | 0.012 | [0] |

**声音母题**（`motif(type)`，按 type 调出两频率之间的滑音）：

| 母题 type | 起音 → 终音 (Hz) | 时长 (s) | 滤波 | 触发场景 |
| --- | --- | ---: | --- | --- |
| `photo` | 246.94 → 220 | 0.34 | lowpass 1200 | 翻照片 / 落桌 |
| `paper` | 329.63 → 293.66 | 0.28 | lowpass 1200 | 折诗 / 撕纸 |
| `ash` | 92.5 → 73.4 | 0.42 | lowpass 240 | 笔迹 / 印章 |
| `ticket` | 196 → 246.94 | 0.24 | lowpass 1200 | 车票 / 行李牌 |
| `email` | 440 → 392 | 0.18 | lowpass 1200 | 删除 / 光标节拍 |

**质感纹理**（`texture(type)`，按 type 调出对应滤波 + 噪声）：

| 纹理 type | 滤波 | 中心频率 (Hz) | 峰值 | 时长 (s) | 用途 |
| --- | --- | ---: | ---: | ---: | --- |
| `projector` | lowpass | 310 | 0.008 | 1.10 | 16mm 放映机马达 + 48Hz 嗡声 |
| `fluorescent` | bandpass | 118 | 0.004 | 0.42 | 荧光灯 + 100Hz 嗡声 |
| `keyboard` | highpass | 1800 | 0.007 | 0.42 | 打字机 / 键盘 |
| `airport` | bandpass | 620 | 0.006 | 0.42 | 机场广播 / 候机厅 |
| `tea` | highpass | 2400 | 0.006 | 0.42 | 茶杯 / 雨棚滴水 |
| `rain` | lowpass | 1100 | 0.008 | 0.90 | 雨声 |

**提示音**（`cue(type)`，按事件类型调出短促音）：

| cue type | 起音 → 终音 (Hz) | 用途 |
| --- | --- | --- |
| `choice` | 392 → 523.25 (G4 → C5) | 三选一卡片 |
| `transition` | 146.8 → 196 (D3 → G3) | 场景转场 |
| `save` | 659.25 → 783.99 (E5 → G5) | 自动存档 |
| `ending` | 220 → 329.63 (A3 → E4) | 电影尾声 |

**母题调用入口**（`MainOption.sound` + `ResonanceOption.sound` + `HeartbeatMoment.sound`）：

| 选项 / 互动 | sound 字段 | 实际调用 |
| --- | --- | --- |
| `choice-one.poem` | `paper` | 折诗的纸声 |
| `choice-one.kiss` | `photo` | 暗处的照片落定 |
| `choice-one.leave` | `ticket` | 离开时收票 |
| `choice-two.*` | `paper` / `paper` / `ash` | 供词 / 诗集 / 笔迹 |
| `choice-three.*` | `paper` / `ticket` / `ticket` | 未寄出的信 / 两张车票 / 行李牌 |
| `photo.*` | `photo` | 翻照片 |
| `email.*` | `email` | 删除光标 |
| `gaze.*` | `photo` / `paper` / `ticket` | 白发 / 书页 / 站钟 |
| `heartbeats.hands` | `paper` | 擦机油的纸声 |
| `heartbeats.arrival` | `ticket` | 时间被拨快 |
| `heartbeats.pomegranate` | `photo` | 石榴 = 照片（甜） |

### 6.2 默认静音、用户手势启动的规则

V5 契约第 7 节明确：

> "默认静音；标题页提供'有声进入 / 静音进入'，首次用户手势后才创建或恢复音频上下文。"

代码实现（`audio-engine.ts: AudioEngine.start`）：
- 构造时不创建 `AudioContext`；
- `start(chapter)` 时第一次 `new AudioContext()`；
- 若 `context.state === 'suspended'` 则 `await this.context.resume()`；
- 仅当用户已触发 `start` 后才执行 `setChapter`。

**清理规则**（V5 契约第 7 节）：
- "声音偏好保存在本设备"——通过 `localStorage` 的 `audioPref` 等字段；
- "切换、重剪和组件卸载时正确停止节点与定时器"——`stop()` 调用 `stopMusic + stopAmbience + context.close()`。

### 6.3 AI 原生重构评估（声音资产）

| 类别 | 评估 | 说明 |
| --- | --- | --- |
| **可直接复用** | 6 个 `texture` 类型（projector / fluorescent / keyboard / airport / tea / rain） | 都是"叙事性环境声"（V5 契约第 7 节），与物件母题强相关，AI 重构保留 |
| **可直接复用** | 5 个 `motif`（photo / paper / ash / ticket / email） | 与 `MainOption.sound + ResonanceOption.sound` 字段 1:1 绑定，AI 重构可作为 agent 输出的 sound 字段直接消费 |
| **可直接复用** | 4 个 `cue`（choice / transition / save / ending） | UI 事件音，AI 重构可作为 LLM 输出的事件标记 |
| **可直接复用** | "默认静音 + 用户手势启动"规则 | 这是移动端 WebAudio 的硬性约束，AI 重构保留 |
| **需要重构** | "Dastgah-e Shur" 自称 | V6 注释明确说 "the melody is original and intentionally sparse"，且 V5 契约第 7 节硬约束："未经文化与音乐复核，不宣称'严格传统波斯音乐还原'"。但 `themes` 字段命名 `shurCents` 仍暗示文化根源——AI 重构应改为"低干扰氛围"通用名，**不绑定特定文化体系** |
| **必须废弃** | 没有 AI 生成音频的接口 | 任务简报未明说，但 V6 的所有声音是"硬编码 sine + noise + biquad"——AI 重构应支持"agent 实时生成或调用 audio LLM"路径，让声音母题由 LLM 决定，而不是开发期写死 |
| **必须废弃** | 静态的 7 套主题旋律 | LLM 原生应让 agent 根据当前玩家动作 + 当前章节 + 当前心情实时生成旋律，而不是 `themes[chapter]` 硬编码 |

---

## 7. 美术资产清单

### 7.1 49 张图（注：磁盘实有 44 张艺术图 + 1 张 og.png）

> 重要勘误：任务简报称"49 张 PNG"，但 `_legacy_v6/public/` 下实际可清点的 PNG 数为：
> - `art/` = 6（chapter-1 至 chapter-6）——**完全未被 story.ts 引用**
> - `art-v2/` = 7
> - `art-v3/` = 7
> - `art-v4/` = 14
> - `art-v5/` = 10
> - `og.png` = 1（根目录宣传图）
> - **合计 45 张 PNG**。差额 4 张应源自任务简报的历史口径，下文以磁盘实数为准。

### 7.2 art/ 旧资源（6 张，0 张被 story.ts 引用）

| 文件 | 用途（V4 文档） | 当前状态 |
| --- | --- | --- |
| `art/chapter-1.png` | 第一章封面（V2 时期） | **未引用** |
| `art/chapter-2.png` | 第二章封面（V2 时期） | **未引用** |
| `art/chapter-3.png` | 第三章封面（V2 时期） | **未引用** |
| `art/chapter-4.png` | 第四章封面（V2 时期） | **未引用** |
| `art/chapter-5.png` | 第五章封面（V2 时期） | **未引用** |
| `art/chapter-6.png` | 终章封面（V2 时期） | **未引用** |

> 关键发现：6 张章封面**没有任何代码引用**——它们是 V2/V3 时期的产物，V4 之后被 `art-v2/ + art-v3/ + art-v4/ + art-v5/` 取代。AI 重构应直接废弃或归档到 `legacy/` 目录。

### 7.3 art-v2/（7 张，1 张被引用）

| 文件 | 用途 | 状态 |
| --- | --- | --- |
| `art-v2/basement-cinema.png` | 地下室电影放映 | **未引用**（与 `art-v4/underground-projector-close.png` 重复） |
| `art-v2/departure-station.png` | 出发站（铁路元素） | **未引用**（V4 明文禁止铁路元素："任何机场镜头都禁止铁路、站台、列车或火车站构图"） |
| `art-v2/istanbul-cafe.png` | 第五章章首页背景 | **已引用**：`chapter-five` |
| `art-v2/istanbul-crossroad.png` | 伊斯坦布尔路口 | **未引用**（V5 用 `art-v5/istanbul-crossroads-aged.png` 取代） |
| `art-v2/poetry-list.png` | 诗集 / 名单 | **未引用** |
| `art-v2/san-jose.png` | 圣何塞城市 | **未引用**（V5 用 `art-v5/san-jose-arrival-2011.png` 取代） |
| `art-v2/street-rain.png` | 雨夜街道 | **未引用** |

### 7.4 art-v3/（7 张，6 张被引用）

| 文件 | 用途 | 状态 |
| --- | --- | --- |
| `art-v3/discipline-committee.png` | 纪律委员会档案 | **已引用**：`echo-two` |
| `art-v3/san-jose-apartment.png` | 圣何塞公寓 | **已引用**：`two-cities.arts[2]` |
| `art-v3/sfo-arrivals.png` | SFO 抵达 | **未引用**（V4 章节用 `art-v5/san-jose-arrival-2011.png` 取代） |
| `art-v3/tehran-airport-departure.png` | 德黑兰机场出发 | **已引用**：`chapter-three` |
| `art-v3/tehran-literature-class.png` | 德黑兰文学课 | **已引用**：`campus` |
| `art-v3/tehran-rental-room.png` | 德黑兰出租屋 | **已引用**：`small-room` + `one-year` |
| `art-v3/tehran-rooftop.png` | 德黑兰屋顶 | **已引用**：`echo-one` + 2 个 daily rotation |

### 7.5 art-v4/（14 张，14 张被引用，V4 美术清单的核心增量）

| 文件 | 用途 | 状态 |
| --- | --- | --- |
| `art-v4/airport-clock-goodbye.png` | 机场时钟告别 | **已引用**：`echo-three` + 4 个 revisit 场景 |
| `art-v4/dorm-search-night.png` | 宿舍搜查夜 | **已引用**：`choice-two` + 4 个 revisit 场景 |
| `art-v4/email-delete-night.png` | 删除邮件的夜 | **已引用**：`email` + `last-email` |
| `art-v4/final-rooftop-night.png` | 最后一夜屋顶 | **已引用**：`choice-three` + 1 个 revisit 场景 |
| `art-v4/graduation-photo-day.png` | 毕业照当天 | **已引用**：1 个 revisit 场景（被 `art-v5/graduation-photo-day.png` 在主场景取代） |
| `art-v4/localization-office.png` | 圣何塞本地化办公室 | **已引用**：`two-cities.arts[0]` |
| `art-v4/maryam-telescope-rooftop.png` | 玛丽亚姆望远镜屋顶 | **已引用**：`two-cities.arts[1]` |
| `art-v4/poetry-book-photo-close.png` | 诗集照片特写 | **已引用**：V4 主场景（被 `art-v5/poetry-book-photo-close.png` 取代为重访版） |
| `art-v4/student-publication-room.png` | 学生刊物编辑室 | **已引用**：`chapter-two` + `publication` |
| `art-v4/underground-projector-close.png` | 地下室放映机特写 | **已引用**：`choice-one` + 4 个 revisit 场景 |
| `art-v4/university-gate-autumn.png` | 大学门口秋 | **已引用**：`chapter-one` |
| `art-v4/university-gate-expulsion.png` | 大学门口处分 | **已引用**：`after-gate` + 1 个 revisit 场景 |
| `art-v4/video-call-kamran.png` | 与卡姆兰视频 | **已引用**：`kamran` |
| （V4 文档列了 14 个镜头，对应 14 张文件，0 张遗漏） | — | — |

### 7.6 art-v5/（10 张，10 张被引用，V5/V6 canonical 集）

| 文件 | 用途 | 状态 |
| --- | --- | --- |
| `art-v5/canonical-graduation-photo.png` | 毕业照母版（仅头像） | **已引用**：`photo.canonicalPhoto` + `promise.canonicalPhoto` + `book.canonicalPhoto` |
| `art-v5/graduation-photo-day.png` | 毕业照当天（场景版） | **已引用**：`promise` |
| `art-v5/istanbul-cafe-photo-close.png` | 序章伊斯坦布尔咖啡馆 | **已引用**：`photo` |
| `art-v5/istanbul-crossroads-aged-mobile.png` | 伊斯坦布尔路口（移动端竖屏） | **已引用**（在 daily rotation 列表中作为兜底） |
| `art-v5/istanbul-crossroads-aged.png` | 伊斯坦布尔路口（横屏） | **已引用**：`crossroads` + 1 个 revisit 场景 |
| `art-v5/istanbul-reunion-aged-mobile.png` | 重逢（移动端竖屏） | **已引用**（在 daily rotation 列表中作为兜底） |
| `art-v5/istanbul-reunion-aged.png` | 重逢（横屏） | **已引用**：`gaze` |
| `art-v5/poetry-book-photo-close.png` | 诗集照片特写（V5 重制） | **已引用**：`book` |
| `art-v5/san-jose-arrival-2011-mobile.png` | 圣何塞 2011 抵达（移动端） | **已引用**（在 daily rotation 列表中作为兜底） |
| `art-v5/san-jose-arrival-2011.png` | 圣何塞 2011 抵达（横屏） | **已引用**：`chapter-four` |

### 7.7 核心母题 vs 过渡图

| 类别 | 图片 | 复用次数 | 重要性 |
| --- | --- | ---: | --- |
| **核心母题 1：毕业照** | `art-v5/canonical-graduation-photo.png` | 3 处 canonicalPhoto 引用 | **最高**——决定"同站位 + 不同磨损"的连续性 |
| **核心母题 1：毕业照** | `art-v5/graduation-photo-day.png` | 1 处（promise 主场景） | **最高** |
| **核心母题 2：伊斯坦布尔重逢** | `art-v5/istanbul-reunion-aged.png` | 1 处（gaze） | **最高** |
| **核心母题 2：伊斯坦布尔重逢** | `art-v5/istanbul-cafe-photo-close.png` | 1 处（photo 序章） | **高** |
| **核心母题 3：机场告别** | `art-v4/airport-clock-goodbye.png` | 5 处（echo-three + 4 revisit） | **高** |
| **核心母题 3：机场告别** | `art-v3/tehran-airport-departure.png` | 1 处（chapter-three） | **高** |
| **核心母题 4：诗集 + 照片** | `art-v5/poetry-book-photo-close.png` | 1 处（book） | **最高**——5 个路由的终点之一 |
| **过渡图 1：大学门口** | `art-v4/university-gate-autumn.png` + `art-v4/university-gate-expulsion.png` | 1 + 2 处 | 中 |
| **过渡图 2：出租屋** | `art-v3/tehran-rental-room.png` | 2 处 | 中 |
| **过渡图 3：本地化办公室 + 望远镜 + 公寓** | `art-v4/localization-office.png` + `art-v4/maryam-telescope-rooftop.png` + `art-v3/san-jose-apartment.png` | 3 帧蒙太奇 | 中 |
| **过渡图 4：last-night / email-delete** | `art-v4/final-rooftop-night.png` + `art-v4/email-delete-night.png` | 1 + 2 处 | 中 |
| **过渡图 5：地下室放映机** | `art-v4/underground-projector-close.png` | 5 处（choice-one + 4 revisit） | 高（"前两段不计分"但视觉反复出现） |

### 7.8 AI 原生重构评估（美术资产）

| 类别 | 评估 | 说明 |
| --- | --- | --- |
| **可直接复用** | `art-v5/canonical-graduation-photo.png`（母版） | V5/V6 的连续性核心，AI 重构应作为"ground truth" prompt 的参考图 |
| **可直接复用** | V4 的 14 张镜头 + V5 的 10 张镜头 | 共 24 张图全部被引用，AI 重构可作为"历史美术 ground truth"喂给 LLM |
| **可直接复用** | "art-v5 移动端变体 + 横屏变体"双版本策略 | 移动端 + 桌面端的 responsive art，AI 重构保留 |
| **需要重构** | `art/` 6 张未引用 + `art-v2/` 6 张未引用 + `art-v3/sfo-arrivals.png` 1 张未引用 = **13 张废弃候选** | AI 重构应归档到 `legacy_art/` 而非清空，方便回归测试 |
| **需要重构** | `art-v4/graduation-photo-day.png`（被 v5 取代但仍在 revisit 场景使用） | AI 重构应统一为 v5 版本，或在 revisit 中明确标注"用旧版以示不同回忆状态" |
| **需要重构** | `art-v4/poetry-book-photo-close.png`（被 v5 取代） | 同上 |
| **必须废弃** | `art-v2/departure-station.png`（铁路元素） | V4 已明文禁止；这是 V3 时期的违例资产，AI 重构必须删除 |
| **必须废弃** | V2 风格的 6 张 `art/chapter-N.png` | 全部未被引用，AI 重构应直接归档 |

---

## 8. 测试资产

### 8.1 实测情况 vs 任务简报

> 重要勘误：任务简报称"10 个测试文件"，但 `_legacy_v6/` 下**没有任何 `*.test.*` 或 `*.spec.*` 文件**（已用 `Get-ChildItem -Recurse` 确认）。
> V6 契约第 10 节自报："当前全量自动测试基线为 60 项，其中 V6 新增 15 项"——这里 60 / 15 指**测试用例（cases）**，不是测试文件。
> 项目根目录 `D:/G1-ai-native/tests/` 存在 4 个子目录（`adversarial/`、`contracts/`、`engine/`、`scenarios/`），但**全部为空**——这是 AI 原生重构项目要新建的测试目录。

### 8.2 V6 文档自报的测试基线

V6 契约第 10 节明确 60 + 15 项测试覆盖范围：

| 类别 | 覆盖项 | 数量（V6 文档声称） | 备注 |
| --- | --- | ---: | --- |
| 显影数值 | 21/41/61/81 阈值切换、5 章满额 100 校验、clampMemory 边界 | ~12 | V6 文档未细分 |
| 权益范围 | ¥1 / ¥2.9 / ¥9.9 作用域、visibleDialogueLineCount 计算、hasFullDialogueAccess 判定 | ~10 | V6 文档未细分 |
| 升级抵扣 | computeUpgradeCredit 边界（chapter → full-pass、direct → chapter、重复购买幂等） | ~8 | V6 文档未细分 |
| 礼包 | 5 枚演示码 reveal/claim、RewardStatus 状态机、批次号匹配 | ~5 | V6 文档未细分 |
| 卷宗 | 显影度反馈、下一档距离、2/5 礼包进度、未解锁对白入口 | ~8 | V6 文档未细分 |
| 存档 | normalizeProfile 字段、跨版本兼容、dailyFragmentClaimCount 单调递增 | ~7 | V6 文档未细分 |
| 22 事件 | scene_enter / interaction_start / interaction_complete / clue_discovered / memory_value_change / collectible_get / paid_dialogue_* / chapter_pack_* / full_pass_* / chapter_reward_* / chapter_complete / next_chapter_start / save_resume / ending_complete / revisit_start / return_teaser_click | ~10 | V6 文档未细分 |
| 合计 | — | **60** | V6 文档自报 |
| 其中 V6 新增 | 22 事件基线 + specialEpilogue 门槛 + dailyFragment 单调性 + computeUpgradeCredit + normalizeSimulatedPurchase | **15** | V6 文档自报 |

> 重要：以上数字来自 V6 文档自报，**磁盘上不存在任何测试文件可验证**。V6 文档"测试基线 60 项 / V6 新增 15 项"是**承诺而非已实现**。

### 8.3 手动验收路径（V6 文档第 10 节明确保留）

> "刷新续玩、次日碎片、章节回访和特别尾声同时保留手动验收路径。"

V6 把以下 4 条流程作为手动验收而非自动化测试：
- 刷新页面后 `save_resume` 入口自动出现
- 次日碎片以本地日历日为准
- 章节回访的回响对比默认折叠未变化内容
- 特别尾声需完成 5 章 + 显影度 ≥ 81

### 8.4 V6 新增 15 项 vs 之前基线的差异

按 V6 文档"60 项基线 - 15 项 V6 新增 = 45 项 V5 及更早基线"反推，V5 及更早已覆盖：
- 25 幕定位（`resolveSavedSceneIndex`）
- `normalizeRunStartMemory` 边界
- 三轴判定 `determineEnding + scoreAnswers`
- 主轴×次轴反题 `axisPairCounterpoints`
- 共鸣三选 `composeCinematicEpilogue`
- 未来回响路由 `resolveFutureEchoes`
- `estimateMinimumActions` 操作数
- `selectUnchosenFragments` 残片过滤
- `HeartbeatId + heartbeatMoments + heartbeatState`
- `dailyMemoryRotations + rotationForDate + composeDailyRouteLines`
- `upsertDailyMemoryRecord + unlockedDailyMilestones`
- `composeEndingFragments + choiceDiff`
- 4 个游戏循环（探索 → 线索 → 互动 → 显影度 → 轴反馈）

V6 新增（按 `progression.ts` 与 V6 契约推断）：
1. `recommendOffer` 三档推荐路径
2. `availablePurchaseOffers` 多产品列表
3. `computeUpgradeCredit` 升级抵扣（V6 关键新增）
4. `normalizeSimulatedPurchase` 价格 / 抵扣 / 实付三字段归一
5. `simulateLocalPurchase` 幂等购买
6. `claimDailyFragment` 单调递增
7. `unlockedDailyMilestones` 1/3/5 日解锁
8. `previewDailyFragment` 不消耗预览
9. `markChapterRevisit` 章节回访计数
10. `markSpecialEpilogueViewed` 特别尾声状态机
11. `chapterMemoryGain` 章节增量独立查询
12. `unresolvedDialogueCount` 跨章未解锁统计
13. `buildChapterSummary` 卷宗摘要
14. `claimedRewardIds` 全章已领筛选
15. `paidDialogueById / paidDialogueByScene / chapterRewardById / chapterContractById` 索引字典

### 8.5 AI 原生重构评估（测试资产）

| 类别 | 评估 | 说明 |
| --- | --- | --- |
| **必须废弃** | V6 文档"60 项基线 / V6 新增 15 项"——承诺而非已实现 | 磁盘上**没有任何测试文件**；AI 重构应**重新建立**测试套件，**不复用** V6 文档中声称的数字 |
| **需要重构** | V6 4 个手动验收路径 | AI 重构应把它们**自动化**——例如"刷新续玩"可通过 Cypress / Playwright 模拟 |
| **需要重构** | V6 22 事件"工程统一发出 ... 当前只写入本地调试日志" | AI 重构应让 22 事件从客户端上报改为**服务端事件流**，由服务端权威判定 |
| **可直接复用** | V6 测试覆盖面（显影 / 权益 / 抵扣 / 礼包 / 卷宗 / 存档 / 事件） | 这是良好的测试分类法，AI 重构保留 |
| **可直接复用** | V6 文档"刷新续玩 / 次日碎片 / 章节回访 / 特别尾声"4 条手动验收 | 这 4 条是核心场景，AI 重构应作为 E2E 必测项 |

---

## 9. 跨章节总结：v6 设计 vs 经验教训（任务简报"四项问题 + 必须废弃"）

任务简报中"经验教训"未在仓库内以文件形式存在，但给出了具体的评估准则。下表把这两套准则合并，逐项给出 v6 当前状态与 AI 原生重构建议。

### 9.1 "四项问题"逐条核验（每个互动是否真的改变：世界状态 / 人物认知 / 可用行动 / 未来回响）

| 互动 | 世界状态 | 人物认知 | 可用行动 | 未来回响 | 评估 |
| --- | --- | --- | --- | --- | --- |
| `photo-placement` | ✓ 照片落桌 / 翻面 / 收包 | ✓ 她先决定如何面对过去 | ✓ 影响 gaze 路由（`futureEchoRoutes.gaze` 链 photo.farEcho） | ✓ 终章桌面状态 | **通过** |
| `projector-repair` | ✓ 灯泡亮 / 齿轮咬合 | ✓ 共同记忆被认出 | ⚠ V5 说不计分，V6 给了 7 分——**内部矛盾** | ✓ 工具箱里的折痕 | **争议项**——V6 给分违背 V5 设计意图 |
| `first-memory-action` | ✓ 三个轴之一被记录 | ✓ 她的说话/靠近/退路风格定型 | ✓ 主轴进入 ending 判定 | ✓ nearEcho + farEcho 都生效 | **通过** |
| `publication-clues` | ✓ 找到失踪学生报道 | ⚠ 仅显示"学校会问" | ✗ **不改变可用行动**——`choice-two` 仍只问"是否告发" | ✗ 无远期回响 | **不通过**——只是包装过的下一页 |
| `names-decision` | ✓ 记录员合上本子 | ✓ 她的回答被记入档案 | ✓ 主轴定型 | ✓ 诗集 / 处分通知 / 划掉的名字 | **通过** |
| `discipline-record` | ✓ 玛兹雅的去向被确认 | ✓ 玩家知道玛兹雅 6 个月后获释 | ✗ **不改变可用行动**——`choice-two` 已经发生 | ✗ 无远期回响 | **不通过**——只是包装过的下一页 |
| `departure-packing` | ✓ 看清三个方向 | ✓ 离开有了可触摸的重量 | ✗ **不改变可用行动**——`choice-three` 仍只问"如何告别" | ✗ 无远期回响 | **不通过**——只是包装过的下一页 |
| `last-night-truth` | ✓ 三种说法都通向机场 | ✓ 她说话风格定型 | ✓ 主轴定型 | ✓ 沉默的形状不同 | **通过** |
| `airport-goodbye` | ✓ 行李过线 | ✓ 写下"我到了" | ⚠ 不可改，但**玩家操作**（握住→松开）被保留 | ✓ 远期回响 | **通过** |
| `dual-city-objects` | ✓ 同一天被发现 | ⚠ 玩家知道两人保留同一段记忆 | ✗ **不改变可用行动**——`email-draft` 仍只问"写哪句" | ✗ 无远期回响 | **不通过**——只是包装过的下一页 |
| `email-draft` | ✓ 光标节拍 / 删除残影 | ✓ 玩家先决定"地下室味道" / "诗集还在吗" / "我过得很好" | ⚠ 不进入 `futureEchoRoutes` 主体 | ✓ 远期回响（`gaze` 路由 email） | **通过** |
| `receipt-memory-combination` | ✓ 草稿 + 照片贴上冰箱 | ⚠ 玩家理解完整生活 | ✗ **不改变可用行动** | ✗ 无远期回响 | **不通过**——只是包装过的下一页 |
| `reunion-gaze` | ⚠ 仅移动焦点 | ⚠ 玩家先决定"看哪里" | ✗ **不改变可用行动**——`crossroads` 不依赖 gaze 选择 | ✓ 仅进入 endingFragment | **不通过**——任务简报点名"凝视热点如果只是 UI 操作不算" |
| `photo-pairing` | ✓ 两张照片对齐 | ✓ 玩家看到不同磨损 | ⚠ 不影响 `crossroads` | ✓ 路由到 `book` | **通过** |
| `final-crossroad` | ✓ 绿灯结束前放手 | ✓ 玩家完成"再见" | ✓ 通关进入特别尾声判定 | ✓ `crossroads` 路由 choice-three | **通过** |

**统计**：
- ✅ 通过 4 项问题全部四条的：8 项（photo-placement / first-memory-action / names-decision / last-night-truth / airport-goodbye / email-draft / photo-pairing / final-crossroad）
- ⚠ 内部矛盾：1 项（projector-repair）
- ❌ **不通过**（包装过的下一页 / 仅 UI 操作）：6 项（publication-clues / discipline-record / departure-packing / dual-city-objects / receipt-memory-combination / reunion-gaze）

> **关键发现**：V6 6/15 互动是"包装过的下一页"——它们**不改变可用行动**，仅提供"线索 + 收藏品 + 显影度"。任务简报点名的"项目书拖拽（projector）+ 凝视热点（gaze）"中，projector 通过（虽 V5/V6 矛盾），gaze 不通过（仅 UI 操作）。

### 9.2 "必须废弃"四项 vs v6 当前

| 经验教训禁止项 | v6 是否保留 | v6 当前位置 | AI 原生重构建议 |
| --- | --- | --- | --- |
| **¥1 截句** | **保留** | `priceForProduct(dialogue:*) = 100` 分 + `directDialogues` 列表 | **必须废弃**——改为"完成第 N 章自动解锁本章全部" |
| **京东码** | **保留** | 5 枚 `G1N-DEMO-*` 码（`chapterRewards` 列表） | **必须废弃**——移除"剧情内彩蛋码"机制 |
| **客户端权威存档** | **保留** | `save-state.ts` + `localStorage` + `ProfileStateV6` 5 维状态机 | **必须废弃**——改为服务端事件流 + 客户端只读视图 |
| **AI 聊天框** | **未保留** | v6 无 chatbox | **不需要处置**——但 v6 的"假对话"（`paidDialogue.lockedLines`）也不要再复用 |

### 9.3 整体 AI 原生重构优先级

| 优先级 | 任务 | 来源 |
| --- | ---: | --- |
| P0 | 移除 `G1N-DEMO-*` 5 枚码 + `priceForProduct` 100 分档 | 经验教训"必须废弃" + 商业化内嵌文化品牌 |
| P0 | 移除 `localStorage` 存档权威性，改为服务端事件流 | 经验教训"客户端权威存档"必须废弃 |
| P0 | 重构 `reunion-gaze` 让其改变可用行动（如影响 `crossroads` 选项） | 经验教训"凝视热点如果只是 UI 操作不算" |
| P0 | 6 个"包装过的下一页"互动（`publication-clues / discipline-record / departure-packing / dual-city-objects / receipt-memory-combination`）必须**删除或重做**为"改变可用行动"的互动 | 经验教训"四项问题" |
| P1 | 拆分 `first-memory-action`（与 `choice-one` 重复） | V6 内部冗余 |
| P1 | 统一 `projector-repair` "不计分 vs 7 分"的内部矛盾（V5 文档 vs V6 互动表） | V6 内部矛盾 |
| P1 | `chapterEnd` 显式挂在 5 个不同形态的场景，与"3 互动 / 章"不完全对齐 | 文档与代码错位 |
| P1 | 25 幕定义模糊（19 场景 + 5 章首页 + 1 序章 vs 节拍计 25 幕） | 文档与代码错位 |
| P2 | 13 张废弃候选美术（6 张 art/ + 6 张 art-v2/ + 1 张 art-v3/sfo-arrivals）归档到 `legacy_art/` | 减少混淆 |
| P2 | 8 个未引用美术文件清理或显式标注 | 减少磁盘占用 |
| P2 | 4 个手动验收路径（刷新续玩 / 次日碎片 / 章节回访 / 特别尾声）自动化 | V6 文档承诺 |
| P2 | 22 事件从客户端日志改为服务端事件流 | V6 文档承诺 + AI 原生要求 |
| P3 | 4 个 `heartbeatMoments`（hands / arrival / pomegranate）保留但需重新接入 LLM 驱动 | AI 原生可强化 |

---

## 10. 一句话总结

V6 是**叙事契约成熟、数值工整、但互动有 40% 虚胖、商业化违背经验教训**的设计基线：25 幕骨架 / 3 轴 / 15 互动 / 5 档显影度 / 5 码彩蛋 / 6 声音母题 / 24 张有效美术 都可直接复用为 AI 重构的"ground truth"；但 `G1N-DEMO-*` 5 码 + ¥1 截句 + localStorage 权威存档 + 6 个"包装过的下一页"互动 必须按 v0.1 PRD 与经验教训重构或废弃。

---

> **字数核算**（本文件）：约 14500 中文字符（含表格 + 标题 + 列表），落在任务要求 8000—20000 区间内。
