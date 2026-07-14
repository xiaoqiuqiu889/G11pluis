export const chapterIds = ["chapter1", "chapter2", "chapter3", "chapter4", "chapter5"] as const;
export type ChapterId = (typeof chapterIds)[number];
export const memoryAxes = ["speak", "keep", "survive"] as const;
export type MemoryAxis = (typeof memoryAxes)[number];
export type AxisValues = Record<MemoryAxis, number>;
export type InteractionKind = "photo" | "projector" | "choice" | "explore" | "combine" | "email" | "gaze" | "silence";

export interface MemoryCollectible {
  id: string;
  label: string;
  motif: "photo" | "paper" | "ash" | "ticket" | "email" | "book";
  description: string;
}

export interface InteractionContract {
  id: string;
  chapterId: ChapterId;
  requirement: "required" | "optional";
  steps?: string[];
  sceneId: string;
  kind: InteractionKind;
  title: string;
  prompt: string;
  action: string;
  completion: string;
  memoryGain: number;
  clue?: { id: string; label: string; text: string };
  collectible?: MemoryCollectible;
  isCore?: boolean;
  handledByScene?: boolean;
}

const interaction = (value: InteractionContract) => value;

/** Fifteen authored interactions: three per chapter, with no filler-only hotspots. */
export const interactionCatalog: readonly InteractionContract[] = [
  interaction({
    id: "photo-placement", chapterId: "chapter1", sceneId: "photo", kind: "photo", requirement: "required", handledByScene: true,
    title: "安放毕业照", prompt: "拿起女生保存的那张照片，决定它如何等待男生。",
    action: "拖动、翻面，或把照片收回帆布包。", completion: "纸边擦过桌布。十三年前的两张照片，先有一张找到了位置。", memoryGain: 5,
    clue: { id: "two-identical-prints", label: "两次冲洗", text: "毕业那天冲洗了两张相同照片。后来，他们各自保留一张。" },
    collectible: { id: "leila-graduation-photo", label: "女生的毕业照", motif: "photo", description: "边角被机场与抽屉磨得发白的一张。" },
  }),
  interaction({
    id: "projector-repair", chapterId: "chapter1", sceneId: "campus", kind: "projector", requirement: "required", handledByScene: true, isCore: true,
    title: "修好旧放映机", prompt: "先校准焦距，再把错位的画面推回银幕中央。",
    action: "完成两段修理，并从闪回画面里认出共同记忆。", completion: "齿轮重新咬合。黑暗里，两个人同时说：别松手。", memoryGain: 7,
    clue: { id: "projector-toolbox-note", label: "工具箱里的折痕", text: "男生把每次约会时间写在维修清单背面，最早的一条只有三个字：我到了。" },
    collectible: { id: "underground-film-ticket", label: "地下放映会电影票", motif: "ticket", description: "日期被机油晕开，座位号仍看得清。" },
  }),
  interaction({
    id: "first-memory-action", chapterId: "chapter1", sceneId: "choice-one", kind: "choice", requirement: "required", handledByScene: true,
    title: "停电后的第一个动作", prompt: "让女生先说、先靠近，或先确认出口。",
    action: "作出第一段主记忆选择。", completion: "放映机尚未亮起，这个动作已经留在他们往后的停电里。", memoryGain: 6,
    clue: { id: "first-do-not-let-go", label: "第一次“别松手”", text: "年轻时它像一句玩笑；后来，他们才知道手会在什么时候松开。" },
  }),
  interaction({
    id: "publication-clues", chapterId: "chapter2", sceneId: "publication", kind: "explore", requirement: "optional",
    title: "检查刊物桌面", prompt: "查看打字机、退稿信和刊物末页，弄清学校为什么传唤他们。",
    action: "依次查看三个有用途的物件。", steps: ["触摸打字机上发干的色带", "展开出版社退回的信", "掀起刊物最后一页的折角"],
    completion: "刊物报道了三名失踪学生。第二天，学校开始追问其他编辑是谁。", memoryGain: 5,
    clue: { id: "maziya-last-note", label: "玛兹雅的页边字", text: "她写：如果我没回来，先把这一期保存好。" },
    collectible: { id: "publication-margin", label: "刊物页边", motif: "paper", description: "印着半句被裁掉的诗和玛兹雅画下的蓝色太阳。" },
  }),
  interaction({
    id: "names-decision", chapterId: "chapter2", sceneId: "choice-two", kind: "choice", requirement: "required", handledByScene: true, isCore: true,
    title: "是否告发同伴", prompt: "只承认自己、拒绝告发，或说出同伴的名字。",
    action: "承担一种收益，也承担它留下的代价。", completion: "记录员合上本子。无论她怎样回答，处分程序都会继续。", memoryGain: 7,
    clue: { id: "twenty-eight-names", label: "问话记录", text: "调查者问谁参与了刊物；她的回答会在多年后以不同方式回来。" },
  }),
  interaction({
    id: "discipline-record", chapterId: "chapter2", sceneId: "echo-two", kind: "explore", requirement: "optional",
    title: "翻看纪律记录", prompt: "从印章日期、缺席记录和释放通知中确认玛兹雅的去向。",
    action: "把三处记录按时间排好。", steps: ["核对带走当夜的印章日期", "把六个月缺席记录接在后面", "最后展开设拉子寄来的释放通知"],
    completion: "玛兹雅六个月后获释，没有回到大学。她后来在设拉子的儿童图书馆工作。", memoryGain: 6,
    clue: { id: "maziya-fixed-future", label: "玛兹雅的后来", text: "她活了下来，也失去了原来的生活。女生在问话室里的回答不会改写这个结果。" },
    collectible: { id: "discipline-stamp", label: "纪律委员会印章拓片", motif: "ash", description: "红色印泥盖住了女生的继续深造资格。" },
  }),
  interaction({
    id: "departure-packing", chapterId: "chapter3", sceneId: "small-room", kind: "explore", requirement: "optional",
    title: "整理离开前的桌面", prompt: "钥匙、复健单和护照申请放在同一张桌上，却指向三个方向。",
    action: "依次翻看出租屋钥匙、父亲的复健单与没有回音的护照申请。", steps: ["拿起出租屋钥匙", "展开父亲的复健单", "翻到护照申请最后一页"],
    completion: "女生把钥匙推回男生一侧。离开第一次有了可触摸的重量。", memoryGain: 5,
    clue: { id: "three-directions", label: "三个方向", text: "留下不是一句理想；离开也不是一句背叛。" },
    collectible: { id: "rental-room-key", label: "出租屋钥匙", motif: "ticket", description: "他们曾经共同生活过的最普通证据。" },
  }),
  interaction({
    id: "last-night-truth", chapterId: "chapter3", sceneId: "choice-three", kind: "choice", requirement: "required", handledByScene: true,
    title: "完成最后一夜", prompt: "把卡姆兰与机票说到什么程度，由女生亲手决定。",
    action: "选择全部说完、再问一条共同的路，或只说航班。", completion: "三种说法都通向机场；只有沉默的形状不同。", memoryGain: 7,
    clue: { id: "sealed-flight-envelope", label: "装着航班的信封", text: "卡姆兰的名字是否被说出，会在十三年后的路口回来。" },
  }),
  interaction({
    id: "airport-goodbye", chapterId: "chapter3", sceneId: "echo-three", kind: "silence", requirement: "required", isCore: true,
    title: "握住，然后松开", prompt: "广播响起以前握住他的手；行李箱开始移动时，由你松开。",
    action: "按住画面，直到广播抵达；再让手回到各自一侧。", steps: ["握住他的手", "听完登机广播", "让行李箱越过黄线"],
    completion: "她写下“我到了”，没有发送。最后，是行李箱轮子把他们分开。", memoryGain: 5,
    clue: { id: "unsent-arrival", label: "未发送的“我到了”", text: "年轻时它是赴约；这一次，它只留在草稿里。" },
    collectible: { id: "one-way-luggage-tag", label: "单程行李牌", motif: "ticket", description: "目的地很清楚，告别没有。" },
  }),
  interaction({
    id: "dual-city-objects", chapterId: "chapter4", sceneId: "two-cities", kind: "combine", requirement: "optional",
    title: "对齐两座城市", prompt: "把圣何塞的底片编号与德黑兰的观测日期放在同一条时间线上。",
    action: "组合底片、手写日期与同一天的流星记录。", steps: ["卡姆兰的底片编号", "玛丽亚姆的流星日期"],
    completion: "十三小时的时差里，两个人都把同一天藏在手边。", memoryGain: 5,
    clue: { id: "parallel-date", label: "同一天", text: "旧爱没有让现在的生活暂停；现在的生活也没有抹掉旧日。" },
    collectible: { id: "parallel-date-card", label: "双城日期卡", motif: "photo", description: "一边是底片编号，一边是流星时间。" },
  }),
  interaction({
    id: "email-draft", chapterId: "chapter4", sceneId: "email", kind: "email", requirement: "required", handledByScene: true, isCore: true,
    title: "处理未发送邮件", prompt: "写下一句，再亲手删除。删除不等于从记忆里消失。",
    action: "选择一句作者预设文本并逐字删除。", completion: "屏幕重新空白；卷宗里留下了句子的残影。", memoryGain: 7,
    clue: { id: "deleted-draft-shadow", label: "删除后的残影", text: "被删除的句子会改变重逢时她先认出的东西。" },
  }),
  interaction({
    id: "receipt-memory-combination", chapterId: "chapter4", sceneId: "last-email", kind: "combine", requirement: "optional",
    title: "把草稿与照片收在一起", prompt: "将邮件草稿残影与卡姆兰刚洗好的黑白照片叠在一起。",
    action: "组合未发送草稿与雾中高速公路照片。", steps: ["未发送邮件残影", "雾中高速公路底片"],
    completion: "她说照片不像革命街，却把它贴在冰箱上。", memoryGain: 4,
    collectible: { id: "draft-shadow", label: "未发送邮件残影", motif: "email", description: "没有寄出，仍然属于她完整生活的一部分。" },
  }),
  interaction({
    id: "reunion-gaze", chapterId: "chapter5", sceneId: "gaze", kind: "gaze", requirement: "required", handledByScene: true,
    title: "决定第一眼", prompt: "先看手与白发、旧诗集，或时钟与机场方向。",
    action: "让视线真实落到画面中的一个位置。", completion: "门开了。男生说：“我到了。”女生回答：“我知道。”", memoryGain: 5,
    clue: { id: "arrival-finally", label: "终于抵达", text: "同一句“我到了”，隔了十三年才真正抵达彼此面前。" },
  }),
  interaction({
    id: "photo-pairing", chapterId: "chapter5", sceneId: "book", kind: "combine", requirement: "required", isCore: true,
    title: "对齐两张相同照片", prompt: "翻看两张照片的磨损，再把它们放进同一个取景框。",
    action: "组合女生的折角照片与男生夹在诗集里的照片。", steps: ["女生保存的雨痕折角", "男生保存的书页黄斑"],
    completion: "同一次冲印。两种磨损。没有一张被丢掉。", memoryGain: 6,
    collectible: { id: "paired-graduation-photos", label: "两张同版毕业照", motif: "photo", description: "站位相同，十三年的磨损不同。" },
  }),
  interaction({
    id: "final-crossroad", chapterId: "chapter5", sceneId: "crossroads", kind: "silence", requirement: "required",
    title: "走到路中央", prompt: "人群涌来时握住衣袖；到分岔处，再亲手松开。",
    action: "按住越过人群，再在绿灯结束前放手。", steps: ["握住衣袖", "穿过路中央", "在分岔处松开"],
    completion: "这一次，他们把再见走完。眼前的生活没有暂停。", memoryGain: 5,
    clue: { id: "last-do-not-let-go", label: "最后一次“别松手”", text: "他们只握到路中央，然后成熟地放开。" },
  }),
];

