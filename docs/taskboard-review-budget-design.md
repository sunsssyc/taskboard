# Taskboard：把 Agent 产出变成可分诊的审查队列

> 调研日期：2026-08-27
> 状态：A 层已实现；B/C/D 待排期，另有「概念对齐」待补为 E 层

## 问题

Agent 写代码的速度已经超过人读代码的速度，人的时间只够读一部分，但今天**没有依据决定读哪一部分**，于是要么全读（读不完）要么随便读（漏关键改动）。

实测（`taskboard` 仓库近 14 天，40 个提交）：

- 单次提交改动行数中位数 171、p90 1007、最大 8901
- 08-24 一天 7 个提交共 12998 行
- 122 个任务里 `pr` 字段填写数为 **0** —— 审查不发生在 GitHub PR 上，发生在本地提交上

看板已经记了"为什么改"（任务 detail、验收条件、finding），git 记了"改了什么"（diff），**两者之间没有可信映射**。现有的那一条映射是坏的：

- `board done` 只记一个 `git_head_sha()`（[cli.py:143](../taskboard/cli.py:143)、[cli.py:412](../taskboard/cli.py:412)），取的是 **CLI 进程的 cwd**，不是任务关联仓库
- 只有终点没有起点，无法还原区间
- 90 条带 commit 的 done 事件只落在 **56 个不同 SHA** 上，其中 48 条与别的任务共用同一个 SHA。实例：`#30` 与 `#31` 都记 `043a3ef`，`#27` 记的 `9e144b7` 是另一个任务的提交
- 另有 17 条 done 事件完全没有 commit（在仓库外执行 `board done`）

推断：这不是"看板缺一个审查页面"，而是**任务与它产出的代码之间缺一层数据**。没有这层，任何排序、分诊、审查进度都建立在猜测上。已登记的尾巴 [189]「多仓库完成证据仍缺少逐仓库 artifacts」是同一问题的一个切面。

## 方案

四层，后面依赖前面。A 是基础设施，C 才是真正缓解"读不完"的那一层。

### A. 任务提交区间（已实现，任务 #35）

新表 `task_commits(task_id, repository_id, base_sha, head_sha, base_at, head_at)`：

- `todo→active` 时对任务的**每个**关联仓库分别取 HEAD 写 `base_sha`
- `→done` 时同样逐仓库取 HEAD 写 `head_sha`
- 反复 start/done 只更新最后一次 `head_sha`，`base_sha` 保留第一次

顺带修掉 [cli.py:412](../taskboard/cli.py:412) 按 cwd 取 SHA 的缺陷，并闭合尾巴 [189]。

[store.py:633](../taskboard/store.py:633) 已经记录过一个判断：SHA 存在任务字段上会被 squash/rebase 弄失效。这条对本方案同样成立，处理办法是**取不到对象时明说"区间已失效"，不退化成错误的 diff**——审查发生在改动落地后不久，绝大多数情况区间仍然有效。

### B. `board review <ref>`：单任务审查包

一屏内给出判断"这次改动是否兑现了当初的意图"所需的全部材料：

- 任务标题、detail（为什么做）、验收条件
- 逐仓库 diffstat 与变更文件清单（按改动行数排序）
- 命中的 `board link` 关键文件
- 区间内新增或被推翻的 finding

不渲染 diff 本身。`board review <ref> --diff` 直接 exec `git diff base..head`，渲染交给 git/delta。

### C. `board review --queue`：按风险排序，不按时间

这一层直接对抗"读不完"。排序信号全部由现有数据算出，不需要人额外打标：

| 信号 | 数据来源 | 现有存量 |
| --- | --- | --- |
| 改动规模 | A 层区间 + `git diff --shortstat` | — |
| 触碰关键文件 | `notes` 中 `kind='link'` | 31 条 |
| 闸门任务 | `tasks.gate` | 2 条 |
| 期间推翻过结论 | `note_superseded` 事件 | 91 条 |
| 跨仓库 | `task_repositories` | 1 条任务 |
| 无验收条件 | `tasks.accept` 为空 | — |

「触碰关键文件」和「期间推翻过结论」是本项目独有的信号，通用代码审查工具拿不到——这是看板做这件事的正当理由。

