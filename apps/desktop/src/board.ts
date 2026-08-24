import { invoke } from "@tauri-apps/api/core";
import { demoSnapshot } from "./demo";
import type { BoardLoadResponse } from "./types";

export async function loadBoardSnapshot(): Promise<BoardLoadResponse> {
  if (!window.__TAURI_INTERNALS__) {
    return {
      snapshot: demoSnapshot,
      source: "浏览器演示数据",
    };
  }
  return invoke<BoardLoadResponse>("load_board");
}
