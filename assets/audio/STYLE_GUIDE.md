# 革命街 AI 原生重构 · 声音风格指南

> 本文档是 W5-B 声音补全产物的统一风格规范。
> 适用范围：`assets/audio/ambient/`（章节环境声）、`assets/audio/motifs/`（声音母题）、`assets/audio/music/`（章节音乐）、`client/src/audio/AudioEngine.ts`（运行时引擎）。
> 引擎基准：v6 canonical（`_legacy_v6/app/audio-engine.ts`）+ 现有 `client/src/audio/AudioEngine.ts` 的程序化合成核心。
> 美术基准：`assets/images/STYLE_GUIDE.md`（同色调、同暗调、同电影感）。

---

## 0. TL;DR（一句话锚点）

> **声音承担场景切换和情绪留白，不持续抢台词。**
> 不要做：温馨 / 明亮 / 卡通 / 完整歌词演唱 / 大动态主旋律 / 商业电影预告片式预告。

| 维度 | 规范 |
|---|---|
| 整体调性 | 电影感（cinematic）、克制、留白、暗调 |
| 动态范围 | 母题峰值 ≤ 0.35、章节音乐 mix ≤ 0.30、章节环境声 mix ≤ 0.55 |
| 母题 | 短促（1-5 秒）、单次、不重叠 |
| 环境声 | 30 秒可无缝循环、全程背景音量 |
| 章节音乐 | 60-90 秒、主旋律仅在情绪高潮段出现 8-15 秒 |
| 默认状态 | 静音（`audioEnabled = false`） |
| 启动方式 | 用户手势（click / keydown / pointerdown）后 `audioEngine.start()` |
| 章节切换 | 1.5 秒 cross-fade（gain ramp linear） |

---

## 1. 声音哲学

### 1.1 核心原则

> **声音是叙事的留白，不是叙事的复述。**

W5-A 美术定调为「电影感、暗调、暖黄高光、克制现实主义」。声音沿用同一套美学，但**声音的特殊性是它会持续抢台词**——一旦音乐起来，对白 / 旁白就听不清；一旦动态太猛，情绪就被声音推动而非玩家自己抵达。所以本项目的核心声音哲学是：

- **声音承担场景切换和情绪留白**（决策 5 配套）
- **不持续抢台词**（背景音 90% 时间 ≤ mix 0.30，主旋律仅在情绪高潮出现）
- **不重复文字**（不出现叙事已经在说的内容，例如不要在 farewell_2011 音乐里出现"离别"二字或人声朗读诗句）
- **不替代玩家注意力**（玩家眼睛在看画面、脑子在想选择——声音是这一切的"底色"）

### 1.2 与 v6 procedural 引擎的关系

v6 `audio-engine.ts` 的核心是**程序化合成**（Web Audio API 实时生成 brown noise + Persian dastgah scale + tombak drum）。这套架构在 v6 时代处理"低带宽 / 0 资产"是合理的，但有两个局限：

1. **没有"真实环境"**——brown noise + lowpass filter 不是"2008 地下室"，是"听起来昏暗的噪音"
2. **没有"真实质感"**——母题是用 sine/triangle 振荡器画的"模拟纸声"，不是纸

W5-B 的策略是**扩展而非替换 v6 架构**：

- **保留** v6 procedural 引擎作为「即时兜底层」——首次启动 / 文件解码失败时仍能出声
- **新增** 真实文件层：3 章节环境声 + 6 声音母题 + 3 章节音乐
- **双层并行**（procedural 立即 + asset 加载完成后 cross-fade 接入）

这是为什么 AudioEngine 的 class 内部同时存在 `startProceduralAmbience` 和 `crossfadeAmbient`：它们不是 if/else 替换关系，是"先 procedural 在场，等 asset 到位后无缝替换"。

### 1.3 与 W5-A 美术的关系

| 维度 | W5-A 美术 | W5-B 声音 |
|---|---|---|
| 基底 | 炭灰 + 烟褐 | 棕色噪音 + lowpass |
| 高光 | 烟熏琥珀 | 暖光高混响（2008 灯泡、2011 航班牌、2024 油灯） |
| 冷光 | 暗蓝灰 | 冷空（2011 机场 H1 顶灯、2024 雨窗） |
| 颗粒 | 35mm film grain | tape hiss / 模拟介质底噪（不放） |
| 暗角 | 1.05-1.10 | 母题峰值克制、不打亮中频 |
| 比例 | 2.35:1 / 16:9 | N/A（声音无比例） |
| 留暗 | 30% 暗部 | 主旋律 ≤ 30% mix 峰值，剩余时间让位给环境 + 玩家想象 |

---

## 2. 资产清单（W5-B 已交付）

### 2.1 章节环境声（3 个，30 秒可循环）

