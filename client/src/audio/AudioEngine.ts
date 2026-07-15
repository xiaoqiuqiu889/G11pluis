// =============================================================================
// 革命街没有尽头 · 声音引擎（W5-B 升级版）
// -----------------------------------------------------------------------------
// 基于 _legacy_v6/app/audio-engine.ts 改造，保留 v6 核心 procedural 架构
// （pluck / santurSpark / tombak / motif / texture / cue），仅扩展。
//
// W5-B 新增：
//   1. 6 个文件式声音母题（AudioContext.decodeAudioData + AudioBufferSourceNode）
//   2. 3 章节真实环境声（可循环，可与 procedural 棕色噪音混合）
//   3. 3 章节真实音乐（可循环，可与 procedural 波斯主题叠播）
//   4. 章节切换 1.5 秒 cross-fade（gain ramp）
//   5. 资源懒加载（preload on first use + idle warmup）
//   6. 完整 zustand 集成（audioEnabled / setAudio / audioVolume）
//
// 决策锚点：
//   - 决策 2-5：默认静音 + 用户手势启动
//   - 决策 5：背景音量克制（主旋律仅在情绪高潮出现）
//   - 风格指南：声音承担场景切换和情绪留白，不持续抢台词
// =============================================================================

type Cue = "choice" | "transition" | "save" | "ending";
type ProceduralMotif = "photo" | "paper" | "ash" | "ticket" | "email" | string;
type Texture = "projector" | "fluorescent" | "keyboard" | "airport" | "tea" | "rain";

// W5-B 新增：6 个文件式声音母题
type AssetMotif =
  | "photo_turn"   // 照片翻动
  | "email_delete" // 邮件删除
  | "clock_tick"   // 机场钟秒针
  | "rain_drip"    // 雨棚水滴
  | "poetry_turn"  // 诗集翻页
  | "ticket_tear"; // 公交票撕痕

type Motif = ProceduralMotif | AssetMotif;

// 章节 ID（与 scene runner 一致）
type ChapterId =
  | "prologue"
  | "photo_lab_2008"
  | "farewell_2011"
  | "reunion_2024"
  | "ending"
  | string;

interface ThemePreset {
  tempo: number;
  base: number;
  volume: number;
  melody: number[];
  drum: number[];
}

// -----------------------------------------------------------------------------
// 路径表：与 assets/audio 目录结构对齐
// -----------------------------------------------------------------------------
const ASSET_BASE = "/assets/audio";

// W12: case-aware 路径表 — 每案独立 ambient / music / motifs
// case_01 沿用旧根目录结构（向后兼容）；case_02 用 /assets/audio/case_02/
interface CaseAudioPaths {
  ambient: Partial<Record<string, string>>;
  music: Partial<Record<string, string>>;
  motifs: Partial<Record<AssetMotif, string>>;
}

const CASE_AUDIO_PATHS: Record<string, CaseAudioPaths> = {
  // 默认：case_01（根目录 ambient / music / motifs）
  case_01_revolution_street: {
    ambient: {
      photo_lab_2008: `${ASSET_BASE}/ambient/chapter-2008-basement-ambient.mp3`,
      farewell_2011: `${ASSET_BASE}/ambient/chapter-2011-airport-ambient.mp3`,
      reunion_2024: `${ASSET_BASE}/ambient/chapter-2024-istanbul-cafe-ambient.mp3`,
    },
    music: {
      photo_lab_2008: `${ASSET_BASE}/music/chapter-2008-music.mp3`,
      farewell_2011: `${ASSET_BASE}/music/chapter-2011-music.mp3`,
      reunion_2024: `${ASSET_BASE}/music/chapter-2024-music.mp3`,
    },
    motifs: {
      photo_turn: `${ASSET_BASE}/motifs/motif-photo-page-turn.mp3`,
      email_delete: `${ASSET_BASE}/motifs/motif-email-delete.mp3`,
      clock_tick: `${ASSET_BASE}/motifs/motif-airport-clock-tick.mp3`,
      rain_drip: `${ASSET_BASE}/motifs/motif-rain-drip.mp3`,
      poetry_turn: `${ASSET_BASE}/motifs/motif-poetry-page-turn.mp3`,
      ticket_tear: `${ASSET_BASE}/motifs/motif-bus-ticket-tear.mp3`,
    },
  },
  // case_02：/assets/audio/case_02/{ambient,music,motifs}/
  case_02_moscow_no_fairy_tale: {
    ambient: {
      "1985_meeting": `${ASSET_BASE}/case_02/ambient/chapter-1985-conservatory-ambient.mp3`,
      "1989_farewell": `${ASSET_BASE}/case_02/ambient/chapter-1989-svo2-ambient.mp3`,
      "2008_reunion": `${ASSET_BASE}/case_02/ambient/chapter-2008-kreuzberg-ambient.mp3`,
    },
    music: {
      "1985_meeting": `${ASSET_BASE}/case_02/music/chapter-1985-music.mp3`,
      "1989_farewell": `${ASSET_BASE}/case_02/music/chapter-1989-music.mp3`,
      "2008_reunion": `${ASSET_BASE}/case_02/music/chapter-2008-music.mp3`,
    },
    motifs: {
      // case_02 复用 case_01 母题（雨滴 / 秒针 / 翻页等通用声音）
      photo_turn: `${ASSET_BASE}/case_02/motifs/motif-notebook-page-turn.mp3`,
      email_delete: `${ASSET_BASE}/case_02/motifs/motif-pencil-circles.mp3`,
      clock_tick: `${ASSET_BASE}/case_02/motifs/motif-aeroflot-chime.mp3`,
      rain_drip: `${ASSET_BASE}/case_02/motifs/motif-cassette-rewind.mp3`,
      poetry_turn: `${ASSET_BASE}/case_02/motifs/motif-postcard-unveil.mp3`,
      // 替代 first_turn — case_02 用 piano-sustain-pedal 作为核心母题
      ticket_tear: `${ASSET_BASE}/case_02/motifs/motif-piano-sustain-pedal.mp3`,
    },
  },
};

