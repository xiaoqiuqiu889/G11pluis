import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// 革命街客户端 Vite 配置
// 基础配置：开发服务器、路径别名、生产构建
export default defineConfig({
  plugins: [react()],
  base: "./",
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
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
