// =============================================================================
// 革命街没有尽头 · 8 个核心 JSON Schema 的 TypeScript 类型
// -----------------------------------------------------------------------------
// 严格匹配 server/config/schemas/*.json
// 客户端不持有权威状态，类型仅用于通信对齐
// =============================================================================

// -----------------------------------------------------------------------------
// 1. PlayerAction
// -----------------------------------------------------------------------------
export type ActionType =
  | "investigate"
  | "reveal"
  | "conceal"
  | "question"
  | "confront"
  | "comfort"
  | "give"
  | "destroy"
  | "promise"
  | "wait"
  | "leave"
  | "silence";

export type Tone =
  | "hesitant"
  | "firm"
  | "gentle"
  | "angry"
  | "sad"
  | "playful"
  | "neutral";

export interface PlayerAction {
  runId: string;
  sceneId: string;
  clientActionId: string;
  expectedEventSequence: number;
  actionType: ActionType;
  actorId: string;
  targetId: string | null;
  evidenceIds: string[];
  utterance: string;
  tone: Tone;
  disclosureLevel: number;
  isDeceptive: boolean;
  clientTimestamp: string;
  schemaVersion: "1.0.0";
}

// -----------------------------------------------------------------------------
// 2. NpcProposal
// -----------------------------------------------------------------------------
export type SpeechIntent =
  | "seek_confirmation"
  | "defend"
  | "accuse"
  | "comfort"
  | "question"
  | "admit"
  | "deflect"
  | "threaten"
  | "plead"
  | "reassure"
  | "taunt"
  | "reveal_truth"
  | "conceal_truth"
  | "remain_silent";

export type ReasonCode =
  | "player_disclosed_truth"
  | "player_lied"
  | "player_kept_promise"
  | "player_broke_promise"
  | "memory_resurfaced"
  | "belief_contradicted"
  | "belief_confirmed"
  | "witnessed_action"
  | "third_party_intervention"
  | "environmental_threat"
  | "deadline_approaching"
  | "secret_almost_revealed"
  | "traumatic_association"
  | "love_obligation"
  | "duty_obligation"
  | "self_preservation"
  | "guilt_compensation"
  | "ambition"
  | "spite"
  | "curiosity";

export type Emotion =
  | "calm"
  | "tense"
  | "angry"
  | "afraid"
  | "sad"
  | "guilty"
  | "hopeful"
  | "loving"
  | "ashamed"
  | "proud"
  | "numb"
  | "conflicted";

export interface BeliefUpdateRequest {
  subject: string;
  newState: "certain" | "uncertain" | "wrong" | "denied" | "reinforced";
  confidence: number;
  evidenceMemoryId: string | null;
}

export interface EmotionalTransition {
  from: Emotion;
  to: Emotion;
  intensity: number;
}

export interface NpcProposal {
  proposalId: string;
  runId: string;
  characterId: string;
  triggerPlayerActionId: string | null;
  proposedAction: ActionType;
  targetId: string | null;
  speechIntent: SpeechIntent;
  referencedMemoryIds: string[];
  beliefUpdatesRequested: BeliefUpdateRequest[];
  emotionalTransition?: EmotionalTransition;
  reasonCodes: ReasonCode[];
  confidence: number;
  expectedContradictions: string[];
  timestamp: string;
  schemaVersion: "1.0.0";
}

// -----------------------------------------------------------------------------
// 3. DirectorBeat
// -----------------------------------------------------------------------------
export interface DirectorBeat {
  proposalId: string;
  runId: string;
  sceneId: string;
  proposedBeat: string;
  allowedByContract: true;
  forbiddenRevealsChecked: string[];
  transitionToNext: boolean;
  suggestedTargetSceneId: string | null;
  reasoning: string;
  pacingPressure: number;
  expectedTensionDelta: number;
  involvedCharacterIds: string[];
  firedCausalSeeds: string[];
  timestamp: string;
  schemaVersion: "1.0.0";
}

// -----------------------------------------------------------------------------
// 4. ResolverOutcome
// -----------------------------------------------------------------------------
export type Transition = "continue" | "advance_scene" | "end_scene" | "end_run";

export interface ClampingRecord {
  path: string;
  original: number;
  applied: number;
  min: number;
  max: number;
}

export interface LLMAudit {
  agent: "player_client" | "npc_agent" | "director_agent" | "resolver" | "memory_recall";
  model: string;
  inputTokens: number;
  outputTokens: number;
  latencyMs: number;
}

