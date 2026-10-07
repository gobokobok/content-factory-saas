/* P-UX3 prototype — hash-routed, in-memory. Reload resets everything. */

// ── Helpers ────────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
function esc(v) {
  return String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
function go(hash) { location.hash = hash; }
function toast(msg) {
  const el = $('toast');
  el.textContent = msg; el.classList.add('on');
  clearTimeout(toast.t); toast.t = setTimeout(() => el.classList.remove('on'), 2600);
}
function demo(what) { toast(`Demo: ${what}`); }
const proj = id => DB.projects.find(p => p.id === id);
const runOf = id => DB.runs.find(r => r.id === id);
const runsOf = pid => DB.runs.filter(r => r.project === pid);
const ideasOf = pid => DB.ideas.filter(i => i.project === pid);
/** A project's effective value: its own override, else the tenant default. */
const resolve = (p, key) => (p.settings[key] !== undefined ? p.settings[key] : DB.defaults[key]);
function opts(map, value) {
  return Object.entries(map).map(([k, v]) => `<option value="${esc(k)}"${k === value ? ' selected' : ''}>${esc(v)}</option>`).join('');
}
function thumb(hue, label, cls) {
  if (hue === undefined || hue === null) return `<div class="thumb blank ${cls || ''}">${esc(label || '—')}</div>`;
  return `<div class="thumb ${cls || ''}" style="background:linear-gradient(135deg,hsl(${hue} 45% 42%),hsl(${(hue + 40) % 360} 55% 24%))">${esc(label || '')}</div>`;
}

const ICON = {
  projects: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  videos: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m10 9 5 3-5 3z"/>',
  audio: '<path d="M4 10v4M8 6v12M12 9v6M16 4v16M20 10v4"/>',
  footage: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m3 16 5-5 4 4 3-3 6 6"/><circle cx="15.5" cy="8.5" r="1.5"/>',
  ai: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M18 6l-2.5 2.5M8.5 15.5 6 18"/>',
  music: '<path d="M9 18V5l11-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/>',
  integrations: '<path d="M9 7V3M15 7V3M6 7h12v4a6 6 0 0 1-12 0zM12 17v4"/>',
  defaults: '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
  fold: '<path d="m14 7-5 5 5 5"/><path d="M19 5v14"/>',
  out: '<path d="M10 5H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h4M15 8l4 4-4 4M19 12H9"/>',
};
const ico = n => `<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON[n]}</svg>`;

// ── State and routing ──────────────────────────────────────────────────────
const S = {
  fold: (() => { try { return localStorage.getItem('cf_proto_fold') === '1'; } catch { return false; } })(),
  runUnfold: false,   // in a run the panel starts folded; unfolding there is not remembered
  ideaSel: new Set(),
  lib: { project: '', facet: '', q: '' },
  runFilter: '',
  scene: null, sceneTab: 'stock',
  sbView: 'board',   // storyboard: 'board' | 'script'
};

function route() {
  const parts = location.hash.replace(/^#\/?/, '').split('/').filter(Boolean);
  const [a, b, c] = parts;
  if (a === 'p' && proj(b)) return { kind: 'project', project: proj(b), tab: c || 'overview' };
  if (a === 'r' && runOf(b)) {
    const run = runOf(b);
    const steps = STEPS;
    return { kind: 'run', run, project: proj(run.project), step: steps.includes(c) ? c : steps[Math.min(run.done, steps.length - 1)] };
  }
  if (a === 'lib' && LIBS[b]) return { kind: 'lib', lib: b };
  if (a === 'settings') return { kind: 'settings', tab: b === 'defaults' ? 'defaults' : 'integrations' };
  return { kind: 'projects' };
}

function isFolded(r) { return r.kind === 'run' ? !S.runUnfold : S.fold; }
function toggleFold() {
  const r = route();
  if (r.kind === 'run') S.runUnfold = !S.runUnfold;
  else { S.fold = !S.fold; try { localStorage.setItem('cf_proto_fold', S.fold ? '1' : '0'); } catch { /* private mode */ } }
  render();
}
function openNav() { document.body.classList.add('nav-open'); }
function closeNav() { document.body.classList.remove('nav-open'); }

// ── Left panel ─────────────────────────────────────────────────────────────
function navItem(href, icon, label, on, extra) {
  return `<a class="nav-item${on ? ' on' : ''}" href="${href}" title="${esc(label)}">${icon ? ico(icon) : ''}<span class="lbl">${esc(label)}</span>${extra || ''}</a>`;
}
function renderNav(r) {
  const cur = r.project;
  const sub = (tab, label, soon) => {
    const on = (r.kind === 'project' && r.tab === tab) || (r.kind === 'run' && tab === 'runs');
    return `<a class="nav-item${on ? ' on' : ''}" href="#/p/${cur.id}${tab === 'overview' ? '' : '/' + tab}"><span class="lbl">${label}</span>${soon ? `<span class="soon">${soon}</span>` : ''}</a>`;
  };
  $('nav').innerHTML = `
    <div class="nav-head">
      <div class="brand-mark" aria-hidden="true"></div>
      <div class="brand-name">CF <span>Studio</span></div>
      <button class="icon-btn fold-btn" onclick="toggleFold()" aria-label="Fold or unfold the panel" title="Fold / unfold"><span class="fold-ico" style="display:inline-flex">${ico('fold')}</span></button>
    </div>
    <div class="nav-scroll">
      <div class="nav-group">Projects</div>
      ${navItem('#/projects', 'projects', 'All projects', r.kind === 'projects', `<span class="nav-count">${DB.projects.length}</span>`)}
      ${cur ? `<div class="nav-sub">
          <a class="nav-item proj" href="#/p/${cur.id}"><span class="lbl">${esc(cur.name)}</span></a>
          ${sub('overview', 'Overview')}${sub('ideas', 'Ideas')}${sub('runs', 'Runs')}
          ${sub('research', 'Research', 'P15')}${sub('publishing', 'Publishing', 'P16')}${sub('settings', 'Settings')}
        </div>` : ''}
      <div class="nav-group">Libraries</div>
      ${Object.entries(LIBS).map(([k, v]) => navItem(`#/lib/${k}`, k, v.label, r.kind === 'lib' && r.lib === k, `<span class="nav-count">${DB.assets[k].length}</span>`)).join('')}
      <div class="nav-group">Settings</div>
      ${navItem('#/settings/integrations', 'integrations', 'Integrations', r.kind === 'settings' && r.tab === 'integrations')}
      ${navItem('#/settings/defaults', 'defaults', 'Defaults', r.kind === 'settings' && r.tab === 'defaults')}
    </div>
    <div class="nav-foot"><button class="nav-item" onclick="demo('you would be logged out')" title="Log out">${ico('out')}<span class="lbl">Log out</span></button></div>`;
}

function renderCrumbs(r) {
  const c = [['Projects', '#/projects']];
  if (r.kind === 'project' || r.kind === 'run') c.push([r.project.name, `#/p/${r.project.id}`]);
  if (r.kind === 'project' && r.tab !== 'overview') c.push([r.tab[0].toUpperCase() + r.tab.slice(1)]);
  if (r.kind === 'run') { c.push(['Runs', `#/p/${r.project.id}/runs`]); c.push([r.run.title]); }
  if (r.kind === 'lib') { c.length = 0; c.push(['Libraries'], [LIBS[r.lib].label]); }
  if (r.kind === 'settings') { c.length = 0; c.push(['Settings'], [r.tab === 'defaults' ? 'Defaults' : 'Integrations']); }
  $('crumbs').innerHTML = c.map(([label, href], i) => {
    const last = i === c.length - 1;
    const el = href && !last ? `<a href="${href}">${esc(label)}</a>` : `<span class="${last ? 'here' : ''}">${esc(label)}</span>`;
    return (i ? '<span class="sep">/</span>' : '') + el;
  }).join('');
}

// ── Shared pieces ──────────────────────────────────────────────────────────
const voiceLabel = run => (run.mode ? MODES[run.mode] : 'Script not started');
/** One chip that says where the run is: done, failed at a step, or the step it waits at. */
function statusChip(run) {
  const at = STEP_LABELS[STEPS[Math.min(run.done, STEPS.length - 1)]];
  if (run.status === 'complete') return '<span class="chip ok">Done</span>';
  if (run.status === 'failed') return `<span class="chip bad">Needs attention · ${at}</span>`;
  return `<span class="chip run">At ${at}</span>`;
}
function runRow(run) {
  return `<a class="row" href="#/r/${run.id}">
    <div class="row-main">
      <div class="row-name">${esc(run.title)}</div>
      <div class="row-meta"><span>${voiceLabel(run)}</span><span>${LANGS[run.language]}</span><span>${run.format}</span></div>
    </div>
    ${statusChip(run)}
  </a>`;
}

// ── Projects ───────────────────────────────────────────────────────────────
function viewProjects() {
  const rows = DB.projects.map(p => {
    const runs = runsOf(p.id);
    const active = runs.filter(r => r.status === 'running').length;
    const bad = runs.filter(r => r.status === 'failed').length;
    return `<a class="row" href="#/p/${p.id}">
      <div class="row-main">
        <div class="row-name">${esc(p.name)}</div>
        <div class="row-meta"><span>${esc(p.niche || 'No niche set')}</span></div>
      </div>
      ${bad ? `<span class="chip bad">${bad} needs attention</span>` : active ? `<span class="chip run">${active} in progress</span>` : ''}
      <span class="mono muted">${runs.length} run${runs.length === 1 ? '' : 's'}</span>
    </a>`;
  }).join('');
  return `<div class="wrap">
    <div class="page-head"><div><h1>Projects</h1><div class="sub">A project is one channel or series: its ideas, its runs and its defaults.</div></div>
      <button class="btn btn-primary" onclick="dlgNewProject()">+ New project</button></div>
    ${rows}
  </div>`;
}

function dlgNewProject() {
  const d = DB.defaults;
  overlay(`<div class="modal">
    <h2>New project</h2><div class="sub">Everything else is inherited from tenant Defaults and can be changed later in the project's Settings.</div>
    <div class="grid2" style="margin-top:18px;">
      <div class="field full"><label class="label" for="np-name">Name</label><input class="input" id="np-name" placeholder="The Housing Equation"></div>
      <div class="field full"><label class="label" for="np-niche">Niche — passed to script generation for every run (optional)</label><input class="input" id="np-niche" placeholder="american housing economics"></div>
      <div class="field"><label class="label" for="np-lang">Language</label><select class="select" id="np-lang">${opts(LANGS, d.language)}</select><div class="hint">Tenant default: ${LANGS[d.language]}</div></div>
      <div class="field"><label class="label" for="np-format">Format</label><select class="select" id="np-format">${opts(FORMATS, d.format)}</select><div class="hint">Tenant default: ${d.format}</div></div>
    </div>
    <div class="actions"><button class="btn btn-primary" onclick="createProject()">Create project</button><button class="btn btn-ghost" onclick="closeOverlay()">Cancel</button></div>
  </div>`);
  $('np-name').focus();
}
function createProject() {
  const name = $('np-name').value.trim();
  if (!name) { $('np-name').focus(); return toast('Give the project a name.'); }
  const settings = {};
  if ($('np-lang').value !== DB.defaults.language) settings.language = $('np-lang').value;
  if ($('np-format').value !== DB.defaults.format) settings.format = $('np-format').value;
  const p = { id: 'p' + Date.now().toString(36), name, niche: $('np-niche').value.trim(), source: 'generate', settings, aiLook: '', updated: 'today' };
  DB.projects.unshift(p);
  closeOverlay(); go(`#/p/${p.id}`);
}

// ── Project pages ──────────────────────────────────────────────────────────
function projectHead(p, title, sub, action) {
  return `<div class="page-head"><div><h1>${esc(title)}</h1><div class="sub">${sub}</div></div>${action || ''}</div>`;
}
const newRunBtn = (p, label) => `<button class="btn btn-primary" onclick="dlgNewRun('${p.id}')">${label || '+ New run'}</button>`;

function viewOverview(p) {
  const runs = runsOf(p.id), ideas = ideasOf(p.id);
  const attention = runs.filter(r => r.status !== 'complete');
  const videos = DB.assets.videos.filter(a => a.project === p.id).length;
  const stat = (n, label, href) => `<a class="stat" href="${href}"><b>${n}</b><span>${label}</span></a>`;
  return `<div class="wrap">
    ${projectHead(p, p.name, esc(p.niche || 'No niche set — add one in Settings'), newRunBtn(p))}
    <div class="stats">
      ${stat(ideas.length, 'Ideas', `#/p/${p.id}/ideas`)}${stat(runs.length, 'Runs', `#/p/${p.id}/runs`)}
      ${stat(runs.filter(r => r.status === 'running').length, 'In progress', `#/p/${p.id}/runs`)}${stat(videos, 'Videos', '#/lib/videos')}
    </div>
    ${!runs.length && !ideas.length ? `<div class="empty" style="margin-top:24px;"><strong>Start this project</strong>Add an idea to work from, or start a run and enter the details there.
        <div class="actions"><button class="btn btn-secondary" onclick="go('#/p/${p.id}/ideas');setTimeout(dlgIdea,60)">+ Add idea</button>${newRunBtn(p)}</div></div>` : `
    <div class="sec-head"><h2>Continue</h2><span class="count">${attention.length}</span><a class="more" href="#/p/${p.id}/runs">All runs →</a></div>
    ${attention.length ? attention.map(runRow).join('') : '<div class="empty">Nothing in progress.</div>'}
    <div class="sec-head"><h2>Newest ideas</h2><span class="count">${ideas.length}</span><a class="more" href="#/p/${p.id}/ideas">All ideas →</a></div>
    ${ideas.length ? ideas.slice(-3).reverse().map(i => ideaRow(i, false)).join('') : '<div class="empty">No ideas yet.</div>'}`}
  </div>`;
}

const METHOD = { manual: '', trend: 'ink', competitor: 'ink' };
function ideaRow(i, selectable) {
  const n = DB.runs.filter(r => r.ideas.includes(i.id)).length;
  const sel = S.ideaSel.has(i.id);
  return `<div class="row${sel && selectable ? ' sel' : ''}">
    ${selectable ? `<input type="checkbox" aria-label="Select idea" ${sel ? 'checked' : ''} onchange="toggleIdea('${i.id}')">` : ''}
    <div class="row-main">
      <div class="row-name">${esc(i.title)}</div>
      ${i.summary ? `<div style="font-size:13px;color:var(--ink-sub);margin-top:2px;">${esc(i.summary)}</div>` : ''}
      ${i.method !== 'manual' || i.source || n ? `<div class="row-meta">${i.method !== 'manual' ? `<span class="chip ink">${i.method}</span>` : ''}${i.source ? `<span>${esc(i.source)}</span>` : ''}${n ? `<span>${n} run${n === 1 ? '' : 's'}</span>` : ''}</div>` : ''}
    </div>
    ${selectable ? `<button class="btn btn-ghost btn-sm" onclick="dlgIdea('${i.id}')">Edit</button>` : ''}
    <button class="btn btn-secondary btn-sm" onclick="dlgNewRun('${i.project}', ['${i.id}'])">Start run →</button>
  </div>`;
}
function toggleIdea(id) { S.ideaSel.has(id) ? S.ideaSel.delete(id) : S.ideaSel.add(id); render(); }

function viewIdeas(p) {
  const ideas = ideasOf(p.id);
  const sel = [...S.ideaSel].filter(id => ideas.some(i => i.id === id));
  return `<div class="wrap">
    ${projectHead(p, 'Ideas', 'The shortlist. Start a run from one idea, or tick several to combine them into one video.',
      `<button class="btn btn-secondary" onclick="dlgIdea()">+ Add idea</button>`)}
    ${ideas.length ? ideas.slice().reverse().map(i => ideaRow(i, true)).join('')
      : `<div class="empty"><strong>No ideas yet</strong>Add one by hand. You can also start a run without an idea.<div class="actions">${newRunBtn(p, 'New run without an idea')}</div></div>`}
    ${sel.length > 1 ? `<div class="selbar"><span>${sel.length} ideas selected — combined into one video</span>
      <button class="btn btn-ghost btn-sm" style="color:#fff;" onclick="S.ideaSel.clear();render()">Clear</button>
      <button class="btn btn-primary btn-sm" onclick='dlgNewRun("${p.id}", ${JSON.stringify(sel)})'>Start run →</button></div>` : ''}
  </div>`;
}
function dlgIdea(id) {
  const r = route(); const i = id ? DB.ideas.find(x => x.id === id) : null;
  overlay(`<div class="modal"><h2>${i ? 'Edit idea' : 'Add idea'}</h2>
    <div class="grid2" style="margin-top:16px;">
      <div class="field full"><label class="label" for="id-title">Idea / title</label><input class="input" id="id-title" value="${esc(i ? i.title : '')}" placeholder="Why starter homes disappeared from America"></div>
      <div class="field full"><label class="label" for="id-sum">Summary (optional)</label><textarea class="input" id="id-sum" placeholder="What the video is about, in a sentence or two">${esc(i ? i.summary : '')}</textarea></div>
      <div class="field full"><label class="label" for="id-src">Source (optional)</label><input class="input" id="id-src" value="${esc(i ? i.source : '')}" placeholder="A report, a channel, a conversation"></div>
    </div>
    <div class="actions"><button class="btn btn-primary" onclick="saveIdea('${id || ''}','${r.project.id}')">${i ? 'Save' : 'Add to ideas'}</button>
      <button class="btn btn-ghost" onclick="closeOverlay()">Cancel</button>
      ${i ? `<button class="btn btn-danger btn-sm" style="margin-left:auto;" onclick="removeIdea('${id}')">Remove</button>` : ''}</div></div>`);
  $('id-title').focus();
}
function saveIdea(id, pid) {
  const title = $('id-title').value.trim();
  if (!title) return toast('An idea needs a title.');
  const data = { title, summary: $('id-sum').value.trim(), source: $('id-src').value.trim() };
  if (id) Object.assign(DB.ideas.find(x => x.id === id), data);
  else DB.ideas.push({ id: 'i' + Date.now().toString(36), project: pid, method: 'manual', date: 'today', ...data });
  closeOverlay(); render();
}
function removeIdea(id) {
  if (!confirm('Remove this idea? Runs already created from it are kept.')) return;
  DB.ideas.splice(DB.ideas.findIndex(x => x.id === id), 1); closeOverlay(); render();
}

function viewRuns(p) {
  const all = runsOf(p.id);
  const runs = all.filter(r => !S.runFilter || r.status === S.runFilter).slice().reverse();
  return `<div class="wrap">
    ${projectHead(p, 'Runs', 'One run is one video, from script or voiceover to the finished file.', newRunBtn(p))}
    <div class="toolbar"><select class="select" onchange="S.runFilter=this.value;render()" aria-label="Filter runs">
      <option value="">All runs (${all.length})</option>${opts({ running: 'In progress', failed: 'Needs attention', complete: 'Done' }, S.runFilter)}</select></div>
    ${runs.length ? runs.map(runRow).join('') : `<div class="empty"><strong>No runs${all.length ? ' match this filter' : ' yet'}</strong>Start one from an idea, or on its own.<div class="actions">${newRunBtn(p)}</div></div>`}
  </div>`;
}

/** A field whose value is inherited from the tenant unless the project overrides it. */
function inheritField(p, key, label, map) {
  const over = p.settings[key] !== undefined;
  return `<div class="field"><label class="label">${label}</label>
    <select class="select" onchange="setProjectSetting('${p.id}','${key}',this.value)">${opts(map, resolve(p, key))}</select>
    <div class="hint${over ? ' over' : ''}">${over
      ? `Overridden for this project · <a href="javascript:void 0" onclick="setProjectSetting('${p.id}','${key}')">Reset to tenant default (${esc(map[DB.defaults[key]])})</a>`
      : `Inherited from tenant Defaults: ${esc(map[DB.defaults[key]])}`}</div></div>`;
}
function setProjectSetting(pid, key, value) {
  const p = proj(pid);
  if (value === undefined || value === DB.defaults[key]) delete p.settings[key]; else p.settings[key] = value;
  render(); toast('Saved. New runs use this; existing runs keep their own settings.');
}
function viewProjectSettings(p) {
  return `<div class="wrap narrow">
    ${projectHead(p, 'Project settings', 'Defaults for new runs in this project. A run copies them when it is created and can change them for itself.')}
    <div class="card"><div class="card-title">Project</div><div class="card-sub">Used by every run.</div>
      <div class="grid2">
        <div class="field"><label class="label">Name</label><input class="input" value="${esc(p.name)}" onchange="proj('${p.id}').name=this.value;render()"></div>
        <div class="field"><label class="label">Niche</label><input class="input" value="${esc(p.niche)}" placeholder="american housing economics" onchange="proj('${p.id}').niche=this.value"></div>
      </div></div>
    <div class="card"><div class="card-title">Defaults for new runs</div><div class="card-sub">Each shows where its value comes from.</div>
      <div class="grid2">
        ${inheritField(p, 'language', 'Language', LANGS)}
        ${inheritField(p, 'format', 'Format', FORMATS)}
        ${inheritField(p, 'captions', 'Captions', CAPTIONS)}
        ${inheritField(p, 'voice', 'Voice (generated runs)', VOICES)}
        <div class="field"><label class="label">Usual script source</label><select class="select" onchange="proj('${p.id}').source=this.value">${opts(SOURCES, p.source)}</select><div class="hint">Preselected in a new run's Script step.</div></div>
      </div></div>
    <div class="card"><div class="card-title">AI images</div><div class="card-sub">Provider and key come from <a href="#/settings/integrations">Settings · Integrations</a>.</div>
      <label class="label">Look across scenes — added in front of every AI image prompt in this project</label>
      <textarea class="input" placeholder="Muted editorial illustration, flat colours, soft grain, no text" onchange="proj('${p.id}').aiLook=this.value">${esc(p.aiLook)}</textarea></div>
    <div class="card"><div class="card-title">Channel <span class="soon">P16</span></div><div class="card-sub" style="margin-bottom:0;">The default destination for this project's videos will be chosen here.</div></div>
  </div>`;
}
function viewPlanned(p, tab) {
  const t = tab === 'research'
    ? ['Research', 'P15', 'Trend research (Google Trends, Reddit, YouTube, Google News) and competitor research for this project\'s language and region. Each result carries its evidence; ticking one adds it to Ideas.']
    : ['Publishing', 'P16', 'The schedule of this project\'s videos per channel, with publication status. Destinations and publish time are set in a run\'s Metadata step.'];
  return `<div class="wrap narrow">${projectHead(p, t[0], `Planned for sprint ${t[1]}. Shown here to agree its place in the navigation.`)}<div class="empty"><strong>Not built yet</strong>${t[2]}</div></div>`;
}

// ── New run ────────────────────────────────────────────────────────────────
function dlgNewRun(pid, ideaIds) {
  const p = proj(pid);
  const ideas = (ideaIds || []).map(id => DB.ideas.find(i => i.id === id)).filter(Boolean);
  const title = ideas.length ? ideas[0].title : '';
  const brief = ideas.map(i => i.summary).filter(Boolean).join(' ');
  S.newRunIdeas = ideas.map(i => i.id);
  overlay(`<div class="modal">
    <h2>New run</h2><div class="sub">${ideas.length ? `From ${ideas.length === 1 ? 'the idea' : ideas.length + ' ideas'} below — edit anything.` : 'No idea attached. Enter the details here.'} In ${esc(p.name)}.</div>
    ${ideas.length ? `<div class="run-facts" style="margin-top:12px;">${ideas.map(i => `<span class="chip">${esc(i.title)}</span>`).join('')}</div>` : ''}
    <div class="grid2" style="margin-top:16px;">
      <div class="field full"><label class="label" for="nr-title">Title</label><input class="input" id="nr-title" value="${esc(title)}" placeholder="What is this video about?"></div>
      <div class="field full"><label class="label" for="nr-brief">Brief (optional) — what the script should cover</label><textarea class="input" id="nr-brief" placeholder="Angle, key numbers, what to leave out">${esc(brief)}</textarea></div>
      <div class="field"><label class="label" for="nr-lang">Language</label><select class="select" id="nr-lang">${opts(LANGS, resolve(p, 'language'))}</select><div class="hint">Project default: ${LANGS[resolve(p, 'language')]}</div></div>
      <div class="field"><label class="label" for="nr-format">Format</label><select class="select" id="nr-format">${opts(FORMATS, resolve(p, 'format'))}</select><div class="hint">Project default: ${resolve(p, 'format')}. Decides which footage is acquired.</div></div>
    </div>
    <div class="actions"><button class="btn btn-primary" onclick="createRun('${pid}')">Create run →</button><button class="btn btn-ghost" onclick="closeOverlay()">Cancel</button></div>
  </div>`);
  if (!title) $('nr-title').focus();
}
function createRun(pid) {
  const p = proj(pid); const title = $('nr-title').value.trim();
  if (!title) { $('nr-title').focus(); return toast('Give the run a title.'); }
  const run = { id: 'r-' + Math.random().toString(16).slice(2, 8), project: pid, title, brief: $('nr-brief').value.trim(), ideas: S.newRunIdeas || [],
    mode: null, src: p.source, language: $('nr-lang').value, format: $('nr-format').value,
    captions: resolve(p, 'captions'), pace: 'normal', style: 'educational', music: '', done: 0, status: 'created', cost: 0, created: 'today', acquired: false };
  DB.runs.push(run); S.ideaSel.clear(); closeOverlay(); go(`#/r/${run.id}`);
}

// ── Run ────────────────────────────────────────────────────────────────────
function viewRun(r) {
  const { run, project: p, step } = r; const steps = STEPS;
  // Arrow-shaped steps with one status dot each — the pattern from policy-scout (its D-037).
  const stepper = steps.map((s, i) => {
    const state = i < run.done ? 'done' : i > run.done ? 'idle' : run.status === 'failed' ? 'fail' : 'run';
    const title = { done: 'Completed', run: 'In progress', fail: 'Failed', idle: 'Not started' }[state];
    return `<a class="step step-${state}${s === step ? ' current' : ''}" href="#/r/${run.id}/${s}" title="${title}"${s === step ? ' aria-current="step"' : ''}>${STEP_LABELS[s]}</a>`;
  }).join('');
  return `<div class="wrap">
    <div class="run-head"><div>
        <h1>${esc(run.title)}</h1>
        <div class="run-facts"><span class="chip ink">${voiceLabel(run)}</span><span class="chip">${LANGS[run.language]}</span><span class="chip">${run.format}</span>${statusChip(run)}</div>
      </div>
      <button class="btn btn-secondary btn-sm" onclick="dlgRunSettings('${run.id}')">Run settings</button>
    </div>
    <nav class="steps" aria-label="Run steps">${stepper}</nav>
    ${run.error && steps[run.done] === step ? `<div class="note err" style="margin-top:14px;">${esc(run.error)} <a href="javascript:void 0" onclick="retryStep('${run.id}')">Retry</a></div>` : ''}
    <div class="pane">${PANES[step](run, p, steps.indexOf(step) < run.done)}</div>
  </div>`;
}
function retryStep(id) { const run = runOf(id); run.error = ''; run.status = 'running'; render(); toast('Retried.'); }
/** Mark the given step done and move to the next one. */
function advance(id, step) {
  const run = runOf(id), steps = STEPS, i = steps.indexOf(step);
  run.done = Math.max(run.done, i + 1); run.error = '';
  run.status = run.done >= steps.length ? 'complete' : 'running';
  run.cost += 0.03;
  if (i + 1 < steps.length) go(`#/r/${run.id}/${steps[i + 1]}`); else { render(); toast('Run complete.'); }
}
function optsBlock(body, changed) {
  return `<details class="opts"><summary>Options${changed ? ` · ${changed} changed` : ''}</summary><div class="opts-body">${body}</div></details>`;
}
const cta = (run, step, label, extra) => `<div class="actions"><button class="btn btn-primary" onclick="advance('${run.id}','${step}')">${label}</button>${extra || ''}</div>`;

const PANES = {
  script(run, p, done) {
    const has = done || run.scriptReady;
    const startOver = `<button class="btn btn-ghost" onclick="restartScript('${run.id}')">Start again from a different source</button>`;
    // 1 — no script yet: choose where it comes from.
    if (!has) {
      const src = run.src || p.source || 'generate';
      const card = (k, title, text) => `<button class="choice${k === src ? ' on' : ''}" onclick="runOf('${run.id}').src='${k}';render()"><b>${title}</b><span>${text}</span></button>`;
      const body = {
        generate: `<div class="grid2">
            <div class="field full"><label class="label">Brief — from the run</label><textarea class="input">${esc(run.brief || run.title)}</textarea></div>
            <div class="field"><label class="label">Target length</label><select class="select"><option>30 s</option><option selected>60 s</option><option>90 s</option><option>3 min</option></select></div></div>
          ${optsBlock(`<div class="grid2">
            <div class="field"><label class="label">Niche</label><input class="input" value="${esc(p.niche)}"><div class="hint">From the project</div></div>
            <div class="field"><label class="label">Narration style</label><select class="select">${opts(STYLES, run.style)}</select></div>
            <div class="field"><label class="label">Model</label><select class="select"><option>claude-sonnet-5-5 (tenant default)</option><option>claude-opus-5-5</option></select></div></div>`)}
          <div class="actions"><button class="btn btn-primary" onclick="setScript('${run.id}','generated')">Generate script</button></div>`,
        paste: `<textarea class="script-box" placeholder="Paste your script here…"></textarea>
          <div class="actions"><button class="btn btn-primary" onclick="setScript('${run.id}','generated')">Use this script</button></div>`,
        upload: `<div class="drop" onclick="setScript('${run.id}','uploaded');toast('Demo: uploaded and transcribed.')"><strong>Drop your voiceover, or click to choose</strong>.mp3, .wav or .m4a · 10 seconds to 10 minutes</div>
          <div class="hint">Transcribed in <b>${LANGS[run.language]}</b>. <a href="javascript:void 0" onclick="dlgRunSettings('${run.id}')">Change language</a>. The transcript becomes the script, and the recording becomes the voice.</div>`,
      }[src];
      return `<h2>Script</h2><div class="sub">Where does the script come from?</div>
        <div class="choices three" style="margin:16px 0 20px;">
          ${card('generate', 'Generate', 'From the brief, in the project\'s niche.')}
          ${card('paste', 'Paste', 'You already have the text.')}
          ${card('upload', 'From a voiceover', 'Upload a recording; its transcript is the script.')}
        </div>${body}`;
    }
    // 2 — script from an uploaded voiceover: the audio is fixed, so edits are timing-safe.
    if (run.mode === 'uploaded') {
      return `<h2>Script</h2><div class="sub">Transcribed from your voiceover. Click a word to replace it — you can change what a word says, not when it is spoken.</div>
        <div class="words" style="margin-top:16px;">${DB.script.split(/\s+/).map(w => `<span onclick="editWord(this)">${esc(w.replace(/[.,—]/g, '')) || '·'}</span>`).join(' ')}</div>
        <div class="hint">To rewrite it freely, generate a voice in the next step — that replaces your recording.</div>
        <div class="actions"><button class="btn btn-primary" onclick="advance('${run.id}','script')">Continue to Voice →</button>${startOver}</div>`;
    }
    // 3 — generated or pasted script: free text.
    return `<h2>Script</h2><div class="sub">Edit freely — the voice is generated from exactly this text.</div>
      <textarea class="script-box" style="margin-top:16px;">${esc(DB.script)}</textarea>
      <div class="hint">${DB.script.split(/\s+/).length} words · about 0:41 at normal pace</div>
      <div class="actions"><button class="btn btn-primary" onclick="advance('${run.id}','script')">${done ? 'Save & regenerate voice →' : 'Approve script & generate voice →'}</button>${startOver}</div>`;
  },
  voice(run, p, done) {
    if (run.mode === 'uploaded') {
      return `<h2>Voice</h2><div class="sub">This run uses your uploaded voiceover.</div>
        <div class="player" style="margin-top:16px;"><button class="btn btn-secondary btn-sm" onclick="demo('the voiceover would play')">▶ Play</button><div class="bar"></div><span class="mono">0:14 / 0:58</span></div>
        <div class="hint">uploaded.m4a · in <a href="#/lib/audio">Library · Audio</a> as <span class="mono">AUD-0107</span></div>
        <div class="actions"><button class="btn btn-primary" onclick="advance('${run.id}','voice')">${run.done > 2 ? 'Go to Storyboard →' : 'Create storyboard →'}</button>
          <button class="btn btn-ghost" onclick="replaceUpload('${run.id}')">Generate a voice from the script instead</button></div>`;
    }
    return `<h2>Voice</h2><div class="sub">Generated from the script. Its word timings drive the storyboard.</div>
      <div class="grid2" style="margin:16px 0;">
        <div class="field"><label class="label">Voice</label><select class="select">${opts(VOICES, resolve(p, 'voice'))}</select></div>
        <div class="field"><label class="label">Pace</label><select class="select">${opts(PACES, run.pace)}</select></div>
      </div>
      <div class="player"><button class="btn btn-secondary btn-sm" onclick="demo('the voiceover would play')">▶ Play</button><div class="bar"></div><span class="mono">0:14 / 0:41</span></div>
      ${optsBlock(`<div class="grid2"><div class="field"><label class="label">Style</label><select class="select">${opts(STYLES, run.style)}</select></div></div>
        <div class="actions"><button class="btn btn-secondary btn-sm" onclick="demo('the voice would be generated again')">Regenerate voice</button></div>`)}
      <div class="actions"><button class="btn btn-primary" onclick="advance('${run.id}','voice')">${run.done > 2 ? 'Go to Storyboard →' : 'Create storyboard →'}</button></div>`;
  },
  storyboard(run, p, done) {
    const wide = run.format === '16:9', script = S.sbView === 'script';
    const total = DB.scenes.reduce((t, s) => t + s.dur, 0);
    const sfxNames = DB.assets.music.filter(m => m.facet === 'sfx').map(m => m.name);
    let at = 0;
    const scenes = DB.scenes.map((s, i) => {
      const t = `${fmtT(at)}–${fmtT(at += s.dur)}`;
      const hue = run.acquired || s.strategy === 'ai' ? s.hue : null;
      const words = s.vo.split(' ').map((w, j) => j === 0 ? esc(w) : `<span class="vo-word" title="Split the scene before this word" onclick="splitScene(${s.n},${j})">${esc(w)}</span>`).join(' ');
      return `<div class="scene${wide ? ' wide' : ''}"><div class="thumb-wrap">${thumb(hue, hue === null ? (s.strategy === 'upload' ? 'empty' : '—') : '')}
          <button class="pencil" onclick="dlgScene(${s.n})" aria-label="Change the asset of scene ${s.n}" title="Change this scene's asset">${PENCIL}</button></div>
        <div class="scene-main">
          <div class="scene-top"><span class="mono muted">Scene ${s.n} · ${t}</span>
            <select class="chip-select" aria-label="Asset type" onchange="DB.scenes[${i}].strategy=this.value;render()">${opts({ stock: 'Stock', upload: 'Your upload', ai: 'AI image' }, s.strategy)}</select></div>
          <div class="scene-vo">${words}</div>
          <div class="scene-tools">
            <input class="chip-input${s.text ? ' on' : ''}" aria-label="On-screen text" placeholder="+ On-screen text" value="${esc(s.text)}" size="${Math.max(16, (s.text || '').length + 2)}"
              onchange="DB.scenes[${i}].text=this.value.trim();render()" onkeydown="if(event.key==='Enter')this.blur()">
            <select class="chip-select${s.sfx ? ' on' : ''}" aria-label="Sound effect" onchange="DB.scenes[${i}].sfx=this.value;render()"><option value="">${s.sfx ? 'No sound effect' : '+ Sound effect'}</option>${sfxNames.map(n => `<option${n === s.sfx ? ' selected' : ''}>${esc(n)}</option>`).join('')}</select>
            ${i < DB.scenes.length - 1 ? `<button class="chip-btn merge" onclick="mergeScene(${s.n})" title="Merge with the next scene">⤵ Merge with next</button>` : ''}
          </div>
        </div></div>`;
    }).join('');
    const scriptView = `<div class="hint" style="margin:0 0 8px;">One paragraph per scene. Move the blank lines to move the scene boundaries, then apply. The words themselves cannot be changed here.</div>
      <textarea class="script-box" id="sb-script" rows="16" spellcheck="false" oninput="checkBoundaries()">${esc(DB.scenes.map(s => s.vo).join('\n\n'))}</textarea>
      <div class="actions"><button class="btn btn-secondary btn-sm" id="sb-apply" onclick="applyBoundaries()" disabled>Apply boundaries</button>
        <button class="btn btn-ghost btn-sm" onclick="render()">Reset</button><span class="hint" id="sb-msg" style="margin:0;">${DB.scenes.length} scenes — no boundary changes</span></div>`;
    return `<div class="pane-head"><div><h2>Storyboard</h2><div class="sub">${DB.scenes.length} scenes · ${fmtT(total)}${script ? '' : ' · click a word to split a scene there'}</div></div>
        <div class="seg" role="tablist"><button class="${script ? '' : 'on'}" onclick="S.sbView='board';render()">Storyboard</button><button class="${script ? 'on' : ''}" onclick="S.sbView='script';render()">Script</button></div></div>
      <div style="margin-top:16px;">${script ? scriptView : scenes}</div>
      ${script ? '' : optsBlock(`<div class="grid2"><div class="field"><label class="label">Model</label><select class="select"><option>claude-sonnet-5-5 (tenant default)</option></select></div>
          <div class="field"><label class="label">AI images on this run</label><input class="input" value="$0.04 of $${DB.defaults.spendCap.toFixed(2)}" disabled></div></div>
        <div class="actions"><button class="btn btn-secondary btn-sm" onclick="if(confirm('Regenerate the storyboard?\\n\\nThe scenes, their on-screen text and sound effects, and every acquired asset are discarded. AI images stay in the library.'))toast('Demo: storyboard regenerated.')">Regenerate storyboard</button></div>`)}
      <div class="actions">${run.acquired
        ? `<button class="btn btn-primary" onclick="advance('${run.id}','storyboard')">Go to Video →</button><button class="btn btn-ghost" onclick="demo('stock scenes would be fetched again')">Re-acquire stock scenes</button>`
        : `<button class="btn btn-primary" onclick="runOf('${run.id}').acquired=true;render();toast('Demo: assets acquired.')">Confirm storyboard & acquire assets</button>`}</div>`;
  },
  video(run, p, done) {
    const path = run.path || run.rendered || '';
    const pick = k => `runOf('${run.id}').path='${k}';render()`;
    const frame = `<div class="video-frame${run.format === '16:9' ? ' wide' : ''}" style="background:linear-gradient(160deg,hsl(215 45% 38%),hsl(250 55% 20%))">▶</div>`;
    const ready = (id, origin) => `<div class="card" style="display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin-top:14px;">${frame}
      <div style="flex:1;min-width:200px;"><div class="card-title">Video ready</div><div class="card-sub">${origin} · ${run.format} · in <a href="#/lib/videos">Library · Videos</a> as <span class="mono">${id}</span></div>
      <button class="btn btn-secondary btn-sm" onclick="demo('the file would download')">Download</button></div></div>`;
    return `<h2>Video</h2><div class="sub">Choose how this video is finished. You can use both on one run.</div>
      <div class="choices" style="margin-top:14px;">
        <button class="choice${path === 'server' ? ' on' : ''}" onclick="${pick('server')}"><b>Render here</b><span>The finished video in a few minutes, with captions and music as set below.</span></button>
        <button class="choice${path === 'capcut' ? ' on' : ''}" onclick="${pick('capcut')}"><b>Finish in CapCut</b><span>Download the project, edit and render it in CapCut, then upload the result here.</span></button>
      </div>
      ${path === 'server' ? (run.renderedNow || run.rendered === 'server' ? ready('VID-0041', 'Server render')
          : `<div class="actions"><button class="btn btn-primary" onclick="runOf('${run.id}').renderedNow=true;render();toast('Demo: rendered.')">Render video</button></div>`) : ''}
      ${path === 'capcut' ? `<ol class="todo" style="margin-top:14px;">
          <li><span>Download the CapCut package (timeline, assets, voiceover)</span><button class="btn btn-secondary btn-sm" onclick="demo('the zip would download')">Download</button></li>
          <li><span>Run the included command on your laptop, then edit and render in CapCut</span></li>
          <li><span>Upload the finished video</span><button class="btn btn-secondary btn-sm" onclick="runOf('${run.id}').capcutUp=true;render()">Upload .mp4</button></li></ol>
          ${run.capcutUp || run.rendered === 'capcut' ? ready('VID-0044', 'Uploaded from CapCut') : ''}` : ''}
      ${optsBlock(`<div class="grid2">
        <div class="field"><label class="label">Captions</label><select class="select">${opts(CAPTIONS, run.captions)}</select></div>
        <div class="field"><label class="label">Music</label><select class="select"><option value="">None</option>${DB.assets.music.filter(m => m.facet === 'music').map(m => `<option${m.name === run.music ? ' selected' : ''}>${m.name}</option>`).join('')}</select>
          <div class="hint">From <a href="#/lib/music">Library · Music & SFX</a></div></div></div>`, run.captions !== resolve(p, 'captions') ? 1 : 0)}
      ${path ? cta(run, 'video', 'Continue to Metadata →') : ''}`;
  },
  metadata(run, p, done) {
    const has = done || run.metaReady;
    return `<h2>Metadata</h2><div class="sub">Title, description and tags for publishing, in ${LANGS[run.language]}.</div>
      ${has ? `<div class="grid2" style="margin-top:14px;">
          <div class="field full"><label class="label">Title</label><input class="input" value="${esc(run.title)}"></div>
          <div class="field full"><label class="label">Description</label><textarea class="input">Starter homes were 40% of new construction in 1982 and 7% in 2020. Here is what happened. #housing #economics</textarea></div>
          <div class="field full"><label class="label">Tags</label><input class="input" value="housing, starter homes, zoning, permit fees"></div></div>
          ${optsBlock('<div class="hint" style="margin:0;">Alternative titles: “Who killed the starter home?” · “The $40,000 fee that ended small houses”</div>')}
          <div class="card" style="margin-top:16px;"><div class="card-title">Publish <span class="soon">P16</span></div><div class="card-sub" style="margin:2px 0 0;">Destinations, publish time and status will be here.</div></div>
          ${run.done < STEPS.length ? cta(run, 'metadata', 'Finish run') : ''}`
        : `<div class="actions"><button class="btn btn-primary" onclick="runOf('${run.id}').metaReady=true;render()">Generate metadata</button></div>`}`;
  },
};
const PENCIL = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>';
const fmtT = s => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`;

// ── Script and voice source ────────────────────────────────────────────────
/** A script now exists; `mode` says whether the voice is generated from it or is the upload it came from. */
function setScript(id, mode) { const run = runOf(id); run.scriptReady = true; run.mode = mode; if (run.status === 'created') run.status = 'running'; render(); }
function restartScript(id) {
  const run = runOf(id);
  const later = run.done > 0 ? '\n\nThe voice, the storyboard and its acquired assets are discarded.' : '';
  if (!confirm('Start the script again from a different source?' + later)) return;
  Object.assign(run, { scriptReady: false, mode: null, done: 0, acquired: false, status: 'running' }); render();
}
/** Switch an uploaded-voiceover run to a generated voice — the case the operator must confirm. */
function replaceUpload(id) {
  const run = runOf(id);
  const sb = run.done > 2 ? ' The storyboard and its acquired assets are discarded, because the word timings change.' : '';
  if (!confirm('Replace your uploaded voiceover with a generated voice?\n\nThe voice will be generated from the script.' + sb + '\n\nYour recording stays in Library · Audio.')) return;
  Object.assign(run, { mode: 'generated', done: 1, acquired: false, status: 'running' }); render();
  toast('Now a generated voice. The script can be edited freely.');
}

// ── Storyboard: split, merge, on-screen text, boundaries ───────────────────
const renumber = () => DB.scenes.forEach((s, i) => { s.n = i + 1; });
function splitScene(n, at) {
  const s = DB.scenes[n - 1], words = s.vo.split(' ');
  if (!confirm(`Split scene ${n} before “${words[at]}”?\n\nThe new scene starts without an asset, on-screen text or sound effect.`)) return;
  const share = at / words.length, dur = s.dur;
  s.vo = words.slice(0, at).join(' '); s.dur = Math.max(1, Math.round(dur * share));
  DB.scenes.splice(n, 0, { dur: Math.max(1, dur - s.dur), vo: words.slice(at).join(' '), strategy: 'stock', query: '', hue: (s.hue + 75) % 360, text: '', sfx: '' });
  renumber(); render();
}
function mergeScene(n) {
  const s = DB.scenes[n - 1], next = DB.scenes[n];
  const lost = [next.text ? `on-screen text “${next.text}”` : '', next.sfx ? `sound effect “${next.sfx}”` : ''].filter(Boolean);
  if (!confirm(`Merge scene ${n} with scene ${n + 1}?` + (lost.length ? `\n\nScene ${n + 1}'s ${lost.join(' and ')} and its asset are dropped.` : `\n\nScene ${n + 1}'s asset is dropped.`))) return;
  s.vo += ' ' + next.vo; s.dur += next.dur; DB.scenes.splice(n, 1); renumber(); render();
}
const paragraphs = text => text.trim().split(/\n\s*\n/).map(p => p.trim().split(/\s+/).filter(Boolean)).filter(p => p.length);
function checkBoundaries() {
  const typed = paragraphs($('sb-script').value);
  const changedWords = typed.flat().join(' ') !== DB.scenes.map(s => s.vo).join(' ');
  const same = typed.map(p => p.join(' ')).join('|') === DB.scenes.map(s => s.vo).join('|');
  $('sb-msg').textContent = changedWords ? 'The words differ from the voiceover. Change the text in the Script step.'
    : same ? `${DB.scenes.length} scenes — no boundary changes` : `${DB.scenes.length} scenes → ${typed.length}`;
  $('sb-msg').style.color = changedWords ? 'var(--red)' : '';
  $('sb-apply').disabled = changedWords || same;
}
function applyBoundaries() {
  const typed = paragraphs($('sb-script').value);
  if (!confirm(`${DB.scenes.length} scenes become ${typed.length}.\n\nA scene whose start does not move keeps its asset, on-screen text and sound effect. Apply?`)) return;
  const total = DB.scenes.reduce((t, s) => t + s.dur, 0), count = typed.flat().length;
  const byStart = {}; let pos = 0;
  DB.scenes.forEach(s => { byStart[pos] = s; pos += s.vo.split(' ').length; });
  pos = 0;
  DB.scenes = typed.map((p, i) => {
    const old = byStart[pos] || { strategy: 'stock', query: '', hue: (i * 67) % 360, text: '', sfx: '' };
    pos += p.length;
    return { ...old, vo: p.join(' '), dur: Math.max(1, Math.round(total * p.length / count)) };
  });
  renumber(); S.sbView = 'board'; render(); toast('Scene boundaries applied.');
}

function editWord(el) {
  const v = prompt('Replace this word (one word, or several for the same moment):', el.textContent);
  if (v === null) return;
  if (!v.trim()) return toast('A spoken word cannot be deleted — only replaced.');
  el.textContent = v.trim(); el.classList.add('ed');
}

function dlgRunSettings(id) {
  const run = runOf(id), p = proj(run.project);
  const hasText = run.done >= 1;
  const diff = (key, map) => run[key] !== resolve(p, key)
    ? `<div class="hint over">● Differs from the project default (${esc(map[resolve(p, key)])}) · <a href="javascript:void 0" onclick="setRun('${id}','${key}','${resolve(p, key)}')">Reset</a></div>`
    : '<div class="hint">Same as the project default</div>';
  overlay(`<div class="drawer">
    <div style="display:flex;align-items:flex-start;gap:8px;"><div style="flex:1;"><h2>Run settings</h2><div class="sub">For this run only. Available from every step.</div></div>
      <button class="icon-btn" onclick="closeOverlay()" aria-label="Close">✕</button></div>
    <div class="grid2" style="margin-top:18px;">
      <div class="field"><label class="label">Voice</label><input class="input" value="${voiceLabel(run)}" disabled><div class="hint">Follows the script's source. Switch it in the Voice step.</div></div>
      <div class="field"><label class="label">Language</label><select class="select" ${hasText ? 'disabled' : ''} onchange="setRun('${id}','language',this.value)">${opts(LANGS, run.language)}</select>
        ${hasText ? `<div class="hint">Locked: a script exists in this language.</div>` : diff('language', LANGS)}</div>
      <div class="field"><label class="label">Format</label><select class="select" onchange="setRun('${id}','format',this.value)">${opts(FORMATS, run.format)}</select>
        ${run.acquired ? '<div class="hint" style="color:var(--amber);">Assets were acquired for this format. Changing it means acquiring them again.</div>' : diff('format', FORMATS)}</div>
      <div class="field"><label class="label">Captions</label><select class="select" onchange="setRun('${id}','captions',this.value)">${opts(CAPTIONS, run.captions)}</select>${diff('captions', CAPTIONS)}</div>
      ${run.mode === 'generated' ? `<div class="field"><label class="label">Narration pace</label><select class="select" onchange="setRun('${id}','pace',this.value)">${opts(PACES, run.pace)}</select></div>
        <div class="field"><label class="label">Narration style</label><select class="select" onchange="setRun('${id}','style',this.value)">${opts(STYLES, run.style)}</select></div>` : ''}
    </div>
    <div class="sec-head" style="margin-top:26px;"><h2>About this run</h2></div>
    <div class="row-meta" style="display:block;line-height:1.9;">Project: <a href="#/p/${p.id}" onclick="closeOverlay()">${esc(p.name)}</a><br>
      Ideas: ${run.ideas.length ? run.ideas.map(i => esc((DB.ideas.find(x => x.id === i) || {}).title || 'removed idea')).join(', ') : 'none — started on its own'}<br>
      Created: ${run.created} · Cost so far: $${run.cost.toFixed(2)} · ID: <span class="mono">${run.id}</span></div>
    <div class="actions" style="margin-top:26px;"><button class="btn btn-danger btn-sm" onclick="demo('the run would be archived')">Delete run</button></div>
  </div>`, true);
}
function setRun(id, key, value) {
  const run = runOf(id);
  if (key === 'format' && run.acquired && value !== run.format) {
    if (!confirm('Change the format?\n\nThe acquired assets were chosen for ' + run.format + '. They will be discarded and acquired again.')) return dlgRunSettings(id);
    run.acquired = false;
  }
  run[key] = value; render(); dlgRunSettings(id);
}

function dlgScene(n) { S.scene = n; S.sceneTab = { stock: 'stock', upload: 'upload', ai: 'ai' }[DB.scenes[n - 1].strategy]; drawScene(); }
function drawScene() {
  const s = DB.scenes[S.scene - 1], t = S.sceneTab;
  const tab = (k, label) => `<button class="tab${t === k ? ' on' : ''}" onclick="S.sceneTab='${k}';drawScene()">${label}</button>`;
  const body = {
    stock: `<label class="label">Search words</label><div style="display:flex;gap:8px;"><input class="input" value="${esc(s.query || '')}" placeholder="city council zoning map"><button class="btn btn-secondary" onclick="setScene('stock')">Find</button></div>
      <div class="hint">Searches Pexels, then Pixabay. Or pick from <a href="#/lib/footage" onclick="closeOverlay()">Library · Footage</a>.</div>`,
    upload: `<div class="drop" onclick="setScene('upload')"><strong>Drop a file, or click to choose</strong>.mp4, .webm, .jpg, .png or .webp</div>`,
    ai: `<label class="label">Describe the image</label><textarea class="input" placeholder="Subject, setting, light, composition">${esc(s.prompt || s.vo)}</textarea>
      <div class="hint">The project's look is added in front. About $0.04 per image · $0.04 of $${DB.defaults.spendCap.toFixed(2)} used on this run.</div>
      <div class="actions"><button class="btn btn-secondary" onclick="setScene('ai')">Generate</button></div>`,
  }[t];
  overlay(`<div class="modal"><h2>Scene ${s.n}</h2><div class="sub">${esc(s.vo)}</div>
    <div class="tabs">${tab('stock', 'Stock')}${tab('upload', 'Upload')}${tab('ai', 'AI image')}</div>${body}
    <div class="field" style="margin-top:18px;max-width:220px;"><label class="label">Motion</label><select class="select"><option>Automatic</option><option>Ken Burns (slow zoom)</option><option>None</option></select></div>
    <div class="actions"><button class="btn btn-ghost" onclick="closeOverlay()">Close</button></div></div>`);
}
function setScene(strategy) {
  DB.scenes[S.scene - 1].strategy = strategy; closeOverlay(); render();
  toast(`Demo: scene ${S.scene} is now ${{ stock: 'a stock scene', upload: 'your upload', ai: 'an AI image' }[strategy]}.`);
}

// ── Libraries ──────────────────────────────────────────────────────────────
function viewLib(kind) {
  const lib = LIBS[kind], f = S.lib, all = DB.assets[kind];
  const facets = [...new Set(all.map(a => a.facet).filter(Boolean))];
  const list = all.filter(a => (!f.project || a.project === f.project) && (!f.facet || a.facet === f.facet)
    && (!f.q || `${a.id} ${a.name} ${a.facts}`.toLowerCase().includes(f.q.toLowerCase())));
  const cards = list.map(a => {
    const p = a.project && proj(a.project), run = a.run && runOf(a.run);
    return `<div class="asset">${lib.thumb ? thumb(a.hue, kind === 'videos' ? '▶' : '') : ''}
      <div class="asset-body"><div class="asset-name">${esc(a.name)}</div>
        ${p ? `<a class="asset-link" href="#/p/${p.id}" title="Project">${esc(p.name)}</a>` : '<span class="asset-link">Shared — all projects</span>'}
        ${run ? `<a class="asset-link" href="#/r/${run.id}" title="Run">↳ ${esc(run.title)}</a>` : ''}
        <div class="asset-facts">${esc(a.facts)} · ${a.date}</div>
        <div class="asset-foot"><span class="mono" title="Asset ID">${a.id}</span>
          ${kind === 'footage' || kind === 'ai' ? `<button class="btn btn-ghost btn-sm" onclick="demo('you would pick a scene in an open run')" title="Later build story">Use</button>` : ''}
          <button class="btn btn-secondary btn-sm" onclick="demo('${a.name} would download')">Download</button></div></div></div>`;
  }).join('');
  return `<div class="wrap" style="max-width:1180px;">
    <div class="page-head"><div><h1>${lib.label}</h1><div class="sub">${lib.blurb}</div></div>
      ${kind === 'music' ? `<button class="btn btn-secondary" onclick="demo('a track would be added to the library')">+ Upload</button>` : ''}</div>
    <div class="toolbar">
      <input class="input" placeholder="Search by name, ID or description" value="${esc(f.q)}" oninput="S.lib.q=this.value;refreshLib()" id="lib-q">
      ${kind !== 'music' ? `<select class="select" onchange="S.lib.project=this.value;render()" aria-label="Project"><option value="">All projects</option>${DB.projects.map(p => `<option value="${p.id}"${f.project === p.id ? ' selected' : ''}>${esc(p.name)}</option>`).join('')}</select>` : ''}
      ${facets.length > 1 ? `<select class="select" onchange="S.lib.facet=this.value;render()" aria-label="Type"><option value="">All types</option>${facets.map(x => `<option${f.facet === x ? ' selected' : ''}>${x}</option>`).join('')}</select>` : ''}
    </div>
    <div class="count" style="margin-bottom:10px;">${list.length} of ${all.length}</div>
    ${list.length ? `<div class="assets">${cards}</div>` : '<div class="empty"><strong>Nothing matches</strong>Change the search or the filters.</div>'}
  </div>`;
}
/** Re-render the library while keeping the caret in the search box. */
function refreshLib() { render(); const q = $('lib-q'); if (q) { q.focus(); q.setSelectionRange(q.value.length, q.value.length); } }

// ── Tenant settings ────────────────────────────────────────────────────────
function viewIntegrations() {
  const keyState = i => i.key === 'tenant' ? `<span class="dot-s ok"></span>Saved key ending ${i.hint}`
    : i.key === 'env' ? '<span class="dot-s env"></span>Using the Railway variable' : '<span class="dot-s"></span>No key yet';
  const row = i => `<div class="integ">
      <div><div class="row-name">${i.name} ${i.planned ? `<span class="soon">${i.planned}</span>` : ''}${i.active ? '<span class="chip run" style="margin-left:6px;">image provider in use</span>' : ''}</div><div class="row-meta" style="margin-top:1px;">${i.use}</div></div>
      <div style="font-size:12px;">${keyState(i)}</div>
      <div>${i.models ? `<select class="select" aria-label="Default model">${i.models.map(m => `<option${m === i.model ? ' selected' : ''}>${m}</option>`).join('')}</select>` : '<span class="muted" style="font-size:12px;">No model to choose</span>'}</div>
      <button class="btn btn-secondary btn-sm" onclick="S.keyEdit=S.keyEdit==='${i.id}'?'':'${i.id}';render()">${i.key === 'tenant' ? 'Replace key' : 'Add key'}</button>
      ${i.warn ? `<div class="warnrow">⚠ ${i.warn}</div>` : ''}
      ${S.keyEdit === i.id ? `<div class="keyrow"><input class="input" type="text" placeholder="Paste a key — it is stored encrypted and never shown again" aria-label="API key">
        <button class="btn btn-primary btn-sm" onclick="saveKey('${i.id}')">Save</button>${i.key === 'tenant' ? `<button class="btn btn-ghost btn-sm" onclick="clearKey('${i.id}')">Remove saved key</button>` : ''}</div>` : ''}
    </div>`;
  return `<div class="wrap">
    <div class="page-head"><div><h1>Integrations</h1><div class="sub">Every service the pipeline calls: its key and default model, set once for the tenant. Projects and runs use them; they never see a key.</div></div></div>
    <div class="note">A key saved here wins over the Railway variable of the same service. Without one, the Railway variable is used.</div>
    ${DB.integrations.map(row).join('')}
  </div>`;
}
function saveKey(id) { const i = DB.integrations.find(x => x.id === id); i.key = 'tenant'; i.hint = '••••'; i.warn = ''; S.keyEdit = ''; render(); toast('Demo: key saved.'); }
function clearKey(id) { DB.integrations.find(x => x.id === id).key = 'env'; S.keyEdit = ''; render(); }

function viewDefaults() {
  const d = DB.defaults;
  const overriding = key => DB.projects.filter(p => p.settings[key] !== undefined).length;
  const f = (key, label, map) => `<div class="field"><label class="label">${label}</label>
    <select class="select" onchange="DB.defaults['${key}']=this.value;render();toast('Saved. Projects that have not overridden it now use this.')">${opts(map, d[key])}</select>
    <div class="hint">${overriding(key) ? `${overriding(key)} of ${DB.projects.length} projects override this` : 'Used by every project'}</div></div>`;
  return `<div class="wrap narrow">
    <div class="page-head"><div><h1>Defaults</h1><div class="sub">What every project starts from. Order of precedence: run, then project, then these.</div></div></div>
    <div class="card"><div class="card-title">New projects and runs</div><div class="card-sub">Existing runs are not changed by an edit here.</div>
      <div class="grid2">${f('language', 'Language', LANGS)}${f('format', 'Format', FORMATS)}${f('captions', 'Captions', CAPTIONS)}${f('voice', 'Voice (generated runs)', VOICES)}</div></div>
    <div class="card"><div class="card-title">Spend</div><div class="card-sub">A run stops generating AI images when it reaches the cap.</div>
      <div class="grid2"><div class="field"><label class="label">AI image cap per run (USD)</label><input class="input" type="number" step="0.5" min="0" value="${d.spendCap}" onchange="DB.defaults.spendCap=Number(this.value)||0"></div></div></div>
  </div>`;
}

// ── Overlay and render ─────────────────────────────────────────────────────
function overlay(html, side) {
  $('overlay').innerHTML = `<div class="backdrop${side ? ' side' : ''}" onmousedown="if(event.target===this)closeOverlay()">${html}</div>`;
}
function closeOverlay() { $('overlay').innerHTML = ''; }
document.addEventListener('keydown', e => { if (e.key === 'Escape') { closeOverlay(); closeNav(); } });

function render() {
  const r = route();
  $('shell').classList.toggle('folded', isFolded(r));
  renderNav(r); renderCrumbs(r);
  const page = $('page');
  if (r.kind === 'projects') page.innerHTML = viewProjects();
  else if (r.kind === 'project') {
    const v = { overview: viewOverview, ideas: viewIdeas, runs: viewRuns, settings: viewProjectSettings };
    page.innerHTML = v[r.tab] ? v[r.tab](r.project) : (r.tab === 'research' || r.tab === 'publishing') ? viewPlanned(r.project, r.tab) : viewOverview(r.project);
  }
  else if (r.kind === 'run') page.innerHTML = viewRun(r);
  else if (r.kind === 'lib') page.innerHTML = viewLib(r.lib);
  else page.innerHTML = r.tab === 'defaults' ? viewDefaults() : viewIntegrations();
}
let lastHash = null;
window.addEventListener('hashchange', () => {
  closeNav(); closeOverlay();
  if (route().kind !== 'run') S.runUnfold = false;
  render();
  if (location.hash !== lastHash) document.querySelector('.main').scrollTop = 0;
  lastHash = location.hash;
});
render();
