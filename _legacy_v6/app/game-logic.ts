export type Axis = "speak" | "keep" | "survive";
export type EndingKey = Axis | "mixed";
export type Scores = Record<Axis, number>;

export type AnswerRecord = {
  choiceId: string;
  optionId: string;
  label: string;
  axis: Axis;
  /** V5: 当场动作与感官确认独立保存；可选以兼容旧存档。 */
  action?: string;
  confirmation?: string;
  memory: string;
  motif: string;
  sound: string;
  nearEcho: string;
  farEcho: string;
  endingFragment: string;
  revisitEcho: string;
};

export type ResonanceRecord = {
  resonanceId: string;
  optionId: string;
  label: string;
  motif: string;
  /** V5: echo 保留为旧存档兼容字段，新的远期路由读取 farEcho。 */
  action?: string;
  confirmation?: string;
  echo: string;
  farEcho?: string;
  endingFragment: string;
  sound: string;
};

export const emptyScores = (): Scores => ({ speak: 0, keep: 0, survive: 0 });

export function scoreAnswers(answers: Record<string, AnswerRecord>): Scores {
  return Object.values(answers).reduce((scores, answer) => {
    scores[answer.axis] += 1;
    return scores;
  }, emptyScores());
}

export function determineEnding(scores: Scores): EndingKey {
  const entries = Object.entries(scores) as [Axis, number][];
  const highest = Math.max(...entries.map(([, value]) => value));
  const leaders = entries.filter(([, value]) => value === highest);
  return leaders.length === 1 ? leaders[0][0] : "mixed";
}

const axisList: Axis[] = ["speak", "keep", "survive"];

/**
 * 返回明确的次轴；如果剩余两轴同分，则回到主轴自身，代表这一轮没有
 * 被数组顺序虚构出来的“第二倾向”。mixed 不需要次轴。
 */
export function determineSecondaryAxis(scores: Scores, endingKey: EndingKey): Axis | null {
  if (endingKey === "mixed") return null;
  const candidates = axisList.filter((axis) => axis !== endingKey);
  const [left, right] = candidates;
  if (scores[left] === scores[right]) return endingKey;
  return scores[left] > scores[right] ? left : right;
}

const primaryOpenings: Record<EndingKey, string> = {
  speak: "绿灯亮时，她记得自己曾把最难的话说完。",
  keep: "绿灯亮时，她摸到被留下之物的硬边。",
  survive: "绿灯亮时，她先确认机场方向与回程时间。",
  mixed: "绿灯亮时，诗页、出口与未说完的话同时留在画面里。她没有让一种记忆替另外两种作证。",
};

/** 主轴×次轴反题；同轴项用于三次一致选择，不伪造不存在的少数派动作。 */
const axisPairCounterpoints: Record<Axis, Record<Axis, string>> = {
  speak: {
    speak: "真话抵达了，仍没能替他们决定去向。",
    keep: "真话抵达时，仍有一页纸舍不得合上。",
    survive: "真话抵达时，回程时间也没有停下。",
  },
  keep: {
    speak: "留下的物件里，仍压着一句必须说出的真话。",
    keep: "留下的证据不要求他们回到原处。",
    survive: "她留住触感，也没有错过现实的出口。",
  },
  survive: {
    speak: "她向出口走，也没有把那句真话吞回去。",
    keep: "她向出口走，仍让一页旧纸留在身后。",
    survive: "离开不是胜利，只把下一程交回她手里。",
  },
};

function resonanceObjectClause(resonances: Record<string, ResonanceRecord>): string {
  const gaze = resonances.gaze?.optionId;
  if (gaze === "book") return "最后的焦点落在他臂弯里的旧诗集。";
  if (gaze === "clock") return "最后的焦点越过人群，停在机场方向牌。";
  if (gaze === "hands") return "最后的焦点停在他放开茶杯的手上。";
  const photo = resonances.photo?.optionId;
  if (photo === "front") return "糖罐旁的毕业照仍正面朝上。";
  if (photo === "back") return "糖罐旁只露出照片背面的日期。";
  if (photo === "bag") return "包里的毕业照顶着帆布。";
  const email = resonances.email?.optionId;
  if (email) return "删除过的邮件仍留着光标的节拍。";
  return "那张毕业照仍留在他们之间。";
}

