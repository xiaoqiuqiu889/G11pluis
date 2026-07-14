/** @type {import('tailwindcss').Config} */
// 电影感色板：暗色调、暖黄高光、冷蓝阴影、颗粒友好
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // 主调：暗色电影感
        ink: {
          900: "#08080a",
          800: "#0d0d10",
          700: "#14141a",
          600: "#1c1c24",
          500: "#26262f",
          400: "#3a3a45",
        },
        // 暖光（灯泡、黄昏）
        amber: {
          glow: "#d4a155",
          dim: "#7a5a2a",
          soft: "#b88a44",
        },
        // 冷光（夜晚、机场、伊斯坦布尔雨）
        cool: {
          steel: "#5b6b78",
          fog: "#889aa6",
          night: "#2a3340",
        },
        // 血（石榴、记忆、丧失）
        vermillion: {
          500: "#a83a2a",
          300: "#c66a55",
        },
        // 默白（字幕、UI 文字）
        paper: {
          100: "#f1ecdf",
          200: "#d8d2c2",
        },
      },
      fontFamily: {
        // 中文字体栈：衬线优先，匹配小说感
        zh: [
          "Source Han Serif SC",
          "Noto Serif SC",
          "Songti SC",
          "STSong",
          "SimSun",
          "serif",
        ],
        // 拉丁字体：手写体（"你看到了 X"）+ 经典衬线
        en: [
          "EB Garamond",
          "Cormorant Garamond",
          "Source Serif Pro",
          "Georgia",
          "serif",
        ],
        sans: [
          "Inter",
          "system-ui",
          "-apple-system",
          "BlinkMacSystemFont",
          "Helvetica Neue",
          "PingFang SC",
          "sans-serif",
        ],
        mono: ["JetBrains Mono", "Menlo", "Consolas", "monospace"],
      },
      letterSpacing: {
        cinematic: "0.02em",
        wide: "0.08em",
      },
      animation: {
        "fade-in": "fadeIn 800ms ease-out forwards",
        "fade-out": "fadeOut 800ms ease-in forwards",
        "slide-up": "slideUp 600ms ease-out forwards",
        "typewriter": "typewriter 60ms steps(20) forwards",
        "grain-shift": "grainShift 8s steps(8) infinite",
        "flicker": "flicker 3200ms ease-in-out infinite",
      },
      keyframes: {
        fadeIn: { "0%": { opacity: "0" }, "100%": { opacity: "1" } },
        fadeOut: { "0%": { opacity: "1" }, "100%": { opacity: "0" } },
        slideUp: {
          "0%": { transform: "translateY(20px)", opacity: "0" },
          "100%": { transform: "translateY(0)", opacity: "1" },
        },
        typewriter: {
          "0%": { width: "0" },
          "100%": { width: "100%" },
        },
        grainShift: {
          "0%,100%": { transform: "translate(0,0)" },
          "10%": { transform: "translate(-2%,-1%)" },
          "20%": { transform: "translate(1%,2%)" },
          "30%": { transform: "translate(-1%,-2%)" },
          "40%": { transform: "translate(2%,1%)" },
          "50%": { transform: "translate(-2%,1%)" },
          "60%": { transform: "translate(1%,-1%)" },
          "70%": { transform: "translate(-1%,2%)" },
          "80%": { transform: "translate(2%,-2%)" },
          "90%": { transform: "translate(-2%,-1%)" },
        },
        flicker: {
          "0%,100%": { opacity: "1" },
          "92%": { opacity: "1" },
          "93%": { opacity: "0.85" },
          "94%": { opacity: "1" },
          "96%": { opacity: "0.92" },
          "97%": { opacity: "1" },
        },
      },
      backdropBlur: {
        cinematic: "8px",
      },
    },
  },
  plugins: [],
};
