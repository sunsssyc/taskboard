"""把状态快照渲染成自包含 HTML(无外部资源,可直接发布)。

视觉语言:冷石板中性色 + 汽油蓝主色,状态用语义色单独承载;标题与技术正文无衬线、
数据等宽,长结论切换成全宽阅读布局。明暗主题按 token 三态定义。
"""
from __future__ import annotations

import html
import json
import re
from datetime import datetime
from urllib.parse import urlsplit

STATUS_LABEL = {'todo': '待办', 'active': '进行中', 'waiting': '等人工',
                'done': '已完成', 'dropped': '已放弃'}
HTML_PREFIX = '<!doctype html><meta charset="utf-8">'
LONG_NOTE_BODY_CHARS = 320


def html_document(body: str) -> str:
    """补齐静态文件和 WebView 都能可靠识别的 UTF-8 文档头。"""
    return HTML_PREFIX + body

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

.toolbar { position:sticky; top:10px; z-index:4; display:flex; flex-wrap:wrap; gap:8px;
           padding:10px; background:color-mix(in srgb,var(--ground) 88%,transparent);
           border:1px solid var(--rule); border-radius:5px; backdrop-filter:blur(10px); }
.toolbar .search { flex:1 1 250px; min-width:0; }
input, select, textarea { min-width:0; border:1px solid var(--rule); border-radius:3px;
  background:var(--surface); color:var(--ink); font:inherit; padding:7px 9px; }
input:focus-visible, select:focus-visible, textarea:focus-visible {
  outline:2px solid var(--accent); outline-offset:1px; border-color:var(--accent); }
button.action { border:1px solid var(--rule); border-radius:3px; background:var(--surface);
  color:var(--ink); font:inherit; font-size:13px; padding:7px 11px; cursor:pointer; }
button.action:hover { border-color:var(--accent); color:var(--accent); }
button.action.primary { color:var(--accent); border-color:var(--accent); background:var(--accent-soft); }
button.action.danger { color:var(--alert); border-color:var(--alert); }
button.action:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
.filter-empty { display:none; color:var(--ink-faint); font-size:13px; }
.filter-empty[data-on] { display:block; }

.overview { display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:12px; }
/* 卡片是切换按钮:点它只看该项目,再点一次看全部。
   不用锚点跳转——页面常被宿主整高渲染,文档自身不滚动,#锚点点了没反应。 */
.pcard { position:relative; background:var(--surface); border:1px solid var(--rule); border-radius:4px;
         padding:14px 16px; display:flex; flex-direction:column; gap:9px; box-shadow:var(--shadow);
         cursor:pointer; text-align:left; font:inherit; color:inherit; width:100%;
         transition:border-color .15s ease, transform .15s ease; }
.pcard:hover { border-color:var(--accent); transform:translateY(-1px); }
.pcard:hover h3 { color:var(--accent); }
.pcard:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
.pcard[aria-pressed="true"] { border-color:var(--accent); box-shadow:inset 3px 0 0 var(--accent), var(--shadow); }
.pcard[aria-pressed="true"] h3 { color:var(--accent); }
.overview[data-filtered] .pcard[aria-pressed="false"] { opacity:.5; }
.filter-note { display:none; align-items:center; gap:10px; font-family:var(--mono); font-size:11.5px;
               color:var(--ink-faint); }
.filter-note[data-on] { display:flex; }
.filter-note button { font:inherit; color:var(--accent); background:none; border:1px solid var(--rule);
                      border-radius:2px; padding:3px 9px; cursor:pointer; }
.filter-note button:hover { border-color:var(--accent); }
.filter-note button:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
@media (prefers-reduced-motion: reduce) {
  .pcard { transition:none; }
  .pcard:hover { transform:none; }
}
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

html { scroll-behavior:smooth; }
@media (prefers-reduced-motion: reduce) { html { scroll-behavior:auto; } }
/* 锚点跳转后标题不贴着视口顶边 */
section { display:flex; flex-direction:column; gap:14px; scroll-margin-top:18px; }
/* display:flex 会压过 UA 的 [hidden]{display:none},切换项目时必须显式盖回来 */
section[hidden] { display:none; }
.sec-head { display:flex; align-items:baseline; gap:12px; flex-wrap:wrap; border-bottom:1px solid var(--rule); padding-bottom:9px; }
.sec-head h2 { margin:0; font-size:17px; font-weight:620; letter-spacing:-.01em; }
.sec-head .key { max-width:100%; min-width:0; overflow-wrap:anywhere; font-family:var(--mono);
                 font-size:11.5px; color:var(--ink-faint); }
.sec-head p { margin:0; font-size:13px; color:var(--ink-muted); flex:1 1 240px; }

.spine { display:flex; flex-direction:column; min-width:0; }
.step { display:grid; grid-template-columns:32px minmax(0,1fr); gap:13px; position:relative;
        min-width:0; padding-bottom:11px; }
.step[hidden], [data-filter-item][hidden] { display:none; }
.step::before { content:""; position:absolute; left:15px; top:25px; bottom:0; width:1px; background:var(--rule); }
.step:last-child::before { display:none; }
.node { width:31px; height:31px; border-radius:50%; display:grid; place-items:center; z-index:1;
        font-family:var(--mono); font-size:12px; font-variant-numeric:tabular-nums;
        background:var(--surface); border:1px solid var(--rule); color:var(--ink-muted); }
.step[data-status="done"] .node { background:var(--done-soft); border-color:var(--done); color:var(--done); }
.step[data-status="active"] .node { background:var(--active-soft); border-color:var(--active); color:var(--active); font-weight:700; }
.step[data-status="dropped"] .node { color:var(--ink-faint); opacity:.6; }
.card { background:var(--surface); border:1px solid var(--rule); border-radius:4px; padding:12px 15px;
        display:flex; flex-direction:column; gap:6px; min-width:0; box-shadow:var(--shadow); }
.step[data-status="active"] .card { border-left:3px solid var(--active); }
.step[data-status="done"] .card { background:var(--sunken); box-shadow:none; }
.step[data-status="dropped"] .card { opacity:.55; }
.card-top { display:flex; flex-wrap:wrap; gap:7px 11px; align-items:center; min-width:0; }
.card-top h3 { margin:0; min-width:0; overflow-wrap:anywhere; font-size:14.5px; font-weight:600;
               letter-spacing:-.004em; flex:1 1 180px; }