| 章节 | 文件 | 关键元素 | mix 峰值 |
|---|---|---|---|
| `photo_lab_2008` | `ambient/chapter-2008-basement-ambient.mp3` | 40W 灯泡电流声（带 flicker）+ 16mm 放映机低频马达 + 远处德黑兰城市交通 | 0.55 |
| `farewell_2011` | `ambient/chapter-2011-airport-ambient.mp3` | 模糊广播 PA + 行李轮过石面 + 远处飞机引擎 + 暖通低频 | 0.55 |
| `reunion_2024` | `ambient/chapter-2024-istanbul-cafe-ambient.mp3` | 雨打落地窗 + 加拉塔桥船笛 + 远处宣礼塔（弱）+ 咖啡机蒸汽 | 0.55 |

> 三个环境声都设计为 30 秒可无缝循环——首尾帧无 click/pop；使用 loop 段头尾相位匹配。
> 中文场景（2024 伊斯坦布尔）有"远处宣礼塔"作为**中文 / 亚洲文化圈氛围的弱化锚**——不是要做出礼拜场景，只是让那个空间的"东方感"在场。

### 2.2 声音母题（6 个，1-5 秒）

| ID | 文件 | 触发场景 | 时长 | 峰值 |
|---|---|---|---|---|
| `photo_turn` | `motifs/motif-photo-page-turn.mp3` | 玩家拿出 / 翻看毕业照（2008 / 2024） | 2s | 0.32 |
| `email_delete` | `motifs/motif-email-delete.mp3` | 玩家写下并删除一封未发送的邮件（锚点 4 凌晨） | 1.5s | 0.22 |
| `clock_tick` | `motifs/motif-airport-clock-tick.mp3` | 2011 机场时钟秒针（在 farewell_2011 多次出现） | 4s | 0.28 |
| `rain_drip` | `motifs/motif-rain-drip.mp3` | 2024 伊斯坦布尔窗台、咖啡馆门口、路口信号灯 | 2s | 0.26 |
| `poetry_turn` | `motifs/motif-poetry-page-turn.mp3` | 玩家翻动阿拉什的诗集（2008 / 2024） | 3s | 0.24 |
| `ticket_tear` | `motifs/motif-bus-ticket-tear.mp3` | 玩家撕下 304 公交票（锚点 2 burn 路径 / 锚点 4 诗集末页） | 1s | 0.35 |

> 母题是**单次、瞬时、不可重复触发**的——同一种母题在 3 秒内不应连续播放两次（避免出现"电子门铃"感）。
> 峰值已在 AudioEngine 中按 `ASSET_MOTIF_VOLUME` 预置，UI 层不应再覆盖。

### 2.3 章节音乐（3 段，60-90 秒）

| 章节 | 文件 | 乐器 | 风格描述 | mix 峰值 |
|---|---|---|---|---|
| `photo_lab_2008` | `music/chapter-2008-music.mp3` | 波斯风格低频弦乐（tanbur 暗示）+ 软大提琴底 | 1970s 伊朗艺术电影配乐感，节制不抢 | 0.28 |
| `farewell_2011` | `music/chapter-2011-music.mp3` | 单簧管主旋律 + 远景机场环境 | 送别、克制、冷 | 0.28 |
| `reunion_2024` | `music/chapter-2024-music.mp3` | 钢琴 + 大提琴二重奏 | 留白多、长音之间沉默 | 0.28 |

> 三段音乐都遵循「主旋律峰值仅在情绪高潮段出现 8-15 秒，剩余时间让位给环境 + 玩家」的原则。
> 音乐风格描述中**没有使用"严格传统波斯音乐还原"**——这是 W5-B 红线之一（未经文化复核的措辞）。我们用"波斯风格低频弦乐"而非"伊朗传统六弦琴"，避免把"灵感"误称成"还原"。

### 2.4 母题/章节 ID 与场景对齐

```ts
// AudioEngine.ts
type ChapterId =
  | "prologue"
  | "photo_lab_2008"
  | "farewell_2011"
  | "reunion_2024"
  | "ending"
  | string;

type AssetMotif =
  | "photo_turn"
  | "email_delete"
  | "clock_tick"
  | "rain_drip"
  | "poetry_turn"
  | "ticket_tear";
```

| 场景 YAML | ChapterId | 触发的 AssetMotif |
|---|---|---|
| `photo_lab_2008.yaml` | `photo_lab_2008` | `photo_turn`、`poetry_turn`、`ticket_tear`（按 burn 路径） |
| `farewell_2011.yaml` | `farewell_2011` | `clock_tick`、`ticket_tear`、`photo_turn`（按 escape 路径） |
| `reunion_2024.yaml` | `reunion_2024` | `poetry_turn`、`photo_turn`、`rain_drip`、`email_delete`（按 well 路径回忆） |

