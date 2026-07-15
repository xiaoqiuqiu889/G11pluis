// =============================================================================
// 革命街 AI 原生 · 场景 Mock 数据（mock 模式用）
// -----------------------------------------------------------------------------
// W12: 6 个场景（3 case_01 + 3 case_02）— V5 命题"内容可规模化"实证
// 字段对齐 SceneMeta 类型；服务端运行时优先用 server loader 返回的数据
// ============================================================================

import type { SceneMeta } from "@/types/schemas";

// -----------------------------------------------------------------------------
// case_01 — 《革命街没有尽头》· 3 场景
// -----------------------------------------------------------------------------

const photoLab2008: SceneMeta = {
  sceneId: "photo_lab_2008",
  caseSlug: "case_01_revolution_street",
  title: "革命街地下放映室与两张同版毕业照",
  era: "2000_2012_globalization",
  location: "德黑兰大学·革命街旧书店地下室·地下放映室",
  atmosphere: ["闷热", "旧灯泡", "机油", "毕业季", "胶片气味", "黄昏透进窄窗"],
  contract: {
    sceneId: "photo_lab_2008",
    title: "革命街地下放映室与两张同版毕业照",
    era: "2000_2012_globalization",
    location: "德黑兰大学·革命街旧书店地下室·地下放映室",
    timeOfDay: "evening",
    weather: "clear",
    cast: [
      { characterId: "leila", role: "protagonist" },
      { characterId: "arash", role: "ally", initialDisposition: 0.6 },
      { characterId: "dagang", role: "witness", initialDisposition: 0 },
    ],
    required_anchors: [
      { anchorId: "photo_canonical", description: "两张同版毕业照", mandatory: true },
      { anchorId: "two_photos_question", description: "摄影师大刚问过「照片要冲两张吗？」", mandatory: true },
      { anchorId: "leila_age", description: "莱拉 21—22 岁", mandatory: true },
      { anchorId: "arash_age", description: "阿拉什 22—23 岁", mandatory: true },
      { anchorId: "projector_present", description: "16mm 放映机、灯泡点亮", mandatory: true },
      { anchorId: "toolbox_present", description: "阿拉什工具盒", mandatory: true },
      { anchorId: "carry_to_2011", description: "为 2011 机场准备携带物", mandatory: true },
      { anchorId: "open_to_2024", description: "为 2024 重逢准备共同证据", mandatory: true },
    ],
    core_conflict: "是否把两张同版毕业照分别交给两人",
    allowed_beats: [
      { beatId: "probe", label: "试探", tier: "setup" },
      { beatId: "joke", label: "玩笑", tier: "setup" },
      { beatId: "avoid", label: "回避", tier: "rising" },
      { beatId: "confession_unfinished", label: "表白未遂", tier: "climax" },
      { beatId: "shared_secret", label: "共同秘密形成", tier: "climax" },
      { beatId: "decide_for_other", label: "替对方做决定", tier: "falling" },
      { beatId: "keep_way_out", label: "替自己保留退路", tier: "falling" },
      { beatId: "leave_a_word", label: "留下一个不属于当下的字", tier: "resolution" },
      { beatId: "care_about_being_cared", label: "在意对方是否在意", tier: "resolution" },
    ],
    forbidden_reveals: [
      { revealKey: "leila_marriage_kamran", reason: "2011 之后" },
      { revealKey: "thirteen_years_later", reason: "2024 才揭示" },
      { revealKey: "maziya_release_2009", reason: "未发生于本场" },
      { revealKey: "arash_father_rehab", reason: "私人细节" },
    ],
    max_turns: 8,
    total_action_budget: 16,
    legal_endings: [
      { endingId: "shared_secret", label: "共同秘密", conditions: ["photo_in_pocket", "photo_in_book"], tone: "bittersweet" },
      { endingId: "one_sided_memory", label: "单方面记忆", conditions: ["both_photos_with_one"], tone: "sober" },
      { endingId: "misunderstood_gesture", label: "动作被误解", conditions: ["grip_then_release", "no_photo_handed"], tone: "ambiguous" },
      { endingId: "emotional_retreat", label: "情绪性退缩", conditions: ["leave"], tone: "ambiguous" },
      { endingId: "promise_formed", label: "约定成形", conditions: ["date_written_on_back"], tone: "open" },
    ],
    causal_seeds: ["photo_in_pocket", "photo_in_book", "date_written_on_back", "grip_then_release"],
    narratorVoice: "第三人称旁观者；用「你看到了 X」保持距离感；不显示精确数值。",
    schemaVersion: "1.0.0",
  },
  investigatableObjects: [
    { id: "photo_pair", name: "两张同版照片", description: "同一底片、同一裁切的两张冲印件", initialLocation: "牛皮纸袋", keywords: ["照片", "两张", "同版"], requires: [], leadsTo: ["photo_in_pocket", "photo_in_book"], iconKey: "photo" },
    { id: "envelope", name: "牛皮纸袋", description: "装着两张冲印件", initialLocation: "桌面", keywords: ["纸袋", "冲印"], requires: [], leadsTo: ["photo_pair"], iconKey: "paper" },
    { id: "projector", name: "16mm 放映机", description: "阿拉什白天修的放映机，灯泡刚点亮", initialLocation: "放映室中央木桌", keywords: ["放映机", "灯泡", "胶片"], requires: [], leadsTo: ["toolbox"], iconKey: "projector" },
    { id: "toolbox", name: "阿拉什的工具盒", description: "装着螺丝刀、备用灯泡、胶带", initialLocation: "放映机下", keywords: ["工具盒", "螺丝刀"], requires: ["projector"], leadsTo: ["poem_in_toolbox"], iconKey: "toolbox" },
    { id: "book_jalal", name: "旧版鲁米诗集", description: "阿拉什的诗集，书脊开裂", initialLocation: "阿拉什夹克内", keywords: ["诗集", "鲁米"], requires: [], leadsTo: ["photo_in_book"], iconKey: "book" },
    { id: "bus_ticket_pair", name: "旧公交票（两张）", description: "阿拉什多撕的一张 304 路票", initialLocation: "工具盒盖内", keywords: ["公交票", "304"], requires: ["toolbox"], leadsTo: ["bus_ticket_in_book"], iconKey: "ticket" },
  ],
  charactersPresent: [
    { id: "leila", name: "莱拉", initialState: "试探", visibility: "主角视角可见", stateNotes: ["文学系三年级", "头巾边缘露卷黑发", "牛皮纸袋"] },
    { id: "arash", name: "阿拉什", initialState: "紧张", visibility: "主角视角可见", stateNotes: ["物理系毕业", "下午修放映机", "工具盒"] },
    { id: "dagang", name: "大刚（摄影师）", initialState: "中立", visibility: "主角视角可见", stateNotes: ["毕业季摄影师", "问过冲两张吗"] },
  ],
  turnBudget: { investigate: 3, reveal: 2, conceal: 1, question: 2, confront: 2, comfort: 1, give: 3, destroy: 1, promise: 2, wait: 2, leave: 1, silence: 2 },
  causalSeeds: [
    { id: "photo_in_pocket", description: "莱拉把照片放进斜挎包内袋", trigger: "give_to_self or conceal on photo_pair", effects: ["2011 机场摸到照片", "2024 取出与诗集配对"] },
    { id: "photo_in_book", description: "阿拉什把照片夹进诗集", trigger: "give on book_jalal or photo_pair", effects: ["2011 机场诗集滑落", "2024 抱在臂弯里"] },
    { id: "grip_then_release", description: "分照片时握一下手又松开", trigger: "comfort + give + silence on arash", effects: ["2011 安检前重复", "2024 端茶时拇指摩挲"] },
  ],
  legalEndings: [
    { id: "shared_secret", label: "共同秘密", description: "两人各拿一张照片", causalSeedRequired: ["photo_in_pocket", "photo_in_book"] },
    { id: "one_sided_memory", label: "单方面记忆", description: "莱拉留下两张", causalSeedRequired: ["both_photos_with_one"] },
    { id: "misunderstood_gesture", label: "动作被误解", description: "握—松未交付", causalSeedRequired: ["grip_then_release", "no_photo_handed"] },
    { id: "promise_formed", label: "约定成形", description: "背面写下一行字", causalSeedRequired: ["date_written_on_back", "photo_in_pocket"] },
  ],
  audioChapter: "photo_lab_2008",
};

