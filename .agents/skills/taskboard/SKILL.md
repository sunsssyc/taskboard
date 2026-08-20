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

静态导出默认隐藏数据库和仓库绝对路径，但任务正文、结论、风险、分支名和链接会保留。
发布前检查内容，并用 `-p` 限定准备分享的项目。`board serve` 没有身份认证，默认只应
监听 `127.0.0.1`，不要直接暴露到公网或不可信局域网。