export interface ResolverOutcome {
  outcomeId: string;
  runId: string;
  eventSequence: number;
  triggerPlayerActionId: string | null;
  triggerDirectorProposalId: string | null;
  idempotencyKey: string;
  acceptedNpcAction: {
    proposalId: string;
    characterId: string;
    proposedAction: ActionType;
    speechIntent: SpeechIntent;
    resolvedText: string;
  };
  rejectedNpcActions: Array<{
    proposalId: string;
    reason: string;
    detail?: string;
  }>;
  relationshipDelta: Array<{
    from: string;
    to: string;
    trust: number;
    intimacy: number;
    unresolvedConflict: number;
    respect?: number;
    fear?: number;
  }>;
  beliefUpdates: Array<{
    characterId: string;
    subject: string;
    newState: "certain" | "uncertain" | "wrong" | "denied" | "reinforced";
    confidence: number;
    evidenceMemoryId: string | null;
    previousState:
      | "certain"
      | "uncertain"
      | "wrong"
      | "denied"
      | "reinforced"
      | "unset";
  }>;
  artifactUpdates: Array<{
    artifactId: string;
    operation: "create" | "transfer" | "destroy" | "modify_state" | "reveal" | "conceal";
    newOwnerId: string | null;
    newState: string | null;
    reasonCode: string;
  }>;
  newCausalSeeds: string[];
  firedCausalSeeds: string[];
  nextBeat: {
    sceneId: string;
    beatId: string;
    transition: Transition;
    legalEndingId: string | null;
  };
  clampedValues: ClampingRecord[];
  auditTrail: {
    llmCalls: LLMAudit[];
    deterministicDecisions: string[];
  };
  timestamp: string;
  schemaVersion: "1.0.0";
}

// -----------------------------------------------------------------------------
// 5. BeliefMatrix
// -----------------------------------------------------------------------------
export type BeliefState = "certain" | "uncertain" | "wrong" | "denied" | "reinforced";
export type DistortionType =
  | "none"
  | "traumatic_exaggeration"
  | "traumatic_suppression"
  | "rosy_retrospection"
  | "self_serving_bias"
  | "confabulation"
  | "misattribution"
  | "moral_reframing"
  | "time_compression"
  | "time_expansion";

export interface BeliefMatrix {
  characterId: string;
  runId?: string;
  objective_facts: Array<{
    factId: string;
    description: string;
    establishedAt: number;
    establishedBy: string;
    isContested: boolean;
  }>;
  character_knowledge: Array<{
    subject: string;
    belief_state: BeliefState;
    confidence: number;
    reasoning: string;
    evidenceMemoryIds: string[];
    lastUpdatedAt: number;
  }>;
  character_memories: Array<{
    memoryId: string;
    summary: string;
    emotional_weight: number;
    distortion_type: DistortionType;
    formedAt: number;
    involvedCharacterIds: string[];
    recallCount: number;
    decayScore: number;
  }>;
  hidden_secrets: Array<{
    secretId: string;
    content: string;
    isSecret: boolean;
    knownByCharacterIds: string[];
    leakageRisk: number;
    createdAt: number;
  }>;
  schemaVersion: "1.0.0";
}

// -----------------------------------------------------------------------------
// 6. NarrativeContract
// -----------------------------------------------------------------------------
export type Era =
  | "pre_1911_qing"
  | "1911_1927_republic"
  | "1927_1937_nanjing_decade"
  | "1937_1945_war"
  | "1945_1949_civil_war"
  | "1949_1965_socialist_build"
  | "1966_1976_cultural_revolution"
  | "1977_1989_reform_early"
  | "1989_2000_boom"
  | "2000_2012_globalization"
  | "2012_present_ai_age"
  | "present"
  | "epilogue";

export type Phase = "setup" | "rising" | "climax" | "falling" | "resolution" | "ended";

export type SceneRole = "protagonist" | "ally" | "antagonist" | "witness" | "bystander" | "off_stage";

export type TimeOfDay = "dawn" | "morning" | "noon" | "afternoon" | "evening" | "night" | "late_night" | "unspecified";

export type Weather = "clear" | "cloudy" | "rain" | "storm" | "snow" | "fog" | "heat" | "cold" | "unspecified";

export type BeatTier = "setup" | "rising" | "climax" | "falling" | "resolution";
export type EndingTone = "triumphant" | "bittersweet" | "tragic" | "ambiguous" | "open" | "comic" | "sober";

export interface NarrativeContract {
  sceneId: string;
  title: string;
  era: Era;
  location: string;
  timeOfDay?: TimeOfDay;
  weather?: Weather;
  cast: Array<{
    characterId: string;
    role: SceneRole;
    initialDisposition?: number;
  }>;
  required_anchors: Array<{
    anchorId: string;
    description: string;
    mandatory?: boolean;
  }>;
  core_conflict: string;
  allowed_beats: Array<{
    beatId: string;
    label: string;
    tier: BeatTier;
    tensionDelta?: number;
    prerequisites?: string[];
  }>;
  forbidden_reveals: Array<{
    revealKey: string;
    reason: string;
  }>;
  max_turns: number;
  total_action_budget: number;
  legal_endings: Array<{
    endingId: string;
    label: string;
    conditions: string[];
    tone?: EndingTone;
  }>;
  causal_seeds?: string[];
  // UP-20260715-004: enum mirrors server/config/schemas/narrative_contract.schema.json
  // (default_third_person_observer | observer_leila | observer_arash).
  // observer_leila / observer_arash are paid unlocks (决策 4 ¥3/段).
  narratorVoice?: "default_third_person_observer" | "observer_leila" | "observer_arash";
  schemaVersion: "1.0.0";
}