export function firstRunRequiredInteractions(chapterId?: ChapterId): readonly InteractionContract[] {
  return interactionCatalog.filter(item => item.requirement === "required" && (!chapterId || item.chapterId === chapterId));
}

export function firstRunOptionalInteractions(chapterId?: ChapterId): readonly InteractionContract[] {
  return interactionCatalog.filter(item => item.requirement === "optional" && (!chapterId || item.chapterId === chapterId));
}

export type PaidDialogueId =
  | "paid-photo-developing"
  | "paid-lab-door"
  | "paid-marriage-truth"
  | "paid-two-cities-choice"
  | "paid-reunion-hypothesis";

export interface PaidDialogueContract {
  id: PaidDialogueId;
  chapterId: ChapterId;
  anchorSceneId: string;
  title: string;
  previewLine: string;
  lockedLines: string[];
  archiveTitle: string;
}

export const paidDialogues: readonly PaidDialogueContract[] = [
  {
    id: "paid-photo-developing", chapterId: "chapter1", anchorSceneId: "promise", title: "两张相同的照片",
    previewLine: "“照片要冲两张吗？”",
    lockedLines: ["男生：“一样的两张。她带一张。”", "女生：“另一张呢？”", "男生：“我留着。免得以后有人说，我们那天没站在一起。”"],
    archiveTitle: "冲洗照片时没有继续说完的话",
  },
  {
    id: "paid-lab-door", chapterId: "chapter2", anchorSceneId: "after-gate", title: "铁门合上以前",
    previewLine: "“其实那天，我本来想叫住你。”",
    lockedLines: ["女生：“我想说，我还爱你。”", "“可我不能再留在原地。”", "“别再让我等一年。”", "门先在这句话以前关上了。"],
    archiveTitle: "实验室门口没有说出的告白",
  },
  {
    id: "paid-marriage-truth", chapterId: "chapter3", anchorSceneId: "kamran", title: "视频挂断以前",
    previewLine: "卡姆兰：“我知道你不是因为爱我才答应这次见面。”",
    lockedLines: ["女生：“我需要一条能离开的路。这一点，我不能假装。”", "卡姆兰：“我也不接受没有代价的假装。结婚以后，我们得把生活当真的。”", "女生：“我会认真和你生活，但不会把过去删掉。”", "卡姆兰：“那就不删。我们只答应，不拿沉默惩罚对方。”"],
    archiveTitle: "婚前视频里说清的边界",
  },
  {
    id: "paid-two-cities-choice", chapterId: "chapter4", anchorSceneId: "two-cities", title: "望远镜旁的答案",
    previewLine: "玛丽亚姆：“如果那年可以重新选一次，你会跟她走吗？”",
    lockedLines: ["男生：“我会先把父亲安顿好，再问她愿不愿等。”", "“可那一年，她已经等完了。”", "玛丽亚姆：“所以答案不是会不会走。”", "男生：“是我会不会早点把不能走说清楚。”"],
    archiveTitle: "两座城市里最诚实的回答",
  },
  {
    id: "paid-reunion-hypothesis", chapterId: "chapter5", anchorSceneId: "book", title: "一个没有发生的假设",
    previewLine: "女生：“如果我们现在都没有结婚呢？”",
    lockedLines: ["男生：“那我们会不会又把亏欠误认成爱情？”", "女生：“也许。也许我们只会一起喝完这杯茶。”", "男生：“然后呢？”", "女生：“然后各自回家。只是这次，把再见说完。”"],
    archiveTitle: "旧书旁没有继续追问的假设",
  },
];

