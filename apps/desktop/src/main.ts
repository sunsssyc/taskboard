import { createApp } from "vue";
import { createPinia } from "pinia";
import App from "./App.vue";
import "./style.css";

async function bootstrap() {
  // vite dev --mode web 通过代理连 board serve,页面里没有注入上下文,先取一次
  if (import.meta.env.MODE === "web" && !window.__TAURI_INTERNALS__ && !window.__TASKBOARD_WEB__) {
    try {
      const response = await fetch("/api/session", { cache: "no-store" });
      if (response.ok) window.__TASKBOARD_WEB__ = await response.json();
    } catch {
      // 拿不到就退回演示数据,页面会明确提示
    }
  }
  createApp(App).use(createPinia()).mount("#app");
}

void bootstrap();
