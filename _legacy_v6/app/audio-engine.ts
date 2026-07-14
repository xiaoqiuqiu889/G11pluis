type Cue="choice"|"transition"|"save"|"ending";
type Motif="photo"|"paper"|"ash"|"ticket"|"email"|string;
type Texture="projector"|"fluorescent"|"keyboard"|"airport"|"tea"|"rain";

type ThemePreset={tempo:number;base:number;volume:number;melody:number[];drum:number[]};

const chapterSound:Record<string,{cutoff:number;volume:number}>= {
  prologue:{cutoff:720,volume:.012},chapter1:{cutoff:1050,volume:.014},chapter2:{cutoff:520,volume:.016},
  chapter3:{cutoff:430,volume:.017},chapter4:{cutoff:820,volume:.011},chapter5:{cutoff:680,volume:.010},ending:{cutoff:560,volume:.009},
};

// Dastgah-e Shur inspired pitch collection: the second and sixth sit between piano keys.
// The melody is original and intentionally sparse so it remains beneath the text.
const shurCents=[0,150,300,500,700,850,1000,1200,1350,1500];
const themes:Record<string,ThemePreset>={
  prologue:{tempo:72,base:146.83,volume:.015,melody:[0,-1,3,-1,2,-1,1,-1,0,-1,4,-1,3,-1,1,-1],drum:[0,6,10]},
  chapter1:{tempo:84,base:146.83,volume:.019,melody:[0,2,3,-1,4,3,2,1,0,-1,3,4,5,4,3,-1],drum:[0,4,7,10,14]},
  chapter2:{tempo:68,base:130.81,volume:.014,melody:[0,-1,1,2,-1,1,0,-1,3,-1,2,1,-1,0,-1,-1],drum:[0,9]},
  chapter3:{tempo:76,base:130.81,volume:.016,melody:[0,-1,3,2,1,-1,0,-1,4,3,-1,2,1,-1,0,-1],drum:[0,6,11]},
  chapter4:{tempo:78,base:146.83,volume:.014,melody:[0,3,-1,4,5,-1,4,3,2,-1,1,0,-1,2,1,-1],drum:[0,8]},
  chapter5:{tempo:66,base:146.83,volume:.013,melody:[0,-1,1,-1,3,2,-1,1,0,-1,4,-1,3,1,-1,-1],drum:[0,10]},
  ending:{tempo:60,base:130.81,volume:.012,melody:[0,-1,3,-1,2,-1,1,-1,0,-1,3,-1,1,-1,0,-1],drum:[0]},
};

export class AudioEngine{
  private context:AudioContext|null=null;
  private master:GainNode|null=null;
  private ambience:AudioNode[]=[];
  private currentChapter="";
  private musicTimer:number|null=null;
  private nextNoteTime=0;
  private musicStep=0;

  async start(chapter:string){
    if(!this.context){
      this.context=new AudioContext();this.master=this.context.createGain();this.master.gain.value=.62;this.master.connect(this.context.destination);
    }
    if(this.context.state==="suspended")await this.context.resume();
    this.setChapter(chapter);
  }

  setChapter(chapter:string){
    if(!this.context||!this.master||chapter===this.currentChapter)return;
    this.stopAmbience();this.stopMusic();this.currentChapter=chapter;
    const ambience=chapterSound[chapter]||chapterSound.prologue;
    const buffer=this.context.createBuffer(1,this.context.sampleRate*2,this.context.sampleRate);
    const data=buffer.getChannelData(0);let brown=0;
    for(let i=0;i<data.length;i+=1){const white=Math.random()*2-1;brown=(brown+.02*white)/1.02;data[i]=brown*2.2}
    const noise=this.context.createBufferSource();noise.buffer=buffer;noise.loop=true;
    const filter=this.context.createBiquadFilter();filter.type="lowpass";filter.frequency.value=ambience.cutoff;
    const noiseGain=this.context.createGain();noiseGain.gain.value=ambience.volume;
    noise.connect(filter).connect(noiseGain).connect(this.master);noise.start();this.ambience=[noise,filter,noiseGain];
    this.startPersianTheme(chapter);
  }

