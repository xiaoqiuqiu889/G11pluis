// =============================================================================
// 革命街没有尽头 · 视角暗示（决策 2 关键）
// -----------------------------------------------------------------------------
// 免费样章里**暗示**其他视角存在，但**不给**。
// 例：「莱拉的角度是另一个故事。」
// 例：「阿拉什在灯下没有看镜头。他看的方向——那是一段你还没有的视角。」
// 暗示出现时机：
//   1. 关键节点（如阿拉什转过身去时）
//   2. 决定之后 4-6 秒
//   3. 场景结尾过渡
// ============================================================================

import { useEffect, useState } from "react";
import { useStore } from "@/lib/store";
import type { POVMode } from "@/lib/store";

const HINT_LIBRARY: Record<POVMode, string[]> = {
  observer: [
    // 不暗示
  ],
  leila: [
    "（莱拉的角度是另一个故事——她的手在找一样东西的边角时，心里的温度和此刻不一样。）",
    "（如果你是莱拉，那张牛皮纸袋里的气味会带你回某个具体的下午。）",
    "（她没有说出来的那一句，要从她的角度才听得见。）",
  ],
  // W12: case_02 人物占位（决策 2 暗示规则同样适用）
  natasha_roschina: [
    "（娜塔莎的角度是另一个故事——Petrof 大提琴松香渍在她左手食指指节，她没在看你。）",
    "（如果你是娜塔莎，305 琴房的延音踏板会带你回某个具体的 1985-11 排练夜。）",
  ],
  ilya_berman: [
    "（伊利亚的角度是另一个故事——红色笔记本第 1 页是 И. Б. 圈注，他没在合上。）",
    "（如果你是伊利亚，铅笔在总谱上画的那三小节他自己也说不清为什么。）",
  ],
  sasha_kuzmin: [
    "（萨沙在塔甘卡衣帽间把手放在娜塔莎肩上时，鸭舌帽下他没看她的手——他看的是挂钟。）",
  ],
  lisa_hoffmann: [
    "（莉莎在 SVO-2 候机区拨盘电话时，红金色长发挡住了脸——她问还是不问，是另一段故事。）",
  ],
  arash: [
    "（阿拉什在灯下没有看镜头。他看的方向——那是一段你还没有的视角。）",
    "（如果你是阿拉什，你会先听见放映机的低频，再听见自己心跳。）",
    "（他把工具盒盖合上的那一下——那是从他那一侧才听得见的声音。）",
  ],
  kamran: [
    "（卡姆兰不在这一夜的地下放映室。他在另一个时区、另一段你尚未打开的叙事里。）",
    "（他的画面直到第二个本子才出现——现在还只是一段没有被许可的视角。）",
  ],
  maryam: [
    "（玛丽亚姆记录过的每一个夜晚，都是从一个屋顶开始的。）",
    "（她的视角像天文台——是另一种坐标。）",
  ],
};

export interface ObserverHintProps {
  /** 触发条件（基于场景事件类型） */
  trigger: "after_choice" | "scene_end" | "critical_moment" | "manual";
  /** 指定暗示哪个视角 */
  pov?: POVMode;
  /** 多久后显示（ms） */
  delayMs?: number;
  /** 手动控制 */
  onShow?: () => void;
}

export function ObserverHint({ trigger, pov = "leila", delayMs = 2400, onShow }: ObserverHintProps) {
  const unlockedPOVs = useStore((s) => s.unlockedPOVs);
  const povMode = useStore((s) => s.povMode);
  const [visible, setVisible] = useState(false);
  const [text, setText] = useState("");

  useEffect(() => {
    // 决策 2：默认不暗示已解锁视角；当前已切到的视角也不暗示
    if (unlockedPOVs.includes(pov)) return;
    if (povMode === pov) return;

    const pool = HINT_LIBRARY[pov];
    if (!pool || pool.length === 0) return;

    const t = window.setTimeout(() => {
      setText(pool[Math.floor(Math.random() * pool.length)]);
      setVisible(true);
      onShow?.();
    }, delayMs);

    return () => window.clearTimeout(t);
  }, [trigger, pov, delayMs, unlockedPOVs, povMode, onShow]);

  if (!visible) return null;
  return (
    <div
      className="pov-hint mx-auto my-4 max-w-2xl animate-fade-in"
      role="note"
      aria-label="未解锁视角的暗示"
    >
      <span className="t-italic">{text}</span>
      <span className="block mt-1 text-[10px] tracking-widest text-amber-glow/70 uppercase">
        ✶ 来自 {pov} 的视角
      </span>
    </div>
  );
}

/** 一次性暗示触发器（用作父组件控制） */
export function useHintTrigger() {
  const [trigger, setTrigger] = useState<{ pov: POVMode; key: number } | null>(null);
  const fire = (pov: POVMode = "leila") => setTrigger({ pov, key: Date.now() });
  return { trigger, fire };
}