const sharedRealityClosure =
  "过街后，女生把航班时间发给卡姆兰。男生回拨玛丽亚姆，问云会不会遮住流星。过去没有消失，眼前的生活也没有暂停。";

/**
 * 先给玩家一段电影尾声，再由界面按需展开测评信息。文本只使用本轮
 * 主次轴与已发生的共鸣物件，且稳定控制在 120 个汉字以内。
 */
export function composeCinematicEpilogue(
  endingKey: EndingKey,
  answers: Record<string, AnswerRecord>,
  resonances: Record<string, ResonanceRecord>,
): string {
  const scores = scoreAnswers(answers);
  const secondary = determineSecondaryAxis(scores, endingKey);
  const counterpoint = endingKey === "mixed" || secondary === null
    ? ""
    : axisPairCounterpoints[endingKey][secondary];
  return `${primaryOpenings[endingKey]}${counterpoint}${resonanceObjectClause(resonances)}${sharedRealityClosure}`;
}

export type FutureEchoRoute = {
  source: "choice" | "resonance";
  id: string;
  field: "farEcho";
};

/** 按配置兑现未来回响，并在逻辑层硬性限制单场最多两条。 */
export function resolveFutureEchoes(
  routes: FutureEchoRoute[] | undefined,
  answers: Record<string, AnswerRecord>,
  resonances: Record<string, ResonanceRecord>,
): string[] {
  if (!routes) return [];
  return routes.flatMap((route) => {
    const record = route.source === "choice" ? answers[route.id] : resonances[route.id];
    const value = record?.farEcho;
    return value ? [value] : [];
  }).slice(0, 2);
}

export function memoryStrength(value: number): "微弱" | "清晰" | "强烈" {
  if (value <= 1) return "微弱";
  if (value === 2) return "清晰";
  return "强烈";
}

export function composeEndingFragments(
  answers: Record<string, AnswerRecord>,
  resonances: Record<string, ResonanceRecord>,
  choiceOrder: string[],
  resonanceOrder: string[],
) {
  return [
    ...choiceOrder.flatMap((id) => answers[id]?.endingFragment ? [answers[id].endingFragment] : []),
    ...resonanceOrder.flatMap((id) => resonances[id]?.endingFragment ? [resonances[id].endingFragment] : []),
  ];
}

export function choiceDiff(
  previous: Record<string, AnswerRecord>,
  current: Record<string, AnswerRecord>,
  choiceIds: string[],
) {
  return choiceIds.map((choiceId) => ({
    choiceId,
    before: previous[choiceId] ?? null,
    after: current[choiceId] ?? null,
    changed: previous[choiceId]?.optionId !== current[choiceId]?.optionId,
    futureBefore: previous[choiceId]?.revisitEcho ?? "",
    futureAfter: current[choiceId]?.revisitEcho ?? "",
  }));
}

export function estimateMinimumActions(scenes: Array<{
  kind: string;
  body?: string[];
  progressive?: boolean;
}>) {
  return 1 + scenes.reduce((total, scene) => {
    let actions = 1;
    if (scene.kind === "choice" || scene.kind === "resonance") actions += 1;
    if (scene.kind === "montage") actions += 1;
    if (scene.progressive && scene.body) actions += Math.max(0, scene.body.length - 1);
    return total + actions;
  }, 0);
}


export function selectUnchosenFragments(
  fragments: Array<{ optionId: string; text: string }>,
  answers: Record<string, AnswerRecord>,
  resonances: Record<string, ResonanceRecord>,
  limit = 2,
) {
  const selected = new Set([
    ...Object.values(answers).map((answer) => answer.optionId),
    ...Object.values(resonances).map((resonance) => resonance.optionId),
  ]);
  return fragments.filter((fragment) => !selected.has(fragment.optionId)).slice(0, limit);
}