  private startPersianTheme(chapter:string){
    if(!this.context||!this.master)return;
    const preset=themes[chapter]||themes.prologue;this.nextNoteTime=this.context.currentTime+.06;this.musicStep=0;
    const schedule=()=>{
      if(!this.context||this.context.state!=="running")return;
      const stepDuration=60/preset.tempo/2;
      while(this.nextNoteTime<this.context.currentTime+.28){
        const note=preset.melody[this.musicStep%preset.melody.length];
        if(note>=0){
          const frequency=preset.base*Math.pow(2,shurCents[note]/1200);
          this.pluck(frequency,this.nextNoteTime,preset.volume,this.musicStep%4===0);
          if(this.musicStep%8===6)this.santurSpark(frequency*2,this.nextNoteTime+.035,preset.volume*.55);
        }
        if(preset.drum.includes(this.musicStep%16))this.tombak(this.nextNoteTime,this.musicStep%16===0);
        this.nextNoteTime+=stepDuration;this.musicStep+=1;
      }
    };
    schedule();this.musicTimer=window.setInterval(schedule,90);
  }

  private pluck(frequency:number,time:number,volume:number,accent:boolean){
    if(!this.context||!this.master)return;
    const osc=this.context.createOscillator();const overtone=this.context.createOscillator();const gain=this.context.createGain();const filter=this.context.createBiquadFilter();
    osc.type="triangle";overtone.type="sine";osc.frequency.setValueAtTime(frequency,time);overtone.frequency.setValueAtTime(frequency*2.01,time);
    filter.type="lowpass";filter.frequency.setValueAtTime(1800,time);filter.frequency.exponentialRampToValueAtTime(520,time+.72);
    const peak=volume*(accent?1.18:1);gain.gain.setValueAtTime(.0001,time);gain.gain.exponentialRampToValueAtTime(peak,time+.012);gain.gain.exponentialRampToValueAtTime(.0001,time+.78);
    osc.connect(filter);overtone.connect(filter);filter.connect(gain).connect(this.master);osc.start(time);overtone.start(time);osc.stop(time+.8);overtone.stop(time+.55);
  }

  private santurSpark(frequency:number,time:number,volume:number){
    if(!this.context||!this.master)return;
    for(const offset of [0,.022]){const osc=this.context.createOscillator();const gain=this.context.createGain();osc.type="triangle";osc.frequency.value=frequency*(offset?1.004:1);gain.gain.setValueAtTime(.0001,time+offset);gain.gain.exponentialRampToValueAtTime(volume,time+offset+.006);gain.gain.exponentialRampToValueAtTime(.0001,time+offset+.34);osc.connect(gain).connect(this.master);osc.start(time+offset);osc.stop(time+offset+.36)}
  }

  private tombak(time:number,accent:boolean){
    if(!this.context||!this.master)return;
    const buffer=this.context.createBuffer(1,Math.floor(this.context.sampleRate*.16),this.context.sampleRate);const data=buffer.getChannelData(0);
    for(let i=0;i<data.length;i+=1)data[i]=(Math.random()*2-1)*Math.pow(1-i/data.length,3);
    const source=this.context.createBufferSource();source.buffer=buffer;const filter=this.context.createBiquadFilter();filter.type="bandpass";filter.frequency.value=accent?145:240;filter.Q.value=1.4;
    const gain=this.context.createGain();gain.gain.setValueAtTime(accent?.018:.011,time);gain.gain.exponentialRampToValueAtTime(.0001,time+.15);source.connect(filter).connect(gain).connect(this.master);source.start(time);source.stop(time+.17);
  }