.detail-button { border:0; background:none; color:var(--accent); font:inherit; font-size:12px;
                 padding:2px 4px; cursor:pointer; white-space:nowrap; }
.detail-button:hover { text-decoration:underline; text-underline-offset:2px; }
.detail-button:focus-visible { outline:2px solid var(--accent); outline-offset:1px; }
.step[data-status="dropped"] .card-top h3 { text-decoration:line-through; }
.card p { margin:0; min-width:0; overflow-wrap:anywhere; font-size:13.5px; color:var(--ink-muted);
          max-width:76ch; }
.card .markdown { max-width:76ch; font-size:13.5px; color:var(--ink-muted); }
.chip { font-family:var(--mono); font-size:10.5px; letter-spacing:.06em; text-transform:uppercase;
        padding:3px 8px; border-radius:2px; white-space:nowrap; border:1px solid transparent; }
.chip.done { background:var(--done-soft); color:var(--done); border-color:var(--done); }
.chip.active { background:var(--active-soft); color:var(--active); border-color:var(--active); }
.chip.todo { background:var(--wait-soft); color:var(--wait); border-color:var(--rule); }
.chip.waiting { background:var(--active-soft); color:var(--active); border-color:var(--rule); }
.chip.meta { background:var(--sunken); color:var(--ink-muted); border-color:var(--rule); text-transform:none; }
.accept { font-size:13px; color:var(--ink-muted); border-left:2px solid var(--accent);
          padding-left:9px; }
.accept b { font-family:var(--mono); font-size:10.5px; letter-spacing:.06em; color:var(--accent);
            text-transform:uppercase; margin-right:6px; }
.done-fold { margin-top:2px; }
.done-fold summary { cursor:pointer; font-family:var(--mono); font-size:11.5px; color:var(--ink-faint);
                     padding:7px 0 7px 45px; }
.done-fold summary:focus-visible { outline:2px solid var(--accent); outline-offset:3px; }
.done-fold[open] summary { color:var(--ink-muted); }
.chip.dropped { background:var(--wait-soft); color:var(--ink-faint); border-color:var(--rule); }
.chip.gate { background:var(--alert-soft); color:var(--alert); border-color:var(--alert); }
.chip.who { background:var(--accent-soft); color:var(--accent); }
.chip.ready { background:var(--accent-soft); color:var(--accent); border-color:var(--accent); }
.dep { font-family:var(--mono); font-size:11.5px; color:var(--ink-faint); }
.dep b { color:var(--alert); font-weight:600; }

.markdown { min-width:0; overflow-wrap:anywhere; }
.markdown > :first-child { margin-top:0; }
.markdown > :last-child { margin-bottom:0; }
.markdown p { margin:0 0 7px; }
.markdown ul, .markdown ol { margin:5px 0 8px; padding-left:22px; }
.markdown li { margin:2px 0; }
.markdown blockquote { margin:7px 0; padding:2px 0 2px 11px; border-left:2px solid var(--accent);
                      color:var(--ink-muted); }
.markdown h5, .markdown h6 { margin:10px 0 5px; font-size:13px; line-height:1.45; font-weight:620; }
.markdown code, .accept code { font-family:var(--mono); font-size:.92em; background:var(--sunken);
                               border-radius:2px; padding:1px 4px; }
.markdown pre { margin:7px 0; padding:10px 12px; overflow:auto; background:var(--sunken);
                border:1px solid var(--rule-soft); border-radius:3px; white-space:pre; }
.markdown pre code { padding:0; background:none; border-radius:0; white-space:inherit; overflow-wrap:normal; }
.markdown a, .accept a, .linklist a { color:var(--accent); text-decoration:underline;
                                     text-underline-offset:2px; }
.markdown a:focus-visible, .accept a:focus-visible, .linklist a:focus-visible {
  outline:2px solid var(--accent); outline-offset:2px; border-radius:2px;
}

.notes { display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:12px; }
.category-index { display:flex; flex-wrap:wrap; gap:7px; padding:9px 10px; background:var(--sunken);
                  border:1px solid var(--rule-soft); border-radius:4px; }
.category-index a { display:inline-flex; gap:6px; align-items:center; color:var(--ink-muted);
                    text-decoration:none; font-size:12px; border:1px solid var(--rule);
                    border-radius:2px; padding:3px 8px; background:var(--surface); }
.category-index a:hover { color:var(--accent); border-color:var(--accent); }
.category-index a[hidden] { display:none; }
.category-index a:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
.category-index b { color:var(--ink-faint); font-family:var(--mono); font-weight:500; }
.note-groups { display:flex; flex-direction:column; gap:20px; }
.note-group { display:flex; flex-direction:column; gap:9px; scroll-margin-top:82px; }
.note-group[hidden] { display:none; }
.note-group-head { display:flex; align-items:baseline; gap:9px; border-bottom:1px solid var(--rule-soft);
                   padding:5px 2px 7px; cursor:pointer; }
.note-group-head:hover h3 { color:var(--accent); }
.note-group-head:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
.note-group-head h3 { margin:0; font-size:14px; font-weight:650; }
.note-group-head span { font-family:var(--mono); font-size:10.5px; color:var(--ink-faint); }
.note-group > .notes, .note-group > .linklist { margin-top:9px; }
.note { background:var(--surface); border:1px solid var(--rule); border-radius:4px; padding:13px 15px;
        display:flex; flex-direction:column; gap:5px; }
.note.risk { border-left:3px solid var(--alert); }
.note[id] { scroll-margin-top:18px; }
.note-aside { display:flex; flex-direction:column; gap:5px; min-width:0; }
.note-title { display:flex; align-items:baseline; gap:8px; flex-wrap:wrap; }
.note h4 { margin:0; font-size:13.5px; font-weight:620; }
.note-title h4 { flex:1 1 180px; }
.note-id { font-family:var(--mono); font-size:11px; color:var(--ink-faint); white-space:nowrap; }
.note p { margin:0; min-width:0; overflow-wrap:anywhere; font-family:var(--sans); font-size:14px;
          line-height:1.7; color:var(--ink); }
