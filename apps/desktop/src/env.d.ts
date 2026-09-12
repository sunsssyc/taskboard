/// <reference types="vite/client" />

interface Window {
  __TAURI_INTERNALS__?: unknown;
  __TASKBOARD_WEB__?: import("./types").WebContext;
}