  motif(type:Motif){
    if(!this.context||!this.master||this.context.state!=="running")return;
    const now=this.context.currentTime;const patterns:Record<string,[number,number,number]>={photo:[246.94,220,.34],paper:[329.63,293.66,.28],ash:[92.5,73.4,.42],ticket:[196,246.94,.24],email:[440,392,.18]};
    const [from,to,duration]=patterns[type]||patterns.paper;const oscillator=this.context.createOscillator();const gain=this.context.createGain();const filter=this.context.createBiquadFilter();
    oscillator.type=type==="ash"?"sawtooth":type==="photo"?"sine":"triangle";oscillator.frequency.setValueAtTime(from,now);oscillator.frequency.exponentialRampToValueAtTime(to,now+duration);filter.type="lowpass";filter.frequency.value=type==="ash"?240:1200;
    gain.gain.setValueAtTime(.0001,now);gain.gain.exponentialRampToValueAtTime(type==="ash"?.012:.022,now+.025);gain.gain.exponentialRampToValueAtTime(.0001,now+duration);oscillator.connect(filter).connect(gain).connect(this.master);oscillator.start(now);oscillator.stop(now+duration+.02);
  }

  texture(type:Texture){
    if(!this.context||!this.master||this.context.state!=="running")return;
    const now=this.context.currentTime;const duration=type==="projector"?1.1:type==="rain"?.9:.42;
    const buffer=this.context.createBuffer(1,Math.floor(this.context.sampleRate*duration),this.context.sampleRate);const data=buffer.getChannelData(0);
    for(let i=0;i<data.length;i+=1){const falloff=Math.pow(1-i/data.length,type==="rain"?.45:1.8);data[i]=(Math.random()*2-1)*falloff}
    const source=this.context.createBufferSource();source.buffer=buffer;const filter=this.context.createBiquadFilter();const gain=this.context.createGain();
    const profiles:Record<Texture,[BiquadFilterType,number,number]>={projector:["lowpass",310,.008],fluorescent:["bandpass",118,.004],keyboard:["highpass",1800,.007],airport:["bandpass",620,.006],tea:["highpass",2400,.006],rain:["lowpass",1100,.008]};
    const [filterType,frequency,peak]=profiles[type];filter.type=filterType;filter.frequency.value=frequency;gain.gain.setValueAtTime(.0001,now);gain.gain.linearRampToValueAtTime(peak,now+.025);gain.gain.exponentialRampToValueAtTime(.0001,now+duration);
    source.connect(filter).connect(gain).connect(this.master);source.start(now);source.stop(now+duration+.02);
    if(type==="projector"||type==="fluorescent"){
      const hum=this.context.createOscillator();const humGain=this.context.createGain();hum.type="sine";hum.frequency.value=type==="projector"?48:100;humGain.gain.setValueAtTime(.0001,now);humGain.gain.linearRampToValueAtTime(type==="projector"?.006:.003,now+.03);humGain.gain.exponentialRampToValueAtTime(.0001,now+duration);hum.connect(humGain).connect(this.master);hum.start(now);hum.stop(now+duration+.02);
    }
  }

  cue(type:Cue){
    if(!this.context||!this.master||this.context.state!=="running")return;
    const now=this.context.currentTime;const oscillator=this.context.createOscillator();const gain=this.context.createGain();const frequencies:Record<Cue,[number,number]>={choice:[392,523.25],transition:[146.8,196],save:[659.25,783.99],ending:[220,329.63]};
    oscillator.type=type==="transition"?"sine":"triangle";oscillator.frequency.setValueAtTime(frequencies[type][0],now);oscillator.frequency.exponentialRampToValueAtTime(frequencies[type][1],now+.18);gain.gain.setValueAtTime(.0001,now);gain.gain.exponentialRampToValueAtTime(.024,now+.025);gain.gain.exponentialRampToValueAtTime(.0001,now+.28);oscillator.connect(gain).connect(this.master);oscillator.start(now);oscillator.stop(now+.3);
  }

  private stopMusic(){if(this.musicTimer!==null){window.clearInterval(this.musicTimer);this.musicTimer=null}}
  private stopAmbience(){for(const node of this.ambience){if("stop" in node){try{(node as AudioScheduledSourceNode).stop()}catch{}}try{node.disconnect()}catch{}}this.ambience=[]}
  stop(){this.stopMusic();this.stopAmbience();if(this.context)void this.context.close();this.context=null;this.master=null;this.currentChapter=""}
}
