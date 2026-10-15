/* Super screens of the new design (Sprint P-CORE, D118).
 *
 * The Creator page (creator.js) is the host. For a Super session it loads this file, which adds the
 * screens the old Studio and its shell pages used to have: Projects, one project (overview, ideas, runs,
 * settings, assets), the five Libraries, Integrations and Defaults. The run-flow additions (script
 * generation, voice upload, stock footage, metadata, CapCut, Auto-advance) are in core-run.js.
 *
 * Everything here only draws what the server returns; every call it makes is checked by the server, so a
 * Basic session that somehow loaded this file would still get 403s.
 */
(function () {
  'use strict';

  let A = null;                       // window.CFApp from creator.js
  let BASIC = false;                  // a Basic session gets the Libraries screen only
  const ROUTES = ['projects', 'project', 'library', 'settings'];
  const LANGS = { en: 'English', ru: 'Русский' };
  const FORMATS = { '9:16': '9:16 Portrait', '16:9': '16:9 Landscape' };
  const CAPTIONS = { standard: 'On — Standard', punch: 'On — Punch', none: 'Off' };
  const PACES = { slow: 'Slow', normal: 'Normal', fast: 'Fast' };
  const NARR_STYLES = { educational: 'Educational', emotional: 'Emotional' };
  const STEP_LABELS = { script: 'Script', voice: 'Voice', storyboard: 'Storyboard', render: 'Render', metadata: 'Metadata' };
  const ASSET_KINDS = { character: 'Character', setting: 'Place', prop: 'Object' };
  const BIN = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/></svg>';
  const BASIC_LIBS = ['videos', 'ai', 'images', 'assets', 'music'];
  const LIBS = { videos: 'Videos', audio: 'Audio', footage: 'Footage', ai: 'AI generations', images: 'Images', assets: 'AI assets', music: 'BG music' };
  // What each screen says about itself lives in the right-hand Information panel, not on the page.
  const HELP = {
    projects: ['Projects', ['A project is one channel or series: its ideas, its videos and its defaults.']],
    'project-overview': ['Project', ['What is in progress, the newest ideas and the numbers for this project.']],
    'project-ideas': ['Ideas', ['The shortlist. Start a video from one idea, or tick several to combine them into one video.']],
    'project-runs': ['Videos', ['Every video made in this project.']],
    'project-settings': ['Project settings', [
      'The niche is passed to script generation for every video.',
      'Channel identity: describe the channel once — topics, audience, tone. The description and tags are written for it.',
      'Defaults for new videos: each shows where its value comes from. A project value wins over the Defaults.',
      'Master visual prompt: the look every AI image in this project shares. A video can set its own; the video\'s wins.',
      'Project assets: recurring characters, places and objects. An animated video\'s storyboard reuses them, with exactly this description, instead of inventing new ones. Save one from a video\'s characters and props, or add it here.']],
    'library-videos': ['Videos', ['Every final video: server renders and videos uploaded from CapCut.']],
    'library-audio': ['Audio', ['Every voiceover, generated or uploaded.']],
    'library-footage': ['Footage', ['Every image and clip acquired for a scene or uploaded by you.']],
    'library-images': ['Images', ['Every still image: pictures acquired from stock or uploaded, and AI-generated ones, including the ones you replaced.',
      'Use the type filter to show only stock or only AI-generated images.']],
    'library-ai': ['AI generations', ['Every AI-generated image, including the ones you replaced.']],
    'library-assets': ['AI assets', ['Your characters, places and objects. Save one from a video\'s storyboard or add it here.',
      'When you create a video you can pick a character from this library instead of describing it again.']],
    'library-music': ['BG music', ['Background music only: tracks you uploaded and tracks the platform provides.',
      'Sound effects are not listed here.', 'Choose a track for a video in its Render step.']],
    integrations: ['Integrations', ['The services the pipeline calls, in five blocks. Each provider has its own key; a block with several providers has one default.',
      'A key saved here wins over the Railway variable of the same service. Without one, the Railway variable is used.']],
    defaults: ['Defaults', ['What every project starts from. Order of precedence: the video, then the project, then these.',
      'Existing videos are not changed by an edit here.', 'A video stops generating AI images when it reaches the spend cap.']],
  };


  const C = {
    tenant: null, projects: [], project: null, items: [], runs: [], tab: 'overview', selected: new Set(), runFilter: '',
    lib: { kind: 'videos', data: { items: [], projects: [] }, filters: { q: '', project: '', facet: '' } },
    settings: { blocks: null, image: null, defaults: null, keyEdit: '' },
    newRun: { projectId: '', itemIds: [], title: '', brief: '' },
  };

  const esc = v => String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const $ = sel => document.querySelector(sel);
  const opts = (map, value) => Object.entries(map).map(([k, v]) => `<option value="${esc(k)}"${k === value ? ' selected' : ''}>${esc(v)}</option>`).join('');
  const fmtDate = iso => { const d = new Date(iso); return isNaN(d) ? '' : d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }); };
  const qs = id => document.getElementById(id);

  // ── Shared pieces ─────────────────────────────────────────────────────────

  /** A small message that disappears by itself. */
  function toast(msg) {
    let el = qs('core-toast');
    if (!el) {
      el = document.createElement('div');
      el.id = 'core-toast';
      el.setAttribute('role', 'status');
      document.body.appendChild(el);
    }
    el.textContent = msg;
    el.classList.add('on');
    clearTimeout(toast.t);
    toast.t = setTimeout(() => el.classList.remove('on'), 3200);
  }

  /** The error line at the top of the Super screen. */
  function showErr(msg) {
    const el = qs('x-err');
    if (!el) return;
    el.textContent = msg || '';
    el.classList.toggle('on', !!msg);
  }

  /** A modal built from markup; returns the backdrop. Click outside or Escape closes it. */
  function modal(html, wide) {
    closeModal();
    const bd = document.createElement('div');
    bd.className = 'modal-bd on';
    bd.id = 'core-modal';
    bd.innerHTML = `<div class="modal" role="dialog" aria-modal="true" style="max-width:${wide || 520}px">
      <button class="icon-btn m-x" onclick="Core.closeModal()" aria-label="Close"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg></button>${html}</div>`;
    bd.addEventListener('mousedown', e => { if (e.target === bd) closeModal(); });
    document.body.appendChild(bd);
    const first = bd.querySelector('input,textarea,select');
    if (first) first.focus();
    return bd;
  }
  function closeModal() { const m = qs('core-modal'); if (m) m.remove(); }
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });

  /** JSON call via the host's api(); returns {ok,status,data}. */
  const call = (path, method, body) => A.api(path, body === undefined ? { method: method || 'GET' } : { method, body });

  function setNav(key) {
    document.querySelectorAll('#super-menu [data-nav]').forEach(a => a.classList.toggle('on', a.dataset.nav === key));
    const runs = qs('nav-runs');
    if (runs) runs.classList.remove('on');
    if (!key.startsWith('project:') && key !== 'projects') paintProjectNav(null);
  }
  /** Under "All projects": the open project and its pages, as the beta panel had them. */
  function paintProjectNav(tab) {
    const box = qs('nav-project');
    if (!box) return;
    if (!tab || !C.project) { box.innerHTML = ''; return; }
    const id = encodeURIComponent(C.project.project_id);
    const item = (t, label) => `<a class="nav-btn sm${t === tab ? ' on' : ''}" href="#project/${id}${t === 'overview' ? '' : '/' + t}" style="text-decoration:none">${label}</a>`;
    box.innerHTML = `<div class="sub"><div class="proj">${esc(C.project.name)}</div>${item('overview', 'Overview')}${item('ideas', 'Ideas')}${item('runs', 'Runs')}${item('settings', 'Settings')}</div>`;
  }
  function clearNav() { document.querySelectorAll('#super-menu [data-nav].on').forEach(a => a.classList.remove('on')); }

  const crumbs = parts => parts.map(([label, href]) => href ? `<a href="${href}">${esc(label)}</a>` : esc(label)).join(' / ');
  function frame(crumb, body) {
    qs('s-x').innerHTML = `<div class="crumb">${crumb || '&nbsp;'}</div><div class="err-line" id="x-err"></div>${body}`;
  }
  const loading = () => frame('', '<p class="meta">Loading…</p>');

  async function tenantDefaults() {
    if (C.tenant) return C.tenant;
    const r = await call('/platform/tenant/defaults');
    C.tenant = r.ok ? r.data : { language: 'en', format: '9:16', captions: 'standard', spend_cap: 2 };
    return C.tenant;
  }
  /** What a project sets, in tenant-default vocabulary (only what it overrides). */
  function overrides(project) {
    const c = (project && project.config) || {}, rd = c.run_defaults || {}, out = {};
    if (c.language) out.language = c.language;
    if (rd.aspect_ratio) out.format = rd.aspect_ratio;
    if (rd.subtitles === 'none') out.captions = 'none';
    else if (rd.caption_style) out.captions = rd.caption_style;
    return out;
  }

  // ── Routing ───────────────────────────────────────────────────────────────

  /** The Information panel's entry for a route. */
  function helpKey(name, id, step) {
    if (name === 'projects') return 'projects';
    if (name === 'project') return 'project-' + (['ideas', 'runs', 'settings'].includes(step) ? step : 'overview');
    if (name === 'library') return 'library-' + (LIBS[id] ? id : 'videos');
    return id === 'defaults' ? 'defaults' : 'integrations';
  }
  const handles = name => (BASIC ? name === 'library' : ROUTES.includes(name));

  async function route(name, id, step, more) {
    showErr('');
    A.setHelp(helpKey(name, id, step));
    try {
      if (name === 'projects') return await viewProjects();
      if (name === 'project') return await viewProject(id, ['ideas', 'runs', 'settings'].includes(step) ? step : 'overview');
      if (name === 'library') return await viewLibrary(LIBS[id] && (!BASIC || BASIC_LIBS.includes(id)) ? id : 'videos');
      if (name === 'settings') return await viewSettings(id === 'defaults' ? 'defaults' : 'integrations');
    } catch (e) {
      frame('', '');
      showErr(`This page could not load: ${e.message}`);
    }
  }

  // ── Projects ──────────────────────────────────────────────────────────────

  function projectRow(p) {
    const lang = (p.config && p.config.language) || C.tenant.language;
    const arrow = '<svg class="arrow" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6"/></svg>';
    return `<a class="run-item" href="#project/${encodeURIComponent(p.project_id)}" style="text-decoration:none;color:inherit"><div class="main-col">
      <div class="t">${esc(p.name)}</div>
      <div class="m"><span>${p.niche ? esc(p.niche) : 'No niche set'}</span><span class="sep">·</span><span>${esc(LANGS[lang] || lang)}</span><span class="sep">·</span>
      <span>${p.run_count} video${p.run_count === 1 ? '' : 's'}${p.last_activity ? ' · ' + esc(fmtDate(p.last_activity)) : ''}</span></div></div>${arrow}</a>`;
  }
  async function viewProjects() {
    paintProjectNav(null);
    setNav('projects');
    loading();
    await tenantDefaults();
    const r = await call('/platform/projects');
    if (!r.ok) throw new Error(A.why(r));
    C.projects = r.data;
    frame('&nbsp;', `<div class="page-head"><h1>Projects</h1><button class="btn primary" onclick="Core.dlgNewProject()">+ New project</button></div>
      <div class="run-list">${C.projects.length ? C.projects.map(projectRow).join('')
        : '<div class="empty"><b>No projects yet</b><p>Create a project to collect ideas and make videos for one channel.</p><button class="btn primary" onclick="Core.dlgNewProject()">New project</button></div>'}</div>`);
  }
  function dlgNewProject() {
    const d = C.tenant || { language: 'en', format: '9:16' };
    modal(`<h2>New project</h2><p class="sub-t">Everything else is inherited from Defaults and can be changed in the project's settings.</p>
      <label class="field"><span class="lbl">Name</span><input type="text" id="np-name" maxlength="120" placeholder="The Housing Equation"></label>
      <label class="field"><span class="lbl">Niche — passed to script generation for every video (optional)</span><input type="text" id="np-niche" maxlength="200" placeholder="american housing economics"></label>
      <div class="row"><label class="field"><span class="lbl">Language</span><select id="np-lang">${opts(LANGS, d.language)}</select></label>
      <label class="field"><span class="lbl">Format</span><select id="np-format">${opts(FORMATS, d.format)}</select></label></div>
      <div class="e-foot"><button class="btn accent sm" id="np-go" onclick="Core.createProject()">Create project</button><button class="btn sm" onclick="Core.closeModal()">Cancel</button></div>
      <div class="m-msg" id="np-msg"></div>`);
  }
  async function createProject() {
    const name = qs('np-name').value.trim();
    if (!name) { qs('np-msg').textContent = 'Give the project a name.'; return; }
    const d = C.tenant || {};
    const config = {};
    if (qs('np-lang').value !== d.language) config.language = qs('np-lang').value;
    if (qs('np-format').value !== d.format) config.run_defaults = { aspect_ratio: qs('np-format').value };
    qs('np-go').disabled = true;
    const r = await call('/platform/projects', 'POST', { name, niche: qs('np-niche').value.trim(), config });
    if (!r.ok) { qs('np-go').disabled = false; qs('np-msg').textContent = A.why(r); return; }
    closeModal();
    A.go(`#project/${encodeURIComponent(r.data.project_id)}`);
  }

  // ── One project ───────────────────────────────────────────────────────────

  const isDone = r => r.steps_done >= 5;
  function runStatusChip(r) {
    if (isDone(r)) return '<span class="chip">Done</span>';
    const at = STEP_LABELS[r.current_step] || 'Script';
    if (r.status === 'failed') return `<span class="chip flag">Needs attention · ${esc(at)}</span>`;
    return `<span class="chip ent">At ${esc(at)}</span>`;
  }
  function runRow(r) {
    const stage = isDone(r) ? 'metadata' : (r.current_step || 'script');
    const voice = !r.steps_done ? 'Script not started' : r.voice_source === 'uploaded' ? 'Uploaded voice' : 'Generated voice';
    return `<a class="run-item" href="#run/${encodeURIComponent(r.run_id)}/${stage}" style="text-decoration:none;color:inherit"><div class="main-col">
      <div class="t">${esc(r.name || 'Untitled video')}</div><div class="m"><span>${voice}</span><span class="sep">·</span><span>${esc(LANGS[r.language] || r.language)}</span>${r.format ? `<span class="sep">·</span><span>${esc(r.format)}</span>` : ''}</div></div>${runStatusChip(r)}</a>`;
  }
  function ideaRow(i, selectable) {
    const sel = C.selected.has(i.item_id), id = esc(i.item_id);
    const meta = [i.discovery_method !== 'manual' ? `<span class="chip">${esc(i.discovery_method)}</span>` : '', i.source ? `<span>${esc(i.source)}</span>` : '',
      i.run_count ? `<span>${i.run_count} video${i.run_count === 1 ? '' : 's'}</span>` : ''].filter(Boolean).join('<span class="sep">·</span>');
    return `<div class="run-item" style="cursor:default${sel && selectable ? ';border-color:var(--accent)' : ''}">
      ${selectable ? `<input type="checkbox" aria-label="Select idea" ${sel ? 'checked' : ''} onchange="Core.toggleIdea('${id}')" style="width:16px;height:16px">` : ''}
      <div class="main-col"><div class="t" style="white-space:normal">${esc(i.title)}</div>${i.summary ? `<div class="meta" style="margin-top:2px">${esc(i.summary)}</div>` : ''}
      ${meta ? `<div class="m">${meta}</div>` : ''}</div>
      ${selectable ? `<button class="btn sm" onclick="Core.dlgIdea('${id}')">Edit</button>` : ''}
      <button class="btn sm next" onclick="Core.startRun(['${id}'])">Start video →</button></div>`;
  }

  async function loadProject(id) {
    const r = await call(`/platform/projects/${encodeURIComponent(id)}`);
    if (r.status === 404) { A.go('#projects'); return false; }
    if (!r.ok) throw new Error(A.why(r));
    C.project = r.data;
    return true;
  }
  async function loadItems() {
    const r = await call(`/platform/projects/${encodeURIComponent(C.project.project_id)}/shortlist`);
    if (!r.ok) throw new Error(A.why(r));
    C.items = r.data;
  }
  async function loadRuns() {
    const r = await call(`/platform/projects/${encodeURIComponent(C.project.project_id)}/runs`);
    if (!r.ok) throw new Error(A.why(r));
    C.runs = r.data;
  }
  const base = () => `/platform/projects/${encodeURIComponent(C.project.project_id)}`;
  const tabHref = tab => `#project/${encodeURIComponent(C.project.project_id)}${tab === 'overview' ? '' : '/' + tab}`;

  async function viewProject(id, tab) {
    setNav('projects');
    C.tab = tab;
    if (!C.project || C.project.project_id !== id) { loading(); if (!await loadProject(id)) return; C.selected.clear(); }
    await tenantDefaults();
    await Promise.all([loadItems(), loadRuns()]);
    paintProject();
  }
  function paintProject() {
    const p = C.project, tab = C.tab;
    document.querySelectorAll('#super-menu [data-nav].on').forEach(a => a.classList.remove('on'));
    paintProjectNav(tab);
    const tabs = [['overview', 'Overview'], ['ideas', 'Ideas'], ['runs', 'Runs'], ['settings', 'Settings']]
      .map(([k, l]) => `<button class="${k === tab ? 'on' : ''}" onclick="location.hash='${tabHref(k)}'">${l}</button>`).join('');
    const body = { overview: viewOverview, ideas: viewIdeas, runs: viewRuns, settings: viewProjectSettings }[tab]();
    frame(crumbs([['Projects', '#projects'], [p.name]]),
      `<div class="page-head"><h1>${esc(p.name)}</h1><button class="btn primary" onclick="Core.startRun([])">+ New video</button></div>
       <div class="tabs core-tabs">${tabs}</div>${body}`);
  }
  function viewOverview() {
    const open = C.runs.filter(r => !isDone(r)), stat = (n, l, tab) => `<a class="core-stat" href="${tabHref(tab)}"><b>${n}</b><span>${l}</span></a>`;
    const empty = !C.runs.length && !C.items.length;
    return `<p class="meta" style="margin:14px 0 18px">${esc(C.project.niche || 'No niche set — add one in Settings')}</p>
      <div class="core-stats">${stat(C.items.length, 'Ideas', 'ideas')}${stat(C.runs.length, 'Videos', 'runs')}${stat(open.length, 'In progress', 'runs')}${stat(C.runs.length - open.length, 'Done', 'runs')}</div>
      ${empty ? `<div class="empty"><b>Start this project</b><p>Add an idea to work from, or start a video and enter the details there.</p>
        <button class="btn" onclick="Core.dlgIdea()">+ Add idea</button> <button class="btn primary" onclick="Core.startRun([])">+ New video</button></div>` : `
      <h2 class="core-h">Continue</h2>${open.length ? open.slice(0, 5).map(runRow).join('') : '<p class="meta">Nothing in progress.</p>'}
      <h2 class="core-h">Newest ideas</h2>${C.items.length ? C.items.slice(0, 3).map(i => ideaRow(i, false)).join('') : '<p class="meta">No ideas yet.</p>'}`}`;
  }
  function viewIdeas() {
    const live = [...C.selected].filter(id => C.items.some(i => i.item_id === id));
    return `<div class="core-bar"><span></span><button class="btn sm" onclick="Core.dlgIdea()">+ Add idea</button></div>
      ${C.items.length ? C.items.map(i => ideaRow(i, true)).join('')
        : '<div class="empty"><b>No ideas yet</b><p>Add one by hand. You can also start a video without an idea.</p><button class="btn primary" onclick="Core.startRun([])">New video without an idea</button></div>'}
      ${live.length > 1 ? `<div class="core-selbar"><span>${live.length} ideas selected — combined into one video</span>
        <button class="btn sm" onclick="Core.clearSel()">Clear</button><button class="btn sm accent" onclick='Core.startRun(${JSON.stringify(live)})'>Start video →</button></div>` : ''}`;
  }
  function viewRuns() {
    const f = C.runFilter;
    const list = C.runs.filter(r => !f || (f === 'done' ? isDone(r) : f === 'failed' ? r.status === 'failed' : !isDone(r) && r.status !== 'failed'));
    return `<div class="core-bar"><select class="inline" onchange="Core.setRunFilter(this.value)" aria-label="Filter videos">
      <option value="">All videos (${C.runs.length})</option>${opts({ progress: 'In progress', failed: 'Needs attention', done: 'Done' }, f)}</select></div>
      ${list.length ? list.map(runRow).join('') : `<div class="empty"><b>No videos${C.runs.length ? ' match this filter' : ' yet'}</b><p>Start one from an idea, or on its own.</p><button class="btn primary" onclick="Core.startRun([])">+ New video</button></div>`}`;
  }
  const clearSel = () => { C.selected.clear(); paintProject(); };
  const setRunFilter = v => { C.runFilter = v; paintProject(); };
  const toggleIdea = id => { C.selected.has(id) ? C.selected.delete(id) : C.selected.add(id); paintProject(); };

  // Ideas
  function dlgIdea(id) {
    const i = id ? C.items.find(x => x.item_id === id) : null;
    modal(`<h2>${i ? 'Edit idea' : 'Add idea'}</h2>
      <label class="field" style="margin-top:14px"><span class="lbl">Idea / title</span><input type="text" id="id-title" maxlength="300" value="${esc(i ? i.title : '')}" placeholder="Why starter homes disappeared from America"></label>
      <label class="field"><span class="lbl">Summary (optional)</span><textarea id="id-sum" rows="3" maxlength="2000" style="min-height:70px">${esc(i ? i.summary : '')}</textarea></label>
      <div class="row"><label class="field"><span class="lbl">Source (optional)</span><input type="text" id="id-src" maxlength="200" value="${esc(i ? i.source || '' : '')}"></label>
      <label class="field"><span class="lbl">Notes (optional)</span><input type="text" id="id-notes" maxlength="2000" value="${esc(i && i.evidence ? i.evidence.notes || '' : '')}"></label></div>
      <div class="e-foot"><button class="btn accent sm" id="id-save" onclick="Core.saveIdea('${id || ''}')">${i ? 'Save' : 'Add to ideas'}</button><button class="btn sm" onclick="Core.closeModal()">Cancel</button>
      <span style="flex:1"></span>${i ? `<button class="btn sm e-del" onclick="Core.removeIdea('${esc(id)}')">Remove</button>` : ''}</div><div class="m-msg" id="id-msg"></div>`);
  }
  async function saveIdea(id) {
    const title = qs('id-title').value.trim();
    if (!title) { qs('id-msg').textContent = 'An idea needs a title.'; return; }
    const body = { title, summary: qs('id-sum').value.trim(), source: qs('id-src').value.trim(), notes: qs('id-notes').value.trim() };
    qs('id-save').disabled = true;
    const r = id ? await call(`${base()}/shortlist/${encodeURIComponent(id)}`, 'PATCH', body)
                 : await call(`${base()}/shortlist`, 'POST', { ...body, source: body.source || null, notes: body.notes || null });
    if (!r.ok) { qs('id-save').disabled = false; qs('id-msg').textContent = A.why(r); return; }
    closeModal(); await loadItems(); paintProject();
  }
  async function removeIdea(id) {
    const item = C.items.find(i => i.item_id === id);
    if (!item) return;
    const note = item.run_count ? ' Videos already made from it are kept.' : '';
    if (!await A.confirmBox('Remove this idea?', `"${item.title}" leaves the shortlist.${note}`, 'Remove')) return;
    const r = await call(`${base()}/shortlist/${encodeURIComponent(id)}`, 'DELETE');
    if (!r.ok && r.status !== 404) { showErr(A.why(r)); return; }
    C.selected.delete(id); closeModal(); await loadItems(); paintProject();
  }

  // Start a video from this project: the New video screen, with the project and ideas filled in.
  function startRun(itemIds) {
    const picked = itemIds.map(id => C.items.find(i => i.item_id === id)).filter(Boolean);
    C.newRun = {
      projectId: C.project.project_id,
      itemIds: picked.map(i => i.item_id),
      title: picked.length ? picked.map(i => i.title).join(' + ') : '',
      brief: picked.length > 1 ? picked.map(i => i.summary).filter(Boolean).join(' ') : '',
    };
    A.go(`#new/${encodeURIComponent(C.project.project_id)}`);
  }

  // Project settings
  async function patchProject(fields, msg) {
    const r = await call(base(), 'PATCH', fields);
    if (!r.ok) { showErr(`Could not save: ${A.why(r)}`); return; }
    C.project = r.data; showErr(''); paintProject(); toast(msg || 'Saved.');
  }
  function setDefault(key, value) {
    const config = JSON.parse(JSON.stringify(C.project.config || {}));
    const rd = config.run_defaults = config.run_defaults || {};
    const reset = value === undefined || value === '';
    if (key === 'language') { if (reset) delete config.language; else config.language = value; }
    else if (key === 'format') { if (reset) delete rd.aspect_ratio; else rd.aspect_ratio = value; }
    else if (key === 'captions') {
      if (reset) { delete rd.subtitles; delete rd.caption_style; }
      else if (value === 'none') { rd.subtitles = 'none'; delete rd.caption_style; }
      else { rd.subtitles = 'TikTok'; rd.caption_style = value; }
    } else if (key === 'pace') { if (reset) delete rd.narration_pace; else rd.narration_pace = value; }
    else if (key === 'style') { if (reset) delete rd.narration_style; else rd.narration_style = value; }
    if (!Object.keys(rd).length) delete config.run_defaults;
    patchProject({ config }, 'Saved. New videos use this; existing videos keep their own settings.');
  }
  const patchConfig = (k, v, msg) => patchProject({ config: { ...(C.project.config || {}), [k]: v } }, msg);

  function inheritField(key, label, map) {
    const t = C.tenant, over = overrides(C.project)[key] !== undefined;
    const value = overrides(C.project)[key] ?? t[key];
    return `<label class="field"><span class="lbl">${label}</span><select onchange="Core.setDefault('${key}', this.value)">${opts(map, value)}</select>
      <span class="meta">${over ? `Overridden for this project · <a class="link" href="javascript:void 0" onclick="Core.setDefault('${key}')">Reset to Defaults (${esc(map[t[key]] || t[key])})</a>`
        : `Inherited from Defaults: ${esc(map[t[key]] || t[key])}`}</span></label>`;
  }
  function viewProjectSettings() {
    const p = C.project, rd = (p.config && p.config.run_defaults) || {};
    const assets = (p.config && p.config.assets) || [];
    return `<div class="core-card"><h3>Project</h3>
        <div class="row"><label class="field"><span class="lbl">Name</span><input type="text" maxlength="120" value="${esc(p.name)}" onchange="if(this.value.trim())Core.patchProject({name:this.value.trim()});else this.value='${esc(p.name)}'"></label>
        <label class="field"><span class="lbl">Niche — passed to script generation for every video</span><input type="text" maxlength="200" value="${esc(p.niche)}" placeholder="american housing economics" onchange="Core.patchProject({niche:this.value.trim()})"></label></div></div>
      <div class="core-card"><h3>Channel identity</h3>
        <textarea maxlength="2000" rows="4" style="min-height:96px" placeholder="Plain-spoken explainers on American housing for first-time buyers. Calm, numbers first, no hype."
          onchange="Core.patchConfig('channel_identity', this.value.trim(), 'Channel identity saved.')">${esc((p.config && p.config.channel_identity) || '')}</textarea></div>
      <div class="core-card"><h3>Defaults for new videos</h3>
        <div class="row">${inheritField('language', 'Language', LANGS)}${inheritField('format', 'Format', FORMATS)}${inheritField('captions', 'Captions', CAPTIONS)}
        <label class="field"><span class="lbl">Narration pace (generated voice)</span><select onchange="Core.setDefault('pace', this.value)"><option value="">Normal (built-in)</option>${opts(PACES, rd.narration_pace)}</select></label>
        <label class="field"><span class="lbl">Narration style (generated voice)</span><select onchange="Core.setDefault('style', this.value)"><option value="">Educational (built-in)</option>${opts(NARR_STYLES, rd.narration_style)}</select></label></div></div>
      <div class="core-card"><h3>Master visual prompt</h3>
        <textarea maxlength="4000" rows="8" style="min-height:160px" placeholder="Muted editorial illustration, flat colours, soft grain, no text"
          onchange="Core.patchConfig('ai_image_style', this.value.trim())">${esc((p.config && p.config.ai_image_style) || '')}</textarea></div>
      <div class="core-card"><h3>Project assets</h3>
        ${assets.length ? assets.map(a => `<div class="as-card"><div style="display:flex;gap:8px;align-items:center"><span class="n">${esc(a.name)}</span><span class="chip">${esc(ASSET_KINDS[a.kind] || a.kind)}</span><span style="flex:1"></span>
          <button class="btn sm" onclick="Core.dlgAsset('${esc(a.id)}')">Edit</button><button class="btn sm e-del" onclick="Core.deleteAsset('${esc(a.id)}')">Remove</button></div><p>${esc(a.description)}</p></div>`).join('')
          : '<p class="meta" style="margin-bottom:12px">No assets yet.</p>'}
        <button class="btn sm" onclick="Core.dlgAsset()">+ Add asset</button></div>`;
  }
  function dlgAsset(id) {
    const a = ((C.project.config && C.project.config.assets) || []).find(x => x.id === id) || {};
    modal(`<h2>${id ? 'Edit asset' : 'Add asset'}</h2>
      <div class="row" style="margin-top:14px"><label class="field"><span class="lbl">Name</span><input type="text" id="as-name" maxlength="80" value="${esc(a.name || '')}" placeholder="Maya"></label>
      <label class="field"><span class="lbl">Kind</span><select id="as-kind">${opts(ASSET_KINDS, a.kind || 'character')}</select></label></div>
      <label class="field"><span class="lbl">Description — added verbatim to every image prompt that uses it</span><textarea id="as-desc" maxlength="1200" rows="5" style="min-height:110px" placeholder="A cheerful woman in her thirties, short curly black hair, red scarf, round glasses">${esc(a.description || '')}</textarea></label>
      <div class="e-foot"><button class="btn accent sm" onclick="Core.saveAsset('${esc(id || '')}')">Save</button><button class="btn sm" onclick="Core.closeModal()">Cancel</button></div><div class="m-msg" id="as-msg"></div>`);
  }
  async function saveAsset(id) {
    const body = { name: qs('as-name').value.trim(), kind: qs('as-kind').value, description: qs('as-desc').value.trim() };
    const r = await call(id ? `${base()}/assets/${encodeURIComponent(id)}` : `${base()}/assets`, id ? 'PATCH' : 'POST', body);
    if (!r.ok) { qs('as-msg').textContent = A.why(r); return; }
    closeModal(); await loadProject(C.project.project_id); paintProject(); toast('Asset saved.');
  }
  async function deleteAsset(id) {
    if (!await A.confirmBox('Remove this asset?', 'Videos already made keep their copy.', 'Remove')) return;
    const r = await call(`${base()}/assets/${encodeURIComponent(id)}`, 'DELETE');
    if (!r.ok) { showErr(A.why(r)); return; }
    await loadProject(C.project.project_id); paintProject(); toast('Asset removed.');
  }

  // ── Libraries ─────────────────────────────────────────────────────────────

  /** The AI assets library: characters, places and objects, saved from a storyboard or added by hand. */
  function paintAssetsLibrary() {
    const items = C.libAssets || [];
    frame(crumbs([['Libraries'], [LIBS.assets]]), `<div class="page-head"><h1>${LIBS.assets}</h1>
      <button class="btn primary" style="margin-left:auto" onclick="Core.libAssetDlg()">+ Add asset</button></div>
      ${items.length ? items.map(a => `<div class="as-card"><div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><span class="n">${esc(a.name)}</span><span class="chip">${esc(ASSET_KINDS[a.kind] || a.kind)}</span><span style="flex:1"></span>
          <button class="btn sm" onclick="Core.libAssetDlg('${esc(a.id)}')">Edit</button><button class="icon-btn lib-del" onclick="Core.libAssetDelete('${esc(a.id)}')" title="Delete" aria-label="Delete">${BIN}</button></div><p>${esc(a.description)}</p></div>`).join('')
        : '<div class="empty"><b>No assets yet</b><p>Save a character from a storyboard, or add one with the button above.</p></div>'}`);
  }
  function libAssetDlg(id) {
    const a = (C.libAssets || []).find(x => x.id === id) || {};
    modal(`<h2>${id ? 'Edit asset' : 'Add asset'}</h2>
      <div class="row" style="margin-top:14px"><label class="field"><span class="lbl">Name</span><input type="text" id="as-name" maxlength="80" value="${esc(a.name || '')}" placeholder="Maya"></label>
      <label class="field"><span class="lbl">Kind</span><select id="as-kind">${opts(ASSET_KINDS, a.kind || 'character')}</select></label></div>
      <label class="field"><span class="lbl">Description</span><textarea id="as-desc" maxlength="1200" rows="5" style="min-height:110px" placeholder="A cheerful woman in her thirties, short curly black hair, red scarf, round glasses">${esc(a.description || '')}</textarea></label>
      <div class="e-foot"><button class="btn accent sm" onclick="Core.libAssetSave('${esc(id || '')}')">Save</button><button class="btn sm" onclick="Core.closeModal()">Cancel</button></div><div class="m-msg" id="as-msg"></div>`);
  }
  async function libAssetSave(id) {
    const body = { name: qs('as-name').value.trim(), kind: qs('as-kind').value, description: qs('as-desc').value.trim() };
    const r = await call(id ? `/platform/creator/assets/${encodeURIComponent(id)}` : '/platform/creator/assets', id ? 'PATCH' : 'POST', body);
    if (!r.ok) { qs('as-msg').textContent = A.why(r); return; }
    closeModal(); await viewLibrary('assets'); toast('Asset saved.');
  }
  async function libAssetDelete(id) {
    if (!await A.confirmBox('Remove this asset?', 'Videos already made keep their copy.', 'Remove')) return;
    const r = await call(`/platform/creator/assets/${encodeURIComponent(id)}`, 'DELETE');
    if (!r.ok) { showErr(A.why(r)); return; }
    await viewLibrary('assets'); toast('Asset removed.');
  }

  async function viewLibrary(kind) {
    setNav('library/' + kind);
    loading();
    if (C.lib.kind !== kind) { C.lib.filters = { q: '', project: '', facet: '' }; }
    C.lib.kind = kind;
    if (kind === 'assets') {
      const ar = await call('/platform/creator/assets');
      if (!ar.ok) throw new Error(A.why(ar));
      C.libAssets = ar.data.items;
      return paintAssetsLibrary();
    }
    const r = await call(`/platform/library/${kind}`);
    if (!r.ok) throw new Error(A.why(r));
    C.lib.data = r.data;
    paintLibrary();
  }
  function libPreview(a) {
    const u = a.download_url, kind = C.lib.kind;
    if (!u) return '<div class="core-thumb blank">no preview</div>';
    if (kind === 'videos' || (kind === 'footage' && a.facet === 'video'))
      return `<video class="core-thumb" src="${esc(u)}#t=0.5" preload="metadata" muted playsinline></video>`;
    if (kind === 'footage' || kind === 'ai' || kind === 'images') return `<img class="core-thumb" src="${esc(u)}" loading="lazy" alt="">`;
    return `<div style="padding:12px 12px 0"><audio controls preload="none" src="${esc(u)}" style="width:100%;height:34px"></audio></div>`;
  }
  function libCard(a) {
    const project = BASIC ? '' : a.project_id ? `<a class="link" href="#project/${encodeURIComponent(a.project_id)}">${esc(a.project_name)}</a>` : (C.lib.kind === 'music' ? '' : '<span class="meta">Shared — all projects</span>');
    const run = a.run_id ? `<a class="link" href="#run/${encodeURIComponent(a.run_id)}/storyboard">↳ ${esc(a.run_name)}</a>` : '';
    return `<div class="core-asset">${libPreview(a)}<div class="core-asset-body"><div class="t">${esc(a.name)}</div>${project}${run}
      <div class="meta">${esc(a.facts)}${a.created_at ? ' · ' + esc(fmtDate(a.created_at)) : ''}</div>
      <div class="core-asset-foot"><span class="meta" style="font-family:var(--mono);font-size:11px" title="Asset ID">${esc(a.asset_id)}</span>
      <span style="display:flex;gap:6px;align-items:center"><button class="btn sm" onclick="Core.download(this,'${esc(a.asset_id)}')" ${a.download_url ? '' : 'disabled'}>Download</button>
      ${libDeletable(a) ? `<button class="icon-btn lib-del" onclick="Core.libDelete('${esc(a.asset_id)}')" title="Delete" aria-label="Delete">${BIN}</button>` : ''}</span></div></div></div>`;
  }
  /** The platform's shared tracks and an image a video still uses cannot be deleted. */
  const libDeletable = a => a.facet !== 'platform' && !String(a.facts || '').endsWith('in use');
  async function libDelete(assetId) {
    const kind = C.lib.kind;
    if (!await A.confirmBox('Delete this file?', 'It is removed from your library and cannot be restored.', 'Delete')) return;
    const r = await call(`/platform/library/${kind}/${encodeURIComponent(assetId)}`, 'DELETE');
    if (!r.ok) { showErr(A.why(r)); return; }
    await viewLibrary(kind); toast('Deleted.');
  }
  /** Add a background-music track from the BG music page. */
  async function addTrack(input) {
    const file = input.files && input.files[0];
    if (!file) return;
    const form = new FormData(); form.append('file', file);
    toast(`Uploading ${file.name}…`);
    const r = await A.api('/platform/library/music', { method: 'POST', form });
    input.value = '';
    if (!r.ok) { showErr(A.why(r)); return; }
    await viewLibrary('music'); toast('Track added.');
  }
  function libVisible() {
    const f = C.lib.filters, q = f.q.toLowerCase();
    return C.lib.data.items.filter(a => (!f.project || a.project_id === f.project) && (!f.facet || a.facet === f.facet)
      && (!q || `${a.asset_id} ${a.name} ${a.facts} ${a.run_name || ''} ${a.project_name || ''}`.toLowerCase().includes(q)));
  }
  function paintLibrary(keepFocus) {
    const kind = C.lib.kind, d = C.lib.data, f = C.lib.filters, list = libVisible();
    const facets = kind === 'images' ? ['Stock', 'AI generated'] : [...new Set(d.items.map(a => a.facet).filter(Boolean))];
    frame(crumbs([['Libraries'], [LIBS[kind]]]), `<div class="page-head"><h1>${LIBS[kind]}</h1>
      ${kind === 'music' ? `<button class="btn primary" style="margin-left:auto" onclick="document.getElementById('lib-track').click()">+ Add track</button>
      <input type="file" id="lib-track" class="hidden" accept="audio/mpeg,audio/wav,audio/mp4,audio/x-m4a,.mp3,.wav,.m4a" onchange="Core.addTrack(this)">` : ''}
</div>
      <div class="lib-bar">
        <div class="lib-search" id="lib-search">
          <input type="text" id="lib-q" placeholder="Search by name, ID, video or project" value="${esc(f.q)}" oninput="Core.libFilter('q',this.value,true)" aria-label="Search"></div>
        <div class="lib-filters">
      ${kind !== 'music' && !BASIC ? `<select class="inline" onchange="Core.libFilter('project',this.value)" aria-label="Project"><option value="">All projects</option>${d.projects.map(p => `<option value="${esc(p.project_id)}"${f.project === p.project_id ? ' selected' : ''}>${esc(p.name)}</option>`).join('')}</select>` : ''}
      ${kind !== 'music' && (facets.length > 1 || kind === 'images') ? `<select class="inline" onchange="Core.libFilter('facet',this.value)" aria-label="Type"><option value="">All types</option>${facets.map(x => `<option${f.facet === x ? ' selected' : ''}>${esc(x)}</option>`).join('')}</select>` : ''}</div></div>
      <p class="meta" style="margin-bottom:10px">${list.length} of ${d.items.length}</p>
      ${list.length ? `<div class="core-assets">${list.map(libCard).join('')}</div>`
        : `<div class="empty"><b>${d.items.length ? 'Nothing matches' : 'Nothing here yet'}</b><p>${d.items.length ? 'Change the search or the filters.' : (kind === 'music' ? 'Add a track with the button above.' : 'Assets appear here as videos produce them.')}</p></div>`}`);
    if (keepFocus) { const q = qs('lib-q'); if (q) { q.focus(); q.setSelectionRange(q.value.length, q.value.length); } }
  }
  function libFilter(key, value, keepFocus) { C.lib.filters[key] = value; paintLibrary(keepFocus); }
  /** Download through a blob: the `download` attribute is ignored for a cross-origin presigned URL. */
  async function download(btn, id) {
    const a = C.lib.data.items.find(x => x.asset_id === id);
    if (!a || !a.download_url) return;
    const label = btn.textContent;
    btn.disabled = true; btn.textContent = 'Downloading…';
    try {
      const resp = await fetch(a.download_url);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const url = URL.createObjectURL(await resp.blob());
      const link = document.createElement('a');
      link.href = url; link.download = a.name.includes('.') ? a.name : `${a.name}.${String(a.key || '').split('.').pop()}`;
      document.body.appendChild(link); link.click(); link.remove();
      URL.revokeObjectURL(url);
    } catch (e) { toast('Download failed: ' + e.message); }
    finally { btn.disabled = false; btn.textContent = label; }
  }

  // ── Settings: Integrations and Defaults ───────────────────────────────────

  const WIRED = { full: '', partial: 'Partly wired', planned: 'Planned' };
  async function viewSettings(tab) {
    setNav('settings/' + tab);
    loading();
    C.settings.keyEdit = '';
    if (tab === 'defaults') {
      const [d, p] = await Promise.all([call('/platform/tenant/defaults'), call('/platform/projects')]);
      if (!d.ok) throw new Error(A.why(d));
      C.settings.defaults = d.data; C.projects = p.ok ? p.data : [];
    } else {
      await loadIntegrations();
    }
    C.settings.tab = tab;
    paintSettings();
  }
  async function loadIntegrations() {
    const [b, m] = await Promise.all([call('/platform/tenant/blocks'), call('/platform/tenant/settings/image')]);
    if (!b.ok) throw new Error(A.why(b));
    C.settings.blocks = b.data; C.settings.image = m.ok ? m.data : null;
  }
  function keyState(p) {
    if (p.key_source === 'tenant') return `Saved key ending ${esc(p.key_hint || '••••')}`;
    if (p.key_source === 'env') return 'Using the Railway variable';
    return 'No key yet';
  }
  function imageSuggestions(block, p) {
    const image = C.settings.image;
    if (block.block_id === 'image' && image) {
      const provider = p.provider_id === 'kie' ? 'kie' : 'openai';
      return [...new Set([image.default_models[provider], ...((image.known_models || {})[provider] || [])])].filter(Boolean);
    }
    return p.models;
  }
  function imageCostHint(p) {
    const image = C.settings.image, costs = (image && image.model_costs_usd) || {}, model = p.model || '';
    const known = Object.prototype.hasOwnProperty.call(costs, model);
    const cost = known ? costs[model] : image && image.default_cost_usd;
    return cost == null ? '' : `About $${Number(cost).toFixed(3)} per image${known ? '' : ' (the general estimate)'}.`;
  }
  function providerRow(block, p) {
    const editing = C.settings.keyEdit === p.provider_id, listId = `models-${p.provider_id}`;
    const peers = block.providers.filter(q => (q.role || '') === (p.role || '') && q.can_be_default).length;
    const hint = block.block_id === 'image' && p.is_default && C.settings.image ? imageCostHint(p) : '';
    return `<div class="core-integ"><div class="core-integ-main">
        <div><b>${esc(p.name)}</b>${p.is_default && peers > 1 ? ' <span class="chip ent">Default</span>' : ''}${WIRED[p.wired] ? ` <span class="chip">${WIRED[p.wired]}</span>` : ''}
          ${p.note ? `<div class="meta">${esc(p.note)}</div>` : ''}</div>
        <div class="meta">${p.can_be_default || p.can_save_key ? keyState(p) : ''}</div>
        <div style="display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end">
          ${p.can_save_key ? `<button class="btn sm" onclick="Core.toggleKeyEdit('${esc(p.provider_id)}')">${p.key_source === 'tenant' ? 'Replace key' : 'Add key'}</button>` : '<span class="meta">Railway variable only</span>'}
          ${peers > 1 && p.can_be_default && !p.is_default ? `<button class="btn sm" onclick="Core.makeDefault('${esc(block.block_id)}','${esc(p.provider_id)}')">Make default</button>` : ''}</div></div>
      ${p.models.length || block.block_id === 'image' ? `<div class="core-integ-row"><span class="lbl" style="margin:0">Model</span>
        <input type="text" maxlength="120" autocomplete="off" spellcheck="false" value="${esc(p.model)}" list="${esc(listId)}" onchange="Core.saveModel('${esc(block.block_id)}','${esc(p.provider_id)}', this.value)">
        <datalist id="${esc(listId)}">${imageSuggestions(block, p).map(m => `<option value="${esc(m)}"></option>`).join('')}</datalist>
        ${hint ? `<span class="meta">${esc(hint)}</span>` : ''}</div>` : ''}
      ${editing ? `<div class="core-integ-row"><input type="password" id="key-input" autocomplete="new-password" spellcheck="false" placeholder="Paste a key — it is stored encrypted and never shown again" aria-label="API key" style="font-family:var(--mono)">
        <button class="btn sm accent" onclick="Core.saveKey('${esc(p.service_id)}')">Save</button>
        ${p.key_source === 'tenant' ? `<button class="btn sm" onclick="Core.removeKey('${esc(p.service_id)}')">Remove saved key</button>` : ''}</div>` : ''}</div>`;
  }
  function blockCard(block) {
    const roleNote = block.roles.length > 1 ? `<p class="meta">Its providers do different jobs (${block.roles.join(' and ')}), so each is the default for its own job.</p>` : '';
    return `<div class="core-card"><h3>${esc(block.name)}</h3><p class="meta">${esc(block.description)}</p>${roleNote}${block.providers.map(p => providerRow(block, p)).join('')}</div>`;
  }
  const overriding = key => C.projects.filter(p => overrides(p)[key] !== undefined).length;
  function defaultField(key, label, map) {
    const n = overriding(key), d = C.settings.defaults;
    return `<label class="field"><span class="lbl">${label}</span><select onchange="Core.saveDefault('${key}', this.value)">${opts(map, d[key])}</select>
      <span class="meta">${n ? `${n} of ${C.projects.length} projects override this` : 'Used by every project'}</span></label>`;
  }
  function paintSettings() {
    const tab = C.settings.tab;
    if (tab === 'defaults') {
      const d = C.settings.defaults;
      frame(crumbs([['Settings'], ['Defaults']]), `<div class="page-head"><h1>Defaults</h1></div>
        <div class="core-card"><h3>New projects and videos</h3>
          <div class="row">${defaultField('language', 'Language', LANGS)}${defaultField('format', 'Format', FORMATS)}${defaultField('captions', 'Captions', CAPTIONS)}</div></div>
        <div class="core-card"><h3>Spend</h3>
          <label class="field" style="max-width:280px"><span class="lbl">AI image cap per video (USD)</span><input type="text" inputmode="decimal" value="${esc(d.spend_cap)}" onchange="Core.saveDefault('spend_cap', this.value)"></label></div>`);
      return;
    }
    const b = C.settings.blocks;
    frame(crumbs([['Settings'], ['Integrations']]), `<div class="page-head"><h1>Integrations</h1></div>
      ${b.can_save_keys ? ''
        : '<div class="job on err">Keys cannot be saved yet: SETTINGS_ENCRYPTION_KEY is not set on Railway. Railway key variables still work.</div>'}
      ${b.blocks.map(blockCard).join('')}`);
  }
  const toggleKeyEdit = id => { C.settings.keyEdit = C.settings.keyEdit === id ? '' : id; paintSettings(); };
  async function putService(serviceId, body, msg) {
    const r = await call(`/platform/tenant/integrations/${encodeURIComponent(serviceId)}`, 'PUT', body);
    if (!r.ok) { showErr(`Could not save: ${A.why(r)}`); return; }
    C.settings.keyEdit = ''; showErr('');
    await loadIntegrations(); paintSettings(); toast(msg);
  }
  async function saveKey(serviceId) {
    const key = qs('key-input').value.trim();
    if (!key) { toast('Paste a key first.'); return; }
    await putService(serviceId, { api_key: key }, 'Key saved.');
  }
  async function removeKey(serviceId) {
    if (!await A.confirmBox('Remove the saved key?', 'The Railway variable is used again, if there is one.', 'Remove')) return;
    await putService(serviceId, { clear_key: true }, 'Saved key removed.');
  }
  async function putBlock(blockId, body, msg) {
    const r = await call(`/platform/tenant/blocks/${encodeURIComponent(blockId)}`, 'PUT', body);
    if (!r.ok) { showErr(`Could not save: ${A.why(r)}`); paintSettings(); return; }
    C.settings.blocks = r.data; showErr('');
    if (blockId === 'image') { const m = await call('/platform/tenant/settings/image'); if (m.ok) C.settings.image = m.data; }
    paintSettings(); toast(msg);
  }
  const makeDefault = (blockId, providerId) => putBlock(blockId, { default: providerId }, 'Default changed.');
  const saveModel = (blockId, providerId, model) => putBlock(blockId, { model: { provider: providerId, model: model.trim() } }, 'Model saved.');
  async function saveDefault(key, value) {
    const r = await call('/platform/tenant/defaults', 'PUT', { [key]: value });
    if (!r.ok) { showErr(`Could not save: ${A.why(r)}`); paintSettings(); return; }
    C.settings.defaults = r.data; C.tenant = r.data; showErr(''); paintSettings(); toast('Saved. Projects that have not overridden it now use this.');
  }

  // ── Host hooks ────────────────────────────────────────────────────────────

  const injectedStyles = `
  #core-toast{position:fixed;left:50%;bottom:28px;transform:translateX(-50%) translateY(20px);background:var(--text);color:var(--bg);font-size:13px;padding:9px 16px;border-radius:999px;opacity:0;pointer-events:none;transition:all .2s;z-index:80}
  #core-toast.on{opacity:1;transform:translateX(-50%) translateY(0)}
  .core-tabs{margin:0 0 22px;padding:0}
  .core-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:26px}
  .core-stat{display:block;border:1px solid var(--border);border-radius:var(--r);padding:14px 16px;text-decoration:none;color:inherit}
  .core-stat:hover{border-color:var(--faint)}
  .core-stat b{display:block;font-size:22px;letter-spacing:-.01em}.core-stat span{font-size:12px;color:var(--muted)}
  .core-h{font-size:14px;font-weight:700;margin:24px 0 10px}
  .core-bar{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:14px}
  .core-bar .meta{margin:0}
  .core-selbar{position:sticky;bottom:16px;display:flex;align-items:center;gap:10px;background:var(--text);color:var(--bg);border-radius:var(--r);padding:10px 14px;margin-top:16px;font-size:13px}
  .core-selbar span{flex:1}
  .core-card{border:1px solid var(--border);border-radius:var(--r);padding:18px 20px;margin-bottom:16px}
  .core-card h3{font-size:14px;margin-bottom:4px}
  .core-card>.meta{margin-bottom:14px}
  .core-assets{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}
  .core-asset{border:1px solid var(--border);border-radius:var(--r);overflow:hidden;background:var(--bg)}
  .core-thumb{width:100%;height:130px;object-fit:cover;background:var(--bg-soft);display:block}
  .core-thumb.blank{display:grid;place-items:center;color:var(--faint);font-size:12px}
  .core-asset-body{padding:10px 12px 12px;display:flex;flex-direction:column;gap:3px}
  .core-asset-body .t{font-weight:600;font-size:13px;word-break:break-word}
  .core-asset-foot{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-top:6px}
  .core-integ{border-top:1px solid var(--border);padding:12px 0}
  .core-integ-main{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(0,1fr) auto;gap:12px;align-items:center}
  .core-integ-row{display:flex;gap:8px;align-items:center;margin-top:10px}
  .core-integ-row input{flex:1}
  .core-tabs button.on{color:var(--accent);border-color:var(--accent)}
  .core-src{display:flex;gap:6px;margin-bottom:16px;flex-wrap:wrap}
  .core-tr-words{line-height:2;font-size:14px;border:1px solid var(--border);border-radius:var(--r);padding:12px 14px;max-height:280px;overflow:auto}
  .core-tr-word{cursor:pointer;border-radius:3px;padding:1px 2px}
  .core-tr-word:hover{background:var(--accent-soft)}
  .core-tr-word.sel{background:var(--accent);color:#fff}
  .core-tr-word.playing{background:var(--accent-soft);color:var(--accent);font-weight:600}
  .core-meta-out textarea{min-height:90px}
  .core-auto.on{background:var(--accent-soft);color:var(--accent);border-color:var(--accent)}
  .core-bar,.m-line,.e-foot,.core-asset-foot,.core-selbar{flex-wrap:wrap}
  .lib-del{color:var(--faint)}
  .lib-del:hover{color:var(--red);background:#FEF1F0}
  .lib-bar{display:flex;align-items:center;gap:10px;margin-bottom:12px}
  .lib-search{flex:1;min-width:0;max-width:420px}
  .lib-search input{width:100%}
  .lib-filters{margin-left:auto;display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}
  @media (max-width:720px){.core-stats{grid-template-columns:repeat(2,1fr)}.core-integ-main{grid-template-columns:1fr}}`;

  function init(app, basic) {
    A = app;
    BASIC = !!basic;
    A.addHelp(HELP);
    const style = document.createElement('style');
    style.textContent = injectedStyles;
    document.head.appendChild(style);
    if (!qs('s-x')) {
      const sec = document.createElement('section');
      sec.className = 'screen';
      sec.id = 's-x';
      document.querySelector('main.main').appendChild(sec);
    }
    // core-run.js adds the run-flow controls (Basic: script generation and narration only); it reads this module's helpers through Core.
    const el = document.createElement('script');
    el.src = '/ui/core-run.js';
    el.onload = () => { if (window.CoreRun) window.CoreRun.init(A, window.Core, BASIC); };
    document.head.appendChild(el);
  }

  window.Core = {
    init, handles, route, clearNav,
    // run-flow hooks (core-run.js fills these in when it loads)
    afterPaint() { if (window.CoreRun) window.CoreRun.afterPaint(); },
    afterStoryboard() { if (window.CoreRun) window.CoreRun.afterStoryboard(); },
    afterSettings() { if (window.CoreRun) window.CoreRun.afterSettings(); },
    async onRunOpened() { if (window.CoreRun) await window.CoreRun.onRunOpened(); },
    onNew(projectId) { if (window.CoreRun) window.CoreRun.onNew(projectId); },
    // shared helpers for core-run.js
    helpers: { esc, opts, toast, modal, closeModal, call, qs, LANGS, FORMATS, CAPTIONS, PACES, NARR_STYLES, STEP_LABELS, tenantDefaults, getNewRun: () => C.newRun, setNewRun: v => { C.newRun = v; } },
    // actions called from markup
    closeModal, dlgNewProject, createProject, dlgIdea, saveIdea, removeIdea, startRun, toggleIdea, clearSel, setRunFilter,
    patchProject, patchConfig, setDefault, dlgAsset, saveAsset, deleteAsset,
    libAssetDlg, libAssetSave, libAssetDelete, libDelete, addTrack, libFilter, download, toggleKeyEdit, saveKey, removeKey, makeDefault, saveModel, saveDefault,
  };
})();