export interface ChapterRewardContract {
  chapterId: ChapterId;
  sourceSceneId: string;
  prop: string;
  code: string;
  nextHint: string;
  disclaimer: string;
}

export const chapterRewards: readonly ChapterRewardContract[] = [
  { chapterId: "chapter1", sourceSceneId: "promise", prop: "照片背面的冲印批次号", code: "JD-DEMO-LOVE-01", nextHint: "下一枚藏在一页不该有压痕的旧书里。", disclaimer: "演示礼包码，无实际面值，暂不可兑换。" },
  { chapterId: "chapter2", sourceSceneId: "after-gate", prop: "处分通知的档案编号", code: "JD-DEMO-NAMES-02", nextHint: "下一枚字符，跟着一张只写目的地的行李牌。", disclaimer: "演示礼包码，无实际面值，暂不可兑换。" },
  { chapterId: "chapter3", sourceSceneId: "echo-three", prop: "单程行李牌背面的字符", code: "JD-DEMO-ROAD-03", nextHint: "下一枚不在一座城市里。找两处相同的时间。", disclaimer: "演示礼包码，无实际面值，暂不可兑换。" },
  { chapterId: "chapter4", sourceSceneId: "last-email", prop: "未发送邮件的系统元数据", code: "JD-DEMO-CITIES-04", nextHint: "最后一枚藏在一杯茶和两张旧纸之间。", disclaimer: "演示礼包码，无实际面值，暂不可兑换。" },
  { chapterId: "chapter5", sourceSceneId: "crossroads", prop: "咖啡小票底部的纪念编码", code: "JD-DEMO-MEMORY-05", nextHint: "5/5。终章纪念礼物待解锁。", disclaimer: "演示礼包码，无实际面值，暂不可兑换。" },
];

