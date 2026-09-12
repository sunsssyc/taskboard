import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// --mode web:给 board serve 托管的构建,输出到 Python 包内 taskboard/web,
// 文件名不带 hash,这样提交到仓库的构建产物只在内容变化时产生 diff。
export default defineConfig(({ mode }) => {
  const web = mode === "web";
  return {
    plugins: [vue()],
    clearScreen: false,
    server: {
      port: 1420,
      strictPort: true,
      proxy: web
        ? {
            "/api": "http://127.0.0.1:8787",
            "/state.json": "http://127.0.0.1:8787",
          }
        : undefined,
    },
    envPrefix: ["VITE_", "TAURI_"],
    build: {
      target: "es2022",
      outDir: web ? "../../taskboard/web" : "dist",
      emptyOutDir: true,
      rollupOptions: web
        ? {
            output: {
              entryFileNames: "assets/[name].js",
              chunkFileNames: "assets/[name].js",
              assetFileNames: "assets/[name][extname]",
            },
          }
        : undefined,
    },
  };
});
