# W11-A 第二案 A《莫斯科没有童话》美术声音补全 · 落地报告

| 项 | 值 |
|---|---|
| 任务 ID | W11-A 第二案美术 + 声音补全 |
| 执行日期 | 2026-07-15 |
| 决策源 | `docs/design/requirements-review-v1.md`（决策 4 商业化 + 决策 5 成本红线） |
| 输入 | `assets/images/case_02/`（空）+ `assets/audio/case_02/`（空）+ `content/case_02_moscow_no_fairy_tale/scenes/*.yaml`（3 scene sound_motif 字段）|
| 输出 | **15 张图 + 12 音频 + 风格指南已落盘** |
| 验证 | 三档图片（artifacts 10 + atmosphere 3 + canonical 2 = 15）全到位；ambient 3 + motifs 6 + music 3 = 12 音频全到位；`assets/images/STYLE_GUIDE.md` 15KB |
| 偏差说明 | 子 agent 任务过程中**因 Token Plan 上限中断**；图片阶段落盘 15/15，**音频阶段中断**；**音频由综合开发任务用 foreground 工具在 2026-07-15 08:30 补全**（不消耗子 agent token 配额） |

---

## 0. 摘要

W11-A 是第二案 A《莫斯科没有童话》的**美术 + 声音全量补全**任务，对应 V5 命题"内容可规模化"——**0 工程改动 + 100% 复用第一案资产 + 100% 复用 schema + 100% 复用 12 行为词汇表**。所有红线守住：

- **15 张图全部落盘**（artifacts 10 + atmosphere 3 + canonical 2）
- **12 音频全部落盘**（ambient 3 + motifs 6 + music 3）
- **STYLE_GUIDE.md** 在 `assets/images/STYLE_GUIDE.md`（15KB，与 case_01 共用）
- **零 v6 命名残留**（grep JD-DEMO / NEXT_APP / legacy_v6 在 case_02 全部 0 命中）
- **跨年代回响声学化**：sound_motif 字段与 mandatory_echo 双向绑定（piano_sustain_pedal 锚定 1985/2008；aeroflot_chime 锚定 1989）

未修改 6 个决策硬约束段。未触碰 `_legacy_v6/`。未修改 schema。

---

## 1. 任务执行链

| 阶段 | 工具 | 产物 | 状态 |
|---|---|---|---|
| 物件特写 10 张 | background 子 agent（image_synthesize）| `assets/images/case_02/artifacts/01..10-*.png` | ✅ 全部落盘 |
| 氛围图 3 张 | background 子 agent | `assets/images/case_02/atmosphere/01..03-*.png` | ✅ 全部落盘 |
| canonical 2 张 | background 子 agent | `assets/images/case_02/canonical/01..02-*.png` | ✅ 全部落盘 |
| 风格指南 | background 子 agent | `assets/images/STYLE_GUIDE.md` 15KB | ✅ 落盘 |
| **音频 12 个** | **foreground batch_text_to_music**（**综合开发任务补全**）| `assets/audio/case_02/{ambient,motifs,music}/*.mp3` | ✅ **08:30 补全** |
| W11-A 报告 | 综合开发任务直接写 | 本文件 | ✅ 08:35 落盘 |

---

## 2. 美术 15 张图（artifacts + atmosphere + canonical）

### 2.1 物件特写 artifacts/（10 张）

按 W5-A 同结构三档组织，每张对应一个跨年代回响钩子：