const farewell2011: SceneMeta = {
  sceneId: "farewell_2011",
  caseSlug: "case_01_revolution_street",
  title: "德黑兰国际机场·出发大厅",
  era: "2000_2012_globalization",
  location: "德黑兰伊玛目霍梅尼国际机场·国际出发大厅",
  atmosphere: ["玻璃与不锈钢", "时钟秒针", "模糊广播", "行李箱滚轮"],
  contract: {
    sceneId: "farewell_2011",
    title: "德黑兰国际机场·出发大厅",
    era: "2000_2012_globalization",
    location: "德黑兰伊玛目霍梅尼国际机场·国际出发大厅",
    timeOfDay: "morning",
    weather: "clear",
    cast: [
      { characterId: "leila", role: "protagonist" },
      { characterId: "arash", role: "ally", initialDisposition: 0.4 },
    ],
    required_anchors: [
      { anchorId: "terminal", description: "国际出发大厅", mandatory: true },
      { anchorId: "lab_card", description: "阿拉什胸前仍挂门卡", mandatory: true },
      { anchorId: "leila_luggage", description: "深色行李箱 + 登机牌", mandatory: true },
      { anchorId: "luggage_tag_back", description: "行李牌背面有字符", mandatory: true },
      { anchorId: "reference_2008", description: "引用 photo_lab_2008", mandatory: true },
      { anchorId: "announcement", description: "登机广播在场景结束前响起", mandatory: true },
      { anchorId: "separation", description: "场景结束于分开", mandatory: true },
    ],
    core_conflict: "是否在最后几分钟把三件事一起说完",
    allowed_beats: [
      { beatId: "probe", label: "试探", tier: "setup" },
      { beatId: "joke_bitter", label: "玩笑（带苦味）", tier: "rising" },
      { beatId: "avoid", label: "回避", tier: "rising" },
      { beatId: "confession_unfinished", label: "表白未遂", tier: "climax" },
      { beatId: "shared_secret", label: "共同秘密形成", tier: "climax" },
      { beatId: "decide_for_other", label: "替对方做决定", tier: "falling" },
      { beatId: "keep_way_out", label: "替自己保留退路", tier: "falling" },
      { beatId: "word_in_tag", label: "把动作藏进行李牌", tier: "resolution" },
    ],
    forbidden_reveals: [
      { revealKey: "thirteen_years_later", reason: "2024 才揭示" },
      { revealKey: "leila_san_jose_work", reason: "2011 之后" },
      { revealKey: "maryam_meteor", reason: "其他场景" },
    ],
    max_turns: 8,
    total_action_budget: 16,
    legal_endings: [
      { endingId: "all_said", label: "说完三件事", conditions: ["say_kamran", "say_marriage", "say_ticket"], tone: "bittersweet" },
      { endingId: "kept_back", label: "咽回去", conditions: ["silence_on_2008"], tone: "ambiguous" },
      { endingId: "tag_with_word", label: "行李牌背面写字", conditions: ["word_in_tag"], tone: "open" },
    ],
    causal_seeds: ["luggage_tag_word", "leila_kept_photo", "arash_poem_kept"],
    narratorVoice: "第三人称旁观者；玻璃与广播的混响。",
    schemaVersion: "1.0.0",
  },
  investigatableObjects: [
    { id: "leila_luggage", name: "莱拉的行李箱", description: "登机牌攥在右手；行李牌背面有字符", initialLocation: "莱拉手边", keywords: ["行李箱", "登机牌"], requires: [], leadsTo: ["luggage_tag_word"], iconKey: "luggage" },
    { id: "arash_lab_card", name: "阿拉什实验门卡", description: "物理实验室门卡", initialLocation: "阿拉什胸前", keywords: ["门卡", "物理"], requires: [], leadsTo: ["lab_card_touch"], iconKey: "card" },
    { id: "departure_board", name: "航班板", description: "值机柜台上方", initialLocation: "值机柜台上方", keywords: ["航班板"], requires: [], leadsTo: ["flight_countdown"], iconKey: "board" },
    { id: "leila_bag", name: "莱拉斜挎包", description: "内袋有 2008 照片", initialLocation: "莱拉肩头", keywords: ["斜挎包", "照片"], requires: [], leadsTo: ["leila_kept_photo"], iconKey: "bag" },
    { id: "arash_pocket", name: "阿拉什夹克口袋", description: "口袋有折诗", initialLocation: "阿拉什外套", keywords: ["口袋", "折诗"], requires: [], leadsTo: ["arash_poem_kept"], iconKey: "pocket" },
  ],
  charactersPresent: [
    { id: "leila", name: "莱拉", initialState: "撑", visibility: "主角视角可见", stateNotes: ["登机牌攥在右手", "斜挎包有 2008 照片"] },
    { id: "arash", name: "阿拉什", initialState: "克制", visibility: "主角视角可见", stateNotes: ["胸前门卡", "口袋有折诗"] },
  ],
  turnBudget: { investigate: 2, reveal: 1, conceal: 1, question: 2, confront: 2, comfort: 1, give: 2, destroy: 1, promise: 1, wait: 2, leave: 1, silence: 2 },
  causalSeeds: [
    { id: "luggage_tag_word", description: "莱拉在行李牌背面写字", trigger: "give on leila_luggage", effects: ["2024 街口的人念出"] },
    { id: "leila_kept_photo", description: "斜挎包里的 2008 照片", trigger: "reveal on leila_bag", effects: ["2024 取出与诗集配对"] },
    { id: "arash_poem_kept", description: "口袋里的折诗", trigger: "reveal on arash_pocket", effects: ["2024 提到工具盒诗的方向"] },
  ],
  legalEndings: [
    { id: "all_said", label: "说完三件事", description: "三件事全说", causalSeedRequired: ["say_kamran", "say_marriage", "say_ticket"] },
    { id: "kept_back", label: "咽回去", description: "安静分开", causalSeedRequired: ["silence_on_2008"] },
    { id: "tag_with_word", label: "行李牌写字", description: "行李牌背面写一行字", causalSeedRequired: ["luggage_tag_word"] },
  ],
  audioChapter: "farewell_2011",
};

