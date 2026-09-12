# Taskboard Desktop

Tauri v2 + Vue 3 + TypeScript + Pinia 的桌面版,同一份 Vue 页面也由 `board serve` 托管。
它保留 Python `board` CLI、SQLite 数据模型和现有 Swift 菜单栏 App,不在 Vue 或 Rust 中
复制依赖判断、事件记录或写入语义。

## 数据链路

```text
读取  Vue UI → Tauri load_board command → board export --json → SQLite
状态  Vue UI → Tauri set_task_status command → board todo/start/wait/done → SQLite
概念  Vue UI → Tauri align_concept / reject_concept / update_concept → board align / concept-edit --json
派发  Vue UI → Tauri dispatch_task_agent → Codex app-server / Claude 官方深链
记录  Tauri → board agent-run → SQLite agent_runs
```

同一套页面也给 `board serve` 用:`src/board.ts` 按 `window.__TAURI_INTERNALS__` /
`window.__TASKBOARD_WEB__` 判断后端,网页模式走同源 `/api/*` 接口(CSRF token 由
serve 注入页面),桌面模式走 Tauri command,两者都没有时用内置演示数据。

Rust 侧只允许 `export --json --show-paths --out -` 读取，以及与 `board serve` 网页同一
白名单的状态切换（待办/进行中/等人工/完成，不含放弃）：点击任务状态胶囊弹出菜单，
「已完成」需在弹层内确认验收条件。依赖判断、事件记录与完成时 HEAD 登记全部由 CLI 执行；
负责人修改同样经 `board edit` 落库；任务派发是与负责人分配分开的显式动作。Codex 通过
官方 app-server 创建线程、提交首轮任务，并用 `codex app <仓库>` 打开桌面工作区；Claude
通过官方 `claude://code/new` 深链预填任务和目录，仍由用户确认目录并发送。看板只保存公开
返回的线程/运行 ID 和派发标识，不读取两个桌面应用的私有数据库。其余写入（新建、放弃、
依赖、结论）仍走 CLI。需求拖动顺序与置顶状态通过数据库旁的
`*.view.json` sidecar 与 Swift 版共享。

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

# 给 board serve 的构建：输出到 ../../taskboard/web,文件名不带 hash,需一起提交
npm run build:web

# 对着运行中的 board serve(默认 8787)开发网页模式:/api 代理过去,页面上下文从 /api/session 取
npm run dev:web
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

Codex 默认优先使用 ChatGPT/Codex 桌面应用内置 CLI，也可设置
`TASKBOARD_CODEX_EXECUTABLE=/path/to/codex`。Claude 派发要求 `/Applications/Claude.app`；
深链只负责预填，不会模拟键盘或绕过目录确认。

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

页面覆盖全局统计、搜索、状态/负责人筛选、全部/单需求切换、需求置顶与拖动排序、需求任务
大纲、任务列表与详情折叠、概念卡区、结论按主题分 Sheet,并在 375px、1440px、1600px 三档
宽度下验证过无横向溢出。任务状态切换只走 CLI 白名单子命令;新建、放弃、依赖、结论等写入
仍在 CLI。