// 当前激活的 case（影响后续 asset 路径查找）
let _currentCaseSlug: string = "case_01_revolution_street";

export function setCase(caseSlug: string): void {
  if (CASE_AUDIO_PATHS[caseSlug]) {
    _currentCaseSlug = caseSlug;
  }
}

function _paths(): CaseAudioPaths {
  return CASE_AUDIO_PATHS[_currentCaseSlug] ?? CASE_AUDIO_PATHS.case_01_revolution_street;
}

// 兼容旧 const 引用（重写为按 case 动态取值）
function CHAPTER_AMBIENT_PATH(): Partial<Record<string, string>> {
  return _paths().ambient;
}
function CHAPTER_MUSIC_PATH(): Partial<Record<string, string>> {
  return _paths().music;
}
function MOTIF_PATH(): Record<AssetMotif, string> {
  // 合并 case 的 motifs（如果某个母题 case 没声明，回落到 case_01）
  const base = CASE_AUDIO_PATHS.case_01_revolution_street.motifs;
  const overlay = _paths().motifs;
  return { ...base, ...overlay } as Record<AssetMotif, string>;
}

const ASSET_MOTIF_SET: ReadonlySet<string> = new Set(Object.keys(MOTIF_PATH()));

// -----------------------------------------------------------------------------
// procedural 配置（来自 v6，保留）
// -----------------------------------------------------------------------------

// Dastgah-e Shur 风格音高集；第二与第六音在半音之间
const SHUR_CENTS = [0, 150, 300, 500, 700, 850, 1000, 1200, 1350, 1500];

// 章节环境声（低通截止、噪声音量）—— 保留为 procedural 兜底
const CHAPTER_SOUND: Record<string, { cutoff: number; volume: number }> = {
  prologue: { cutoff: 720, volume: 0.012 },
  chapter1: { cutoff: 1050, volume: 0.014 }, // 革命街放映室
  chapter2: { cutoff: 520, volume: 0.016 },  // 校园小房间
  chapter3: { cutoff: 430, volume: 0.017 },  // 机场大厅
  chapter4: { cutoff: 820, volume: 0.011 },
  chapter5: { cutoff: 680, volume: 0.010 },  // 伊斯坦布尔咖啡馆
  ending: { cutoff: 560, volume: 0.009 },
};

