---
name: taskboard
description: 用 board CLI 查看和更新本地跨项目任务看板。适用于接手长任务、询问进度或下一步、记录已定结论与遗留风险，以及导出看板给别人查看。
---

# 任务看板

`board` 是面向个人与 AI Agent 的本地任务看板。数据默认存放在
`~/.taskboard/board.db`，也可以用 `TASKBOARD_HOME` 或全局 `--db` 覆盖。

如果还没有 `board` 命令，先在 claude-taskboard 源码目录执行：

```bash
python -m pip install -e .
```

## 接手工作先读状态

```bash
board next     # 当前可开工任务；排除未完成前置和 waiting
board notes    # 有效 finding、risk 和 link
```

`finding` 是已经查明、会约束后续决策的结论。先读已有结论，不要在新会话中重复推演。
需要更多上下文时使用 `board brief`、`board ls`、`board show <ref>`、`board log` 或
`board projects`。

## 确定当前项目

项目解析优先级是：

1. `-p <key>` 显式指定。
2. 当前目录落在项目登记的 `repo` 路径下。
3. `board use <key>` 固定的项目。
4. 数据库中只有一个未归档项目。

解析失败时要求用户指定，不要猜项目。

## 推进任务时同步状态

```bash
board start <ref>
board wait <ref>       # 等人工或外部动作，不等同于依赖阻塞
board done <ref>       # 对照验收条件，记录当前 Git HEAD，提示新解锁任务
board add "动作标题" --detail "做什么以及为什么" --owner 我|你|双方
board dep <ref> --on <ref>
```

标题写成动作，详情说明范围和原因。`--gate` 用于会阻塞大片后续工作的关键节点，
`--accept` 写可检查的验收条件，`--branch` 和 `--pr` 记录代码坐标。

## 用 Markdown 写可扫读内容

标题保持单行、直接写结论或动作，不要塞 Markdown。`metric` 只放最关键的数字和口径。
任务 `detail`、记录 `body` 与验收条件可以使用 Markdown；长内容优先按下面顺序组织：

```markdown
**影响**：这项结论会改变什么。

- `证据`：支持判断的代码、数据或实测结果。
- `决定`：后续以什么为准。
- `边界`：仍未验证或不在本次范围内的部分。
```

字段名、函数、命令和路径用反引号；多条事实使用列表；短命令或必要片段才用代码块。
不要粘贴整段日志，也不要使用原始 HTML、图片、表格或复杂嵌套列表；把完整材料放到文件里，
再用 `board link` 记录入口。

CLI 参数必须包含**真实换行**。bash/zsh 中使用 ANSI-C 引号，例如：

```bash
board finding "结论" --body $'**影响**：一句话。\n\n- `证据`：已验证'
```

不要写 `--body "第一段\n\n第二段"`：shell 双引号不会展开 `\n`，CLI 会将这种疑似错误
写法拒绝；正文中的反引号还可能被 shell 当成命令替换。多行 Markdown 参数统一使用
ANSI-C 单引号。如果确实要展示转义符，把它放进行内代码，例如 `` `\n\n` ``。

## 沉淀结论与风险

```bash
board finding "结论" --metric "关键数字" --body "证据与推论"
board risk "遗留风险" --body "为什么暂不阻塞主线"
board link "path/to/file" --body "文件用途"
```

只在旧 finding 的核心判断已经失效、且新 finding 能完整替代它时使用 `supersede`。
修复缺陷、补充证据、增加适用边界或推进交付状态时，如果旧判断仍成立，就并列记录。
误标时用 `board restore <旧记录ID>`。

## 给用户查看

```bash
board serve --open
board export -p <key> --out board.html
board export --json --out board.json
```

`board serve` 的本机页面可搜索/筛选、查看任务正文与事件历史，并轻量执行状态切换、新建
任务和记录 finding。完成操作会要求确认验收条件，并从任务所属项目登记的 `repo` 读取
HEAD。复杂依赖、闸门、supersede、风险/文件记录和长篇内容仍使用 CLI；不要为了点网页
而把结构化信息压成一段难读文本。

静态导出默认隐藏数据库和仓库绝对路径，但任务正文、结论、风险、分支名和链接会保留。
发布前检查内容，并用 `-p` 限定准备分享的项目。静态导出只有搜索筛选，不包含写入控件。
`board serve` 没有用户身份认证，网页写入仅在 loopback 监听时启用，并校验同源与 CSRF；
不要直接暴露到公网或不可信局域网。
