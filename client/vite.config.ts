import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
import fs from "node:fs";

// 革命街客户端 Vite 配置
// 基础配置：开发服务器、路径别名、生产构建
//
// W12-E2E-fix: 美术/声音文件在 D:/G1-ai-native/assets/，不在 client/public/。
// 用 configureServer hook 添加一个简单中间件：把 /assets/* 直接映射到
// 项目根的 assets/ 目录。生产构建时通过 publicDir 复制到 dist/。
function serveProjectAssets(): Plugin {
  return {
    name: "g1n-serve-project-assets",
    configureServer(server) {
      const assetsRoot = path.resolve(__dirname, "../assets");
      server.middlewares.use("/assets", (req, res, next) => {
        if (!req.url) return next();
        const urlPath = decodeURIComponent(req.url.split("?")[0]);
        const filePath = path.join(assetsRoot, urlPath);
        // 安全：阻止路径遍历
        if (!filePath.startsWith(assetsRoot)) return next();
        if (!fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) {
          return next();
        }
        const ext = path.extname(filePath).toLowerCase();
        const mime = {
          ".png": "image/png",
          ".jpg": "image/jpeg",
          ".jpeg": "image/jpeg",
          ".webp": "image/webp",
          ".svg": "image/svg+xml",
          ".mp3": "audio/mpeg",
          ".ogg": "audio/ogg",
          ".wav": "audio/wav",
        }[ext] || "application/octet-stream";
        res.setHeader("Content-Type", mime);
        res.setHeader("Cache-Control", "public, max-age=31536000, immutable");
        fs.createReadStream(filePath).pipe(res);
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), serveProjectAssets()],
  base: "./",
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    fs: {
      allow: [path.resolve(__dirname), path.resolve(__dirname, "../assets")],
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    target: "es2022",
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom"],
          state: ["zustand"],
        },
      },
    },
  },
  optimizeDeps: {
    include: ["react", "react-dom", "zustand", "react-router-dom"],
  },
});