const THEMES: Record<string, ThemePreset> = {
  prologue: {
    tempo: 72,
    base: 146.83,
    volume: 0.015,
    melody: [0, -1, 3, -1, 2, -1, 1, -1, 0, -1, 4, -1, 3, -1, 1, -1],
    drum: [0, 6, 10],
  },
  chapter1: {
    tempo: 84,
    base: 146.83,
    volume: 0.019,
    melody: [0, 2, 3, -1, 4, 3, 2, 1, 0, -1, 3, 4, 5, 4, 3, -1],
    drum: [0, 4, 7, 10, 14],
  },
  chapter2: {
    tempo: 68,
    base: 130.81,
    volume: 0.014,
    melody: [0, -1, 1, 2, -1, 1, 0, -1, 3, -1, 2, 1, -1, 0, -1, -1],
    drum: [0, 9],
  },
  chapter3: {
    tempo: 76,
    base: 130.81,
    volume: 0.016,
    melody: [0, -1, 3, 2, 1, -1, 0, -1, 4, 3, -1, 2, 1, -1, 0, -1],
    drum: [0, 6, 11],
  },
  chapter4: {
    tempo: 78,
    base: 146.83,
    volume: 0.014,
    melody: [0, 3, -1, 4, 5, -1, 4, 3, 2, -1, 1, 0, -1, 2, 1, -1],
    drum: [0, 8],
  },
  chapter5: {
    tempo: 66,
    base: 146.83,
    volume: 0.013,
    melody: [0, -1, 1, -1, 3, 2, -1, 1, 0, -1, 4, -1, 3, 1, -1, -1],
    drum: [0, 10],
  },
  ending: {
    tempo: 60,
    base: 130.81,
    volume: 0.012,
    melody: [0, -1, 3, -1, 2, -1, 1, -1, 0, -1, 3, -1, 1, -1, 0, -1],
    drum: [0],
  },
};

// 章节 → 真实音乐/环境声开关（新增 W5-B）
// 设计取舍：真实文件质量更高，但有 200-400ms 解码成本
// 策略：开始 procedural 让声音即时在场，真实文件解码完成后在下一段 cross-fade 接入
const ASSET_AMBIENT_ENABLED: Record<string, boolean> = {
  photo_lab_2008: true,
  farewell_2011: true,
  reunion_2024: true,
};

const ASSET_MUSIC_ENABLED: Record<string, boolean> = {
  photo_lab_2008: true,
  farewell_2011: true,
  reunion_2024: true,
};

// 母题音量（v6 procedural 母题相对更轻，文件式母题更实）
const ASSET_MOTIF_VOLUME: Record<AssetMotif, number> = {
  photo_turn: 0.32,    // 轻柔
  email_delete: 0.22,   // 短促
  clock_tick: 0.28,     // 清晰
  rain_drip: 0.26,      // 间歇
  poetry_turn: 0.24,    // 慢翻
  ticket_tear: 0.35,    // 尖锐，需要稍微轻
};

// Cross-fade 时长（决策：1.5 秒）
const CROSSFADE_SECONDS = 1.5;

// 母题 / 音乐 / 环境默认 mix
const DEFAULT_AMBIENT_MIX = 0.55;
const DEFAULT_MUSIC_MIX = 0.28;   // 背景音 90% → 主旋律 ≤ 30% 峰值
const MASTER_GAIN_UNMUTED = 0.62;

// =============================================================================
// 引擎
// =============================================================================

export class AudioEngine {
  // --- procedural state ---
  private context: AudioContext | null = null;
  private master: GainNode | null = null;
  private ambience: AudioNode[] = [];
  private currentChapter: ChapterId = "";
  private musicTimer: number | null = null;
  private nextNoteTime = 0;
  private musicStep = 0;
  private muted = true; // 决策：默认静音

  // --- asset state ---
  private ambientBuffers: Map<string, AudioBuffer> = new Map();
  private musicBuffers: Map<string, AudioBuffer> = new Map();
  private motifBuffers: Map<AssetMotif, AudioBuffer> = new Map();

  private ambientSource: AudioBufferSourceNode | null = null;
  private ambientGain: GainNode | null = null;
  private musicSource: AudioBufferSourceNode | null = null;
  private musicGain: GainNode | null = null;

  private currentAmbientChapter = ""; // 当前正在播放的真实环境声对应章节
  private currentMusicChapter = "";   // 当前正在播放的真实音乐对应章节

  private ambientLoadInFlight: Promise<void> | null = null;
  private musicLoadInFlight: Promise<void> | null = null;
  private motifLoadInFlight: Promise<void> | null = null;

  // --- volume state ---
  private ambientMix = DEFAULT_AMBIENT_MIX;
  private musicMix = DEFAULT_MUSIC_MIX;
  private userVolume = 0.6; // 0-1（来自 store.audioVolume）

  // -------------------------------------------------------------------------
  // 生命周期
  // -------------------------------------------------------------------------