UI 层在场景切换 / 物件交互时调用 `audioEngine.motif("photo_turn")` 等即可。

---

## 3. 混音规范

### 3.1 Master / Mix 比例

| 轨道 | mix 默认 | 含义 |
|---|---:|---|
| Master gain | 0.62 | v6 沿用；用户音量 × 0.62 = 实际输出 |
| Ambient mix | 0.55 | 章节环境声（真实文件）+ procedural 棕色噪音 |
| Music mix | 0.28 | 章节音乐（真实文件）+ procedural 波斯主题 |
| Motif peak | 0.22-0.35 | 文件式母题（每次触发瞬时） |
| Cue peak | 0.024 | procedural 短提示音（choice / save / ending） |
| Texture peak | 0.003-0.008 | procedural 短质感（projector / rain 等） |

> **背景音 90% / 主旋律 10%** 是设计原则：90% 的时间音乐 mix ≤ 0.30，让玩家"几乎听不到但能感觉到"；10% 的情绪高潮时间（仅在玩家做出关键选择后 5-10 秒内）才让 mix 短暂升到 0.5。
> **本章没有实现"情绪高潮"自动 mix 调节**——这是 W6 之后的可选项；当前 W5-B 只交付基础 mix。

### 3.2 Cross-fade 规范

- **章节切换**：1.5 秒（`CROSSFADE_SECONDS = 1.5`）
- **类型**：`linearRampToValueAtTime`（不是 exponential，因为音乐是声音文件，不是包络）
- **方向**：旧 source 渐出到 0 + 新 source 渐入到目标 mix
- **fallback**：若新 buffer 还在加载，旧 source 保持不变；新 buffer 到位后下一段 cross-fade 接入

```ts
// 伪代码
newGain.gain.setValueAtTime(0, t0);
newGain.gain.linearRampToValueAtTime(this.musicMix, t0 + 1.5);
oldGain.gain.linearRampToValueAtTime(0, t0 + 1.5);
oldSource.stop(t0 + 1.5 + 0.05);
```

### 3.3 母题节流

- 同一 AssetMotif 3 秒内不重复触发（防止"门铃效应"）
- 不同母题之间可以紧挨（< 100ms）但需用户显式触发
- W5-B 没实现节流——这是 W6 的可选项（UI 层应负责去重）

---

## 4. 降噪规范（与决策 5 配套）

### 4.1 降级链

决策 5 要求"4 级降级链"。音频层面对应：

| 决策 5 级别 | 音频行为 |
|---|---|
| L1（NPC 反应超时） | 母题不触发；保持当前 ambient + music |
| L2（Director 超时） | 同 L1；主调用降级但音频不影响 |
| L3（Resolver 之前失败） | 音频完全暂停（`audioEngine.setMuted(true)`） |
| L4（Resolver 写库失败） | 同 L3；不播放任何 cue / motif |

L3 / L4 时静音是**为玩家注意力**——他们正在看错误提示，不要让音乐继续营造"游戏还在"的错觉。

### 4.2 降级检测

```ts
// 在 store 中订阅 degradationLevel
useStore.subscribe(
  (s) => s.degradationLevel,
  (level) => {
    if (level === "L3" || level === "L4") {
      audioEngine.setMuted(true);
    }
    // 注意：恢复由用户手势重新触发
  },
);
```

> L3 / L4 之后**不自动恢复音频**——必须等用户主动操作（点击"重试"按钮等）后重新 `audioEngine.start()`，避免 autoplay 政策冲突。

---

## 5. 与决策的对应

| 决策 | 音频层执行 |
|---|---|
| 决策 1：行为可玩性门槛 | 母题触发与玩家行为绑定（不是被动播放）——只有 `motif()` 被显式调用才出声 |
| 决策 2：默认旁观者 | POV 切换不改变音频；音频是"空间感"不是"内心独白" |
| 决策 3：mandatory echo | 母题在 mandatory echo 触发时复用——同一 photo_turn 在 2008 / 2024 都可触发，是"远期回响"的声音锚 |
| 决策 4：付费点 | 收藏版的"原声"是 W7 之后的可选项——本章不实现；W5-B 音频免费可用 |
| 决策 5：成本红线 | 音频不消耗 LLM token；不影响 4 级降级链 |
| 决策 6：自检工具 | 工具不检查音频（音频是体验层，不是内容层） |

---

## 6. 红线（生成 / 编辑时必查）