export interface ChapterContract {
  id: ChapterId;
  label: string;
  emotionalTask: string;
  coreInteractionId: string;
  endSceneId: string;
  completionMemory: number;
  nextTeaser: string;
  revisitChange: string;
}

export const chapterContracts: readonly ChapterContract[] = [
  { id: "chapter1", label: "第一章 · 革命街上的恋人", emotionalTask: "相信他们曾经真的幸福。", coreInteractionId: "projector-repair", endSceneId: "promise", completionMemory: 3, nextTeaser: "学校会问：谁和你一起做了刊物？", revisitChange: "投影里会多出你上轮保存的第一个动作。" },
  { id: "chapter2", label: "第二章 · 知识变成证据", emotionalTask: "看见分开并非不爱。", coreInteractionId: "names-decision", endSceneId: "after-gate", completionMemory: 3, nextTeaser: "一张单程行李牌正在等她签字。", revisitChange: "处分记录会按她当年的回答改变。" },
  { id: "chapter3", label: "第三章 · 只有一个人能够离开", emotionalTask: "亲手完成一次遗憾。", coreInteractionId: "airport-goodbye", endSceneId: "echo-three", completionMemory: 3, nextTeaser: "两座城市会在同一天留下相同编号。", revisitChange: "机场会记住你松手的时刻。" },
  { id: "chapter4", label: "第四章 · 两个城市", emotionalTask: "看见两人都保留着同一段记忆。", coreInteractionId: "email-draft", endSceneId: "last-email", completionMemory: 3, nextTeaser: "咖啡馆里，有人带来了另一张照片。", revisitChange: "被删掉的句子会以残影重新出现。" },
  { id: "chapter5", label: "第五章 · 伊斯坦布尔重逢", emotionalTask: "让重逢成为迟到十三年的回答。", coreInteractionId: "photo-pairing", endSceneId: "crossroads", completionMemory: 3, nextTeaser: "完整卷宗与特别尾声等待显影。", revisitChange: "桌面会尊重你最初放置照片的方向。" },
];

export function firstRunRequiredMemory(): number {
  const interactionMemory = firstRunRequiredInteractions().reduce((sum, item) => sum + item.memoryGain, 0);
  return interactionMemory + chapterContracts.reduce((sum, chapter) => sum + chapter.completionMemory, 0);
}

export function fullCollectionMemory(): number {
  const interactionMemory = interactionCatalog.reduce((sum, item) => sum + item.memoryGain, 0);
  return interactionMemory + chapterContracts.reduce((sum, chapter) => sum + chapter.completionMemory, 0);
}

export const interactionById = Object.fromEntries(interactionCatalog.map(item => [item.id, item])) as Record<string, InteractionContract>;
export const interactionsByScene = interactionCatalog.reduce<Record<string, InteractionContract[]>>((result, item) => {
  (result[item.sceneId] ||= []).push(item); return result;
}, {});
export const paidDialogueById = Object.fromEntries(paidDialogues.map(item => [item.id, item])) as Record<PaidDialogueId, PaidDialogueContract>;
export const paidDialogueByScene = Object.fromEntries(paidDialogues.map(item => [item.anchorSceneId, item])) as Record<string, PaidDialogueContract>;
export const chapterRewardById = Object.fromEntries(chapterRewards.map(item => [item.chapterId, item])) as Record<ChapterId, ChapterRewardContract>;
export const chapterContractById = Object.fromEntries(chapterContracts.map(item => [item.id, item])) as Record<ChapterId, ChapterContract>;
export const chapterEndByScene = Object.fromEntries(chapterContracts.map(item => [item.endSceneId, item.id])) as Record<string, ChapterId>;

export type MemoryTier = "base" | "inner" | "details" | "preview" | "archive";
export const memoryTierLabels: Record<MemoryTier, string> = {
  base: "基础剧情", inner: "内心独白", details: "场景细节与纪念物", preview: "隐藏对白预览", archive: "完整记忆卷宗与特别尾声",
};
export function clampMemory(value: number) { return Math.max(0, Math.min(100, Math.round(value || 0))); }
export function memoryTier(value: number): MemoryTier {
  const score = clampMemory(value);
  if (score >= 81) return "archive"; if (score >= 61) return "preview"; if (score >= 41) return "details"; if (score >= 21) return "inner"; return "base";
}
export function nextMemoryUnlock(value: number): { threshold: 21 | 41 | 61 | 81; remaining: number; label: string } | null {
  const score = clampMemory(value);
  const next = ([21, 41, 61, 81] as const).find(threshold => score < threshold);
  return next ? { threshold: next, remaining: next - score, label: memoryTierLabels[memoryTier(next)] } : null;
}

export type RewardStatus = "locked" | "revealed" | "claimed";
export type ProductId = `dialogue:${PaidDialogueId}` | `chapter:${ChapterId}` | "full-pass";