const reunion2024: SceneMeta = {
  sceneId: "reunion_2024",
  caseSlug: "case_01_revolution_street",
  title: "伊斯坦布尔·卡拉柯伊老咖啡馆与路口",
  era: "2012_present_ai_age",
  location: "土耳其·伊斯坦布尔·卡拉柯伊·老咖啡馆 + 街口",
  atmosphere: ["雨后", "木门推开声", "老铜勺碰糖罐", "银发与手背细纹"],
  contract: {
    sceneId: "reunion_2024",
    title: "伊斯坦布尔·卡拉柯伊老咖啡馆与路口",
    era: "2012_present_ai_age",
    location: "土耳其·伊斯坦布尔·卡拉柯伊·老咖啡馆 + 街口",
    timeOfDay: "afternoon",
    weather: "rain",
    cast: [
      { characterId: "leila", role: "protagonist" },
      { characterId: "arash", role: "ally", initialDisposition: 0.5 },
    ],
    required_anchors: [
      { anchorId: "cafe_after_rain", description: "雨后咖啡馆", mandatory: true },
      { anchorId: "leila_aged", description: "莱拉 34—35 岁", mandatory: true },
      { anchorId: "arash_aged", description: "阿拉什 34—35 岁", mandatory: true },
      { anchorId: "arash_poetry_book", description: "阿拉什推门时手抱诗集", mandatory: true },
      { anchorId: "leila_sms_2011", description: "莱拉手机里 2011 短信", mandatory: true },
      { anchorId: "reference_2008_2011", description: "引用 2008 和 2011", mandatory: true },
      { anchorId: "npc_recall_player_action", description: "NPC 主动提起 2008/2011 行为", mandatory: true },
      { anchorId: "ending_crossroad", description: "场景结束于路口绿灯", mandatory: true },
    ],
    core_conflict: "13 年后第一眼落在何处；是否对齐两张照片；是否把卡姆兰说出口",
    allowed_beats: [
      { beatId: "probe", label: "试探", tier: "setup" },
      { beatId: "joke_bitter_warm", label: "玩笑（带苦也带暖）", tier: "rising" },
      { beatId: "avoid", label: "回避", tier: "rising" },
      { beatId: "confession_unfinished", label: "表白未遂", tier: "climax" },
      { beatId: "shared_secret_acknowledged", label: "共同秘密被承认", tier: "climax" },
      { beatId: "thing_kept_recognized", label: "替对方保存的东西被认出", tier: "falling" },
      { beatId: "way_out_given_up", label: "退路被让出", tier: "falling" },
      { beatId: "re_read_i_arrived", label: "重新念「我到了」", tier: "resolution" },
    ],
    forbidden_reveals: [
      { revealKey: "any_2025", reason: "未到时间" },
      { revealKey: "leila_arash_post_2024_health", reason: "场景限制" },
      { revealKey: "maziya_shiraz_post", reason: "其他场景" },
    ],
    max_turns: 8,
    total_action_budget: 16,
    legal_endings: [
      { endingId: "open_crossroad", label: "路口分开", conditions: ["crossroad_green"], tone: "open" },
      { endingId: "two_photos_aligned", label: "两张照片对齐", conditions: ["photos_on_table"], tone: "bittersweet" },
      { endingId: "kamran_said", label: "说出卡姆兰", conditions: ["say_kamran_waiting"], tone: "sober" },
    ],
    causal_seeds: ["photos_aligned", "i_arrived_re_read", "name_at_crossroad"],
    narratorVoice: "第三人称旁观者；雨后木门与铜勺的回响。",
    schemaVersion: "1.0.0",
  },
  investigatableObjects: [
    { id: "leila_phone", name: "莱拉手机", description: "屏幕里 2011 短信", initialLocation: "莱拉手边", keywords: ["手机", "短信"], requires: [], leadsTo: ["i_arrived_re_read"], iconKey: "phone" },
    { id: "arash_poetry_book", name: "阿拉什的诗集", description: "抱在臂弯里", initialLocation: "阿拉什臂弯", keywords: ["诗集", "鲁米"], requires: [], leadsTo: ["photo_in_book_reveal"], iconKey: "book" },
    { id: "sugar_bowl", name: "桌上糖罐", description: "老铜勺碰糖罐的声响", initialLocation: "桌面", keywords: ["糖罐", "铜勺"], requires: [], leadsTo: ["shared_secret_acknowledged"], iconKey: "sugar" },
    { id: "leila_bag", name: "莱拉斜挎包", description: "内袋 2008 照片", initialLocation: "莱拉椅背", keywords: ["斜挎包", "照片"], requires: [], leadsTo: ["photos_aligned"], iconKey: "bag" },
    { id: "cafe_door", name: "咖啡馆木门", description: "推开时发出闷响", initialLocation: "咖啡馆入口", keywords: ["木门", "推开"], requires: [], leadsTo: ["crossroad_green"], iconKey: "door" },
  ],
  charactersPresent: [
    { id: "leila", name: "莱拉", initialState: "远", visibility: "主角视角可见", stateNotes: ["34-35 岁", "鬓边灰白", "手机有 2011 短信"] },
    { id: "arash", name: "阿拉什", initialState: "近", visibility: "主角视角可见", stateNotes: ["34-35 岁", "卷发鬓白", "推门手抱诗集"] },
  ],
  turnBudget: { investigate: 2, reveal: 2, conceal: 1, question: 2, confront: 2, comfort: 1, give: 2, destroy: 1, promise: 1, wait: 2, leave: 1, silence: 2 },
  causalSeeds: [
    { id: "photos_aligned", description: "两张照片在桌上对齐", trigger: "give on leila_bag + reveal on arash_poetry_book", effects: ["场景收束在 2008→2011→2024 完整回响"] },
    { id: "i_arrived_re_read", description: "重新念 2011 短信", trigger: "reveal on leila_phone", effects: ["13 年信号在桌面回响"] },
    { id: "name_at_crossroad", description: "街口留下卡姆兰的名字", trigger: "give on cafe_door", effects: ["场景结束于'分开'的合法结局"] },
  ],
  legalEndings: [
    { id: "open_crossroad", label: "路口分开", description: "绿灯亮起", causalSeedRequired: ["crossroad_green"] },
    { id: "two_photos_aligned", label: "两张照片对齐", description: "在桌上对齐", causalSeedRequired: ["photos_aligned"] },
    { id: "kamran_said", label: "说出卡姆兰", description: "卡姆兰正在等我说出口", causalSeedRequired: ["say_kamran_waiting"] },
  ],
  audioChapter: "reunion_2024",
};