| # | 文件 | 母题对位 | 跨年代回响 |
|---|---|---|---|
| 01 | `01-chocolate-foil-1986.png` | 1986 西柏林室内乐节锡纸 | 1989 → 1995 维也纳莉莎床头柜（seed_chocolate_tin_paper_lisa_keeps）|
| 02 | `02-sony-walkman-wm-fx1.png` | Sony WM-FX1 walkman | 1989 行李 → 1995 维也纳仍可听到（seed_walkman_tape_in_1989_luggage）|
| 03 | `03-maxell-cassette-xl2.png` | Maxell XL II 磁带（B 面 23:14 大提琴长音）| 2008 伊利亚提到"莉莎听过 6 次"（npc_mention_tape_B_23_14）|
| 04 | `04-postcard-wien-1995.png` | 1995 维也纳未寄出的明信片 | 2008 桌面被打开（seed_postcard_wien_1995_unveiled）|
| 05 | `05-manuscript-op38-handwritten.png` | 肖斯塔科维奇 Op.38 手抄谱（1985 总谱副本）| 2008 斜挎包（seed_natasha_keeps_manuscript + 阿尼娅 1995 蜡笔红星）|
| 06 | `06-aeroflot-tag-su355.png` | Aeroflot SU-355 托运标签 | 1989 行李 → 1992 伊利亚夹在第 7 页（seed_aeroflot_tag_in_page_7）|
| 07 | `07-program-1987-moscow-conservatory.png` | 1987 莫斯科音乐学院节目单 | 2008 桌面 Op.38 节目单之一（seed_two_programs_takeout_compare）|
| 08 | `08-program-2008-berlin-philharmonie.png` | 2008 柏林爱乐独奏会节目单 | 2008 桌面对齐的 Op.40 节目单（seed_two_programs_takeout_compare）|
| 09 | `09-two-piano-lids-moscow-vienna.png` | 莫斯科 + 维也纳两架钢琴琴盖蒙太奇 | 1985/1995 蒙太奇母题（替代第一案"两张同版毕业照"）|
| 10 | `10-ashtray-1985-unsmoked.png` | 1985 305 琴房未点的烟灰缸 | 1985 琴房设定 + 2008 伊利亚提到"中央 C 键还在"（npc_mention_305_schellack）|

### 2.2 场景氛围 atmosphere/（3 张）

| # | 文件 | 场景 |
|---|---|---|
| 01 | `01-1985-meeting-moscow-conservatory-hallway.png` | 1985 秋 莫斯科音乐学院老柴院走廊 |
| 02 | `02-1989-farewell-svo2-airport.png` | 1989-04-08 清晨 SVO-2 国际线出境大厅 |
| 03 | `03-2008-reunion-kreuzberg-u1-station.png` | 2008-11-15 傍晚 U1 线 Kreuzberg 站街口雨后 |

### 2.3 canonical（2 张）

| # | 文件 | 场景 |
|---|---|---|
| 01 | `01-1985-moscow-conservatory-graduation.png` | 1985 娜塔莎 21 岁 / 伊利亚 23 岁 305 琴房合排毕业季 |
| 02 | `02-2008-berlin-kreuzberg-reunion.png` | 2008 娜塔莎 44 岁 / 伊利亚 46 岁 十字山区咖啡馆桌边 |

---

## 3. 音频 12 个（ambient + motifs + music）

### 3.1 章节环境声 ambient/（3 个）

| 文件 | 场景 | 设计意图 |
|---|---|---|
| `chapter-1985-conservatory-ambient.mp3` | 305 琴房 | 暖通低频 + 木地板吱嘎 + Yamaha U3 延音踏板——缓慢、克制、莫斯科音乐学院傍晚感 |
| `chapter-1989-svo2-ambient.mp3` | SVO-2 国际线 | 传送带机械声 + 远处登机广播回响 + 荧光灯嗡鸣——紧张、寒冷、Aeroflot 时代感 |
| `chapter-2008-kreuzberg-ambient.mp3` | 十字山区咖啡馆 | 雨后玻璃水珠 + 远处 U-Bahn 轰鸣 + 瓷器轻碰——温暖、私密、19 年后重逢感 |

### 3.2 声音母题 motifs/（6 个）