export interface SimulatedPurchase {
  productId: ProductId;
  /** Legacy alias retained so existing save readers continue to understand the listed price. */
  priceFen: number;
  listPriceFen: number;
  creditFen: number;
  payableFen: number;
  at: number;
  provider: "local-demo";
}
export interface ProgressionState {
  memoryExposure: number; completedInteractionIds: string[]; discoveredClueIds: string[]; collectibleIds: string[];
  completedChapterIds: ChapterId[]; chapterRewards: Record<ChapterId, RewardStatus>;
  chapterMemory: Record<ChapterId, number>; axisValues: AxisValues;
}
export interface EntitlementState {
  directDialogues: PaidDialogueId[]; chapterPacks: ChapterId[]; fullPass: boolean; simulatedPurchases: SimulatedPurchase[];
}
export interface PaidContentState { impressionIds: PaidDialogueId[]; skippedIds: PaidDialogueId[]; completedIds: PaidDialogueId[]; }
export interface RevisitState {
  visitsByChapter: Partial<Record<ChapterId, number>>; dailyFragmentIds: string[]; lastDailyFragmentDate?: string;
  dailyFragmentClaimCount: number;
  specialEpilogue: "locked" | "available" | "viewed";
}
export interface DailyMemoryRecord {
  dateKey: string; rotationId: string; choices: string[]; previousChoices?: string[]; plays: number; completedAt: number;
}
export interface RomanceState {
  heartbeatIds: string[];
  favoriteHeartbeatId?: string;
  dailyMemoryRecords: DailyMemoryRecord[];
  unlockedMilestoneIds: string[];
}
export interface ProfileStateV6 {
  version: 6; progression: ProgressionState; entitlements: EntitlementState; paidContent: PaidContentState;
  revisit: RevisitState; romance: RomanceState; firstPlayedAt: number; lastSeenAt: number;
}
const rewardStatuses=():Record<ChapterId,RewardStatus>=>({chapter1:"locked",chapter2:"locked",chapter3:"locked",chapter4:"locked",chapter5:"locked"});
const emptyChapterMemory=():Record<ChapterId,number>=>({chapter1:0,chapter2:0,chapter3:0,chapter4:0,chapter5:0});
export function createInitialProfile(now=Date.now()):ProfileStateV6 {
  return {
    version:6,
    progression:{memoryExposure:0,completedInteractionIds:[],discoveredClueIds:[],collectibleIds:[],completedChapterIds:[],chapterRewards:rewardStatuses(),chapterMemory:emptyChapterMemory(),axisValues:{speak:0,keep:0,survive:0}},
    entitlements:{directDialogues:[],chapterPacks:[],fullPass:false,simulatedPurchases:[]},
    paidContent:{impressionIds:[],skippedIds:[],completedIds:[]},
    revisit:{visitsByChapter:{},dailyFragmentIds:[],dailyFragmentClaimCount:0,specialEpilogue:"locked"},
    romance:{heartbeatIds:[],dailyMemoryRecords:[],unlockedMilestoneIds:[]},
    firstPlayedAt:now,lastSeenAt:now,
  };
}
function unique<T>(items:T[]){return Array.from(new Set(items))}
function normalizeChapterRecord<T>(value:Partial<Record<ChapterId,T>>|undefined,fallback:()=>Record<ChapterId,T>){return{...fallback(),...(value||{})}}
function normalizeDailyFragmentId(id:string):string {
  const legacyIndex=Number(id);
  if(!Number.isInteger(legacyIndex)||String(legacyIndex)!==id)return id;
  return dailyFragmentEntries[legacyIndex]?.id||id;
}
function normalizeSimulatedPurchase(item:SimulatedPurchase):SimulatedPurchase {
  const legacyPrice=Number.isFinite(item.priceFen)?item.priceFen:priceForProduct(item.productId);
  const listPriceFen=Math.max(0,Math.round(Number.isFinite(item.listPriceFen)?item.listPriceFen:legacyPrice));
  const creditFen=Math.min(listPriceFen,Math.max(0,Math.round(Number.isFinite(item.creditFen)?item.creditFen:0)));
  const payableFen=Math.min(listPriceFen,Math.max(0,Math.round(Number.isFinite(item.payableFen)?item.payableFen:listPriceFen-creditFen)));
  return{...item,priceFen:listPriceFen,listPriceFen,creditFen,payableFen,provider:"local-demo"};
}
export function normalizeProfile(input:Partial<ProfileStateV6>|null|undefined,now=Date.now()):ProfileStateV6 {
  const base=createInitialProfile(now); if(!input||typeof input!=="object")return base;
  const progression=input.progression||base.progression; const entitlements=input.entitlements||base.entitlements;
  const paidContent=input.paidContent||base.paidContent; const revisit=input.revisit||base.revisit; const romance=input.romance||base.romance;
  const heartbeatIds=unique((romance.heartbeatIds||[]).filter(id=>["hands","arrival","pomegranate"].includes(id)));
  const dailyMemoryRecords=(romance.dailyMemoryRecords||[]).filter(record=>record&&typeof record.dateKey==="string"&&Array.isArray(record.choices)).map(record=>({...record,choices:[...record.choices],previousChoices:record.previousChoices?[...record.previousChoices]:undefined,plays:Math.max(1,Math.floor(record.plays||1)),completedAt:Number.isFinite(record.completedAt)?record.completedAt:now}));
  return {
    version:6,
    progression:{...base.progression,...progression,memoryExposure:clampMemory(progression.memoryExposure||0),completedInteractionIds:unique(progression.completedInteractionIds||[]),discoveredClueIds:unique(progression.discoveredClueIds||[]),collectibleIds:unique(progression.collectibleIds||[]),completedChapterIds:unique((progression.completedChapterIds||[]).filter(id=>chapterIds.includes(id))),chapterRewards:normalizeChapterRecord(progression.chapterRewards,rewardStatuses),chapterMemory:normalizeChapterRecord(progression.chapterMemory,emptyChapterMemory),axisValues:{...base.progression.axisValues,...(progression.axisValues||{})}},
    entitlements:{...base.entitlements,...entitlements,directDialogues:unique(entitlements.directDialogues||[]),chapterPacks:unique(entitlements.chapterPacks||[]),simulatedPurchases:(entitlements.simulatedPurchases||[]).map(normalizeSimulatedPurchase)},
    paidContent:{impressionIds:unique(paidContent.impressionIds||[]),skippedIds:unique(paidContent.skippedIds||[]),completedIds:unique(paidContent.completedIds||[])},
    revisit:{...base.revisit,...revisit,visitsByChapter:revisit.visitsByChapter||{},dailyFragmentIds:unique((revisit.dailyFragmentIds||[]).map(normalizeDailyFragmentId)),dailyFragmentClaimCount:Number.isFinite(revisit.dailyFragmentClaimCount)?Math.max(0,Math.floor(revisit.dailyFragmentClaimCount)):unique(revisit.dailyFragmentIds||[]).length},
    romance:{heartbeatIds,favoriteHeartbeatId:heartbeatIds.includes(romance.favoriteHeartbeatId||"")?romance.favoriteHeartbeatId:heartbeatIds.at(-1),dailyMemoryRecords,unlockedMilestoneIds:[{days:1,id:"first-return"},{days:3,id:"three-weather"},{days:5,id:"five-returns"}].filter(item=>new Set(dailyMemoryRecords.map(record=>record.dateKey)).size>=item.days).map(item=>item.id)},
    firstPlayedAt:input.firstPlayedAt||now,lastSeenAt:input.lastSeenAt||now,
  };
}
export function setAxisValues(profile:ProfileStateV6,axisValues:AxisValues):ProfileStateV6 {
  return{...profile,progression:{...profile.progression,axisValues:{...axisValues}}};
}
export interface ProgressMutation { profile:ProfileStateV6; changed:boolean; memoryGained:number; }
export function completeInteraction(profile:ProfileStateV6,interactionId:string):ProgressMutation {
  const contract=interactionById[interactionId];
  if(!contract||profile.progression.completedInteractionIds.includes(interactionId))return{profile,changed:false,memoryGained:0};
  const progression=profile.progression; const memoryExposure=clampMemory(progression.memoryExposure+contract.memoryGain);
  return{changed:true,memoryGained:memoryExposure-progression.memoryExposure,profile:{...profile,progression:{...progression,memoryExposure,completedInteractionIds:[...progression.completedInteractionIds,interactionId],discoveredClueIds:contract.clue?unique([...progression.discoveredClueIds,contract.clue.id]):progression.discoveredClueIds,collectibleIds:contract.collectible?unique([...progression.collectibleIds,contract.collectible.id]):progression.collectibleIds,chapterMemory:{...progression.chapterMemory,[contract.chapterId]:progression.chapterMemory[contract.chapterId]+contract.memoryGain}}}};
}
export function revealChapterReward(profile:ProfileStateV6,chapterId:ChapterId):ProfileStateV6 {
  if(profile.progression.chapterRewards[chapterId]!=="locked")return profile;
  return{...profile,progression:{...profile.progression,chapterRewards:{...profile.progression.chapterRewards,[chapterId]:"revealed"}}};
}
export function claimChapterReward(profile:ProfileStateV6,chapterId:ChapterId):ProfileStateV6 {
  if(profile.progression.chapterRewards[chapterId]==="claimed")return profile;
  return{...profile,progression:{...profile.progression,chapterRewards:{...profile.progression.chapterRewards,[chapterId]:"claimed"}}};
}
export function completeChapter(profile:ProfileStateV6,chapterId:ChapterId):ProgressMutation {
  if(profile.progression.completedChapterIds.includes(chapterId))return{profile:revealChapterReward(profile,chapterId),changed:false,memoryGained:0};
  const contract=chapterContractById[chapterId]; const memoryExposure=clampMemory(profile.progression.memoryExposure+contract.completionMemory);
  const completedChapterIds=[...profile.progression.completedChapterIds,chapterId];
  const specialEpilogue=completedChapterIds.length===5&&memoryExposure>=81?"available" as const:profile.revisit.specialEpilogue;
  const next=revealChapterReward({...profile,progression:{...profile.progression,memoryExposure,completedChapterIds,chapterMemory:{...profile.progression.chapterMemory,[chapterId]:profile.progression.chapterMemory[chapterId]+contract.completionMemory}},revisit:{...profile.revisit,specialEpilogue}},chapterId);
  return{profile:next,changed:true,memoryGained:memoryExposure-profile.progression.memoryExposure};
}