// -----------------------------------------------------------------------------
// W12: case_02 — 《莫斯科没有童话》· 3 场景
// -----------------------------------------------------------------------------

const meeting1985: SceneMeta = {
  sceneId: "1985_meeting",
  caseSlug: "case_02_moscow_no_fairy_tale",
  title: "莫斯科音乐学院 · 305 琴房与两份同版手抄谱",
  era: "1985_soviet_late",
  location: "莫斯科音乐学院 · 老柴院 305 琴房",
  atmosphere: ["大提琴延音踏板", "木地板吱嘎", "21:40 门锁咔哒", "蜂蜜色眼睛 + 黑色高领"],
  contract: {
    sceneId: "1985_meeting",
    title: "莫斯科音乐学院 · 305 琴房与两份同版手抄谱",
    era: "1985_soviet_late",
    location: "莫斯科音乐学院 · 老柴院 305 琴房",
    timeOfDay: "evening",
    weather: "unspecified",
    cast: [
      { characterId: "natasha_roschina", role: "protagonist" },
      { characterId: "ilya_berman", role: "protagonist", initialDisposition: 0 },
      { characterId: "room_administrator_305", role: "witness", initialDisposition: 0 },
    ],
    required_anchors: [
      { anchorId: "305_room", description: "305 琴房 + 1978 Yamaha U3", mandatory: true },
      { anchorId: "op38_a_minor", description: "肖斯塔科维奇 Op.38", mandatory: true },
      { anchorId: "ilya_berman_pencil", description: "伊利亚铅笔圈注 И. Б.", mandatory: true },
      { anchorId: "natasha_first_not_absent", description: "娜塔莎说'给一个不在场的人'", mandatory: true },
      { anchorId: "petroff_rosin_stain", description: "Petrof 1962 大提琴松香渍在中央 C 键", mandatory: true },
      { anchorId: "copy_offer_1985_11_07", description: "11 月 7 日前夜'抄一份给你'", mandatory: true },
      { anchorId: "1985_setting_lock", description: "时代 1985 锁定", mandatory: true },
    ],
    core_conflict: "总谱只能由一人带离琴房；谁带、抄一份、谁先说'你留'",
    allowed_beats: [
      { beatId: "opening_first_measure", label: "开场第一小节", tier: "setup" },
      { beatId: "petrof_schellack_stain", label: "松香渍在中央 C 键", tier: "setup" },
      { beatId: "ilya_pencil_circles", label: "铅笔圈三小节签 И. Б.", tier: "rising" },
      { beatId: "natasha_first_not_absent", label: "第一次把'不在场'说出口", tier: "rising" },
      { beatId: "21_40_door_knock", label: "21:40 管理员敲门", tier: "climax" },
      { beatId: "copy_offer_nov_7", label: "抄一份给你", tier: "falling" },
      { beatId: "parting_at_door", label: "两人各自离开", tier: "resolution" },
    ],
    forbidden_reveals: [
      { revealKey: "ilya_1989_emigration", reason: "1989 移民属锚点 3" },
      { revealKey: "post_soviet_dissolution", reason: "苏联解体属锚点 4" },
      { revealKey: "sasha_natasha_marriage", reason: "1993 结婚属锚点 4" },
      { revealKey: "lisa_vienna", reason: "1986 西柏林出场属锚点 3" },
      { revealKey: "reichenberg_op38_2008", reason: "2008 柏林重逢属锚点 5" },
    ],
    max_turns: 12,
    total_action_budget: 30,
    legal_endings: [
      { endingId: "ending_pencil_admit", label: "铅笔圈注承认", conditions: ["seed_ilya_pencil_page_in_notebook"], tone: "bittersweet" },
      { endingId: "ending_pencil_silent", label: "铅笔圈注沉默", conditions: ["seed_manuscript_stays_in_305"], tone: "sober" },
      { endingId: "ending_copy_offer", label: "抄一份给你", conditions: ["seed_natasha_keeps_manuscript"], tone: "ambiguous" },
      { endingId: "ending_parting_at_door", label: "两人各自离开", conditions: ["parting_at_door"], tone: "open" },
      { endingId: "ending_first_not_absent", label: "第一次把'不在场'说出口", conditions: ["natasha_first_not_absent"], tone: "open" },
    ],
    causal_seeds: [
      "seed_ilya_pencil_page_in_notebook", "seed_manuscript_stays_in_305", "seed_natasha_keeps_manuscript",
      "seed_petroff_schellack_stain_in_2008_cafe", "seed_red_notebook_first_entry_1985",
    ],
    narratorVoice: "第三人称限制视角跟随娜塔莎；句式以大提琴与立式钢琴的物理意象为主；不使用 1985 之后才出现的词。",
    schemaVersion: "1.0.0",
  },
  investigatableObjects: [
    { id: "manuscript_op38", name: "肖斯塔科维奇 Op.38 总谱", description: "图书馆借出 1985-09；伊利亚铅笔圈三小节并签 И. Б.", initialLocation: "钢琴谱架", keywords: ["总谱", "Op38", "圈注"], requires: [], leadsTo: ["ilya_pencil_circles", "copy_offer"], iconKey: "paper" },
    { id: "cello_petroff_1962", name: "Petrof 1962 大提琴", description: "娜塔莎继承自祖母；松香渍在 Yamaha U3 中央 C 键", initialLocation: "娜塔莎椅子旁", keywords: ["大提琴", "Petrof", "松香"], requires: [], leadsTo: ["petroff_schellack_stain"], iconKey: "instrument" },
    { id: "red_notebook_ilya", name: "伊利亚的红色笔记本", description: "1985 年第一本；封面磨损", initialLocation: "伊利亚夹克内袋", keywords: ["笔记本", "红色", "1985"], requires: [], leadsTo: ["red_notebook_first_entry"], iconKey: "notebook" },
    { id: "piano_yamaha_u3", name: "Yamaha U3 立式钢琴", description: "1978 年产；中央 C 键有松香渍", initialLocation: "305 琴房窗下", keywords: ["立式钢琴", "Yamaha", "中央C"], requires: [], leadsTo: ["petrof_schellack_stain"], iconKey: "instrument" },
  ],
  charactersPresent: [
    { id: "natasha_roschina", name: "娜塔莎·罗希娜", initialState: "紧张", visibility: "主角视角可见", stateNotes: ["21 岁", "浅灰头巾 + 深绿高领", "蜂蜜色眼睛"] },
    { id: "ilya_berman", name: "伊利亚·贝尔曼", initialState: "严肃", visibility: "主角视角可见", stateNotes: ["23 岁", "黑色高领 + 圆框眼镜", "深棕色卷发"] },
    { id: "room_administrator_305", name: "305 琴房管理员", initialState: "中立", visibility: "主角视角可见", stateNotes: ["21:40 敲门"] },
  ],
  turnBudget: { investigate: 3, reveal: 2, conceal: 1, question: 2, confront: 1, comfort: 1, give: 2, destroy: 1, promise: 1, wait: 1, leave: 1, silence: 1 },
  causalSeeds: [
    { id: "seed_ilya_pencil_page_in_notebook", source_scene: "1985_meeting", target_scenes: ["1989_farewell", "2008_reunion"], echo_intensity: 0.95 },
    { id: "seed_manuscript_stays_in_305", source_scene: "1985_meeting", target_scenes: ["1989_farewell", "2008_reunion"], echo_intensity: 0.85 },
    { id: "seed_natasha_keeps_manuscript", source_scene: "1985_meeting", target_scenes: ["1989_farewell", "2008_reunion"], echo_intensity: 0.92 },
  ],
  legalEndings: [
    { id: "ending_pencil_admit", label: "铅笔圈注承认", description: "伊利亚把 И. Б. 圈注页撕下夹在红色笔记本", causalSeedRequired: ["seed_ilya_pencil_page_in_notebook"] },
    { id: "ending_pencil_silent", label: "铅笔圈注沉默", description: "总谱留在 305 琴房", causalSeedRequired: ["seed_manuscript_stays_in_305"] },
    { id: "ending_copy_offer", label: "抄一份给你", description: "伊利亚把总谱交给娜塔莎", causalSeedRequired: ["seed_natasha_keeps_manuscript"] },
    { id: "ending_parting_at_door", label: "两人各自离开", description: "21:40 管理员敲门后各自离开", causalSeedRequired: ["parting_at_door"] },
    { id: "ending_first_not_absent", label: "第一次把'不在场'说出口", description: "娜塔莎说'给一个不在场的人'", causalSeedRequired: ["natasha_first_not_absent"] },
  ],
  audioChapter: "1985_meeting",
  crossCaseParallels: ["第一案 photo_lab_2008（两张同版毕业照）↔ 第二案 1985_meeting（两份同版手抄谱）"],
};

