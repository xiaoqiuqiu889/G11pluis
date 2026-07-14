// =============================================================================
// 革命街没有尽头 · 付费商品（决策 4 商业化档位）
// -----------------------------------------------------------------------------
// 红线：所有付费点必须从「已结束 / 已解锁」状态触发，不在主线中段。
// ============================================================================

import type { Product, ProductId, RunState } from "@/types/schemas";

export const PRODUCTS: Product[] = [
  {
    id: "passport",
    name: "案件通行证",
    priceCents: 2500,
    description: "纵切片完整三场景 + 2 次重演 + 200 积分。",
    includes: [
      "完整三场景（不受 5 分钟缩略限制）",
      "2 次平行演算（重演）",
      "200 主调用积分",
      "基础卷宗（记忆账本 / 因果种子）",
    ],
    availableFromState: ["scene_ended", "act_ended", "run_ended"],
    unavailableDuring: [],
    cta: "进入案件",
    iconKey: "passport",
  },
  {
    id: "collectors",
    name: "收藏版",
    priceCents: 4800,
    description: "完整三场景 + 双视角 + 原声 + 私人终章 + 500 积分。",
    includes: [
      "完整三场景（无任何缩略）",
      "解锁两个角色视角（莱拉 + 阿拉什）",
      "Dastgah-e Shur 原声音轨",
      "私人终章（根据本局时间线生成）",
      "500 主调用积分",
      "5 次平行演算",
    ],
    availableFromState: ["act_ended", "run_ended"],
    unavailableDuring: [],
    cta: "升级收藏版",
    iconKey: "collectors",
  },
  {
    id: "parallel_ops",
    name: "平行演算包",
    priceCents: 1200,
    description: "5 次额外重演，回到任何一个事件节点。",
    includes: [
      "5 次平行演算次数",
      "可与已购买通行证叠加",
    ],
    availableFromState: ["scene_ended", "act_ended", "run_ended"],
    unavailableDuring: [],
    cta: "购买 5 次重演",
    iconKey: "parallel",
  },
  {
    id: "credits",
    name: "积分包",
    priceCents: 1200,
    description: "150 次主调用积分。",
    includes: [
      "150 主调用积分",
      "积分不过期（与 runId 绑定）",
    ],
    availableFromState: ["scene_ended", "act_ended", "run_ended"],
    unavailableDuring: [],
    cta: "购买 150 积分",
    iconKey: "credits",
  },
  {
    id: "pov_unlock",
    name: "额外人物视角",
    priceCents: 300,
    description: "1 段。解锁后不是换 UI，是换叙事——记忆账本、情绪演出、NPC 内心独白全变。",
    includes: [
      "解锁指定角色的 1 段视角",
      "记忆账本 + 角色独白 + 情绪演出",
    ],
    availableFromState: ["scene_ended", "act_ended", "run_ended", "unlocked"],
    unavailableDuring: [],
    cta: "解锁 1 段",
    iconKey: "pov",
  },
  {
    id: "keepsake",
    name: "私人纪念品",
    priceCents: 800,
    description: "本局专属信件 + 照片 + 关系报告，可导出为 JSON / 邮件。",
    includes: [
      "本局专属信件（从 NPC 视角写给玩家）",
      "本局关键时刻照片合集",
      "本局关系报告（描述性，不显示精确数值）",
      "可导出 JSON / 邮件转发",
    ],
    availableFromState: ["run_ended"],
    unavailableDuring: [],
    cta: "生成纪念品",
    iconKey: "keepsake",
  },
  {
    id: "free_sample",
    name: "免费样章",
    priceCents: 0,
    description: "序章 + 三场景缩略（每场 5 分钟）+ 1 次 mandatory echo。",
    includes: [
      "序章",
      "三场景缩略（每场 5 分钟）",
      "1 次 mandatory echo（必触发）",
      "30 主调用积分",
      "1 次重演",
    ],
    availableFromState: ["idle"],
    unavailableDuring: [],
    cta: "开始",
    iconKey: "free",
  },
];

export function getProduct(id: ProductId): Product | undefined {
  return PRODUCTS.find((p) => p.id === id);
}

export function canShowProductInState(id: ProductId, state: RunState): boolean {
  const p = getProduct(id);
  if (!p) return false;
  return p.availableFromState.includes(state);
}