.note .metric { font-family:var(--mono); font-size:11.5px; font-variant-numeric:tabular-nums; color:var(--accent); }
.note .overturns { font-family:var(--mono); font-size:11px; color:var(--ink-faint); }
.note.long { grid-column:1/-1; display:grid; grid-template-columns:minmax(240px,.75fr) minmax(0,1.8fr);
             gap:8px 26px; align-items:start; }
.note.long .note-aside { grid-column:1; grid-row:1; }
.note.long > .markdown { grid-column:2; grid-row:1; max-width:82ch;
                         border-left:1px solid var(--rule-soft); padding-left:22px; }
.note-ref { color:inherit; text-decoration:none; text-underline-offset:2px; }
.note-ref:hover { color:var(--accent); text-decoration:underline; }
.note-ref:focus-visible { outline:2px solid var(--accent); outline-offset:2px; border-radius:2px; }
.note.superseded { grid-column:1/-1; background:var(--sunken); border-style:dashed; padding:9px 14px; }
.note-filter-wrapper { grid-column:1/-1; }
.note.superseded summary { cursor:pointer; font-size:13px; color:var(--ink-faint); list-style-position:outside; }
.note.superseded summary:focus-visible { outline:2px solid var(--accent); outline-offset:3px; }
.note.superseded .tag { font-family:var(--mono); font-size:10.5px; letter-spacing:.05em;
                        color:var(--alert); border:1px solid var(--rule); border-radius:2px;
                        padding:1px 6px; margin-right:7px; white-space:nowrap; }
.note.superseded .markdown { margin-top:8px; font-size:13.5px; }
@media (max-width:760px) {
  .note.long { display:flex; }
  .note.long > .markdown { max-width:none; border-left:0; padding-left:0; }
}
.linklist { display:flex; flex-direction:column; gap:5px; font-size:13.5px; color:var(--ink-muted); }
.linklist code { font-family:var(--mono); font-size:12.5px; background:var(--sunken); padding:1px 5px;
                 border-radius:2px; color:var(--ink); overflow-wrap:anywhere; }
.empty { font-size:13.5px; color:var(--ink-faint); }
footer { border-top:1px solid var(--rule); padding-top:14px; font-family:var(--mono); font-size:11.5px;
         color:var(--ink-faint); display:flex; flex-wrap:wrap; gap:6px 20px; }

dialog { width:min(680px,calc(100vw - 28px)); max-height:min(820px,calc(100vh - 28px));
  padding:0; border:1px solid var(--rule); border-radius:6px; color:var(--ink);
  background:var(--surface); box-shadow:0 22px 70px rgba(0,0,0,.3); }
dialog::backdrop { background:rgba(8,15,16,.48); backdrop-filter:blur(2px); }
.dialog-shell { display:flex; flex-direction:column; max-height:inherit; }
.dialog-head { display:flex; gap:12px; align-items:flex-start; padding:17px 19px 12px;
  border-bottom:1px solid var(--rule); }
.dialog-head > div { flex:1; min-width:0; }
.dialog-head h2 { margin:0; font-size:19px; line-height:1.35; }
.dialog-head .meta { font-family:var(--mono); font-size:11px; color:var(--ink-faint); margin-top:4px; }
.dialog-body { padding:16px 19px; overflow:auto; display:flex; flex-direction:column; gap:15px; }
.dialog-body h3 { margin:0 0 5px; font-size:12px; color:var(--ink-faint);
  font-family:var(--mono); letter-spacing:.06em; text-transform:uppercase; }
.dialog-actions { display:flex; flex-wrap:wrap; gap:8px; padding:12px 19px 17px;
  border-top:1px solid var(--rule); }
.detail-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px 18px;
  font-size:12.5px; color:var(--ink-muted); }
.detail-grid b { color:var(--ink); font-weight:600; }
.event-list { display:flex; flex-direction:column; gap:7px; }
.event { display:grid; grid-template-columns:126px minmax(0,1fr); gap:10px; font-size:12px;
  border-top:1px solid var(--rule-soft); padding-top:7px; }
.event time { font-family:var(--mono); color:var(--ink-faint); }
.event code { white-space:pre-wrap; overflow-wrap:anywhere; color:var(--ink-muted); }
.create-form { display:flex; flex-direction:column; gap:11px; }
.create-form label { display:flex; flex-direction:column; gap:4px; font-size:12px;
  color:var(--ink-muted); }