const farewell1989: SceneMeta = {
  sceneId: "1989_farewell",
  caseSlug: "case_02_moscow_no_fairy_tale",
  title: "莫斯科谢列梅捷沃机场 · 出境大厅与第三小节",
  era: "1989_soviet_dissolution_2yr_before",
  location: "SVO-2 国际线出境大厅 + 塔甘卡剧院衣帽间（5:55 电话）",
  atmosphere: ["传送带机械声", "5:55 电话亭 4 秒", "Aeroflot 钟声", "羽绒服 + 鸭舌帽"],
  contract: {
    sceneId: "1989_farewell",
    title: "莫斯科谢列梅捷沃机场 · 出境大厅与第三小节",
    era: "1989_soviet_dissolution_2yr_before",
    location: "SVO-2 国际线出境大厅",
    timeOfDay: "dawn",
    weather: "cold",
    cast: [
      { characterId: "natasha_roschina", role: "protagonist" },
      { characterId: "ilya_berman", role: "protagonist" },
      { characterId: "sasha_kuzmin", role: "ally", initialDisposition: 0.5 },
      { characterId: "lisa_hoffmann", role: "ally", initialDisposition: 0.5 },
    ],
    required_anchors: [
      { anchorId: "svo2_departure_lounge", description: "SVO-2 国际线出境大厅", mandatory: true },
      { anchorId: "ilya_lisa_1986_west_berlin", description: "莉莎 1986 西柏林认识伊利亚", mandatory: true },
      { anchorId: "natasha_not_at_airport", description: "娜塔莎没去机场（处分 3 年观察期）", mandatory: true },
      { anchorId: "lisa_calls_at_5_55", description: "5:55 莉莎电话转达", mandatory: true },
      { anchorId: "su355_takeoff_6_15", description: "SU-355 6:15 起飞", mandatory: true },
      { anchorId: "aeroflot_tag_visible", description: "Aeroflot SU-355 托运标签", mandatory: true },
    ],
    core_conflict: "四个人分处两个地点，通过一个 4 秒延迟的电话'同时在场'",
    allowed_beats: [
      { beatId: "opening_taganka_wardrobe", label: "5:30 塔甘卡衣帽间", tier: "setup" },
      { beatId: "sasha_hand_on_shoulder", label: "萨沙把手放在娜塔莎肩上", tier: "setup" },
      { beatId: "opening_svo2_lisa", label: "5:35 SVO-2 莉莎帮伊利亚托运", tier: "setup" },
      { beatId: "ilya_glance_at_notebook", label: "伊利亚看红色笔记本", tier: "rising" },
      { beatId: "5_55_phone_rings", label: "5:55 电话", tier: "climax" },
      { beatId: "4_second_pickup", label: "4 秒后接起", tier: "climax" },
      { beatId: "third_bar_oral_message", label: "第三小节是给你的", tier: "falling" },
      { beatId: "6_15_announcement", label: "6:15 登机广播", tier: "falling" },
      { beatId: "su355_takeoff", label: "SU-355 起飞", tier: "resolution" },
    ],
    forbidden_reveals: [
      { revealKey: "1992_lisa_ilya_marriage", reason: "1992 维也纳登记" },
      { revealKey: "1993_sasha_natasha_marriage", reason: "1993 莫斯科登记" },
      { revealKey: "1991_dissolution", reason: "1991 苏联解体" },
      { revealKey: "2008_berlin_reunion", reason: "2008 柏林重逢" },
    ],
    max_turns: 14,
    total_action_budget: 32,
    legal_endings: [
      { endingId: "ending_third_bar_spoken", label: "第三小节被说出", conditions: ["seed_lisa_relays_third_bar"], tone: "bittersweet" },
      { endingId: "ending_lisa_silent", label: "莉莎不问", conditions: ["seed_lisa_keeps_silence"], tone: "sober" },
      { endingId: "ending_ilya_notebook_page_1", label: "翻到第 1 页", conditions: ["seed_ilya_glances_page_1"], tone: "bittersweet" },
      { endingId: "ending_ilya_notebook_page_7", label: "翻到第 7 页", conditions: ["seed_ilya_glances_page_7"], tone: "ambiguous" },
      { endingId: "ending_natasha_silent_4_seconds", label: "4 秒沉默", conditions: ["seed_natasha_4_second_silence"], tone: "open" },
      { endingId: "ending_su355_takeoff", label: "SU-355 起飞", conditions: ["su355_takeoff"], tone: "open" },
    ],
    causal_seeds: [
      "seed_lisa_relays_third_bar", "seed_lisa_keeps_silence", "seed_ilya_glances_page_1",
      "seed_ilya_glances_page_7", "seed_natasha_4_second_silence", "seed_aeroflot_tag_in_page_7",
      "seed_walkman_tape_in_1989_luggage",
    ],
    narratorVoice: "双视角交叉：5:30 娜塔莎在塔甘卡衣帽间 / 5:55 莉莎在 SVO-2 电话亭 / 6:15 伊利亚在登机口。",
    schemaVersion: "1.0.0",
  },
  investigatableObjects: [
    { id: "aeroflot_luggage_tag", name: "Aeroflot 托运标签", description: "SU-355 / 1989-04-08 / SVO-PRG-VIE", initialLocation: "伊利亚行李箱", keywords: ["Aeroflot", "SU-355"], requires: [], leadsTo: ["seed_aeroflot_tag_in_page_7"], iconKey: "paper" },
    { id: "red_notebook_ilya_1989", name: "伊利亚的红色笔记本（1989）", description: "1985 起；1985-1987 共 11 页", initialLocation: "伊利亚夹克内袋", keywords: ["笔记本", "红色"], requires: [], leadsTo: ["seed_ilya_glances_page_1"], iconKey: "notebook" },
    { id: "walkman_sony", name: "Sony WM-FX1 walkman", description: "1984 年产；B 面 23:14", initialLocation: "伊利亚行李箱", keywords: ["walkman", "Sony"], requires: [], leadsTo: ["seed_walkman_tape_in_1989_luggage"], iconKey: "instrument" },
    { id: "airport_payphone", name: "机场付费电话亭", description: "莉莎打电话给娜塔莎的电话亭", initialLocation: "SVO-2 候机区", keywords: ["付费电话"], requires: [], leadsTo: ["lisa_calls_at_5_55"], iconKey: "phone" },
    { id: "natasha_home_phone", name: "娜塔莎家电话", description: "黑色拨盘电话", initialLocation: "塔甘卡衣帽间", keywords: ["拨盘电话"], requires: [], leadsTo: ["4_second_pickup"], iconKey: "phone" },
  ],
  charactersPresent: [
    { id: "natasha_roschina", name: "娜塔莎·罗希娜", initialState: "不舍", visibility: "主角视角可见", stateNotes: ["塔甘卡衣帽间", "深绿高领 + 浅灰头巾"] },
    { id: "sasha_kuzmin", name: "萨沙·库兹明", initialState: "沉稳", visibility: "主角视角可见", stateNotes: ["27 岁", "鸭舌帽 + 深蓝衬衫"] },
    { id: "ilya_berman", name: "伊利亚·贝尔曼（远程）", initialState: "紧张", visibility: "主角视角可见（远程）", stateNotes: ["SVO-2 海关柜台前看红色笔记本"] },
    { id: "lisa_hoffmann", name: "莉莎·霍夫曼", initialState: "紧张", visibility: "主角视角可见", stateNotes: ["22 岁", "红金色长发", "SVO-2 电话亭"] },
  ],
  turnBudget: { investigate: 3, reveal: 2, conceal: 1, question: 2, confront: 1, comfort: 1, give: 2, destroy: 1, promise: 1, wait: 1, leave: 1, silence: 1 },
  causalSeeds: [
    { id: "seed_lisa_relays_third_bar", source_scene: "1989_farewell", target_scenes: ["2008_reunion"], echo_intensity: 0.95 },
    { id: "seed_walkman_tape_in_1989_luggage", source_scene: "1989_farewell", target_scenes: ["2008_reunion"], echo_intensity: 0.85 },
    { id: "seed_aeroflot_tag_in_page_7", source_scene: "1989_farewell", target_scenes: ["2008_reunion"], echo_intensity: 0.8 },
  ],
  legalEndings: [
    { id: "ending_third_bar_spoken", label: "第三小节被说出", description: "莉莎 5:55 转达", causalSeedRequired: ["seed_lisa_relays_third_bar"] },
    { id: "ending_lisa_silent", label: "莉莎不问", description: "只传话", causalSeedRequired: ["seed_lisa_keeps_silence"] },
    { id: "ending_ilya_notebook_page_1", label: "翻第 1 页", description: "1985 И. Б. 圈注页", causalSeedRequired: ["seed_ilya_glances_page_1"] },
    { id: "ending_ilya_notebook_page_7", label: "翻第 7 页", description: "1987 大纲 3 页中第 1 页", causalSeedRequired: ["seed_ilya_glances_page_7"] },
    { id: "ending_natasha_silent_4_seconds", label: "4 秒沉默", description: "娜塔莎 4 秒后接电话", causalSeedRequired: ["seed_natasha_4_second_silence"] },
    { id: "ending_su355_takeoff", label: "SU-355 起飞", description: "6:15 登机广播响起", causalSeedRequired: ["su355_takeoff"] },
  ],
  audioChapter: "1989_farewell",
  crossCaseParallels: ["第一案 farewell_2011（我到了短信）↔ 第二案 1989_farewell（5:55 电话）"],
};