export const productPrices:Record<string,number>={"full-pass":990};
export function priceForProduct(productId:ProductId):number {
  if(productId==="full-pass")return 990; if(productId.startsWith("chapter:"))return 290; return 100;
}
export function hasDialogueAccess(entitlements:EntitlementState,dialogue:PaidDialogueContract):boolean {
  return entitlements.fullPass||entitlements.chapterPacks.includes(dialogue.chapterId)||entitlements.directDialogues.includes(dialogue.id);
}
/** A direct segment purchase reveals one continuation line; chapter/full products reveal the whole exchange. */
export function hasFullDialogueAccess(entitlements:EntitlementState,dialogue:PaidDialogueContract):boolean {
  return entitlements.fullPass||entitlements.chapterPacks.includes(dialogue.chapterId);
}
export function visibleDialogueLineCount(entitlements:EntitlementState,dialogue:PaidDialogueContract):number {
  if(hasFullDialogueAccess(entitlements,dialogue))return dialogue.lockedLines.length;
  return entitlements.directDialogues.includes(dialogue.id)?Math.min(1,dialogue.lockedLines.length):0;
}
export function simulateLocalPurchase(profile:ProfileStateV6,productId:ProductId,now=Date.now()):ProfileStateV6 {
  if(profile.entitlements.simulatedPurchases.some(item=>item.productId===productId))return profile;
  const pricing=computeUpgradeCredit(profile,productId);
  const purchase:SimulatedPurchase={productId,priceFen:pricing.paidFen,listPriceFen:pricing.paidFen,creditFen:pricing.creditFen,payableFen:pricing.displayFen,at:now,provider:"local-demo"};
  const entitlements={...profile.entitlements,directDialogues:[...profile.entitlements.directDialogues],chapterPacks:[...profile.entitlements.chapterPacks],simulatedPurchases:[...profile.entitlements.simulatedPurchases,purchase]};
  if(productId==="full-pass")entitlements.fullPass=true;
  else if(productId.startsWith("chapter:"))entitlements.chapterPacks=unique([...entitlements.chapterPacks,productId.slice(8) as ChapterId]);
  else entitlements.directDialogues=unique([...entitlements.directDialogues,productId.slice(9) as PaidDialogueId]);
  return{...profile,entitlements};
}
export function recommendOffer(profile:ProfileStateV6,dialogue:PaidDialogueContract):ProductId|null {
  if(hasFullDialogueAccess(profile.entitlements,dialogue))return null;
  if(profile.entitlements.directDialogues.includes(dialogue.id))return `chapter:${dialogue.chapterId}`;
  if(profile.progression.completedChapterIds.length>=2&&!profile.entitlements.fullPass)return"full-pass";
  return `dialogue:${dialogue.id}`;
}
export type PurchaseOfferScope = "next-line" | "chapter-dialogue" | "all-dialogues";
export interface PurchaseOffer {
  productId: ProductId;
  scope: PurchaseOfferScope;
  label: string;
  description: string;
  listPriceFen: number;
  creditFen: number;
  payableFen: number;
  recommended: boolean;
}

