---
name: taskboard
description: 用 board CLI 查看和更新跨对话的需求/工作流看板。适用于接手长任务、询问进度或下一步、确认关联仓库、记录已定结论与遗留风险，以及导出看板给别人查看。
---

# 任务看板

`board` 是面向个人与 AI Agent 的本地任务看板。左侧一级实体是可持续推进的**需求/工作流**，
不是代码仓库；执行任务位于需求之下，仓库是需求和任务的关联标签与交付坐标。数据默认存放在
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

## 初始化需求前确认目标与仓库

只有目标稳定、包含多个步骤、可能跨对话推进的事项才初始化为一级需求。创建前先明确：

- 需求名称、一句话目标和范围边界；
- 涉及哪些代码仓库（允许多个）；
- 用户是否认可这个需求与仓库集合。

如果仓库是从 cwd、对话或代码引用中推断的，先把候选仓库列给用户确认；用户已经在当前请求中
明确给出仓库集合时，不重复询问。不要静默把当前目录当成唯一仓库。确认后使用重复的 `--repo`：

```bash
board init registration-calibration --name "注册风控模型校准" \
  --summary "修复时代误伤并重构训练数据" \
  --repo /path/to/coinex_backend \
  --repo /path/to/coinex_anti_fraud_service \
  --repo /path/to/coinex_admin_frontend
```

已有需求可用 `board set -p <key> --repo <path> [--repo <path>...]` 替换关联仓库。

仓库只是改名或换了目录时,用 `board repo-move <原名或原路径> <新路径>` 迁移,已有任务关联
跟着走；此时不要用 `board set --repo`,它会把旧路径当成解除关联而被任务占用挡下。

## 确定当前需求

需求解析优先级是：

1. `-p <key>` 显式指定（参数名 `--project` 为兼容保留，语义是需求）。
2. 当前目录落在需求关联的仓库路径下，且只匹配一个需求。
3. `board use <key>` 固定的需求。
4. 数据库中只有一个未归档需求。

同一仓库可能服务多个需求；匹配多个时必须要求用户用 `-p` 指定，不要猜。

## 推进任务时同步状态

```bash
board start <ref>
board wait <ref>       # 等人工或外部动作，不等同于依赖阻塞
board done <ref>       # 对照验收条件，记录当前 Git HEAD，提示新解锁任务
board add "动作标题" --detail "做什么以及为什么" --owner 我|你|双方 --priority P0|P1|P2|P3
board dep <ref> --on <ref>
```

标题写成动作，详情说明范围和原因。`--gate` 用于会阻塞大片后续工作的关键节点，
`--accept` 写可检查的验收条件，`--branch` 和 `--pr` 记录代码坐标。

### 创建任务时必须明确优先级

每个正式任务节点创建时都要显式传 `--priority`，不要依赖兼容旧调用的 P2 默认值：

- `P0`：当前最高优先级，紧急故障、硬阻塞或必须立即处理的事项；
- `P1`：本轮应优先完成的核心路径；
- `P2`：常规计划内任务；
- `P3`：低优先级优化或可延后事项。

优先级是动态的执行判断，不是创建时的永久标签。依赖解除、风险暴露、用户目标或时间窗口变化时，
应使用 `board edit <ref> -p <key> --priority P0|P1|P2|P3` 合理调整，并在任务详情或 finding
中记录会影响后续判断的原因。`board next` 与界面中的“可开工”任务按 P0 到 P3 排序；界面先展示
最高的三项，其余默认折叠，避免低优先级任务挤占当前注意力。

创建正式任务时同时确定它涉及需求仓库集合中的哪几个仓库。需求只有一个仓库时可自动继承；
需求涉及多个仓库时，如果当前请求没有明确任务范围，先向用户列出仓库并确认，再重复传 `--repo`：

```bash
board add "发布三端采样契约" -p registration-calibration \
  --priority P1 \
  --repo coinex_backend --repo coinex_anti_fraud_service --repo coinex_admin_frontend
```

不能把需求外的仓库直接挂到任务上；先确认是否扩大需求范围。已有任务用
`board edit <ref> -p <key> --repo <name> [--repo <name>...]` 修正关联。

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
board finding "结论" --category "模型口径" --metric "关键数字" --body "证据与推论"
board risk "遗留风险" --category "发布协同" --body "为什么暂不阻塞主线"
board link "path/to/file" --category "关键入口" --body "文件用途"
board note-category <id...> --category "模型口径"
```

同一需求复用 2~6 个稳定分类，使用短名词主题（例如“模型口径”“事实补录”“发布协同”），
不要按日期、任务状态或单条结论临时造分类。写新记录前先看 `board notes` 已有分组；没有合适
主题时再新增。旧记录没有分类时会显示在“未分类”，确认主题后用 `board note-category` 回填。

### 分类是写入要求

- 写 `finding`、`risk` 或 `link` 前，先运行 `board notes -p <key>`，复用该需求已有分类原名。
- 主题能够判断时必须传 `--category`；不要为了省事把新记录留在“未分类”。
- 只有现有分类无法覆盖、且新主题预计会复用时才新增分类；分类保持 2~6 个，避免同义词分裂。
- 分类描述“讨论主题”，不描述日期、任务状态、分支、提交或单条事件。
- 新 finding 推翻旧 finding 时，默认沿用旧记录分类；只有核心主题确实变化时才改分类。
- 遇到本次工作直接相关且语义明确的未分类记录，可用 `board note-category` 一并回填；不要借机
  批量重分无关项目或不确定记录。

只在旧 finding 的核心判断已经失效、且新 finding 能完整替代它时使用 `supersede`。
修复缺陷、补充证据、增加适用边界或推进交付状态时，如果旧判断仍成立，就并列记录。
误标时用 `board restore <旧记录ID>`。

## 给用户查看

```bash
board serve --open
board export -p <key> --out board.html
board export --json --out board.json
```

`board serve` 的本机页面可按需求搜索/筛选、查看任务正文与事件历史，并轻量执行状态切换、新建
任务和记录 finding。完成操作会要求确认验收条件，并从任务所属项目登记的 `repo` 读取
HEAD。复杂依赖、闸门、supersede、风险/文件记录和长篇内容仍使用 CLI；不要为了点网页
而把结构化信息压成一段难读文本。

静态导出默认隐藏数据库和仓库绝对路径，但任务正文、结论、风险、分支名和链接会保留。
发布前检查内容，并用 `-p` 限定准备分享的项目。静态导出只有搜索筛选，不包含写入控件。
`board serve` 没有用户身份认证，网页写入仅在 loopback 监听时启用，并校验同源与 CSRF；
不要直接暴露到公网或不可信局域网。
