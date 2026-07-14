export type HeartbeatId = "hands" | "arrival" | "pomegranate";

export interface HeartbeatMoment {
  id: HeartbeatId;
  label: string;
  action: string;
  response: string;
  nearEcho: string;
  endingFragment: string;
  motif: "机油" | "时间" | "石榴";
  sound: "paper" | "ticket" | "photo";
}

export const heartbeatMoments: readonly HeartbeatMoment[] = [
  {
    id: "hands",
    label: "替他擦掉机油",
    action: "女生用电影票背面，擦掉男生指节上的机油。",
    response: "他没有躲，只把沾脏的那一角折好，放回她掌心。",
    nearEcho: "后来每次修完机器，他都会先把手擦干净，再把伞柄递给她。",
    endingFragment: "她记得他的手：年轻时沾着机油，十三年后扶住发黄的书页。",
    motif: "机油",
    sound: "paper",
  },
  {
    id: "arrival",
    label: "记住他准时到达",
    action: "女生把电影票翻过来，在“20:03”旁写下：你到了。",
    response: "男生把表拨快三分钟：下次我会比你先到。",
    nearEcho: "从那以后，他每次迟到都会先报时间；她嘴上嫌他认真，还是会等。",
    endingFragment: "十三年后，他又发来“我到了”。她仍能想起那只被拨快三分钟的表。",
    motif: "时间",
    sound: "ticket",
  },
  {
    id: "pomegranate",
    label: "分给他半颗石榴",
    action: "女生掰开石榴，把更甜的那一半塞进男生的工具盒。",
    response: "他挑出一粒放到她舌尖：维修费要当面验收。",
    nearEcho: "屋顶的夜里，他们总把最后一粒石榴留给对方，直到谁也不肯先吃。",
    endingFragment: "咖啡馆没有石榴。她看见茶碟上的红糖，仍想起那粒被他递到唇边的甜。",
    motif: "石榴",
    sound: "photo",
  },
] as const;

export interface DailyRouteOption { id: string; label: string; line: string; }
export interface DailyRouteStep { id: "approach" | "keep" | "echo"; eyebrow: string; prompt: string; options: readonly DailyRouteOption[]; }
export interface DailyMemoryRotation {
  id: string;
  title: string;
  weather: string;
  subtitle: string;
  art: string;
  steps: readonly DailyRouteStep[];
  rewardFragment: string;
}

const approachOptions: readonly DailyRouteOption[] = [
  { id: "hands", label: "靠近他的手", line: "她先认出机油味，再认出那双替她扶过椅背的手。" },
  { id: "voice", label: "靠近他的声音", line: "停电以后，声音比面孔更早回到她身边。" },
  { id: "time", label: "靠近他的时间", line: "她记得他把表拨快三分钟，也记得他最终迟到了十三年。" },
];
const keepOptions: readonly DailyRouteOption[] = [
  { id: "poem", label: "留下折诗", line: "纸沿旧折痕合上，像一句仍知道去处的话。" },
  { id: "photo", label: "留下照片", line: "两张同版照片隔着城市，边角各自变旧。" },
  { id: "ticket", label: "留下车票", line: "目的地已经作废，纸上的时间仍然清楚。" },
];
const echoOptions: readonly DailyRouteOption[] = [
  { id: "rain", label: "让雨声回来", line: "伞沿一响，两个人同时想起那句“别松手”。" },
  { id: "projector", label: "让放映机回来", line: "齿轮重新咬合，银幕替他们保存了一秒靠近。" },
  { id: "airport", label: "让机场广播回来", line: "航班准时起飞，没说完的话仍在候机厅里。" },
];

