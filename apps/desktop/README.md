# Taskboard Desktop POC

Tauri v2 + Vue 3 + TypeScript + Pinia 的只读桌面验证。它保留 Python `board` CLI、
SQLite 数据模型和现有 Swift 菜单栏 App，不在 Vue 或 Rust 中复制依赖判断、事件记录或写入语义。

## 数据链路

```text
Vue UI → Tauri load_board command → board export --json → SQLite
```

Rust command 只允许执行 `export --json --show-paths --out -`。任务状态、新建记录和 SQLite
仍保持只读；需求拖动顺序与置顶状态通过数据库旁的 `*.view.json` sidecar 与 Swift 版共享。

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

看板每 60 秒自动刷新一次：窗口隐藏时暂停计时，重新可见后立即补一次；手动刷新或
加载进行中时跳过当轮。刷新失败沿用现有行为，保留上一次数据并提示错误。

桌面缩放快捷键：

- `Command/Ctrl + =` 或 `Command/Ctrl + +`：放大 10%；
- `Command/Ctrl + -`：缩小 10%；
- `Command/Ctrl + 0`：恢复 100%。

缩放范围限制为 75%–175%，比例保存在本机 WebView 存储中。

若已经安装稳定的 `board` 可执行文件，也可设置 `TASKBOARD_BOARD_EXECUTABLE`。开发构建优先
从仓库根目录运行 Python 模块，避免可编辑安装因仓库改名而失效。

## 打包与菜单栏壳联动

```bash
npm run tauri build
```

产出 `src-tauri/target/release/bundle/macos/Taskboard Desktop.app`（bundle id
`com.sunsssyc.taskboard`）。命名刻意与 Swift 菜单栏壳的 `Taskboard.app` 区分，
两者可同时安装到 `/Applications`。

Swift 壳的「打开任务看板」按以下顺序唤起本应用：运行中则激活，已安装则启动，
都找不到时回退壳内原生窗口。壳按 `TASKBOARD_DESKTOP_APP` 环境变量、壳 Info.plist 的
`TaskboardDesktopApp` 键、`/Applications` 与 `~/Applications` 的顺序定位 .app，并校验
bundle id 防止唤起壳自身。打包后的 .app 从 Finder 启动时没有终端 PATH，Rust 侧会按
`/opt/anaconda3`、`/opt/homebrew`、`/usr/local`、`~/.local` 的既有约定探测 `board`。

## 验证

```bash
npm run test
npm run build
cargo test --manifest-path src-tauri/Cargo.toml
npm run tauri build -- --no-bundle   # 只验证编译时可跳过打包
```

当前 POC 已按成熟看板视觉迁移全局统计、搜索、状态/负责人筛选、全部/单需求切换、需求置顶/
拖动排序、需求任务大纲、任务 spine、任务详情折叠与结论/风险分类折叠，并覆盖 375px、
1440px、1600px 三档布局。任务状态写入和 sidecar 正式打包不在本阶段范围内。