- ❌ 任何**完整歌词演唱**（即使是小语种）——声音是氛围，不是歌曲
- ❌ 任何**京东 / 合作方 logo 提示音**（品牌音效）
- ❌ 任何**真实艺人演唱**（AI 合成可以，但禁止"还原某歌手音色"）
- ❌ 任何**温馨 / 明亮 / 卡通 / 赛博朋克**风格声音
- ❌ 任何**中文场景只放抽象环境**（必须含 1-2 个中文/亚洲文化圈的具体元素：2011 机场的中文广播模糊、2024 宣礼塔等）
- ❌ 任何**音乐持续抢台词**（mix > 0.50 持续超过 10 秒）
- ❌ 任何**"严格传统波斯音乐还原"措辞**（未经文化复核）
- ❌ 任何**5 章节（ending）突然变成温馨钢琴**（与整体暗调冲突）
- ❌ 任何**母题峰值超过 0.40**（会盖过 narrator 文字）
- ❌ 任何**章节音乐主旋律超过 90 秒一直持续**（必须留白）

---

## 7. 与 v6 canonical 的关系

| 资产 | 关系 | 使用建议 |
|---|---|---|
| v6 `audio-engine.ts` procedural 核心 | 不可修改，本项目起点 | AudioEngine 已嵌入为 fallback |
| v6 theme presets（prologue / chapter1-5 / ending） | 全部保留 | procedural 兜底在用 |
| v6 cue / texture / motif（oscillator-based） | 保留 | procedural 母题仍可调用（向后兼容） |
| W5-B ambient 3 个 | 新增 | 主入口；procedural brown noise 仍并行 |
| W5-B motifs 6 个 | 新增 | 取代 v6 的"模拟母题"——UI 层应优先用 asset 版 |
| W5-B music 3 段 | 新增 | 取代 v6 procedural Persian 主题的真实感不足——procedural 仍并行 |
| W7+ 原声收藏 | 推迟 | 收藏版的"原声" = W5-B 这 12 个文件 + 后续扩展 |

---

## 8. 验收 checklist

每条音频资产交付前必须通过：

### 8.1 文件层

- [ ] 文件命名 `chapter-{year}-{place}-{type}.mp3` 或 `motif-{event}.mp3`，全小写 + 短横线
- [ ] 时长符合规范（ambient 20-35s / music 60-90s / motif 1-5s）
- [ ] MP3 128kbps+ 即可（不需无损——决策 5 成本红线）
- [ ] 循环段首尾无 click / pop（ambient 必须 30 秒自循环）

### 8.2 风格层

- [ ] 整体暗调、无高频尖刺（≤ 12kHz 有 -12dB 衰减）
- [ ] 母题峰值 ≤ 0.35（4-6 dB 留余量给 narrator 文字）
- [ ] 章节音乐主旋律 ≤ 30% 时间
- [ ] 中文场景有中文 / 亚洲文化圈的具体元素
- [ ] 没有歌词、没有京东 / 合作方 logo
- [ ] 没有温馨 / 明亮 / 卡通 / 赛博朋克调性

### 8.3 集成层

- [ ] 路径对齐 `assets/audio/{ambient,motifs,music}/`
- [ ] AudioEngine 启动后能 `motif("photo_turn")` 触发文件式母题
- [ ] 章节切换时 ambient + music 都 1.5 秒 cross-fade
- [ ] zustand store 的 `audioEnabled` 切换 = 引擎静音 / 解静音
- [ ] zustand store 的 `audioVolume` 变化 = 引擎 master 增益变化
- [ ] 默认 `audioEnabled = false`（用户手势前不出声）

### 8.4 红线层

- [ ] 没有触犯 §6 的任何红线
- [ ] 没有"严格传统波斯音乐还原"等未经文化复核的措辞
- [ ] 没有连续 10 秒以上 mix > 0.50 的音乐

---

## 9. 风格速记卡（给后续 AI 声音 agent 用）

```
cinematic, dark, restrained, melancholic, bittersweet,
no lyrics, no singing, no bright, no cute, no cartoon, no cyberpunk,
ambient 30s seamless loop, music 60-90s, motif 1-5s single-shot,
mix ambient ≤ 0.55, music ≤ 0.30, motif peak ≤ 0.35,
master gain 0.62 × user_volume,
default muted, user gesture required to start,
1.5s linear cross-fade on chapter switch,
always preserve v6 procedural as fallback,
subtle Persian / Iranian / Turkish textures (NOT "authentic reproduction"),
per chapter: 2008 basement → 2011 airport → 2024 Istanbul cafe,
always autumn or winter, never summer-bright,
leave silence between phrases — silence IS the soundtrack.
```

---

*本指南由 W5-B 声音补全任务编写，作为后续 W6（实时降级链）、W7（收藏版原声）、跨案复用（第二案、第三案）声音的基线。*
*若 v6 canonical 后续更新（v6.1+），本指南以 W5-B 12 个文件为基线，procedural 兜底层不破坏。*