/** Returns every currently useful local-demo offer; recommendation never removes the lower-price choices. */
export function availablePurchaseOffers(profile:ProfileStateV6,dialogue:PaidDialogueContract):readonly PurchaseOffer[] {
  const recommendedProductId=recommendOffer(profile,dialogue);
  const candidates:ProductId[]=[];
  if(!hasDialogueAccess(profile.entitlements,dialogue))candidates.push('dialogue:'+dialogue.id as ProductId);
  if(!profile.entitlements.fullPass&&!profile.entitlements.chapterPacks.includes(dialogue.chapterId))candidates.push('chapter:'+dialogue.chapterId as ProductId);
  if(!profile.entitlements.fullPass)candidates.push("full-pass");
  return candidates.map((productId):PurchaseOffer=>{
    const pricing=computeUpgradeCredit(profile,productId);
    if(productId==="full-pass")return{productId,scope:"all-dialogues",label:"五章隐藏对白通行证",description:"在剧情抵达时显影五章隐藏对白。",listPriceFen:pricing.paidFen,creditFen:pricing.creditFen,payableFen:pricing.displayFen,recommended:productId===recommendedProductId};
    if(productId.startsWith("chapter:"))return{productId,scope:"chapter-dialogue",label:"本章完整对话",description:"补齐本章当前对话的全部剩余句子。",listPriceFen:pricing.paidFen,creditFen:pricing.creditFen,payableFen:pricing.displayFen,recommended:productId===recommendedProductId};
    return{productId,scope:"next-line",label:"显影下一句",description:"只续接当前隐藏对白的下一句。",listPriceFen:pricing.paidFen,creditFen:pricing.creditFen,payableFen:pricing.displayFen,recommended:productId===recommendedProductId};
  });
}