  /**
   * 用户手势后启动；返回 Promise<started>。
   * 必须由 click / keydown / pointerdown 等用户事件回调中调用，
   * 否则 AudioContext 会因 autoplay policy 处于 suspended。
   */
  async start(chapter: ChapterId): Promise<boolean> {
    if (!this.context) {
      try {
        const Ctor: typeof AudioContext =
          window.AudioContext ||
          (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
        this.context = new Ctor();
        this.master = this.context.createGain();
        this.master.gain.value = 0; // start muted
        this.master.connect(this.context.destination);
      } catch {
        return false;
      }
    }
    if (this.context.state === "suspended") {
      try {
        await this.context.resume();
      } catch {
        return false;
      }
    }
    this.setChapter(chapter);

    // 后台空闲时预热母题（首次启动后）
    void this.preloadMotifs();
    return true;
  }

  /** 解锁 / 静音（来自 store.audioEnabled） */
  setMuted(muted: boolean): void {
    this.muted = muted;
    if (this.master && this.context) {
      this.master.gain.cancelScheduledValues(this.context.currentTime);
      this.master.gain.setTargetAtTime(muted ? 0 : MASTER_GAIN_UNMUTED * this.userVolume, this.context.currentTime, 0.05);
    }
  }

  setVolume(v: number): void {
    this.userVolume = Math.max(0, Math.min(1, v));
    if (this.master && this.context) {
      const target = this.muted ? 0 : MASTER_GAIN_UNMUTED * this.userVolume;
      this.master.gain.setTargetAtTime(target, this.context.currentTime, 0.05);
    }
  }

  /** 设置母题在混音中的相对音量（0-1） */
  setAmbientMix(v: number): void {
    this.ambientMix = Math.max(0, Math.min(1, v));
    this.applyAmbientMix();
  }

  /** 设置音乐在混音中的相对音量（0-1） */
  setMusicMix(v: number): void {
    this.musicMix = Math.max(0, Math.min(1, v));
    this.applyMusicMix();
  }

  isRunning(): boolean {
    return !!this.context && this.context.state === "running";
  }

  // -------------------------------------------------------------------------
  // 章节切换（含 1.5 秒 cross-fade）
  // -------------------------------------------------------------------------

  /**
   * 切换章节。
   * - procedural 环境声立即停 / 启
   * - 真实环境声 + 音乐：cross-fade 1.5 秒
   * - 音乐主题（procedural Persian）：立即重启
   */
  setChapter(chapter: ChapterId): void {
    if (!this.context || !this.master || chapter === this.currentChapter) return;
    this.currentChapter = chapter;

    // 1. 关闭旧的 procedural 棕色噪音
    this.stopAmbience();

    // 2. 启 procedural 棕色噪音（保留 v6 行为，作为真实文件的"即时兜底"）
    this.startProceduralAmbience(chapter);

    // 3. procedural 波斯主题（保留 v6 行为）
    this.stopMusic();
    this.startPersianTheme(chapter);

    // 4. cross-fade 真实文件（环境声 + 音乐并行）
    if (ASSET_AMBIENT_ENABLED[chapter]) {
      void this.crossfadeAmbient(chapter);
    } else {
      this.stopAssetAmbient();
    }
    if (ASSET_MUSIC_ENABLED[chapter]) {
      void this.crossfadeMusic(chapter);
    } else {
      this.stopAssetMusic();
    }
  }

  // -------------------------------------------------------------------------
  // 母题 / 质感 / cue（保留 v6 行为 + 新增 asset motif）
  // -------------------------------------------------------------------------

  /**
   * 母题播放。
   * - 如果 type 是 6 个 asset 母题之一：用预加载的 AudioBuffer 播放
   * - 否则回落到 v6 procedural motif
   */
  motif(type: Motif): void {
    if (!this.context || !this.master || this.context.state !== "running" || this.muted) return;

    if (ASSET_MOTIF_SET.has(type)) {
      this.playAssetMotif(type as AssetMotif);
      return;
    }
    this.playProceduralMotif(type);
  }

  /** v6 procedural motif（保留） */
  private playProceduralMotif(type: ProceduralMotif): void {
    if (!this.context || !this.master) return;
    const now = this.context.currentTime;
    const patterns: Record<string, [number, number, number]> = {
      photo: [246.94, 220, 0.34],
      paper: [329.63, 293.66, 0.28],
      ash: [92.5, 73.4, 0.42],
      ticket: [196, 246.94, 0.24],
      email: [440, 392, 0.18],
    };
    const [from, to, duration] = patterns[type] ?? patterns.paper;
    const oscillator = this.context.createOscillator();
    const gain = this.context.createGain();
    const filter = this.context.createBiquadFilter();
    oscillator.type = type === "ash" ? "sawtooth" : type === "photo" ? "sine" : "triangle";
    oscillator.frequency.setValueAtTime(from, now);
    oscillator.frequency.exponentialRampToValueAtTime(to, now + duration);
    filter.type = "lowpass";
    filter.frequency.value = type === "ash" ? 240 : 1200;
    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.exponentialRampToValueAtTime(type === "ash" ? 0.012 : 0.022, now + 0.025);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + duration);
    oscillator.connect(filter).connect(gain).connect(this.master);
    oscillator.start(now);
    oscillator.stop(now + duration + 0.02);
  }