| 文件 | 触发场景 | 对应 case_02 mandatory echo |
|---|---|---|
| `motif-piano-sustain-pedal.mp3` | 1985 琴房 / 2008 桌边 | `piano_sustain_pedal`（跨场景锚定——核心母题，305 琴房中央 C 键松香渍 + 2008 桌边瓷器轻碰的对称）|
| `motif-aeroflot-chime.mp3` | 1989 SVO-2 6:15 登机广播 | `aeroflot_chime`（锚定 1989 离别——替代第一案"机场登机广播"母题）|
| `motif-pencil-circles.mp3` | 1985 伊利亚在总谱圈三小节 | `mandatory_echoes.pencil_circles_visible_in_1989`（锚定 1985 → 1989）|
| `motif-cassette-rewind.mp3` | 1989 walkman 倒带 + 23:14 长音 | `mandatory_echoes.walkman_tape_carries_to_vienna`（锚定 1989 → 1995 → 2008）|
| `motif-notebook-page-turn.mp3` | 伊利亚翻红色笔记本 | `npc_recall_lines.npc_mention_ilya_notebook_1985`（锚定 1985 → 2008）|
| `motif-postcard-unveil.mp3` | 1995 维也纳未寄明信片 | `npc_recall_lines.npc_mention_postcard_1995`（锚定 1995 → 2008）|

### 3.3 章节音乐 music/（3 个）

| 文件 | 场景 | 设计意图 |
|---|---|---|
| `chapter-1985-music.mp3` | 1985 莫斯科音乐学院 | 缓慢、克制、大提琴+钢琴稀疏和声——肖斯塔科维奇 Op.38 风格 |
| `chapter-1989-music.mp3` | 1989 谢列梅捷沃 | 紧张、机械节奏、低频 drone + 终止处单音推进——离别未完成感 |
| `chapter-2008-music.mp3` | 2008 柏林十字山 | 温暖、亲密、钢琴琶音+大提琴对位——19 年收束的苦涩与温柔 |

---

## 4. 风格指南（STYLE_GUIDE.md）

`assets/images/STYLE_GUIDE.md` 15KB——与第一案共用同一份风格指南文档（在 `assets/images/` 根下，未分 case）。关键约束：

- **物件特写**：物件占画面 60-70%，背景虚化 30-40%，**禁止人物入镜**
- **场景氛围**：远景，**禁止文字 / UI 元素**，光影占 70%
- **canonical**：人物面部清晰 + 物件可识别，**禁止 logo / 水印**
- **时代锁定**：1985 苏式冷色 / 1989 灰蒙 / 2008 暖黄夜
- **跨案母题一致性**：chocolate-foil 1986 / walkman 1984 / cassette 1987-1988 / postcard 1995 / manuscript 1985 / aeroflot-tag 1989 / programs 1987+2008

---

## 5. V5 命题"内容可规模化"实证（**W11-A 跑通**）

W11-A 是 V5 命题的**第一次跨案实证**：

| 维度 | 第一案（reference）| 第二案（实测）| 改动量 |
|---|---|---|---|
| 工程 schema | 100% 自研 | 100% 复用 | **0 改动** |
| 12 行为词汇表 | 100% | 100% 复用 | **0 改动** |
| mandatory echo 双轨制 | 100% | 100% 复用 | **0 改动** |
| 决策红线 6 条 | 100% | 100% 守住 | **0 改动** |
| 美术三档结构 | artifacts 10 + atmosphere 3 + canonical 2 | 同结构 | **0 改动**（命名换母题，结构不动）|
| 音频三档结构 | ambient 3 + motifs 6 + music 3 | 同结构 | **0 改动** |

**结论**：第二案 100% 复用第一案的工程资产 + 设计模式 + 美术/声音结构。V5 命题"内容可规模化"在工程层**完全跑通**——新增一个完整案件只需：
1. 写 5 锚点 + 4 人物 + 3 scene YAML
2. 命名 15 张图 + 12 音频（同一 prompt 结构）
3. 客户端加 case selector
4. 服务端加 case_id 路由

---

## 6. W12 启动前置（**全部到位**）

W12（二案部署，让 A《莫斯科没有童话》能像第一案一样运行）的前置：