export function computeUpgradeCredit(profile:ProfileStateV6,target:ProductId):{paidFen:number;creditFen:number;displayFen:number}{
  const paidFen=priceForProduct(target); let creditFen=0;
  if(target==="full-pass"){
    const packedChapters=new Set(profile.entitlements.chapterPacks);
    const uncoveredDirectDialogues=new Set(profile.entitlements.directDialogues.filter(id=>!packedChapters.has(paidDialogueById[id]?.chapterId)));
    creditFen=packedChapters.size*290+uncoveredDirectDialogues.size*100;
  }else if(target.startsWith("chapter:")){
    const chapterId=target.slice(8) as ChapterId;
    creditFen=new Set(profile.entitlements.directDialogues.filter(id=>paidDialogueById[id]?.chapterId===chapterId)).size*100;
  }
  creditFen=Math.min(paidFen,creditFen); return{paidFen,creditFen,displayFen:Math.max(0,paidFen-creditFen)};
}
export function markPaidImpression(profile:ProfileStateV6,id:PaidDialogueId):ProfileStateV6 {
  if(profile.paidContent.impressionIds.includes(id))return profile;
  return{...profile,paidContent:{...profile.paidContent,impressionIds:[...profile.paidContent.impressionIds,id]}};
}
export function markPaidSkipped(profile:ProfileStateV6,id:PaidDialogueId):ProfileStateV6 {
  return{...profile,paidContent:{...profile.paidContent,skippedIds:unique([...profile.paidContent.skippedIds,id])}};
}
export function markPaidComplete(profile:ProfileStateV6,id:PaidDialogueId):ProfileStateV6 {
  return{...profile,paidContent:{...profile.paidContent,completedIds:unique([...profile.paidContent.completedIds,id]),skippedIds:profile.paidContent.skippedIds.filter(item=>item!==id)}};
}
export interface ChapterSummary {
  chapterId:ChapterId; memoryEarned:number; collectibleIds:string[]; clueCount:number; lockedPaidCount:number;
  remainingDialogueLines:number; rewardStatus:RewardStatus; nextTeaser:string;
}
export function buildChapterSummary(profile:ProfileStateV6,chapterId:ChapterId):ChapterSummary {
  const contracts=interactionCatalog.filter(item=>item.chapterId===chapterId);
  const collectibleIds=contracts.flatMap(item=>item.collectible&&profile.progression.collectibleIds.includes(item.collectible.id)?[item.collectible.id]:[]);
  const clueCount=contracts.filter(item=>item.clue&&profile.progression.discoveredClueIds.includes(item.clue.id)).length;
  const chapterDialogues=paidDialogues.filter(item=>item.chapterId===chapterId);
  const lockedPaidCount=chapterDialogues.filter(item=>!hasFullDialogueAccess(profile.entitlements,item)).length;
  const remainingDialogueLines=chapterDialogues.reduce((total,item)=>total+Math.max(0,item.lockedLines.length-visibleDialogueLineCount(profile.entitlements,item)),0);
  return{chapterId,memoryEarned:profile.progression.chapterMemory[chapterId],collectibleIds,clueCount,lockedPaidCount,remainingDialogueLines,rewardStatus:profile.progression.chapterRewards[chapterId],nextTeaser:chapterContractById[chapterId].nextTeaser};
}
export function claimedRewardIds(profile:ProfileStateV6):ChapterId[]{
  return chapterIds.filter(id=>profile.progression.chapterRewards[id]==="claimed");
}
export const dailyFragmentEntries=[
  {id:"kamran-kitchen-photo",text:"卡姆兰把新洗的照片晾在厨房。他总把女生选中的那张放在最前面。"},
  {id:"mariam-meteor-probability",text:"玛丽亚姆记下今晚流星出现的概率。男生替她把望远镜又校准了一次。"},
  {id:"maziya-library-poetry",text:"玛兹雅在儿童图书馆修补一本缺页的诗集。她没有再问女生当年在问话室里说了什么。"},
  {id:"leila-arrival-message",text:"女生在机场落地后给卡姆兰发了一句：我到了。这一次，消息成功送达。"},
  {id:"arash-bus-tickets",text:"男生把两张旧公交票换到新书里。纸边碎了一点，目的地仍在。"},
] as const;
export const dailyFragments= dailyFragmentEntries.map(entry=>entry.text);

export interface DailyFragmentPreview {
  fragment?:string;
  fragmentId?:string;
  available:boolean;
}

/** Reads today's next fragment without consuming it; only claimDailyFragment mutates the profile. */
export function previewDailyFragment(profile:ProfileStateV6,dateKey:string):DailyFragmentPreview {
  if(profile.revisit.lastDailyFragmentDate===dateKey)return{available:false};
  const claimCount=Math.max(0,profile.revisit.dailyFragmentClaimCount||0);
  const entry=dailyFragmentEntries[claimCount%dailyFragmentEntries.length];
  return entry?{available:true,fragment:entry.text,fragmentId:entry.id}:{available:false};
}

export function claimDailyFragment(profile:ProfileStateV6,dateKey:string):{profile:ProfileStateV6;fragment?:string;fragmentId?:string;changed:boolean}{
  const preview=previewDailyFragment(profile,dateKey);
  if(!preview.available||!preview.fragment||!preview.fragmentId)return{profile,changed:false};
  const claimCount=Math.max(0,profile.revisit.dailyFragmentClaimCount||0);
  return{changed:true,fragment:preview.fragment,fragmentId:preview.fragmentId,profile:{...profile,revisit:{...profile.revisit,lastDailyFragmentDate:dateKey,dailyFragmentClaimCount:claimCount+1,dailyFragmentIds:unique([...profile.revisit.dailyFragmentIds,preview.fragmentId])}}};
}
export function markChapterRevisit(profile:ProfileStateV6,chapterId:ChapterId):ProfileStateV6 {
  const count=profile.revisit.visitsByChapter[chapterId]||0;
  return{...profile,revisit:{...profile.revisit,visitsByChapter:{...profile.revisit.visitsByChapter,[chapterId]:count+1}}};
}
export function markSpecialEpilogueViewed(profile:ProfileStateV6):ProfileStateV6 {
  if(profile.revisit.specialEpilogue==="locked")return profile;
  return{...profile,revisit:{...profile.revisit,specialEpilogue:"viewed"}};
}
export function chapterMemoryGain(profile:ProfileStateV6,chapterId:string):number {
  return chapterIds.includes(chapterId as ChapterId)?profile.progression.chapterMemory[chapterId as ChapterId]:0;
}
export function unresolvedDialogueCount(profile:ProfileStateV6):number {
  return paidDialogues.reduce((total,item)=>total+Math.max(0,item.lockedLines.length-visibleDialogueLineCount(profile.entitlements,item)),0);
}