const rotationSeeds = [
  ["雨夜显影", "雨水把触觉留得更久", "雨声让手比语言更早想起彼此。", "/art-v3/tehran-rooftop.png", "他后来买伞，总会先检查伞柄会不会打滑。"],
  ["停电显影", "看不见时，声音会靠近", "把灯关掉一次，重剪他们在黑暗里认出对方的方式。", "/art-v4/underground-projector-close.png", "她在圣何塞听见机器停转，仍会等半秒再开灯。"],
  ["纸页显影", "折痕、日期与没寄出的句子", "今天只看纸留下的证词。", "/art-v5/poetry-book-photo-close.png", "他换过三次工具盒，最旧的纸片从没换位置。"],
  ["到达显影", "每一次“我到了”都不相同", "从地下室到咖啡馆，重新安排一次抵达。", "/art-v5/istanbul-reunion-aged.png", "她关掉手机前，仍会确认最后一条消息有没有送达。"],
  ["石榴显影", "甜味比解释停留得更久", "让一件微小的食物承担今天的记忆。", "/art-v3/tehran-rooftop.png", "他们后来都学会剥石榴，只是不再把最后一粒留在盘里。"],
  ["两城显影", "同一段时间，两种清晨", "在德黑兰与圣何塞之间剪出一条看不见的线。", "/art-v5/san-jose-arrival-2011.png", "两个城市的钟从未一致，某些习惯却在同一刻发生。"],
  ["回程显影", "出口、时钟与眼前的生活", "今天不问如果，只重剪他们怎样回到各自生活。", "/art-v5/istanbul-crossroads-aged.png", "过街以后，两个人都先给正在等自己的人发了消息。"],
] as const;

export const dailyMemoryRotations: readonly DailyMemoryRotation[] = rotationSeeds.map(([title, weather, subtitle, art, rewardFragment], index) => ({
  id: `rotation-${index + 1}`,
  title,
  weather,
  subtitle,
  art,
  steps: [
    { id: "approach", eyebrow: "01 · 靠近", prompt: "今天，你先从哪里靠近男生？", options: approachOptions },
    { id: "keep", eyebrow: "02 · 留下", prompt: "从两个人的一生里，只留下一个物件。", options: keepOptions },
    { id: "echo", eyebrow: "03 · 回声", prompt: "让哪一种声音把这段记忆送回现在？", options: echoOptions },
  ],
  rewardFragment,
}));

export interface DailyMemoryRecord {
  dateKey: string;
  rotationId: string;
  choices: string[];
  previousChoices?: string[];
  plays: number;
  completedAt: number;
}

function dateOrdinal(dateKey: string): number {
  const [year, month, day] = dateKey.split("-").map(Number);
  const value = Date.UTC(year || 1970, Math.max(0, (month || 1) - 1), day || 1);
  return Math.floor(value / 86_400_000);
}

export function rotationForDate(dateKey: string): DailyMemoryRotation {
  const index = ((dateOrdinal(dateKey) % dailyMemoryRotations.length) + dailyMemoryRotations.length) % dailyMemoryRotations.length;
  return dailyMemoryRotations[index];
}

export function heartbeatState(count: number): "初见" | "熟悉" | "牵挂" | "难忘" {
  if (count <= 0) return "初见";
  if (count === 1) return "熟悉";
  if (count === 2) return "牵挂";
  return "难忘";
}

export function composeDailyRouteLines(rotation: DailyMemoryRotation, choiceIds: readonly string[]): string[] {
  return rotation.steps.map((step, index) => step.options.find(option => option.id === choiceIds[index])?.line).filter((line): line is string => Boolean(line));
}

export function upsertDailyMemoryRecord(records: readonly DailyMemoryRecord[], dateKey: string, choiceIds: readonly string[], completedAt = Date.now()): { records: DailyMemoryRecord[]; firstCompletion: boolean; record: DailyMemoryRecord } {
  const rotation = rotationForDate(dateKey);
  const existing = records.find(record => record.dateKey === dateKey);
  const record: DailyMemoryRecord = existing
    ? { ...existing, rotationId: rotation.id, previousChoices: [...existing.choices], choices: [...choiceIds], plays: existing.plays + 1, completedAt }
    : { dateKey, rotationId: rotation.id, choices: [...choiceIds], plays: 1, completedAt };
  return { records: [...records.filter(item => item.dateKey !== dateKey), record], firstCompletion: !existing, record };
}

export const dailyMemoryMilestones = [
  { days: 1, id: "first-return", label: "第一次回来", fragment: "他记得她扶住片门时，先把袖口卷了两折。" },
  { days: 3, id: "three-weather", label: "三种天气", fragment: "她记得他的笑不是突然发生的：总在机器终于运转以后。" },
  { days: 5, id: "five-returns", label: "五次显影", fragment: "他们没有多出一种结局，只多了几种被认真爱过的证据。" },
] as const;

export function unlockedDailyMilestones(records: readonly DailyMemoryRecord[]) {
  const days = new Set(records.map(record => record.dateKey)).size;
  return dailyMemoryMilestones.filter(milestone => days >= milestone.days);
}
