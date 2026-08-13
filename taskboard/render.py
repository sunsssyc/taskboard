"""把状态快照渲染成自包含 HTML(无外部资源,可直接发布)。

视觉语言:冷石板中性色 + 汽油蓝主色,状态用语义色单独承载;标题无衬线、
数据等宽、结论用衬线以区别"叙述"与"状态"。明暗主题按 token 三态定义。
"""
from __future__ import annotations

import html
import json
from datetime import datetime

STATUS_LABEL = {'todo': '待办', 'active': '进行中', 'done': '已完成', 'dropped': '已放弃'}

STYLE = """
:root {
  --ground:#eef2f2; --surface:#fbfcfc; --sunken:#e4eaea; --rule:#cfd9d9; --rule-soft:#dde5e5;
  --ink:#121a1b; --ink-muted:#566264; --ink-faint:#7c8a8c;
  --accent:#0e6b78; --accent-soft:#d9ebee;
  --done:#2b6f52; --done-soft:#dcece4; --active:#8f5a0c; --active-soft:#f6e8cf;
  --wait:#63706f; --wait-soft:#e2e8e8; --alert:#9b3529; --alert-soft:#f5e0dc;
  --shadow:0 1px 2px rgba(18,26,27,.06), 0 6px 16px -10px rgba(18,26,27,.18);
  --sans:system-ui,-apple-system,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
  --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
  --serif:Georgia,"Songti SC","Noto Serif CJK SC",serif;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --ground:#0d1213; --surface:#151d1e; --sunken:#101718; --rule:#26312f; --rule-soft:#1d2626;
    --ink:#e3ecec; --ink-muted:#96a4a5; --ink-faint:#758385;
    --accent:#4fbecb; --accent-soft:#10313a;
    --done:#5cb188; --done-soft:#142b22; --active:#d39c42; --active-soft:#2e2413;
    --wait:#8d9a9a; --wait-soft:#1c2424; --alert:#dd7a70; --alert-soft:#2f1a18;
    --shadow:0 1px 2px rgba(0,0,0,.4), 0 8px 20px -12px rgba(0,0,0,.6);
  }
}
:root[data-theme="dark"] {
  --ground:#0d1213; --surface:#151d1e; --sunken:#101718; --rule:#26312f; --rule-soft:#1d2626;
  --ink:#e3ecec; --ink-muted:#96a4a5; --ink-faint:#758385;
  --accent:#4fbecb; --accent-soft:#10313a;
  --done:#5cb188; --done-soft:#142b22; --active:#d39c42; --active-soft:#2e2413;
  --wait:#8d9a9a; --wait-soft:#1c2424; --alert:#dd7a70; --alert-soft:#2f1a18;
  --shadow:0 1px 2px rgba(0,0,0,.4), 0 8px 20px -12px rgba(0,0,0,.6);
}
* { box-sizing: border-box; }
body {
  margin:0; background:var(--ground); color:var(--ink); font-family:var(--sans);
  font-size:15px; line-height:1.6; -webkit-font-smoothing:antialiased;
  overflow-wrap:break-word;
}
.wrap { max-width:1060px; margin:0 auto; padding:38px 24px 72px; display:flex; flex-direction:column; gap:32px; }
.eyebrow { font-family:var(--mono); font-size:11px; letter-spacing:.13em; text-transform:uppercase; color:var(--ink-faint); }
h1 { margin:0; font-size:clamp(25px,4vw,32px); letter-spacing:-.022em; font-weight:620; text-wrap:balance; }
.masthead { display:flex; flex-direction:column; gap:8px; }
.meta-line { display:flex; flex-wrap:wrap; gap:6px 18px; font-family:var(--mono); font-size:11.5px; color:var(--ink-faint); }

.overview { display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:12px; }
.pcard { background:var(--surface); border:1px solid var(--rule); border-radius:4px; padding:14px 16px;
         display:flex; flex-direction:column; gap:9px; box-shadow:var(--shadow); }
.pcard a { color:inherit; text-decoration:none; }
.pcard a:hover { color:var(--accent); }
.pcard a:focus-visible { outline:2px solid var(--accent); outline-offset:3px; border-radius:2px; }
.pcard h3 { margin:0; font-size:15px; font-weight:620; letter-spacing:-.006em; }
.pcard .key { font-family:var(--mono); font-size:11px; color:var(--ink-faint); }
.bar { height:5px; border-radius:3px; background:var(--sunken); overflow:hidden; display:flex; }
.bar i { display:block; height:100%; }
.bar i.done { background:var(--done); }
.bar i.active { background:var(--active); }
.counts { display:flex; gap:12px; font-family:var(--mono); font-size:11.5px; font-variant-numeric:tabular-nums; color:var(--ink-muted); }
.counts b { font-weight:600; }
.nextline { font-size:13px; color:var(--ink-muted); }
.nextline span { color:var(--ink-faint); }

section { display:flex; flex-direction:column; gap:14px; }
.sec-head { display:flex; align-items:baseline; gap:12px; flex-wrap:wrap; border-bottom:1px solid var(--rule); padding-bottom:9px; }
.sec-head h2 { margin:0; font-size:17px; font-weight:620; letter-spacing:-.01em; }
.sec-head .key { font-family:var(--mono); font-size:11.5px; color:var(--ink-faint); }
.sec-head p { margin:0; font-size:13px; color:var(--ink-muted); flex:1 1 240px; }

.spine { display:flex; flex-direction:column; }
.step { display:grid; grid-template-columns:32px 1fr; gap:13px; position:relative; padding-bottom:11px; }
.step::before { content:""; position:absolute; left:15px; top:25px; bottom:0; width:1px; background:var(--rule); }
.step:last-child::before { display:none; }
.node { width:31px; height:31px; border-radius:50%; display:grid; place-items:center; z-index:1;
        font-family:var(--mono); font-size:12px; font-variant-numeric:tabular-nums;
        background:var(--surface); border:1px solid var(--rule); color:var(--ink-muted); }
.step[data-status="done"] .node { background:var(--done-soft); border-color:var(--done); color:var(--done); }
.step[data-status="active"] .node { background:var(--active-soft); border-color:var(--active); color:var(--active); font-weight:700; }
.step[data-status="dropped"] .node { color:var(--ink-faint); opacity:.6; }
.card { background:var(--surface); border:1px solid var(--rule); border-radius:4px; padding:12px 15px;
        display:flex; flex-direction:column; gap:6px; box-shadow:var(--shadow); }
.step[data-status="active"] .card { border-left:3px solid var(--active); }
.step[data-status="done"] .card { background:var(--sunken); box-shadow:none; }
.step[data-status="dropped"] .card { opacity:.55; }
.card-top { display:flex; flex-wrap:wrap; gap:7px 11px; align-items:center; }
.card-top h3 { margin:0; font-size:14.5px; font-weight:600; letter-spacing:-.004em; flex:1 1 auto; min-width:180px; }
.step[data-status="dropped"] .card-top h3 { text-decoration:line-through; }
.card p { margin:0; font-size:13.5px; color:var(--ink-muted); max-width:76ch; }
.chip { font-family:var(--mono); font-size:10.5px; letter-spacing:.06em; text-transform:uppercase;
        padding:3px 8px; border-radius:2px; white-space:nowrap; border:1px solid transparent; }
.chip.done { background:var(--done-soft); color:var(--done); border-color:var(--done); }
.chip.active { background:var(--active-soft); color:var(--active); border-color:var(--active); }
.chip.todo { background:var(--wait-soft); color:var(--wait); border-color:var(--rule); }
.chip.dropped { background:var(--wait-soft); color:var(--ink-faint); border-color:var(--rule); }
.chip.gate { background:var(--alert-soft); color:var(--alert); border-color:var(--alert); }
.chip.who { background:var(--accent-soft); color:var(--accent); }
.chip.ready { background:var(--accent-soft); color:var(--accent); border-color:var(--accent); }
.dep { font-family:var(--mono); font-size:11.5px; color:var(--ink-faint); }
.dep b { color:var(--alert); font-weight:600; }

.notes { display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:12px; }
.note { background:var(--surface); border:1px solid var(--rule); border-radius:4px; padding:13px 15px;
        display:flex; flex-direction:column; gap:5px; }
.note.risk { border-left:3px solid var(--alert); }
.note h4 { margin:0; font-size:13.5px; font-weight:620; }
.note p { margin:0; font-family:var(--serif); font-size:14px; line-height:1.6; color:var(--ink-muted); }
.note .metric { font-family:var(--mono); font-size:11.5px; font-variant-numeric:tabular-nums; color:var(--accent); }
.linklist { display:flex; flex-direction:column; gap:5px; font-size:13.5px; color:var(--ink-muted); }
.linklist code { font-family:var(--mono); font-size:12.5px; background:var(--sunken); padding:1px 5px;
                 border-radius:2px; color:var(--ink); overflow-wrap:anywhere; }
.empty { font-size:13.5px; color:var(--ink-faint); }
footer { border-top:1px solid var(--rule); padding-top:14px; font-family:var(--mono); font-size:11.5px;
         color:var(--ink-faint); display:flex; flex-wrap:wrap; gap:6px 20px; }
"""

