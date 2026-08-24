# Taskboard Desktop POC

Tauri v2 + Vue 3 + TypeScript + Pinia 的只读桌面验证。它保留 Python `board` CLI、
SQLite 数据模型和现有 Swift 菜单栏 App，不在 Vue 或 Rust 中复制依赖判断、事件记录或写入语义。

## 数据链路

```text
Vue UI → Tauri load_board command → board export --json → SQLite
```

Rust command 只允许执行 `export --json --show-paths --out -`。本阶段没有任务状态、新建记录或
SQLite 直写入口。

## 开发

要求：

- Node.js `20.19+`、`22.12+` 或 `24+`，不支持奇数版本 Node 23；
- Rust stable；
- Python 3.10+，并能从仓库根目录运行 `python -m taskboard.cli`。

```bash
cd apps/desktop
npm install

# 浏览器预览：使用页面内明确标识的演示数据
npm run dev

# Tauri 桌面窗口：读取 ~/.taskboard/board.db
npm run tauri dev
```

可覆盖数据和 Python 入口：

```bash
TASKBOARD_DB=/path/to/board.db \
TASKBOARD_PYTHON=/path/to/python \
npm run tauri dev
```

若已经安装稳定的 `board` 可执行文件，也可设置 `TASKBOARD_BOARD_EXECUTABLE`。开发构建优先
从仓库根目录运行 Python 模块，避免可编辑安装因仓库改名而失效。

## 验证

```bash
npm run test
npm run build
cargo test --manifest-path src-tauri/Cargo.toml
npm run tauri build -- --no-bundle
```

当前 POC 已按成熟看板视觉迁移全局统计、搜索、状态/负责人筛选、全部/单需求切换、需求任务
大纲、任务 spine、任务详情折叠与结论/风险分类折叠，并覆盖 375px、1440px、1600px 三档
布局。状态写入和 sidecar 正式打包不在本阶段范围内。