const reunion2008: SceneMeta = {
  sceneId: "2008_reunion",
  caseSlug: "case_02_moscow_no_fairy_tale",
  title: "柏林 · 十字山区老式咖啡馆与 U1 线街口",
  era: "2008_berlin_reunion",
  location: "柏林 · 十字山区 · 老式咖啡馆 + U1 线地铁站街口",
  atmosphere: ["雨后玻璃水珠", "远处 U-Bahn", "21:05 红灯变绿", "蜂蜜色眼睛 + 鬓角灰白"],
  contract: {
    sceneId: "2008_reunion",
    title: "柏林 · 十字山区老式咖啡馆与 U1 线街口",
    era: "2008_berlin_reunion",
    location: "柏林 · 十字山区",
    timeOfDay: "evening",
    weather: "rain",
    cast: [
      { characterId: "natasha_roschina", role: "protagonist" },
      { characterId: "ilya_berman", role: "protagonist" },
      { characterId: "kreuzberg_cafe_owner", role: "witness", initialDisposition: 0 },
      { characterId: "sasha_kuzmin_remote", role: "off_stage" },
      { characterId: "lisa_hoffmann_remote", role: "off_stage" },
    ],
    required_anchors: [
      { anchorId: "kreuzberg_cafe_setting", description: "十字山区老式咖啡馆", mandatory: true },
      { anchorId: "middle_aged_versions", description: "娜塔莎 44 / 伊利亚 46 中年版本", mandatory: true },
      { anchorId: "ilya_brings_red_notebook", description: "伊利亚抱红色笔记本推门", mandatory: true },
      { anchorId: "scene_must_reference_1985_1989", description: "必须引用 1985/1989 具体行为", mandatory: true },
      { anchorId: "npc_actively_recalls", description: "NPC 必须主动提起 1985/1989 行为", mandatory: true },
      { anchorId: "scene_ends_at_crossing", description: "场景结束于 U1 站街口", mandatory: true },
    ],
    core_conflict: "19 年后第一眼落在何处；是否对齐两份节目单；是否承认 1985/1989 具体行为",
    allowed_beats: [
      { beatId: "opening_18_30_philharmonie_end", label: "18:30 柏林爱乐独奏会结束", tier: "setup" },
      { beatId: "natasha_buys_program_op40", label: "18:50 娜塔莎买 Op.40 节目单", tier: "setup" },
      { beatId: "kreuzberg_cafe_arrival", label: "18:50 娜塔莎到咖啡馆", tier: "setup" },
      { beatId: "ilya_enters_with_notebook", label: "19:15 伊利亚抱笔记本推门", tier: "rising" },
      { beatId: "first_gaze_choice", label: "第一眼选择", tier: "rising" },
      { beatId: "two_programs_align", label: "两份节目单对齐", tier: "climax" },
      { beatId: "red_notebook_page_7_visible", label: "第 7 页胶带痕迹可见", tier: "climax" },
      { beatId: "postcard_wien_1995_on_table", label: "1995 明信片被打开", tier: "falling" },
      { beatId: "21_00_walk_to_u1", label: "21:00 走到 U1 站口", tier: "falling" },
      { beatId: "21_05_red_to_green", label: "21:05 红灯变绿", tier: "resolution" },
      { beatId: "simultaneous_turn_and_smile", label: "两人回头笑一下", tier: "resolution" },
    ],
    forbidden_reveals: [
      { revealKey: "2009_post_reunion", reason: "2009 之后" },
      { revealKey: "next_case", reason: "任何关于下一案的暗示" },
      { revealKey: "case_01_leila_arash", reason: "不引用第一案" },
    ],
    max_turns: 16,
    total_action_budget: 36,
    legal_endings: [
      { endingId: "ending_two_programs_align", label: "两份节目单对齐", conditions: ["seed_two_programs_takeout_compare"], tone: "bittersweet" },
      { endingId: "ending_first_words_admit", label: "第一句话承认 1985/1989", conditions: ["seed_first_words_admit_1985_1989"], tone: "bittersweet" },
      { endingId: "ending_postcard_unveiled", label: "1995 明信片被打开", conditions: ["seed_postcard_wien_1995_unveiled"], tone: "bittersweet" },
      { endingId: "ending_crossroads_parting", label: "街口分开", conditions: ["21_05_red_to_green"], tone: "open" },
      { endingId: "ending_silent_keeping", label: "沉默带过", conditions: ["silence"], tone: "sober" },
      { endingId: "ending_reality_lives_convergence", label: "现实生活共同收束", conditions: ["21_06_ilya_calls_lisa"], tone: "open" },
    ],
    causal_seeds: [
      "seed_two_programs_takeout_compare", "seed_first_words_admit_1985_1989", "seed_postcard_wien_1995_unveiled",
      "seed_petroff_schellack_stain_in_2008_cafe", "seed_aeroflot_tag_visible_in_page_7",
      "seed_walkman_tape_remembered", "seed_third_bar_oral_message_remembered", "seed_4_second_symmetry",
    ],
    narratorVoice: "第三人称限制视角跟随娜塔莎与伊利亚的双重视角交替。",
    schemaVersion: "1.0.0",
  },
  investigatableObjects: [
    { id: "program_op38_2008", name: "2008 Op.38 节目单", description: "伊利亚演出 Op.38 后留下的节目单", initialLocation: "伊利亚夹克内袋", keywords: ["节目单", "Op.38"], requires: [], leadsTo: ["seed_two_programs_takeout_compare"], iconKey: "paper" },
    { id: "program_op40_2008", name: "2008 Op.40 节目单（折角）", description: "娜塔莎 18:50 买的第 2 曲目节目单（折角）", initialLocation: "娜塔莎斜挎包", keywords: ["节目单", "Op.40"], requires: [], leadsTo: ["seed_two_programs_takeout_compare"], iconKey: "paper" },
    { id: "red_notebook_ilya_2008", name: "伊利亚的红色笔记本（2008）", description: "1985 起；现在约 30 页", initialLocation: "伊利亚臂弯", keywords: ["笔记本", "红色", "2008"], requires: [], leadsTo: ["seed_petroff_schellack_stain_in_2008_cafe"], iconKey: "notebook" },
    { id: "notebook_page_7_tape", name: "红色笔记本第 7 页胶带痕迹", description: "1992 第 7 页被撕下又粘回去；1989 Aeroflot 标签夹在里面", initialLocation: "红色笔记本第 7 页", keywords: ["第7页", "胶带", "Aeroflot"], requires: ["red_notebook_ilya_2008"], leadsTo: ["seed_aeroflot_tag_visible_in_page_7"], iconKey: "notebook" },
    { id: "manuscript_op38_in_bag", name: "娜塔莎斜挎包里的 Op.38 手抄谱", description: "1985 总谱副本；阿尼娅 1995 蜡笔红星在封底", initialLocation: "娜塔莎斜挎包内袋", keywords: ["手抄谱", "Op.38", "红星"], requires: [], leadsTo: ["ending_postcard_unveiled"], iconKey: "paper" },
    { id: "postcard_wien_1995", name: "1995 维也纳未寄出的明信片", description: "1995-11-17 娜塔莎在维也纳写但未寄出", initialLocation: "娜塔莎斜挎包内袋", keywords: ["明信片", "维也纳", "1995"], requires: [], leadsTo: ["seed_postcard_wien_1995_unveiled"], iconKey: "paper" },
  ],
  charactersPresent: [
    { id: "natasha_roschina", name: "娜塔莎·罗希娜", initialState: "试探", visibility: "主角视角可见", stateNotes: ["44 岁", "蜂蜜色眼睛 + 灰金短发", "斜挎小棕包"] },
    { id: "ilya_berman", name: "伊利亚·贝尔曼", initialState: "紧张", visibility: "主角视角可见", stateNotes: ["46 岁", "鬓角灰白", "圆框眼镜（金属腿）", "臂弯抱红色笔记本"] },
    { id: "kreuzberg_cafe_owner", name: "咖啡馆老板", initialState: "中立", visibility: "主角视角可见", stateNotes: ["1990 年开店", "维也纳人"] },
  ],
  turnBudget: { investigate: 3, reveal: 2, conceal: 1, question: 2, confront: 1, comfort: 1, give: 2, destroy: 1, promise: 1, wait: 1, leave: 1, silence: 1 },
  causalSeeds: [
    { id: "seed_two_programs_takeout_compare", source_scene: "2008_reunion", target_scenes: ["2008_reunion"], echo_intensity: 0.99 },
    { id: "seed_first_words_admit_1985_1989", source_scene: "2008_reunion", target_scenes: ["2008_reunion"], echo_intensity: 0.95 },
    { id: "seed_postcard_wien_1995_unveiled", source_scene: "2008_reunion", target_scenes: ["2008_reunion"], echo_intensity: 0.9 },
  ],
  legalEndings: [
    { id: "ending_two_programs_align", label: "两份节目单对齐", description: "Op.38 / Op.40 在桌面对齐", causalSeedRequired: ["seed_two_programs_takeout_compare"] },
    { id: "ending_first_words_admit", label: "第一句话承认", description: "伊利亚主动承认 1985/1989 行为", causalSeedRequired: ["seed_first_words_admit_1985_1989"] },
    { id: "ending_postcard_unveiled", label: "明信片被打开", description: "1995 维也纳明信片 13 年后兑现", causalSeedRequired: ["seed_postcard_wien_1995_unveiled"] },
    { id: "ending_crossroads_parting", label: "街口分开", description: "21:05 红灯变绿两人走向不同方向", causalSeedRequired: ["21_05_red_to_green"] },
    { id: "ending_silent_keeping", label: "沉默带过", description: "未把 1989/1995 真相说出口", causalSeedRequired: ["silence"] },
    { id: "ending_reality_lives_convergence", label: "现实生活共同收束", description: "21:06 伊利亚打电话 / 21:08 娜塔莎发短信", causalSeedRequired: ["21_06_ilya_calls_lisa"] },
  ],
  audioChapter: "2008_reunion",
  crossCaseParallels: ["第一案 reunion_2024（两张同版毕业照对齐）↔ 第二案 2008_reunion（两份节目单对齐）"],
};