LIVE_SCRIPT = """
<script>
(function () {
  var current = null;
  async function poll() {
    try {
      var res = await fetch('state.json', { cache: 'no-store' });
      var text = await res.text();
      if (current === null) { current = text; }
      else if (text !== current) { location.reload(); return; }
    } catch (err) { /* 服务停了就静默重试 */ }
    setTimeout(poll, 2000);
  }
  poll();
})();
</script>
"""


def esc(value) -> str:
    return html.escape(str(value if value is not None else ''), quote=True)


def _fmt_stamp(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime('%Y-%m-%d %H:%M UTC')
    except (TypeError, ValueError):
        return iso or ''


def _project_next(project: dict) -> dict | None:
    for task in project['tasks']:
        if task['status'] == 'active' and task['actionable']:
            return task
    for task in project['tasks']:
        if task['actionable']:
            return task
    return None


def _overview_card(project: dict) -> str:
    counts = project['counts']
    total = sum(counts.values()) or 1
    done_pct = counts['done'] / total * 100
    active_pct = counts['active'] / total * 100
    nxt = _project_next(project)
    next_html = (
        f'<div class="nextline"><span>下一步 #{nxt["ref"]}</span> {esc(nxt["title"])}</div>'
        if nxt else '<div class="nextline"><span>没有可动的任务</span></div>'
    )
    gates = (
        f'<div class="nextline"><span>闸门</span> #{", #".join(str(g) for g in project["gates"])}</div>'
        if project['gates'] else ''
    )
    return f"""      <div class="pcard">
        <div class="key">{esc(project['key'])}</div>
        <h3><a href="#p-{esc(project['key'])}">{esc(project['name'])}</a></h3>
        <div class="bar"><i class="done" style="width:{done_pct:.1f}%"></i><i class="active" style="width:{active_pct:.1f}%"></i></div>
        <div class="counts"><span>完成 <b>{counts['done']}</b></span><span>进行 <b>{counts['active']}</b></span><span>待办 <b>{counts['todo']}</b></span></div>
        {next_html}{gates}
      </div>"""


def _task_card(task: dict) -> str:
    chips = [f'<span class="chip {task["status"]}">{STATUS_LABEL[task["status"]]}</span>']
    if task['owner']:
        chips.append(f'<span class="chip who">{esc(task["owner"])}</span>')
    if task['gate'] and task['status'] != 'done':
        chips.append('<span class="chip gate">闸门</span>')
    if task['actionable'] and task['status'] == 'todo':
        chips.append('<span class="chip ready">可开工</span>')

    dep_bits = []
    if task['open_blockers']:
        dep_bits.append('阻塞于 <b>#' + ', #'.join(str(r) for r in task['open_blockers']) + '</b>')
    elif task['blocked_by']:
        dep_bits.append('前置已完成 #' + ', #'.join(str(r) for r in task['blocked_by']))
    if task['blocks']:
        dep_bits.append('阻塞 → #' + ', #'.join(str(r) for r in task['blocks']))
    dep_html = f'<div class="dep">{" · ".join(dep_bits)}</div>' if dep_bits else ''
    detail_html = f'<p>{esc(task["detail"])}</p>' if task['detail'] else ''

    return f"""        <div class="step" data-status="{task['status']}">
          <div class="node">{task['ref']}</div>
          <div class="card">
            <div class="card-top"><h3>{esc(task['title'])}</h3>{''.join(chips)}</div>
            {detail_html}{dep_html}
          </div>
        </div>"""


def _note_card(note: dict, kind: str) -> str:
    metric = f'<div class="metric">{esc(note["metric"])}</div>' if note.get('metric') else ''
    body = f'<p>{esc(note["body"])}</p>' if note.get('body') else ''
    return f"""      <div class="note {kind}">
        <h4>{esc(note['title'])}</h4>{metric}{body}
      </div>"""


def _project_section(project: dict) -> str:
    tasks = project['tasks']
    open_tasks = [t for t in tasks if t['status'] in ('todo', 'active')]
    spine = '\n'.join(_task_card(task) for task in tasks) or '<p class="empty">还没有任务。</p>'
    blocks = [f"""    <section id="p-{esc(project['key'])}">
      <div class="sec-head">
        <h2>{esc(project['name'])}</h2>
        <span class="key">{esc(project['key'])}{' · ' + esc(project['repo']) if project['repo'] else ''}</span>
        {f"<p>{esc(project['summary'])}</p>" if project['summary'] else ''}
      </div>
      <div class="spine">
{spine}
      </div>
    </section>"""]

    if project['findings']:
        cards = '\n'.join(_note_card(note, 'finding') for note in project['findings'])
        blocks.append(f"""    <section>
      <div class="sec-head"><h2>约束性结论</h2><span class="key">{esc(project['key'])} · 已判定,不再推演</span></div>
      <div class="notes">
{cards}
      </div>
    </section>""")

    if project['risks']:
        cards = '\n'.join(_note_card(note, 'risk') for note in project['risks'])
        blocks.append(f"""    <section>
      <div class="sec-head"><h2>尾巴与风险</h2><span class="key">{esc(project['key'])}</span></div>
      <div class="notes">
{cards}
      </div>
    </section>""")

    if project['links']:
        items = '\n'.join(
            f'        <div><code>{esc(note["title"])}</code> {esc(note.get("body") or "")}</div>'
            for note in project['links']
        )
        blocks.append(f"""    <section>
      <div class="sec-head"><h2>关键文件</h2><span class="key">{esc(project['key'])}</span></div>
      <div class="linklist">
{items}
      </div>
    </section>""")

    _ = open_tasks
    return '\n'.join(blocks)


def render(snapshot: dict, title: str = '任务看板', live: bool = False) -> str:
    projects = snapshot['projects']
    totals = {'done': 0, 'active': 0, 'todo': 0, 'dropped': 0}
    for project in projects:
        for status, count in project['counts'].items():
            totals[status] += count
    gate_total = sum(len(project['gates']) for project in projects)
    actionable = sum(
        1 for project in projects for task in project['tasks'] if task['actionable']
    )

    overview = '\n'.join(_overview_card(project) for project in projects)
    sections = '\n'.join(_project_section(project) for project in projects)
    if not projects:
        sections = '<p class="empty">还没有项目。先跑 <code>board init &lt;key&gt; --name "..." --repo .</code></p>'

    return f"""<title>{esc(title)}</title>
<style>{STYLE}</style>
<div class="wrap">
  <header class="masthead">
    <div class="eyebrow">taskboard · 跨项目进度</div>
    <h1>{esc(title)}</h1>
    <div class="meta-line">
      <span>生成于 {_fmt_stamp(snapshot['generated_at'])}</span>
      <span>{len(projects)} 个项目</span>
      <span>完成 {totals['done']} · 进行 {totals['active']} · 待办 {totals['todo']}</span>
      <span>可开工 {actionable}{f" · 闸门 {gate_total}" if gate_total else ''}</span>
    </div>
  </header>

  <div class="overview">
{overview}
  </div>

{sections}

  <footer>
    <span>board export / board serve</span>
    <span>{esc(snapshot.get('db', ''))}</span>
  </footer>
</div>
{LIVE_SCRIPT if live else ''}
"""


def render_json(snapshot: dict) -> str:
    return json.dumps(snapshot, ensure_ascii=False, indent=2)