// -----------------------------------------------------------------------------
// 7. CausalSeed
// -----------------------------------------------------------------------------
export type TriggerType =
  | "scene_match"
  | "character_present"
  | "era_match"
  | "belief_state"
  | "memory_recall"
  | "artifact_present"
  | "location_match"
  | "composite";

export interface CausalSeed {
  id: string;
  source_scene: string;
  source_event: string;
  description: string;
  trigger_condition: {
    type: TriggerType;
    predicate: string;
    minEcho?: number;
  };
  target_scenes: string[];
  echo_intensity: number;
  is_secret: boolean;
  firedAt: number | null;
  firedInSceneId: string | null;
  eraSpan?: { from: Era; to: Era };
  linkedCharacterIds?: string[];
  decayRate?: number;
  tags?: string[];
  schemaVersion: "1.0.0";
}

// -----------------------------------------------------------------------------
// 8. WorldSnapshot
// -----------------------------------------------------------------------------
export interface WorldSnapshot {
  runId: string;
  eventSequence: number;
  canonicalState: {
    currentSceneId: string;
    era: Era;
    turnIndex: number;
    phase: Phase;
    activeContractId: string;
    activeBeatId: string | null;
    endingId: string | null;
    globalTension: number;
  };
  relationshipState: Array<{
    from: string;
    to: string;
    trust: number;
    intimacy: number;
    unresolvedConflict: number;
    respect?: number;
    fear?: number;
    lastUpdatedAt: number;
  }>;
  artifactState: Array<{
    artifactId: string;
    ownerId: string;
    state: string;
    isRevealed: boolean;
    location?: string | null;
    tags?: string[];
  }>;
  directorState: {
    currentBeatId: string;
    elapsedTurnsInScene: number;
    actionsSpentInScene: number;
    firedBeats: string[];
    hitAnchors: string[];
    forbiddenRevealsCheckedAt: number[];
  };
  beliefMatrices: BeliefMatrix[];
  memories: Array<{
    memoryId: string;
    ownerCharacterId: string;
    summary: string;
    recallWeight: number;
    decayScore: number;
    lastRecalledAt: number | null;
    embeddingHash: string;
  }>;
  causalSeedsActive: CausalSeed[];
  recentOutcomes: Array<{
    outcomeId: string;
    eventSequence: number;
    timestamp: string;
  }>;
  timestamp: string;
  checksum: string;
  schemaVersion: "1.0.0";
}

// =============================================================================
// 客户端扩展类型（非服务端协议）
// =============================================================================

/** 降级等级：决策 5 的 4 级降级链 */
export type DegradationLevel = "none" | "L1" | "L2" | "L3" | "L4";

/** 付费商品（决策 4） */
export type ProductId =
  | "passport"        // 案件通行证 ¥25
  | "collectors"      // 收藏版 ¥48
  | "parallel_ops"    // 平行演算包 ¥12
  | "credits"         // 积分包 ¥12
  | "pov_unlock"      // 额外人物视角 ¥3
  | "keepsake"        // 私人纪念品 ¥8
  | "free_sample";    // 免费样章 ¥0

export interface Product {
  id: ProductId;
  name: string;
  priceCents: number;
  description: string;
  includes: string[];
  availableFromState: RunState[];
  unavailableDuring: SceneId[];
  cta: string;
  iconKey: string;
}

/** 场景 ID 集合 */
export type SceneId = "photo_lab_2008" | "farewell_2011" | "reunion_2024";

/** 运行状态：付费点必须从这些状态触发 */
export type RunState =
  | "idle"
  | "scene_active"
  | "scene_ended"
  | "act_ended"
  | "run_ended"
  | "unlocked";

/** 调查对象 */
export interface InvestigatableObject {
  id: string;
  name: string;
  description: string;
  initialLocation: string;
  keywords: string[];
  requires: string[];
  leadsTo: string[];
  iconKey?: string;
}

/** 场景 YAML 客户端镜像（用于 mock 模式） */
export interface SceneMeta {
  sceneId: SceneId;
  title: string;
  era: Era;
  location: string;
  atmosphere: string[];
  contract: NarrativeContract;
  investigatableObjects: InvestigatableObject[];
  charactersPresent: Array<{
    id: string;
    name: string;
    initialState: string;
    stateNotes: string[];
    visibility: string;
  }>;
  turnBudget: Partial<Record<ActionType, number>>;
  causalSeeds: Array<{
    id: string;
    description: string;
    trigger: string;
    effects: string[];
  }>;
  legalEndings: Array<{
    id: string;
    label: string;
    description: string;
    causalSeedRequired: string[];
  }>;
}