// -----------------------------------------------------------------------------
// W12 案例注册表
// -----------------------------------------------------------------------------

export interface CaseMeta {
  caseSlug: string;
  displayName: string;
  subtitle: string;
  sceneIds: string[];
  defaultActorId: string;
  defaultAllyId: string;
  artDirectory: string;
  audioDirectory: string;
}

export const CASE_REGISTRY: Record<string, CaseMeta> = {
  case_01_revolution_street: {
    caseSlug: "case_01_revolution_street",
    displayName: "革命街没有尽头",
    subtitle: "德黑兰 · 伊斯坦布尔 · 13 年",
    sceneIds: ["photo_lab_2008", "farewell_2011", "reunion_2024"],
    defaultActorId: "leila",
    defaultAllyId: "arash",
    artDirectory: "/assets/images",
    audioDirectory: "/assets/audio",
  },
  case_02_moscow_no_fairy_tale: {
    caseSlug: "case_02_moscow_no_fairy_tale",
    displayName: "莫斯科没有童话",
    subtitle: "莫斯科 · 维也纳 · 柏林 · 19 年",
    sceneIds: ["1985_meeting", "1989_farewell", "2008_reunion"],
    defaultActorId: "natasha_roschina",
    defaultAllyId: "ilya_berman",
    artDirectory: "/assets/images/case_02",
    audioDirectory: "/assets/audio/case_02",
  },
};

export const CASE_LIST: CaseMeta[] = Object.values(CASE_REGISTRY).sort(
  (a, b) => a.caseSlug.localeCompare(b.caseSlug),
);

export const SCENE_MOCKS: Record<string, SceneMeta> = {
  photo_lab_2008: photoLab2008,
  farewell_2011: farewell2011,
  reunion_2024: reunion2024,
  "1985_meeting": meeting1985,
  "1989_farewell": farewell1989,
  "2008_reunion": reunion2008,
};

export const SCENES_IN_ORDER: SceneMeta[] = [photoLab2008, farewell2011, reunion2024];

export function scenesForCase(caseSlug: string): SceneMeta[] {
  const meta = CASE_REGISTRY[caseSlug];
  if (!meta) return [];
  return meta.sceneIds
    .map((sid) => SCENE_MOCKS[sid])
    .filter((s): s is SceneMeta => Boolean(s));
}