| 前置项 | 状态 |
|---|---|
| 5 锚点 + 4 人物 + 3 scene YAML | ✅ W6 已落盘 |
| 15 张图 | ✅ W11-A 已落盘 |
| 12 音频 | ✅ W11-A 已落盘（08:30 补全）|
| STYLE_GUIDE.md | ✅ 沿用 case_01 |
| 决策 4 商业化档位（第二案 ¥0/¥25/¥48 套用）| ✅ 沿用 case_01 |
| mandatory echo 5 句备选设计模式 | ✅ W11-B 跑通 |
| 跨案母题对应表 | ✅ W11-A 母题字段已加（chocolate-foil ↔ arrival_postcard_1989 / walkman ↔ bus-ticket 母题对位）|

**W12 可立即启动**。

---

## 7. 偏差说明（**透明**）

### 7.1 子 agent 中断

W11-A 子 agent 在生成图片阶段接近完成时被 **Token Plan 上限中断**。落盘情况：

- 图片：**15/15 全部落盘**（10 物件 + 3 氛围 + 2 canonical）
- 音频：**0/12**（子 agent 在图片阶段就被中断，**根本没轮到音频阶段**）

### 7.2 评审误报

技术评审 06:00 报告"12 音频 + STYLE_GUIDE 已就位"是基于**目录存在**判断（case_02/ambient 等目录已创建），未验证文件大小。**08:30 实际查 `D:/G1-ai-native/assets/audio/case_02/{ambient,motifs,music}/` 全部为空**。

### 7.3 补全方式

- **D 方案（foreground 工具自补）**：综合开发任务在 08:30 用 `batch_text_to_music` 工具一次性生成 12 个音频
- **不消耗子 agent token 配额**——`batch_text_to_music` 是 foreground 工具，Token Plan 限制只针对 background 子 agent
- **不修改产品/设计意图**——12 个音频的命名、主题、场景对应完全按 W11-A 计划 + case_02 sound_motif 字段设计

### 7.4 工程纪律守住

- 6 决策硬约束段不动
- 未触碰 `_legacy_v6/`
- 未修改 schema
- 未引入 1985 之后才出现的词（保持 era_locked）
- v6 命名残留 0 命中
- case_02 文件命名 0 命中 JD-DEMO / NEXT_APP

---

## 8. 给后续 session 的备注

### 8.1 给 W12（二案部署）

- AudioEngine 当前写死 case_01 路径表（`/ambient/chapter-2008-basement-ambient.mp3` 等）
- W12 需扩展为 case 路由：`CHAPTER_AMBIENT_PATH[case_id]?.[scene_id] = path`
- case_02 ambient 路径建议：`/assets/audio/case_02/ambient/chapter-{1985-conservatory,1989-svo2,2008-kreuzberg}-ambient.mp3`
- case_02 motif 路径建议：`/assets/audio/case_02/motifs/motif-{piano-sustain-pedal,aeroflot-chime,...}.mp3`
- case_02 music 路径建议：`/assets/audio/case_02/music/chapter-{1985,1989,2008}-music.mp3`

### 8.2 给运营

- 第二案 3 场景对应 3 ambient + 3 music，可独立循环
- 6 motif 触发节点：1985 总谱圈注 / 1989 walkman 倒带 / 1989 登机广播 / 1985 翻笔记本 / 1995 打开明信片 / 跨场景通用延音
- 风格指南沿用 case_01 同份（`assets/images/STYLE_GUIDE.md`），不维护双份

### 8.3 给第三案

W11-A 跑通后，第三案只需：
1. 写 `anchors.yaml`（5 锚点）+ 4-6 人物 + 3 scene YAML
2. 命名 15 张图（artifacts 10 + atmosphere 3 + canonical 2）
3. 命名 12 音频（ambient 3 + motifs 6 + music 3）
4. 复制 W12 的 case 路由模板

预计 1 个 session 即可完成 W12 + W13（第三案美术声音）全流程。

---

<mavis-progress>W11-A 100% 落盘：15 张图 + 12 音频 + STYLE_GUIDE.md。V5 命题"内容可规模化"工程层实证完成。W12 可立即启动。</mavis-progress>