输出分三档并附一行理由：**精读 / 扫一眼 / 可跳过**。默认只打印"今天该读的前 N 条"，不打印全量列表——全量列表本身就是过载的一部分。

### D. 审查状态显式化

`done` 不等于 `reviewed`。加 `board reviewed <ref>` 与 `board review --skip <ref> --reason "..."`。

价值不在流程，在于把"我没看"变成**一条可回溯的记录**，而不是默认假装看过。事后出问题时能查到"当时是有意跳过的，理由是 X"，从而修正分诊规则。

### E. 让 Agent 交出审查线索（建议暂不做）

`done` 时要求 Agent 至少产出一条 finding 指出"这次最值得看的一处"。风险是 Agent 自评不可信，可能变成新的噪音源。建议 A~D 用起来之后再判断是否还缺这块。

## 约束与取舍

- finding [24]「一个人 + 一个 AI」：不做 approve/request-changes、不做 reviewer 分配、不做评论线程、不做审查耗时图表。
- 不替代 git/GitHub：不渲染 diff、不做行内评论。看板只回答「读哪些、什么顺序、读到哪了」。
- 不把 AI 自动审查放进默认路径。再加一个 Agent 的输出会加重而不是减轻过载；真要做也只能作为 `--explain` 这类显式开关。
- D 与 [24]「拒绝经典看板噪音」存在张力。理由是它不是团队流程而是**个人审查预算**；如果用一段时间发现 `reviewed` 只是多敲一次键盘、没有改变任何决策，就砍掉。
- 区间依赖 SHA 可达，rebase/squash 后失效，见 A 层处理办法。

## 接入点

- [store.py:622](../taskboard/store.py:622) `set_status`：区间写入的唯一入口，`commit_sha` 单参数扩成逐仓库字典
- [cli.py:412](../taskboard/cli.py:412) `_status_cmd`：改为遍历 `task_repositories` 取 HEAD，不再用 cwd
- [cli.py:143](../taskboard/cli.py:143) `git_head_sha`：已支持 `cwd` 参数，直接复用
- [serve.py:279](../taskboard/serve.py:279) `_git_head`：网页端已按仓库取但只取第一个，一并对齐
- `SCHEMA` 与 `_migrate`（[store.py:93](../taskboard/store.py:93) 起）：加 `task_commits` 表；历史 94 条 done 任务不补录，标记为「区间不完整」
- `snapshot()`（[store.py:959](../taskboard/store.py:959)）：桌面端要展示审查状态就从这里出，保持渲染与 CLI 同一份数据

## 验收

- A：新完成的任务 100% 拿到逐仓库 `base_sha`/`head_sha`；两个同时 `done` 的任务不再共用同一区间
- B：`board review <ref>` 一屏输出，不超过 40 行；跨仓库任务逐仓库分节
- C：给定一天的产出，队列前 3 条覆盖当天全部「触碰关键文件或闸门」的改动；实际使用中人读的比例从「全部或随机」变成可陈述的数字
- D：跳过的任务都带理由，`board log` 可回溯
- 全链路：Python 测试通过，新增用例覆盖多仓库区间、rebase 后 SHA 失效、无验收条件任务的分档

## 排期

1. ~~**A 层区间**~~ —— 已完成，见任务 #35
2. **B 层 `board review <ref>`**（依赖 A，单独就有价值：审查时不用再手工拼 diff 范围）
3. **C 层队列与分诊**（依赖 A/B，是解决过载的主体）
4. **D 层审查状态**（依赖 C，用一段时间再决定去留）
5. E 层暂缓

## 前置决策

- **区间语义**：一个任务多次 start/done，区间怎么算？建议「第一次 base + 最后一次 head」。不定的后果是 review 包里混进期间其他任务的提交，C 层的规模信号随之失真。
- **历史数据**：94 个已完成任务是否补录区间？建议不补，标记区间不完整。不定的后果是队列里混入无法计算规模的任务，排序不可比。
- **`reviewed` 落在哪**：新增 `tasks` 列还是记成 note？建议加列，因为要参与队列排序和 `snapshot()`。不定的后果是 C 层无法过滤已审查项，队列每天重复出现同样的条目。