  /** asset motif：通过 AudioBufferSourceNode 播放预加载的 MP3 */
  private playAssetMotif(type: AssetMotif): void {
    if (!this.context || !this.master) return;
    const buffer = this.motifBuffers.get(type);
    if (!buffer) {
      // 还没预热好：用 procedural 兜底 + 异步预热
      const fallback: ProceduralMotif = type === "email_delete" ? "email" : type === "ticket_tear" ? "ticket" : "photo";
      this.playProceduralMotif(fallback);
      void this.ensureMotif(type);
      return;
    }
    const source = this.context.createBufferSource();
    source.buffer = buffer;
    const gain = this.context.createGain();
    const volume = ASSET_MOTIF_VOLUME[type] ?? 0.3;
    gain.gain.value = volume;
    source.connect(gain).connect(this.master);
    source.start();
  }

  texture(type: Texture): void {
    if (!this.context || !this.master || this.context.state !== "running" || this.muted) return;
    const now = this.context.currentTime;
    const duration = type === "projector" ? 1.1 : type === "rain" ? 0.9 : 0.42;
    const buffer = this.context.createBuffer(1, Math.floor(this.context.sampleRate * duration), this.context.sampleRate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < data.length; i += 1) {
      const falloff = Math.pow(1 - i / data.length, type === "rain" ? 0.45 : 1.8);
      data[i] = (Math.random() * 2 - 1) * falloff;
    }
    const source = this.context.createBufferSource();
    source.buffer = buffer;
    const filter = this.context.createBiquadFilter();
    const gain = this.context.createGain();
    const profiles: Record<Texture, [BiquadFilterType, number, number]> = {
      projector: ["lowpass", 310, 0.008],
      fluorescent: ["bandpass", 118, 0.004],
      keyboard: ["highpass", 1800, 0.007],
      airport: ["bandpass", 620, 0.006],
      tea: ["highpass", 2400, 0.006],
      rain: ["lowpass", 1100, 0.008],
    };
    const [filterType, frequency, peak] = profiles[type];
    filter.type = filterType;
    filter.frequency.value = frequency;
    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.linearRampToValueAtTime(peak, now + 0.025);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + duration);
    source.connect(filter).connect(gain).connect(this.master);
    source.start(now);
    source.stop(now + duration + 0.02);
    if (type === "projector" || type === "fluorescent") {
      const hum = this.context.createOscillator();
      const humGain = this.context.createGain();
      hum.type = "sine";
      hum.frequency.value = type === "projector" ? 48 : 100;
      humGain.gain.setValueAtTime(0.0001, now);
      humGain.gain.linearRampToValueAtTime(type === "projector" ? 0.006 : 0.003, now + 0.03);
      humGain.gain.exponentialRampToValueAtTime(0.0001, now + duration);
      hum.connect(humGain).connect(this.master);
      hum.start(now);
      hum.stop(now + duration + 0.02);
    }
  }

  cue(type: Cue): void {
    if (!this.context || !this.master || this.context.state !== "running" || this.muted) return;
    const now = this.context.currentTime;
    const oscillator = this.context.createOscillator();
    const gain = this.context.createGain();
    const frequencies: Record<Cue, [number, number]> = {
      choice: [392, 523.25],
      transition: [146.8, 196],
      save: [659.25, 783.99],
      ending: [220, 329.63],
    };
    oscillator.type = type === "transition" ? "sine" : "triangle";
    oscillator.frequency.setValueAtTime(frequencies[type][0], now);
    oscillator.frequency.exponentialRampToValueAtTime(frequencies[type][1], now + 0.18);
    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.exponentialRampToValueAtTime(0.024, now + 0.025);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.28);
    oscillator.connect(gain).connect(this.master);
    oscillator.start(now);
    oscillator.stop(now + 0.3);
  }

  stop(): void {
    this.stopMusic();
    this.stopAmbience();
    this.stopAssetAmbient();
    this.stopAssetMusic();
    if (this.context) {
      void this.context.close();
    }
    this.context = null;
    this.master = null;
    this.currentChapter = "";
  }

  // -------------------------------------------------------------------------
  // 内部：procedural 棕色噪音 + 波斯主题（v6 行为保留）
  // -------------------------------------------------------------------------

  private startProceduralAmbience(chapter: ChapterId): void {
    if (!this.context || !this.master) return;
    const ambience = CHAPTER_SOUND[chapter] ?? CHAPTER_SOUND.prologue;
    const buffer = this.context.createBuffer(1, this.context.sampleRate * 2, this.context.sampleRate);
    const data = buffer.getChannelData(0);
    let brown = 0;
    for (let i = 0; i < data.length; i += 1) {
      const white = Math.random() * 2 - 1;
      brown = (brown + 0.02 * white) / 1.02;
      data[i] = brown * 2.2;
    }
    const noise = this.context.createBufferSource();
    noise.buffer = buffer;
    noise.loop = true;
    const filter = this.context.createBiquadFilter();
    filter.type = "lowpass";
    filter.frequency.value = ambience.cutoff;
    const noiseGain = this.context.createGain();
    noiseGain.gain.value = ambience.volume;
    noise.connect(filter).connect(noiseGain).connect(this.master);
    noise.start();
    this.ambience = [noise, filter, noiseGain];
  }

  private startPersianTheme(chapter: ChapterId): void {
    if (!this.context || !this.master) return;
    const preset = THEMES[chapter] ?? THEMES.prologue;
    this.nextNoteTime = this.context.currentTime + 0.06;
    this.musicStep = 0;
    const schedule = () => {
      if (!this.context || this.context.state !== "running" || !this.master) return;
      const stepDuration = 60 / preset.tempo / 2;
      while (this.nextNoteTime < this.context.currentTime + 0.28) {
        const note = preset.melody[this.musicStep % preset.melody.length];
        if (note >= 0) {
          const frequency = preset.base * Math.pow(2, SHUR_CENTS[note] / 1200);
          this.pluck(frequency, this.nextNoteTime, preset.volume, this.musicStep % 4 === 0);
          if (this.musicStep % 8 === 6) {
            this.santurSpark(frequency * 2, this.nextNoteTime + 0.035, preset.volume * 0.55);
          }
        }
        if (preset.drum.includes(this.musicStep % 16)) {
          this.tombak(this.nextNoteTime, this.musicStep % 16 === 0);
        }
        this.nextNoteTime += stepDuration;
        this.musicStep += 1;
      }
    };
    schedule();
    this.musicTimer = window.setInterval(schedule, 90);
  }

  private pluck(frequency: number, time: number, volume: number, accent: boolean): void {
    if (!this.context || !this.master) return;
    const osc = this.context.createOscillator();
    const overtone = this.context.createOscillator();
    const gain = this.context.createGain();
    const filter = this.context.createBiquadFilter();
    osc.type = "triangle";
    overtone.type = "sine";
    osc.frequency.setValueAtTime(frequency, time);
    overtone.frequency.setValueAtTime(frequency * 2.01, time);
    filter.type = "lowpass";
    filter.frequency.setValueAtTime(1800, time);
    filter.frequency.exponentialRampToValueAtTime(520, time + 0.72);
    const peak = volume * (accent ? 1.18 : 1);
    gain.gain.setValueAtTime(0.0001, time);
    gain.gain.exponentialRampToValueAtTime(peak, time + 0.012);
    gain.gain.exponentialRampToValueAtTime(0.0001, time + 0.78);
    osc.connect(filter);
    overtone.connect(filter);
    filter.connect(gain).connect(this.master);
    osc.start(time);
    overtone.start(time);
    osc.stop(time + 0.8);
    overtone.stop(time + 0.55);
  }

  private santurSpark(frequency: number, time: number, volume: number): void {
    if (!this.context || !this.master) return;
    for (const offset of [0, 0.022]) {
      const osc = this.context.createOscillator();
      const gain = this.context.createGain();
      osc.type = "triangle";
      osc.frequency.value = frequency * (offset ? 1.004 : 1);
      gain.gain.setValueAtTime(0.0001, time + offset);
      gain.gain.exponentialRampToValueAtTime(volume, time + offset + 0.006);
      gain.gain.exponentialRampToValueAtTime(0.0001, time + offset + 0.34);
      osc.connect(gain).connect(this.master);
      osc.start(time + offset);
      osc.stop(time + offset + 0.36);
    }
  }

  private tombak(time: number, accent: boolean): void {
    if (!this.context || !this.master) return;
    const buffer = this.context.createBuffer(1, Math.floor(this.context.sampleRate * 0.16), this.context.sampleRate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < data.length; i += 1) data[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / data.length, 3);
    const source = this.context.createBufferSource();
    source.buffer = buffer;
    const filter = this.context.createBiquadFilter();
    filter.type = "bandpass";
    filter.frequency.value = accent ? 145 : 240;
    filter.Q.value = 1.4;
    const gain = this.context.createGain();
    gain.gain.setValueAtTime(accent ? 0.018 : 0.011, time);
    gain.gain.exponentialRampToValueAtTime(0.0001, time + 0.15);
    source.connect(filter).connect(gain).connect(this.master);
    source.start(time);
    source.stop(time + 0.17);
  }

  private stopMusic(): void {
    if (this.musicTimer !== null) {
      window.clearInterval(this.musicTimer);
      this.musicTimer = null;
    }
  }

  private stopAmbience(): void {
    for (const node of this.ambience) {
      if ("stop" in node) {
        try {
          (node as AudioScheduledSourceNode).stop();
        } catch {
          /* noop */
        }
      }
      try {
        node.disconnect();
      } catch {
        /* noop */
      }
    }
    this.ambience = [];
  }

  // -------------------------------------------------------------------------
  // 内部：asset 加载 + 播放 + cross-fade
  // -------------------------------------------------------------------------

  private async loadAndDecode(url: string): Promise<AudioBuffer | null> {
    if (!this.context) return null;
    try {
      const resp = await fetch(url);
      if (!resp.ok) return null;
      const arrayBuffer = await resp.arrayBuffer();
      return await this.context.decodeAudioData(arrayBuffer);
    } catch {
      return null;
    }
  }

  /** 启动时预热所有母题（小文件，共 ~3MB） */
  async preloadMotifs(): Promise<void> {
    if (this.motifLoadInFlight) return this.motifLoadInFlight;
    if (!this.context) return;
    const ctx = this.context;
    this.motifLoadInFlight = (async () => {
      const entries = Object.entries(MOTIF_PATH()) as Array<[AssetMotif, string]>;
      await Promise.all(
        entries.map(async ([k, path]) => {
          if (this.motifBuffers.has(k)) return;
          const buffer = await this.loadAndDecode(path);
          if (buffer) this.motifBuffers.set(k, buffer);
        }),
      );
    })();
    try {
      await this.motifLoadInFlight;
    } finally {
      this.motifLoadInFlight = null;
    }
  }

  /** 单独补一个母题的预热（首次 play 时 fallback 之后） */
  private async ensureMotif(type: AssetMotif): Promise<void> {
    if (this.motifBuffers.has(type)) return;
    const buffer = await this.loadAndDecode(MOTIF_PATH()[type]);
    if (buffer) this.motifBuffers.set(type, buffer);
  }

  private async ensureAmbient(chapter: ChapterId): Promise<AudioBuffer | null> {
    const path = CHAPTER_AMBIENT_PATH()[chapter];
    if (!path) return null;
    const cached = this.ambientBuffers.get(chapter);
    if (cached) return cached;
    const buffer = await this.loadAndDecode(path);
    if (buffer) this.ambientBuffers.set(chapter, buffer);
    return buffer;
  }

  private async ensureMusic(chapter: ChapterId): Promise<AudioBuffer | null> {
    const path = CHAPTER_MUSIC_PATH()[chapter];
    if (!path) return null;
    const cached = this.musicBuffers.get(chapter);
    if (cached) return cached;
    const buffer = await this.loadAndDecode(path);
    if (buffer) this.musicBuffers.set(chapter, buffer);
    return buffer;
  }

  /**
   * 1.5 秒 cross-fade：旧 source 渐出 0 → 新 source 渐入。
   * 若 buffer 还在加载：跳过新 source，保留旧 source 不变。
   */
  private async crossfadeAmbient(chapter: ChapterId): Promise<void> {
    if (!this.context || !this.master) return;
    const ctx = this.context;
    if (this.currentAmbientChapter === chapter && this.ambientSource) return;

    const buffer = await this.ensureAmbient(chapter);
    if (!buffer) return;

    // 已被新章节切换取代
    if (this.currentChapter !== chapter) return;
    if (this.currentAmbientChapter === chapter) return;

    const oldSource = this.ambientSource;
    const oldGain = this.ambientGain;

    const newSource = ctx.createBufferSource();
    newSource.buffer = buffer;
    newSource.loop = true;
    const newGain = ctx.createGain();
    newGain.gain.value = 0;
    newSource.connect(newGain).connect(this.master);
    newSource.start();

    const t0 = ctx.currentTime;
    const fadeInEnd = t0 + CROSSFADE_SECONDS;
    newGain.gain.setValueAtTime(0, t0);
    newGain.gain.linearRampToValueAtTime(this.ambientMix, fadeInEnd);

    if (oldSource && oldGain) {
      oldGain.gain.cancelScheduledValues(t0);
      oldGain.gain.setValueAtTime(oldGain.gain.value, t0);
      oldGain.gain.linearRampToValueAtTime(0, fadeInEnd);
      const stopAt = fadeInEnd + 0.05;
      try {
        oldSource.stop(stopAt);
      } catch {
        /* noop */
      }
      window.setTimeout(() => {
        try {
          oldSource.disconnect();
        } catch {
          /* noop */
        }
        try {
          oldGain.disconnect();
        } catch {
          /* noop */
        }
      }, (stopAt - t0) * 1000 + 50);
    }

    this.ambientSource = newSource;
    this.ambientGain = newGain;
    this.currentAmbientChapter = chapter;
  }

  private async crossfadeMusic(chapter: ChapterId): Promise<void> {
    if (!this.context || !this.master) return;
    const ctx = this.context;
    if (this.currentMusicChapter === chapter && this.musicSource) return;

    const buffer = await this.ensureMusic(chapter);
    if (!buffer) return;

    if (this.currentChapter !== chapter) return;
    if (this.currentMusicChapter === chapter) return;

    const oldSource = this.musicSource;
    const oldGain = this.musicGain;

    const newSource = ctx.createBufferSource();
    newSource.buffer = buffer;
    newSource.loop = true;
    const newGain = ctx.createGain();
    newGain.gain.value = 0;
    newSource.connect(newGain).connect(this.master);
    newSource.start();

    const t0 = ctx.currentTime;
    const fadeInEnd = t0 + CROSSFADE_SECONDS;
    newGain.gain.setValueAtTime(0, t0);
    newGain.gain.linearRampToValueAtTime(this.musicMix, fadeInEnd);

    if (oldSource && oldGain) {
      oldGain.gain.cancelScheduledValues(t0);
      oldGain.gain.setValueAtTime(oldGain.gain.value, t0);
      oldGain.gain.linearRampToValueAtTime(0, fadeInEnd);
      const stopAt = fadeInEnd + 0.05;
      try {
        oldSource.stop(stopAt);
      } catch {
        /* noop */
      }
      window.setTimeout(() => {
        try {
          oldSource.disconnect();
        } catch {
          /* noop */
        }
        try {
          oldGain.disconnect();
        } catch {
          /* noop */
        }
      }, (stopAt - t0) * 1000 + 50);
    }

    this.musicSource = newSource;
    this.musicGain = newGain;
    this.currentMusicChapter = chapter;
  }

  private stopAssetAmbient(): void {
    if (this.ambientSource) {
      try {
        this.ambientSource.stop();
      } catch {
        /* noop */
      }
      try {
        this.ambientSource.disconnect();
      } catch {
        /* noop */
      }
    }
    if (this.ambientGain) {
      try {
        this.ambientGain.disconnect();
      } catch {
        /* noop */
      }
    }
    this.ambientSource = null;
    this.ambientGain = null;
    this.currentAmbientChapter = "";
  }

  private stopAssetMusic(): void {
    if (this.musicSource) {
      try {
        this.musicSource.stop();
      } catch {
        /* noop */
      }
      try {
        this.musicSource.disconnect();
      } catch {
        /* noop */
      }
    }
    if (this.musicGain) {
      try {
        this.musicGain.disconnect();
      } catch {
        /* noop */
      }
    }
    this.musicSource = null;
    this.musicGain = null;
    this.currentMusicChapter = "";
  }

  private applyAmbientMix(): void {
    if (!this.ambientGain || !this.context) return;
    this.ambientGain.gain.setTargetAtTime(this.ambientMix, this.context.currentTime, 0.1);
  }

  private applyMusicMix(): void {
    if (!this.musicGain || !this.context) return;
    this.musicGain.gain.setTargetAtTime(this.musicMix, this.context.currentTime, 0.1);
  }
}

// 单例
export const audioEngine = new AudioEngine();

// 暴露母题白名单供 UI 层做能力检查
export const ASSET_MOTIFS: ReadonlyArray<AssetMotif> = Object.keys(MOTIF_PATH()) as AssetMotif[];

// 与 store 同步
import { useStore } from "@/lib/store";
useStore.subscribe(
  (s) => s.audioEnabled,
  (enabled) => audioEngine.setMuted(!enabled),
);
useStore.subscribe(
  (s) => s.audioVolume,
  (v) => audioEngine.setVolume(v),
);