.create-form textarea { min-height:116px; resize:vertical; }
.form-row { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:11px; }
[data-task-only][hidden], [data-finding-only][hidden] { display:none; }
.form-error { min-height:1.4em; color:var(--alert); font-size:12.5px; }
@media (max-width:620px) {
  .wrap { padding:24px 14px 56px; gap:24px; }
  .toolbar { position:static; }
  .toolbar .search, .toolbar select { flex:1 1 100%; }
  .detail-grid, .form-row { grid-template-columns:1fr; }
  .event { grid-template-columns:1fr; gap:2px; }
}
"""

FILTER_SCRIPT = """
<script>
(function () {
  var overview = document.querySelector('.overview');
  var note = document.querySelector('.filter-note');
  if (!overview || !note) return;
  var cards = Array.prototype.slice.call(overview.querySelectorAll('.pcard'));
  var sections = Array.prototype.slice.call(document.querySelectorAll('section[data-project]'));
  var controls = document.querySelector('.toolbar');
  var query = controls && controls.querySelector('[name="query"]');
  var status = controls && controls.querySelector('[name="status"]');
  var owner = controls && controls.querySelector('[name="owner"]');
  var empty = document.querySelector('.filter-empty');
  var selectedProject = null;
  var canSwitchProject = cards.length >= 2; // cards.length < 2 时只保留搜索筛选

  function apply() {
    var needle = query ? query.value.trim().toLowerCase() : '';
    var statusValue = status ? status.value : 'all';
    var ownerValue = owner ? owner.value : 'all';
    cards.forEach(function (card) {
      card.setAttribute('aria-pressed', String(card.dataset.project === selectedProject));
    });
    var visibleItems = 0;
    sections.forEach(function (section) {
      var projectMatches = !selectedProject || section.dataset.project === selectedProject;
      var sectionItems = Array.prototype.slice.call(section.querySelectorAll('[data-filter-item]'));
      var sectionVisible = 0;
      sectionItems.forEach(function (item) {
        var matches = projectMatches;
        if (needle && (item.dataset.search || '').indexOf(needle) === -1) matches = false;
        if (statusValue !== 'all') {
          if (!item.dataset.status) matches = false;
          else if (statusValue === 'actionable') matches = matches && item.dataset.actionable === 'true';
          else matches = matches && item.dataset.status === statusValue;
        }
        if (ownerValue !== 'all') matches = matches && item.dataset.owner === ownerValue;
        item.hidden = !matches;
        if (matches) sectionVisible += 1;
      });
      section.hidden = !projectMatches || (sectionItems.length > 0 && sectionVisible === 0);
      visibleItems += sectionVisible;
      var doneFold = section.querySelector('.done-fold');
      if (doneFold && (needle || statusValue === 'done')) {
        doneFold.open = Boolean(doneFold.querySelector('.step:not([hidden])'));
      }
      section.querySelectorAll('.note-group').forEach(function (group) {
        group.hidden = !group.querySelector('[data-filter-item]:not([hidden])');
        if (needle && !group.hidden) group.open = true;
      });
      section.querySelectorAll('.category-index a').forEach(function (link) {
        var group = document.getElementById(link.getAttribute('href').slice(1));
        link.hidden = Boolean(group && group.hidden);
      });
    });
    if (selectedProject) {
      overview.setAttribute('data-filtered', '');
      note.setAttribute('data-on', '');
      note.querySelector('span').textContent = '只看 ' + selectedProject;
    } else {
      overview.removeAttribute('data-filtered');
      note.removeAttribute('data-on');
    }
    var hasFilter = Boolean(selectedProject || needle || statusValue !== 'all' || ownerValue !== 'all');
    if (empty) empty.toggleAttribute('data-on', hasFilter && visibleItems === 0);
  }

  cards.forEach(function (card) {
    if (!canSwitchProject) return;
    card.addEventListener('click', function () {
      var already = card.getAttribute('aria-pressed') === 'true';
      selectedProject = already ? null : card.dataset.project;
      apply();
    });
  });
  note.querySelector('button').addEventListener('click', function () {
    selectedProject = null;
    apply();
  });
  [query, status, owner].forEach(function (control) {
    if (control) control.addEventListener(control === query ? 'input' : 'change', apply);
  });
  document.querySelectorAll('.category-index a').forEach(function (link) {
    link.addEventListener('click', function () {
      var group = document.getElementById(link.getAttribute('href').slice(1));
      if (group) group.open = true;
    });
  });
})();
</script>
"""

INTERACTIVE_SCRIPT = """
<script>
(function () {
  var root = document.querySelector('.wrap[data-csrf]');
  if (!root) return;
  var csrf = root.dataset.csrf;
  var detailDialog = document.getElementById('task-detail');
  var detailBody = detailDialog.querySelector('.dialog-body');
  var detailTitle = detailDialog.querySelector('h2');
  var detailMeta = detailDialog.querySelector('.meta');
  var detailActions = detailDialog.querySelector('.dialog-actions');
  var createDialog = document.getElementById('create-dialog');
  var createForm = createDialog ? createDialog.querySelector('form') : null;
  var createError = createDialog ? createDialog.querySelector('.form-error') : null;
  var categoryMap = createForm ? JSON.parse(createForm.dataset.categories || '{}') : {};
  var current = null;

  function element(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  async function api(path, options) {
    var opts = options || {};
    opts.headers = Object.assign({}, opts.headers || {}, {
      'Content-Type': 'application/json', 'X-Taskboard-CSRF': csrf
    });
    var response = await fetch(path, opts);
    var value = await response.json().catch(function () { return {error: '响应格式错误'}; });
    if (!response.ok) throw new Error(value.error || ('请求失败 ' + response.status));
    return value;
  }

  function addBlock(title, content, htmlContent) {
    if (!content) return;
    var block = element('div');
    block.appendChild(element('h3', '', title));
    var copy = element('div', 'markdown');
    if (htmlContent) copy.innerHTML = content;
    else copy.textContent = content;
    block.appendChild(copy);
    detailBody.appendChild(block);
  }

  function updateCategoryOptions() {
    if (!createForm) return;
    var list = createForm.querySelector('#finding-categories');
    var project = createForm.elements.project.value;
    list.replaceChildren();
    (categoryMap[project] || []).forEach(function (category) {
      var option = document.createElement('option');
      option.value = category;
      list.appendChild(option);
    });
  }

  async function openDetail(button) {
    detailTitle.textContent = '读取中…';
    detailMeta.textContent = button.dataset.project + ' #' + button.dataset.ref;
    detailBody.replaceChildren();
    detailActions.querySelectorAll('[data-status]').forEach(function (item) { item.disabled = true; });
    detailDialog.showModal();
    try {
      current = await api('/api/tasks/' + encodeURIComponent(button.dataset.project) + '/' + button.dataset.ref);
      var task = current.task;
      detailTitle.textContent = task.title;
      detailMeta.textContent = current.project.name + ' · ' + current.project.key + ' #' + task.ref;
      var grid = element('div', 'detail-grid');
      [['状态', task.status], ['负责人', task.owner || '未指定'], ['分支', task.branch || '—'],
       ['PR', task.pr || '—'], ['依赖', task.blocked_by.length ? '#' + task.blocked_by.join(', #') : '无'],
       ['更新', task.updated_at]].forEach(function (pair) {
        var item = element('div');
        var label = element('b', '', pair[0] + '：');
        item.append(label, document.createTextNode(pair[1]));
        grid.appendChild(item);
      });
      detailBody.appendChild(grid);
      addBlock('任务说明', current.detail_html, true);
      addBlock('验收条件', current.accept_html, true);
      if (current.events.length) {
        var eventsBlock = element('div');
        eventsBlock.appendChild(element('h3', '', '最近事件'));
        var list = element('div', 'event-list');
        current.events.forEach(function (event) {
          var row = element('div', 'event');
          row.append(element('time', '', event.at),
                     element('code', '', event.action + ' ' + JSON.stringify(event.payload)));
          list.appendChild(row);
        });
        eventsBlock.appendChild(list);
        detailBody.appendChild(eventsBlock);
      }
      detailActions.querySelectorAll('[data-status]').forEach(function (item) {
        item.disabled = item.dataset.status === task.status;
      });
    } catch (error) {
      detailTitle.textContent = '无法读取任务';
      detailBody.appendChild(element('div', 'form-error', error.message));
    }
  }

  document.addEventListener('click', function (event) {
    var detailButton = event.target.closest('.detail-button');
    if (detailButton) openDetail(detailButton);
    var closeButton = event.target.closest('[data-close]');
    if (closeButton) closeButton.closest('dialog').close();
    var createButton = event.target.closest('[data-create]');
    if (createButton && createForm) {
      createForm.reset();
      createError.textContent = '';
      createForm.elements.kind.value = createButton.dataset.create;
      createForm.querySelectorAll('[data-task-only]').forEach(function (node) {
        node.hidden = createButton.dataset.create !== 'task';
      });
      createForm.querySelectorAll('[data-finding-only]').forEach(function (node) {
        node.hidden = createButton.dataset.create !== 'finding';
      });
      createDialog.querySelector('h2').textContent = createButton.dataset.create === 'task' ? '新建任务' : '记录结论';
      updateCategoryOptions();
      createDialog.showModal();
    }
  });

  detailActions.addEventListener('click', async function (event) {
    var button = event.target.closest('[data-status]');
    if (!button || !current) return;
    if (button.dataset.status === 'done') {
      var accept = current.task.accept ? '\\n\\n验收条件：' + current.task.accept : '';
      if (!confirm('确认将 #' + current.task.ref + ' 标记为已完成？' + accept)) return;
    }
    button.disabled = true;
    try {
      await api('/api/tasks/' + encodeURIComponent(current.project.key) + '/' + current.task.ref + '/status', {
        method: 'POST', body: JSON.stringify({status: button.dataset.status})
      });
      location.reload();
    } catch (error) {
      button.disabled = false;
      alert(error.message);
    }
  });

  if (createForm) createForm.addEventListener('submit', async function (event) {
    event.preventDefault();
    createError.textContent = '';
    var data = new FormData(createForm);
    var kind = data.get('kind');
    var payload = {project: data.get('project'), title: data.get('title')};
    var path;
    if (kind === 'task') {
      path = '/api/tasks';
      payload.detail = data.get('body');
      payload.owner = data.get('owner');
      payload.accept = data.get('accept');
    } else {
      path = '/api/notes';
      payload.body = data.get('body');
      payload.metric = data.get('metric');
      payload.category = data.get('category');
    }
    try {
      await api(path, {method: 'POST', body: JSON.stringify(payload)});
      location.reload();
    } catch (error) {
      createError.textContent = error.message;
    }
  });
  if (createForm) createForm.elements.project.addEventListener('change', updateCategoryOptions);
})();
</script>
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


INLINE_CODE_RE = re.compile(r'`([^`\n]+)`')
LINK_RE = re.compile(r'\[([^\]\n]+)\]\(([^)\n]+)\)')
STRONG_RE = re.compile(r'\*\*([^*\n]+)\*\*')
EMPHASIS_RE = re.compile(r'(?<!\*)\*([^*\n]+)\*(?!\*)')
UNORDERED_ITEM_RE = re.compile(r'^\s*[-+*]\s+(.+)$')
ORDERED_ITEM_RE = re.compile(r'^\s*\d+\.\s+(.+)$')
HEADING_RE = re.compile(r'^(#{1,4})\s+(.+)$')
FENCE_RE = re.compile(r'^```\s*([A-Za-z0-9_+-]*)\s*$')


def _safe_markdown_href(value: str) -> str | None:
    """只允许 Web/mail 链接与普通相对路径；拒绝 javascript/data 等协议。"""
    href = html.unescape(value).strip()
    normalized = re.sub(r'[\x00-\x20\x7f]+', '', href)
    if not normalized or normalized.startswith('//'):
        return None
    scheme = urlsplit(normalized).scheme.lower()
    return href if scheme in ('', 'http', 'https', 'mailto') else None


def render_inline_markdown(value: str | None) -> str:
    """渲染安全的行内 Markdown 子集；原始 HTML 始终先转义。"""
    text = str(value or '')
    tokens: list[str] = []

    def stash(rendered: str) -> str:
        marker = f'\ue000{len(tokens)}\ue001'
        tokens.append(rendered)
        return marker

    text = INLINE_CODE_RE.sub(
        lambda match: stash(f'<code>{esc(match.group(1))}</code>'), text,
    )

    def render_link(match: re.Match) -> str:
        href = _safe_markdown_href(match.group(2))
        if href is None:
            return match.group(0)
        scheme = urlsplit(href).scheme.lower()
        external = ' target="_blank" rel="noopener noreferrer"' if scheme else ''
        label = render_inline_markdown(match.group(1))
        return stash(f'<a href="{esc(href)}"{external}>{label}</a>')

    text = LINK_RE.sub(render_link, text)
    rendered = esc(text)
    rendered = STRONG_RE.sub(r'<strong>\1</strong>', rendered)
    rendered = EMPHASIS_RE.sub(r'<em>\1</em>', rendered)
    for index, token in enumerate(tokens):
        rendered = rendered.replace(f'\ue000{index}\ue001', token)
    return rendered


def render_markdown(value: str | None) -> str:
    """纯标准库 Markdown:段落、标题、列表、引用、代码块与安全行内格式。"""
    lines = str(value or '').replace('\r\n', '\n').replace('\r', '\n').split('\n')
    blocks: list[str] = []
    paragraph: list[str] = []
    list_kind: str | None = None
    list_items: list[str] = []
    quote_lines: list[str] = []
    code_lines: list[str] = []
    code_language = ''
    in_code = False

    def flush_paragraph() -> None:
        if paragraph:
            text = ' '.join(part.strip() for part in paragraph)
            blocks.append(f'<p>{render_inline_markdown(text)}</p>')
            paragraph.clear()

    def flush_list() -> None:
        nonlocal list_kind
        if list_kind and list_items:
            items = ''.join(f'<li>{render_inline_markdown(item)}</li>' for item in list_items)
            blocks.append(f'<{list_kind}>{items}</{list_kind}>')
        list_kind = None
        list_items.clear()

    def flush_quote() -> None:
        if quote_lines:
            text = ' '.join(part.strip() for part in quote_lines)
            blocks.append(f'<blockquote><p>{render_inline_markdown(text)}</p></blockquote>')
            quote_lines.clear()

    def flush_code() -> None:
        language = f' class="language-{esc(code_language)}"' if code_language else ''
        blocks.append(f'<pre><code{language}>{esc(chr(10).join(code_lines))}</code></pre>')
        code_lines.clear()

    for line in lines:
        fence = FENCE_RE.match(line)
        if in_code:
            if fence:
                flush_code()
                in_code = False
                code_language = ''
            else:
                code_lines.append(line)
            continue
        if fence:
            flush_paragraph()
            flush_list()
            flush_quote()
            in_code = True
            code_language = fence.group(1)
            continue
        if not line.strip():
            flush_paragraph()
            flush_list()
            flush_quote()
            continue

        heading = HEADING_RE.match(line)
        if heading:
            flush_paragraph()
            flush_list()
            flush_quote()
            level = 5 if len(heading.group(1)) <= 2 else 6
            blocks.append(f'<h{level}>{render_inline_markdown(heading.group(2))}</h{level}>')
            continue

        unordered = UNORDERED_ITEM_RE.match(line)
        ordered = ORDERED_ITEM_RE.match(line)
        if unordered or ordered:
            flush_paragraph()
            flush_quote()
            kind = 'ul' if unordered else 'ol'
            if list_kind and list_kind != kind:
                flush_list()
            list_kind = kind
            list_items.append((unordered or ordered).group(1))
            continue

        if line.lstrip().startswith('>'):
            flush_paragraph()
            flush_list()
            quote_lines.append(line.lstrip()[1:].lstrip())
            continue

        flush_list()
        flush_quote()
        paragraph.append(line)

    if in_code:
        flush_code()
    flush_paragraph()
    flush_list()
    flush_quote()
    return ''.join(blocks)


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
    active_pct = (counts['active'] + counts.get('waiting', 0)) / total * 100
    nxt = _project_next(project)
    next_html = (
        f'<div class="nextline"><span>下一步 #{nxt["ref"]}</span> {esc(nxt["title"])}</div>'
        if nxt else '<div class="nextline"><span>没有可动的任务</span></div>'
    )
    gates = (
        f'<div class="nextline"><span>闸门</span> #{", #".join(str(g) for g in project["gates"])}</div>'
        if project['gates'] else ''
    )
    return f"""      <button type="button" class="pcard" data-project="{esc(project['key'])}" aria-pressed="false">
        <div class="key">{esc(project['key'])}</div>
        <h3>{esc(project['name'])}</h3>
        <div class="bar"><i class="done" style="width:{done_pct:.1f}%"></i><i class="active" style="width:{active_pct:.1f}%"></i></div>
        <div class="counts"><span>完成 <b>{counts['done']}</b></span><span>进行 <b>{counts['active']}</b></span>{f"<span>等人工 <b>{counts['waiting']}</b></span>" if counts.get('waiting') else ''}<span>待办 <b>{counts['todo']}</b></span></div>
        {next_html}{gates}
      </button>"""


def _task_card(task: dict, project: str, live: bool = False) -> str:
    chips = [f'<span class="chip {task["status"]}">{STATUS_LABEL[task["status"]]}</span>']
    if task['owner']:
        chips.append(f'<span class="chip who">{esc(task["owner"])}</span>')
    if task['gate'] and task['status'] != 'done':
        chips.append('<span class="chip gate">闸门</span>')
    if task['actionable'] and task['status'] == 'todo':
        chips.append('<span class="chip ready">可开工</span>')
    if task.get('branch'):
        chips.append(f'<span class="chip meta">{esc(task["branch"])}</span>')
    if task.get('pr'):
        chips.append(f'<span class="chip meta">PR {esc(task["pr"])}</span>')

    dep_bits = []
    if task['open_blockers']:
        dep_bits.append('阻塞于 <b>#' + ', #'.join(str(r) for r in task['open_blockers']) + '</b>')
    elif task['blocked_by']:
        dep_bits.append('前置已完成 #' + ', #'.join(str(r) for r in task['blocked_by']))
    if task['blocks']:
        dep_bits.append('阻塞 → #' + ', #'.join(str(r) for r in task['blocks']))
    dep_html = f'<div class="dep">{" · ".join(dep_bits)}</div>' if dep_bits else ''
    detail_html = (
        f'<div class="markdown card-detail">{render_markdown(task["detail"])}</div>'
        if task['detail'] else ''
    )
    accept_html = (
        f'<div class="accept"><b>验收</b>{render_inline_markdown(task["accept"])}</div>'
        if task.get('accept') and task['status'] != 'done' else ''
    )
    search_text = ' '.join(str(task.get(field) or '') for field in (
        'ref', 'title', 'detail', 'accept', 'owner', 'branch', 'pr'
    )).casefold()
    detail_button = (
        f'<button type="button" class="detail-button" data-project="{esc(project)}" '
        f'data-ref="{task["ref"]}">详情</button>' if live else ''
    )

    return f"""        <div class="step" data-filter-item data-status="{task['status']}" data-actionable="{str(bool(task['actionable'])).lower()}" data-owner="{esc(task.get('owner') or '')}" data-search="{esc(search_text)}">
          <div class="node">{task['ref']}</div>
          <div class="card">
            <div class="card-top"><h3>{esc(task['title'])}</h3>{detail_button}{''.join(chips)}</div>
            {detail_html}{accept_html}{dep_html}
          </div>
        </div>"""


def _note_card(note: dict, kind: str) -> str:
    search_text = ' '.join(str(note.get(field) or '') for field in (
        'id', 'category', 'title', 'body', 'metric'
    )).casefold()
    if note.get('is_superseded'):
        # 折叠成一行:保留"曾经这么认为"的痕迹,但不与当前结论争夺注意力
        return f"""      <div class="note-filter-wrapper" data-filter-item data-search="{esc(search_text)}"><details class="note superseded" id="note-{note['id']}">
        <summary><span class="note-id">[{note['id']}]</span> <a class="tag note-ref" href="#note-{note['superseded_by']}">已被 [{note['superseded_by']}] 推翻</a> {esc(note['title'])}</summary>
        {f'<div class="markdown">{render_markdown(note["body"])}</div>' if note.get('body') else ''}
      </details></div>"""
    metric = f'<div class="metric">{esc(note["metric"])}</div>' if note.get('metric') else ''
    body_text = note.get('body') or ''
    body = f'<div class="markdown note-body">{render_markdown(body_text)}</div>' if body_text else ''
    layout_class = ' long' if len(body_text) >= LONG_NOTE_BODY_CHARS else ''
    overturned_refs = ', '.join(
        f'<a class="note-ref" href="#note-{note_id}">[{note_id}]</a>'
        for note_id in note.get('supersedes', [])
    )
    overturns = (
        f'<div class="overturns">推翻了 {overturned_refs}</div>'
        if overturned_refs else ''
    )
    return f"""      <div class="note {kind}{layout_class}" id="note-{note['id']}" data-filter-item data-search="{esc(search_text)}">
        <div class="note-aside"><div class="note-title"><span class="note-id">[{note['id']}]</span><h4>{esc(note['title'])}</h4></div>{metric}{overturns}</div>{body}
      </div>"""


def _note_groups(notes: list[dict], kind: str, project_key: str) -> str:
    """按稳定主题分组；显式分类优先，兼容旧数据的“未分类”固定沉底。"""
    grouped: dict[str, list[dict]] = {}
    for note in notes:
        grouped.setdefault(note.get('category') or '未分类', []).append(note)
    categories = sorted(grouped, key=lambda value: value == '未分类')
    anchors = {
        category: f'{kind}-{project_key}-category-{index}'
        for index, category in enumerate(categories, 1)
    }
    index_html = ''
    if len(categories) > 1:
        links = ''.join(
            f'<a href="#{esc(anchors[category])}">{esc(category)} '
            f'<b>{len(grouped[category])}</b></a>'
            for category in categories
        )
        index_html = f'<nav class="category-index" aria-label="{esc(kind)} 分类">{links}</nav>'
    groups = []
    for index, category in enumerate(categories):
        cards = '\n'.join(_note_card(note, kind) for note in grouped[category])
        groups.append(f"""      <details class="note-group" id="{esc(anchors[category])}"{' open' if index == 0 else ''}>
        <summary class="note-group-head"><h3>{esc(category)}</h3><span>{len(grouped[category])} 条</span></summary>
        <div class="notes">
{cards}
        </div>
      </details>""")
    return index_html + '<div class="note-groups">' + '\n'.join(groups) + '</div>'


def _link_groups(notes: list[dict], project_key: str) -> str:
    grouped: dict[str, list[dict]] = {}
    for note in notes:
        grouped.setdefault(note.get('category') or '未分类', []).append(note)
    categories = sorted(grouped, key=lambda value: value == '未分类')
    anchors = {
        category: f'link-{project_key}-category-{index}'
        for index, category in enumerate(categories, 1)
    }
    index_html = ''
    if len(categories) > 1:
        links = ''.join(
            f'<a href="#{esc(anchors[category])}">{esc(category)} '
            f'<b>{len(grouped[category])}</b></a>' for category in categories
        )
        index_html = f'<nav class="category-index" aria-label="link 分类">{links}</nav>'
    groups = []
    for index, category in enumerate(categories):
        items = '\n'.join(
            f'          <div data-filter-item data-search="{esc((str(note.get("category") or "") + " " + str(note.get("title") or "") + " " + str(note.get("body") or "")).casefold())}"><code>{esc(note["title"])}</code> {render_inline_markdown(note.get("body") or "")}</div>'
            for note in grouped[category]
        )
        groups.append(f"""      <details class="note-group" id="{esc(anchors[category])}"{' open' if index == 0 else ''}>
        <summary class="note-group-head"><h3>{esc(category)}</h3><span>{len(grouped[category])} 条</span></summary>
        <div class="linklist">
{items}
        </div>
      </details>""")
    return index_html + '<div class="note-groups">' + '\n'.join(groups) + '</div>'


def _project_section(project: dict, live: bool = False) -> str:
    tasks = project['tasks']
    # 已完成的折进一个 details:剩余路径才是每天要看的,完成项只作背景
    open_tasks = [task for task in tasks if task['status'] != 'done']
    finished = [task for task in tasks if task['status'] == 'done']
    spine = '\n'.join(_task_card(task, project['key'], live=live) for task in open_tasks)
    if finished:
        folded = '\n'.join(_task_card(task, project['key'], live=live) for task in finished)
        spine += f"""
        <details class="done-fold">
          <summary>已完成 {len(finished)} 项</summary>
{folded}
        </details>"""
    spine = spine or '<p class="empty">还没有任务。</p>'
    blocks = [f"""    <section id="p-{esc(project['key'])}" data-project="{esc(project['key'])}" data-kind="tasks">
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
        groups = _note_groups(project['findings'], 'finding', project['key'])
        blocks.append(f"""    <section data-project="{esc(project['key'])}" data-kind="findings">
      <div class="sec-head"><h2>约束性结论</h2><span class="key">{esc(project['key'])} · 已判定,不再推演</span></div>
{groups}
    </section>""")

    if project['risks']:
        groups = _note_groups(project['risks'], 'risk', project['key'])
        blocks.append(f"""    <section data-project="{esc(project['key'])}" data-kind="risks">
      <div class="sec-head"><h2>尾巴与风险</h2><span class="key">{esc(project['key'])}</span></div>
{groups}
    </section>""")

    if project['links']:
        groups = _link_groups(project['links'], project['key'])
        blocks.append(f"""    <section data-project="{esc(project['key'])}" data-kind="links">
      <div class="sec-head"><h2>关键文件</h2><span class="key">{esc(project['key'])}</span></div>
{groups}
    </section>""")

    return '\n'.join(blocks)


def _toolbar(projects: list[dict], write_enabled: bool) -> str:
    owners = sorted({
        task['owner'] for project in projects for task in project['tasks'] if task.get('owner')
    })
    owner_options = ''.join(f'<option value="{esc(owner)}">{esc(owner)}</option>' for owner in owners)
    write_actions = (
        '<button type="button" class="action primary" data-create="task">新建任务</button>'
        '<button type="button" class="action" data-create="finding">记结论</button>'
        if write_enabled else ''
    )
    return f"""  <div class="toolbar" aria-label="看板筛选与操作">
    <input class="search" name="query" type="search" placeholder="搜索任务、正文、结论…" aria-label="搜索看板">
    <select name="status" aria-label="按状态筛选">
      <option value="all">全部状态</option><option value="actionable">可开工</option>
      <option value="active">进行中</option><option value="waiting">等人工</option>
      <option value="todo">待办</option><option value="done">已完成</option>
    </select>
    <select name="owner" aria-label="按负责人筛选"><option value="all">全部负责人</option>{owner_options}</select>
    {write_actions}
  </div>"""


def _dialogs(projects: list[dict], write_enabled: bool) -> str:
    status_actions = ''
    create_dialog = ''
    if write_enabled:
        status_actions = """
      <button type="button" class="action" data-status="todo">转待办</button>
      <button type="button" class="action primary" data-status="active">开始</button>
      <button type="button" class="action" data-status="waiting">等人工</button>
      <button type="button" class="action primary" data-status="done">完成</button>"""
        options = ''.join(
            f'<option value="{esc(project["key"])}">{esc(project["name"])} · {esc(project["key"])}</option>'
            for project in projects
        )
        category_map = {
            project['key']: sorted({
                note['category'] for note in project['findings'] if note.get('category')
            })
            for project in projects
        }
        category_data = esc(json.dumps(category_map, ensure_ascii=False))
        create_dialog = f"""
  <dialog id="create-dialog">
    <div class="dialog-shell">
      <div class="dialog-head"><div><h2>新建任务</h2><div class="meta">支持 Markdown；复杂编辑仍建议在 Codex 对话中完成</div></div><button type="button" class="action" data-close>关闭</button></div>
      <form class="dialog-body create-form" data-categories="{category_data}">
        <input type="hidden" name="kind" value="task">
        <div class="form-row"><label>项目<select name="project" required>{options}</select></label><label>标题<input name="title" required maxlength="240"></label></div>
        <label>正文<textarea name="body" placeholder="支持段落、列表、引用、代码块与安全链接"></textarea></label>
        <div class="form-row" data-task-only><label>负责人<input name="owner" placeholder="例如 我"></label><label>验收条件<input name="accept"></label></div>
        <div class="form-row" data-finding-only hidden><label>分类<input name="category" list="finding-categories" maxlength="40" placeholder="复用本项目已有主题"><datalist id="finding-categories"></datalist></label><label>度量/证据<input name="metric"></label></div>
        <div class="form-error" role="alert"></div>
        <div><button type="submit" class="action primary">保存</button></div>
      </form>
    </div>
  </dialog>"""
    return f"""
  <dialog id="task-detail">
    <div class="dialog-shell">
      <div class="dialog-head"><div><h2>任务详情</h2><div class="meta"></div></div><button type="button" class="action" data-close>关闭</button></div>
      <div class="dialog-body"></div>
      <div class="dialog-actions">{status_actions}<button type="button" class="action" data-close>关闭</button></div>
    </div>
  </dialog>{create_dialog}"""


def render(snapshot: dict, title: str = '任务看板', live: bool = False,
           csrf_token: str | None = None, write_enabled: bool = False) -> str:
    projects = snapshot['projects']
    totals: dict[str, int] = {status: 0 for status in STATUS_LABEL}
    for project in projects:
        for status, count in project['counts'].items():
            totals[status] = totals.get(status, 0) + count
    gate_total = sum(len(project['gates']) for project in projects)
    actionable = sum(
        1 for project in projects for task in project['tasks'] if task['actionable']
    )

    overview = '\n'.join(_overview_card(project) for project in projects)
    sections = '\n'.join(_project_section(project, live=live) for project in projects)
    if not projects:
        sections = '<p class="empty">还没有项目。先跑 <code>board init &lt;key&gt; --name "..." --repo .</code></p>'
    db_path = (
        f'<span>{esc(snapshot["db"])}</span>'
        if snapshot.get('db') else ''
    )

    root_attrs = f' data-csrf="{esc(csrf_token or "")}"' if live else ''
    toolbar = _toolbar(projects, write_enabled=live and write_enabled)
    dialogs = _dialogs(projects, write_enabled=write_enabled) if live else ''

    return f"""<title>{esc(title)}</title>
<style>{STYLE}</style>
<div class="wrap"{root_attrs}>
  <header class="masthead">
    <div class="eyebrow">taskboard · 跨项目进度</div>
    <h1>{esc(title)}</h1>
    <div class="meta-line">
      <span>生成于 {_fmt_stamp(snapshot['generated_at'])}</span>
      <span>{len(projects)} 个项目</span>
      <span>完成 {totals['done']} · 进行 {totals['active']}{f" · 等人工 {totals['waiting']}" if totals.get('waiting') else ''} · 待办 {totals['todo']}</span>
      <span>可开工 {actionable}{f" · 闸门 {gate_total}" if gate_total else ''}</span>
    </div>
  </header>

{toolbar}

  <div class="overview">
{overview}
  </div>

  <div class="filter-note"><span></span><button type="button">显示全部项目</button></div>
  <div class="filter-empty">没有符合当前筛选条件的内容。</div>

{sections}

  <footer>
    <span>board export / board serve</span>
    {db_path}
  </footer>
</div>
{dialogs}
{FILTER_SCRIPT}{LIVE_SCRIPT if live else ''}{INTERACTIVE_SCRIPT if live else ''}
"""


def render_json(snapshot: dict) -> str:
    return json.dumps(snapshot, ensure_ascii=False, indent=2)
