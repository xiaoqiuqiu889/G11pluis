// =============================================================================
// 革命街没有尽头 · 声音引擎
// -----------------------------------------------------------------------------
// 基于 _legacy_v6/app/audio-engine.ts 改造。
// 适配决策 2-5：默认静音、用户手势启动、降级链兼容。
// 模式：singleton（audioEngine）供全局使用。
// =============================================================================

type Cue = "choice" | "transition" | "save" | "ending";
type Motif = "photo" | "paper" | "ash" | "ticket" | "email" | string;
type Texture = "projector" | "fluorescent" | "keyboard" | "airport" | "tea" | "rain";

interface ThemePreset {
  tempo: number;
  base: number;
  volume: number;
  melody: number[];
  drum: number[];
}

// Dastgah-e Shur 风格音高集；第二与第六音在半音之间
const SHUR_CENTS = [0, 150, 300, 500, 700, 850, 1000, 1200, 1350, 1500];

// 章节环境声（低通截止、噪声音量）
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

export class AudioEngine {
  private context: AudioContext | null = null;
  private master: GainNode | null = null;
  private ambience: AudioNode[] = [];
  private currentChapter = "";
  private musicTimer: number | null = null;
  private nextNoteTime = 0;
  private musicStep = 0;
  private muted = true; // 决策：默认静音

  /** 用户手势后启动；返回 Promise<started> */
  async start(chapter: string): Promise<boolean> {
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
    return true;
  }

  /** 解锁 / 静音 */
  setMuted(muted: boolean): void {
    this.muted = muted;
    if (this.master && this.context) {
      this.master.gain.cancelScheduledValues(this.context.currentTime);
      this.master.gain.setTargetAtTime(muted ? 0 : 0.62, this.context.currentTime, 0.05);
    }
  }

  setVolume(v: number): void {
    if (this.master && this.context) {
      const target = this.muted ? 0 : Math.max(0, Math.min(1, v));
      this.master.gain.setTargetAtTime(target, this.context.currentTime, 0.05);
    }
  }

  isRunning(): boolean {
    return !!this.context && this.context.state === "running";
  }

  setChapter(chapter: string): void {
    if (!this.context || !this.master || chapter === this.currentChapter) return;
    this.stopAmbience();
    this.stopMusic();
    this.currentChapter = chapter;
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
    this.startPersianTheme(chapter);
  }

  private startPersianTheme(chapter: string): void {
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

  motif(type: Motif): void {
    if (!this.context || !this.master || this.context.state !== "running" || this.muted) return;
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

  stop(): void {
    this.stopMusic();
    this.stopAmbience();
    if (this.context) {
      void this.context.close();
    }
    this.context = null;
    this.master = null;
    this.currentChapter = "";
  }
}

// 单例
export const audioEngine = new AudioEngine();

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
