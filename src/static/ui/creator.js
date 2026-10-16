/* Creator pages (P-LITE, D114, D117) — the simplified flow beside the Studio.
 *
 * One page, three screens: Runs (#runs), New video (#new) and one video
 * (#run/<id>/<step>) with four steps: Script, Voice, Storyboard, Render.
 * Everything a run does after it exists goes through the Studio's routes; only
 * the list's project and the New video form have routes of their own
 * (/platform/creator/*). Layout follows docs/mockups/studio-beta-ui.html.
 */
(function () {
  'use strict';

  // The Metadata step is added for a Super session by core.js (P-CORE S9).
  const STEPS = ['script', 'voice', 'storyboard', 'render'];
  const STEP_NAMES = ['Script', 'Voice', 'Storyboard', 'Render'];
  const LANGS = { en: 'English', ru: 'Русский' };
  const KINDS = { character: 'Character', prop: 'Prop', setting: 'Setting' };
  const MOTIONS = [['ken_burns', 'Ken Burns'], ['zoom_in', 'Zoom in'], ['zoom_out', 'Zoom out'],
    ['pan_right', 'Pan right'], ['pan_left', 'Pan left'], ['static', 'Static']];
  const FLAGS = {
    too_long: ['Over 5 s', 'Longer than an animated scene should be. Split it on a word.'],
    needs_prompt: ['Needs a prompt', 'This scene has no image prompt yet.'],
    image_out_of_date: ['Image out of date', 'Its prompt, or a character it uses, changed after this image was made.'],
  };
  const HELP = {
    runs: ['Runs', ['Every video you have started. Open one to continue it, or start a new one.']],
    new: ['New video', ['Say what the video is about and choose its format and language.',
      'The master visual style is the look every image shares. You can change it until the storyboard is created.',
      'List the characters if you want specific people. Only the people you list appear in the video; with none, the characters are invented from the script.',
      'Describe each character in detail: what you write is used for every image they appear in.']],
    script: ['Script', ['Paste the text the narrator will read.', 'The word limit keeps the video to a few minutes.',
      'Once the voiceover exists the script is locked: a different script is a different video. Use "Start a new video from this one" in the video settings to change the words.']],
    voice: ['Voice', ['Choose the voice, its pace and its style, then generate the voiceover. Listen before you go on.',
      'Pace and style are sent to the voice model as an instruction in front of your script.',
      'Pace: Slow is about 145 words per minute, Normal about 160, Fast about 172.',
      'Generating again replaces the voiceover. A storyboard made for the old one has to be created again.']],
    storyboard: ['Storyboard', ['Create the storyboard, check each scene, then create the images.',
      'Click a scene to change its image prompt, motion or on-screen text. Click the pencil to change its image.',
      'Click a word to split the scene there. "Merge with next" joins two scenes. A new scene has no image prompt: open it and click "Write with the director".',
      'Creating images costs money. You see the estimate before anything is made.']],
    render: ['Render', ['Choose captions and background music, then render the video.', 'When it is done you can play it here and download it.']],
    metadata: ['Metadata', ['A title, description and tags for the channel, written from the script. Edit them here and copy them out.']],
  };
  const IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp'];

  const S = {
    cfg: null, runs: [], view: 'runs', leftOpen: true, right: null,
    run: null, settings: {}, step: 0,
    voice: null, sb: null, manifest: {}, video: null, imageJob: null, sbStale: false,
    openScene: null, modalScene: null, entryId: null, split: null, busy: {},
    audio: null, musicKey: null, spend: null, billing: null,
  };

  const $ = sel => document.querySelector(sel);
  const $$ = sel => [...document.querySelectorAll(sel)];
  const esc = v => String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const sleep = ms => new Promise(res => setTimeout(res, ms));
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many || one + 's'}`;
  const money = v => `$${Number(v || 0).toFixed(2)}`;
  const ARROW = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>';

  /** mm:ss.s for a number of seconds. */
  function clock(seconds) {
    const m = Math.floor(seconds / 60), s = (seconds % 60).toFixed(1);
    return `${m}:${s < 10 ? '0' : ''}${s}`;
  }

  /** One API call. Returns {ok, status, data}; a 401 sends the browser to the login page. */
  async function api(path, opts) {
    const o = opts || {};
    const init = { method: o.method || 'GET' };
    if (o.form) init.body = o.form;
    else if (o.body !== undefined) { init.headers = { 'Content-Type': 'application/json' }; init.body = JSON.stringify(o.body); }
    let r;
    try { r = await fetch(path, init); } catch (e) { return { ok: false, status: 0, data: { detail: `Network error: ${e.message}` } }; }
    if (r.status === 401) { location.href = '/login'; return { ok: false, status: 401, data: {} }; }
    const data = await r.json().catch(() => ({}));
    return { ok: r.ok, status: r.status, data };
  }
  /** The readable reason of a failed call. */
  const why = res => (typeof res.data.detail === 'string' && res.data.detail) || `Error ${res.status}`;

  // ── Credits (P-BILL-1): the balance, the price of a step and what was charged. Hidden while billing is off. ──

  /** " · 10 credits" for a flat-priced step while billing is on, else nothing. The server decides what is charged. */
  function priceTag(key) {
    const n = S.billing && S.billing.enabled && S.billing.prices ? S.billing.prices[key] : 0;
    return n > 0 ? ` · ${n} credits` : '';
  }
  /** Read the balance and prices; show the Credits entry only when charging is on. Never blocks the page. */
  async function loadBilling() {
    const r = await api('/platform/billing/me');
    S.billing = r.ok ? r.data : null;
    const on = !!(S.billing && S.billing.enabled);
    $('#nav-credits').classList.toggle('hidden', !on);
    $('#credits-balance').textContent = on ? `${S.billing.balance}` : '';
    if (S.run) { try { paintVoice(); paintStoryboard(); paintRender(); } catch (e) { /* the page repaints itself on its next step */ } }
  }
  const CHARGE_STATE = { held: 'In progress', settled: 'Charged', refunded: 'Refunded' };
  /** The Credits screen: balance, what the steps cost, and the newest priced actions. */
  async function showCredits() {
    err('#credits-err', '');
    await loadBilling();
    const b = S.billing, body = $('#credits-body');
    if (!b || !b.enabled) {
      body.innerHTML = '<div class="empty"><b>Credits are not switched on</b><p>Making videos is not charged yet.</p></div>';
      return;
    }
    const prices = [['Voiceover', 'voice'], ['Storyboard', 'storyboard'], ['Image prompt', 'scene_prompt'], ['Render', 'render']]
      .filter(([, k]) => b.prices[k] > 0).map(([label, k]) => `${label} ${b.prices[k]}`).join(' · ');
    const rows = b.history.map(h => {
      const charge = h.status === 'settled' ? `${h.credits} credits` : h.status === 'held' ? `${h.credits} credits held` : '—';
      return `<div class="run-item"><div class="main-col"><div class="t">${esc(h.what || h.kind)}</div>
        <div class="m"><span>${esc(new Date(h.when).toLocaleString())}</span><span class="sep">·</span><span>${esc(CHARGE_STATE[h.status] || h.status)}</span></div></div>
        <span class="meta">${esc(charge)}</span></div>`;
    }).join('');
    body.innerHTML = `<div class="plan-grid"><div><b>${b.balance}</b><span>credits left</span></div></div>
      ${prices ? `<p style="margin:14px 0 26px;color:var(--muted);font-size:13px">What a step costs, in credits: ${esc(prices)}. Images are priced when you create them, before you confirm. A step that fails is not charged.</p>` : ''}
      <h2 style="font-size:15px;margin:0 0 10px">History</h2>
      <div class="run-list">${rows || '<div class="empty"><b>Nothing yet</b><p>Steps you run will be listed here.</p></div>'}</div>`;
  }

  const runUrl = tail => `/platform/studio/runs/${encodeURIComponent(S.run.id)}${tail}`;

  // ── Errors, progress and failure lines ────────────────────────────────────

  /** Show or clear the error line of a screen or step. */
  function err(id, msg) { const el = $(id); if (!el) return; el.textContent = msg || ''; el.classList.toggle('on', !!msg); }

  /** A running line under the buttons: a spinner, the text and the elapsed time. Returns a stop function. */
  function progress(boxId, text) {
    const box = $(boxId), t0 = Date.now();
    box.className = 'job on';
    box.innerHTML = '<span class="spin"></span><span></span>';
    const paint = () => { const s = Math.round((Date.now() - t0) / 1000); box.lastChild.textContent = `${typeof text === 'function' ? text() : text} ${s}s`; };
    paint();
    const timer = setInterval(paint, 1000);
    return () => { clearInterval(timer); box.className = 'job'; box.innerHTML = ''; };
  }

  /** A visible failure: what failed, why, and a Retry button. */
  function failure(boxId, title, msg, retry) {
    const box = $(boxId);
    box.className = 'job on err';
    box.innerHTML = `<span><b>${esc(title)}</b> ${esc(msg)}</span>${retry ? '<button class="btn sm">Retry</button>' : ''}`;
    if (retry) box.querySelector('button').onclick = retry;
  }
  function clearJob(boxId) { const box = $(boxId); box.className = 'job'; box.innerHTML = ''; }

  /** Poll a status route until it says complete or error. Resolves to the last answer. */
  async function poll(path, intervalMs, maxPolls) {
    let missing = 0;
    for (let i = 0; i < maxPolls; i++) {
      await sleep(intervalMs);
      const res = await api(path);
      const st = res.ok ? res.data : { status: 'running' };
      if (st.status === 'complete' || st.status === 'error') { loadBilling(); return st; }
      // "none": the server has no job for this run. Right after a start that is a short
      // write delay; for long it means the job never began.
      if (st.status === 'none' && ++missing >= 5) return { status: 'error', error: 'The job did not start on the server.' };
    }
    return { status: 'error', error: 'This is taking longer than expected. Reload the page to check again.' };
  }

  // ── Navigation ────────────────────────────────────────────────────────────

  /** Read the address and show the screen it names. */
  async function route() {
    const [name, id, step, more] = location.hash.replace(/^#/, '').split('/');
    if (window.Core && window.Core.handles(name)) {
      stopAudio();
      show('x');
      await window.Core.route(name, id, step, more);
    } else if (name === 'run' && id) {
      if (!S.run || S.run.id !== id) await openRun(id);
      if (!S.run) return;
      const i = STEPS.indexOf(step);
      S.step = i >= 0 ? i : firstOpenStep();
      show('run');
      paintRun();
    } else if (name === 'credits') {
      stopAudio();
      show('credits');
      await showCredits();
    } else if (name === 'new') {
      stopAudio();
      show('new');
      resetNewForm();
      if (window.Core) window.Core.onNew(id);
    } else {
      stopAudio();
      // Everything starts at the Runs page, for Basic and Super alike.
      show('runs');
      await loadRuns();
    }
  }
  function go(hash) { if (location.hash === hash) route(); else location.hash = hash; }

  function show(view) {
    S.view = view;
    $$('.screen').forEach(el => el.classList.toggle('on', el.id === 's-' + view));
    $$('.run-only').forEach(b => b.classList.toggle('hidden', view !== 'run'));
    if (view !== 'run' && S.right !== 'help') S.right = null;
    $('#nav-runs').classList.toggle('on', view === 'runs' || view === 'run');
    $('#nav-credits').classList.toggle('on', view === 'credits');
    if (view !== 'x' && window.Core) window.Core.clearNav();
    paintRight();
    window.scrollTo(0, 0);
  }

  function toggleLeft(open) {
    S.leftOpen = open;
    document.body.classList.toggle('l-open', open);
    $('#left').classList.toggle('closed', !open);
    $('#left-open').classList.toggle('hidden', open);
  }
  const isNarrow = () => window.matchMedia('(max-width:820px)').matches;
  /** Close whichever panels are open (the scrim and the Escape key use this). */
  function closePanels() { toggleLeft(false); if (S.right) { S.right = null; paintRight(); } }
  /** Narrow screens: the panel is a sheet over the page, so it starts closed and closes after a choice. */
  function initPanels() {
    if (isNarrow()) toggleLeft(false);
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && isNarrow()) closePanels(); });
    window.addEventListener('hashchange', () => { if (isNarrow()) toggleLeft(false); });
    let last = window.scrollY;
    window.addEventListener('scroll', () => {
      const bar = $('#fabbar'), y = window.scrollY;
      if (!isNarrow()) { bar.classList.remove('pinned'); last = y; return; }
      if (y <= 8) bar.classList.remove('pinned');
      else if (y < last - 6) bar.classList.add('pinned');
      else if (y > last + 6) bar.classList.remove('pinned');
      last = y;
    }, { passive: true });
  }
  /** Copy this video's title, look, cast and script into a fresh video, so the words can change. */
  async function startFromThis() {
    if (!S.run) return;
    const st = S.settings || {};
    const body = {
      title: S.run.name, aspect_ratio: S.run.format || '9:16', language: S.run.language || 'en',
      master_style: st.master_style || '', characters: st.characters || [], look: st.look === 'realistic' ? 'realistic' : 'animated',
    };
    const text = $('#script').value;
    const res = await api('/platform/creator/runs', { method: 'POST', body });
    if (!res.ok) { err('#err-script', `Not started: ${why(res)}`); return; }
    try { localStorage.setItem(`cf_creator_script_${res.data.run_id}`, text); } catch { /* private mode */ }
    S.right = null; paintRight();
    go(`#run/${encodeURIComponent(res.data.run_id)}/script`);
  }
  /** Delete the open video, after asking. It leaves the Runs list and the libraries. */
  async function deleteRun() {
    if (!S.run) return;
    if (!await confirmBox('Delete this video?', 'It disappears from your Runs and libraries. This cannot be undone.', 'Delete')) return;
    const res = await api(`/platform/creator/runs/${encodeURIComponent(S.run.id)}`, { method: 'DELETE' });
    if (!res.ok) { err('#err-script', `Not deleted: ${why(res)}`); return; }
    S.right = null; paintRight();
    go('#runs');
  }
  async function logOut() { await fetch('/auth/logout', { method: 'POST' }); location.href = '/login'; }

  // ── Account: who is signed in, Super's menu, View as Basic (P-AUTH S7, D118) ──

  /** Paint the account area from /auth/me. The server enforces; this only shows what it allows. */
  async function paintAccount() {
    const r = await api('/auth/me');
    if (!r.ok) return;
    const me = r.data;
    S.me = me;
    loadBilling();
    if (me.email) { $('#who').textContent = me.email; $('#who').classList.remove('hidden'); }
    const isSuper = me.account_type === 'super';
    await mountSuperMenu(me.effective_type !== 'super', !!me.is_owner);
    await loadCore(me.effective_type !== 'super');
    $('#view-as').classList.toggle('hidden', !isSuper);
    $('#view-as-label').textContent = me.view_as_basic ? 'View as Super' : 'View as Basic';
    // A Super account sees which view it is in, as a small mark above its email (no bar over the page).
    const chip = $('#view-chip');
    chip.classList.toggle('hidden', !isSuper);
    chip.textContent = me.view_as_basic ? 'Basic view' : 'Super view';
    chip.classList.toggle('basic', !!me.view_as_basic);
    if (me.abuse_contact) { const a = $('#report-abuse'); a.href = 'mailto:' + me.abuse_contact + '?subject=Content%20Factory%20problem'; a.classList.remove('hidden'); }
  }
  /** Load Super's menu script once and mount it; a Basic session never fetches it. */
  async function mountSuperMenu(basic, owner) {
    if (!window.SuperMenu) {
      await new Promise(resolve => {
        const el = document.createElement('script');
        el.src = '/ui/super-menu.js';
        el.onload = el.onerror = resolve;
        document.head.appendChild(el);
      });
    }
    if (window.SuperMenu) window.SuperMenu.mount($('#super-menu'), !!basic, !!owner);
  }
  /** Load the screens (P-CORE) once: the Libraries for Basic, everything for Super. Run controls are Super's. */
  async function loadCore(basic) {
    if (window.Core) return;
    await new Promise(resolve => {
      const el = document.createElement('script');
      el.src = '/ui/core.js';
      el.onload = el.onerror = resolve;
      document.head.appendChild(el);
    });
    if (window.Core) window.Core.init(window.CFApp, !!basic);
  }
  /** Flip this session between its own account type and Basic, then reload so every call is re-checked. */
  async function toggleViewAs() {
    const res = await api('/auth/view-as', { method: 'POST', body: { basic: !(S.me && S.me.view_as_basic) } });
    if (!res.ok) { err('#runs-err', why(res)); return; }
    location.reload();
  }

  // ── Right panel ───────────────────────────────────────────────────────────

  /** Core's screens register their Information entries and pick one per route. */
  function addHelp(map) { Object.assign(HELP, map); }
  function setHelp(key) { S.helpKey = key; if (S.right === 'help') paintHelp(); }
  function openRight(mode) { S.right = S.right === mode ? null : mode; paintRight(); }
  function paintRight() {
    $('#right').classList.toggle('closed', !S.right);
    document.body.classList.toggle('r-open', !!S.right);
    $$('#right-open [data-r]').forEach(b => b.classList.toggle('active', b.dataset.r === S.right));
    if (!S.right) return;
    $('#right-title').textContent = { settings: 'Video settings', details: 'Video details', help: 'Information' }[S.right];
    $$('.tab').forEach(el => el.classList.toggle('on', el.id === 'tab-' + S.right));
    if (S.right === 'help') paintHelp();
    if (S.right === 'details') paintDetails();
    if (S.right === 'settings') { paintSettings(); if (window.Core) window.Core.afterSettings(); }
  }
  function paintHelp() {
    const key = S.view === 'run' ? STEPS[S.step] : S.view === 'x' ? S.helpKey : S.view;
    const [title, lines] = HELP[key] || HELP.runs;
    $('#help-title').textContent = title;
    $('#help-list').innerHTML = lines.map(l => `<li>${esc(l)}</li>`).join('');
  }
  function paintSettings() {
    if (!S.run) return;
    $$('#set-format-seg button').forEach(b => b.classList.toggle('on', b.dataset.v === (S.run.format || '9:16')));
    $('#set-lang').textContent = LANGS[S.run.language] || S.run.language || 'English';
    const locked = sbScenes().some(hasAsset);
    const style = $('#set-style');
    if (document.activeElement !== style) style.value = S.settings.master_style || '';
    style.disabled = locked;
    $('#set-style-hint').textContent = locked ? 'Fixed once the first image is made.' : 'Used for every image. Change it until the first image is made.';
    const chars = S.settings.characters || [];
    $('#set-chars').innerHTML = chars.length
      ? chars.map(c => `<div class="as-card" style="padding:8px 12px"><span class="n">${esc(c.name)}</span><p>${esc(c.description)}</p></div>`).join('')
      : '<div class="h">None listed. The characters are invented from the script.</div>';
  }
  async function paintDetails() {
    if (!S.run) return;
    const scenes = sbScenes();
    const rows = [
      ['Status', S.video ? 'Rendered' : STEP_NAMES[firstOpenStep()]],
      ['Created', S.run.created ? new Date(S.run.created).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : '—'],
      ['Length', S.voice && S.voice.total_duration_s ? clock(S.voice.total_duration_s) : '—'],
      ['Scenes', scenes.length || '—'],
      ['Images cost', S.spend ? `${money(S.spend.spent_usd)} of ${money(S.spend.cap_usd)}` : '—'],
      ['Video ID', S.run.id.slice(0, 8)],
    ];
    $('#tab-details').innerHTML = rows.map(([k, v]) => `<div class="kv"><span>${k}</span><span>${esc(v)}</span></div>`).join('');
    const res = await api(runUrl('/ai-spend'));
    if (res.ok && S.right === 'details' && JSON.stringify(res.data) !== JSON.stringify(S.spend)) { S.spend = res.data; paintDetails(); }
  }
  async function saveStyle() {
    S.settings.master_style = $('#set-style').value.trim();
    await saveSettings({ master_style: S.settings.master_style });
  }

  // ── My videos ─────────────────────────────────────────────────────────────

  async function loadRuns() {
    err('#runs-err', '');
    const res = await api(`/platform/projects/${encodeURIComponent(S.cfg.project_id)}/runs`);
    if (!res.ok) { err('#runs-err', why(res)); return; }
    S.runs = res.data;
    const box = $('#run-list');
    if (!S.runs.length) {
      box.innerHTML = '<div class="empty"><b>No videos yet</b><p>A video goes from your script to a finished file in four steps.</p></div>';
      return;
    }
    const arrow = '<svg class="arrow" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6"/></svg>';
    box.innerHTML = S.runs.map(r => {
      const stepName = r.has_video ? 'Rendered' : (STEP_NAMES[STEPS.indexOf(r.current_step)] || (r.steps_done ? 'Render' : 'Script'));
      const dot = r.has_video ? 'ok' : r.steps_done ? 'run' : '';
      const date = new Date(r.updated_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
      const parts = ['Animated', r.format || '9:16', LANGS[r.language] || r.language, date];
      return `<a class="run-item" href="#run/${encodeURIComponent(r.run_id)}" style="text-decoration:none;color:inherit"><div class="main-col"><div class="t">${esc(r.name || 'Untitled')}</div>
        <div class="m"><span class="step-st"><span class="dot ${dot}"></span>${esc(stepName)}</span>${parts.map(p => `<span class="sep">·</span><span>${esc(p)}</span>`).join('')}</div></div>${arrow}</a>`;
    }).join('');
  }

  // ── New video ─────────────────────────────────────────────────────────────

  function resetNewForm() {
    err('#new-err', '');
    $('#new-title').value = '';
    $('#new-style').value = '';
    $('#new-chars').innerHTML = '';
    $('#new-char-add').classList.remove('hidden');
    $('#new-create').disabled = false;
    $('#new-title').focus();
  }
  /** Open the AI assets library under the characters: pick one to add it to the video's cast. */
  async function toggleLibrary() {
    const box = $('#new-lib-box');
    if (box.classList.toggle('on') === false) return;
    box.innerHTML = '<p class="meta">Loading…</p>';
    const res = await api('/platform/creator/assets');
    if (!res.ok) { box.innerHTML = `<p class="meta">${esc(why(res))}</p>`; return; }
    const chars = res.data.items.filter(a => a.kind === 'character');
    S.libChars = chars;
    box.innerHTML = chars.length
      ? chars.map((a, i) => `<button class="as-card" style="display:block;width:100%;text-align:left" onclick="Creator.pickLibrary(${i})"><span class="n">${esc(a.name)}</span><p>${esc(a.description)}</p></button>`).join('')
      : '<p class="meta">No characters in the library yet. Save one from a storyboard, or add it under Libraries → AI assets.</p>';
  }
  /** Add the chosen library character as a row of the cast (the user can still edit it). */
  function pickLibrary(i) {
    const a = (S.libChars || [])[i];
    if (!a) return;
    const rows = [...$('#new-chars').children];
    if (rows.some(r => r.querySelector('input').value.trim().toLowerCase() === a.name.toLowerCase())) return;
    if (rows.length >= S.cfg.max_characters) { err('#new-err', `A video can list up to ${S.cfg.max_characters} characters.`); return; }
    addCharRow();
    const row = $('#new-chars').lastElementChild;
    row.querySelector('input').value = a.name;
    row.querySelector('textarea').value = a.description;
    $('#new-lib-box').classList.remove('on');
  }
  /** Save the entry open in the dialog to the account's AI assets library. */
  async function saveToAssets() {
    const msg = $('#e-msg');
    if (!S.entryId) { msg.textContent = 'Save it first, then add it to the AI assets.'; return; }
    const res = await api('/platform/creator/assets/from-run', { method: 'POST', body: { run_id: S.run.id, entry_id: S.entryId } });
    msg.textContent = res.ok ? 'Saved to your AI assets. Pick it when you create a new video.' : `Not saved: ${why(res)}`;
  }
  function addCharRow() {
    const box = $('#new-chars');
    if (box.children.length >= S.cfg.max_characters) return;
    const row = document.createElement('div');
    row.className = 'char-row';
    row.innerHTML = `<input type="text" maxlength="80" placeholder="Name" aria-label="Character name">
      <textarea rows="1" maxlength="1200" placeholder="Age, hair, clothes — every detail that must stay the same" aria-label="Character description"></textarea>
      <button class="icon-btn" aria-label="Remove character" title="Remove"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg></button>`;
    row.querySelector('button').onclick = () => { row.remove(); $('#new-char-add').classList.remove('hidden'); };
    box.appendChild(row);
    $('#new-char-add').classList.toggle('hidden', box.children.length >= S.cfg.max_characters);
    row.querySelector('input').focus();
  }
  async function createRun() {
    err('#new-err', '');
    const title = $('#new-title').value.trim();
    if (!title) { err('#new-err', 'Say what the video is about.'); return; }
    const characters = [];
    for (const row of $$('#new-chars .char-row')) {
      const name = row.querySelector('input').value.trim(), description = row.querySelector('textarea').value.trim();
      if (!name && !description) continue;
      if (!name || !description) { err('#new-err', 'Give every character a name and a description, or remove the row.'); return; }
      characters.push({ name, description });
    }
    $('#new-create').disabled = true;
    const res = await api('/platform/creator/runs', { method: 'POST', body: {
      title, aspect_ratio: $('#new-ar button.on').dataset.v, language: $('#new-lang').value,
      master_style: $('#new-style').value.trim(), characters,
    } });
    $('#new-create').disabled = false;
    if (!res.ok) { err('#new-err', why(res)); return; }
    go(`#run/${encodeURIComponent(res.data.run_id)}/script`);
  }

  // ── One video: loading ────────────────────────────────────────────────────

  /** Load everything a run has made so far. Leaves S.run null when the run cannot be read. */
  async function openRun(id) {
    stopAudio();
    S.run = null; S.voice = null; S.sb = null; S.manifest = {}; S.video = null; S.imageJob = null;
    S.sbStale = false; S.openScene = null; S.settings = {}; S.musicKey = null; S.spend = null; S.busy = {}; S.meta = null; S.context = null;
    ['#job-voice', '#job-sb', '#job-render'].forEach(clearJob);
    ['#err-script', '#err-voice', '#err-sb', '#err-render'].forEach(e => err(e, ''));
    const ctx = await api(`/platform/studio/runs/${encodeURIComponent(id)}/context`);
    if (!ctx.ok) { show('runs'); await loadRuns(); err('#runs-err', ctx.status === 404 ? 'That video no longer exists.' : why(ctx)); return; }
    S.run = { id, name: ctx.data.name || ctx.data.idea_title || 'Untitled', language: ctx.data.language || 'en', format: ctx.data.format || '9:16', created: ctx.data.created_at };
    S.context = ctx.data;
    const [settings, script, voice, sb, manifest, video] = await Promise.all([
      api(`/runs/${encodeURIComponent(id)}/settings`), api(runUrl('/script')), api(runUrl('/voice')),
      api(runUrl('/storyboard')), api(runUrl('/manifest')), api(runUrl('/video')),
    ]);
    if (S.run.id !== id) return;
    if (settings.ok) S.settings = settings.data.settings || {};
    if (S.settings.aspect_ratio) S.run.format = S.settings.aspect_ratio;
    const draft = readDraft();
    $('#script').value = draft != null ? draft : (script.ok ? script.data.script || '' : '');
    if (voice.ok && !String(voice.data.alignment_method || '').startsWith('uploaded')) S.voice = voice.data;
    if (sb.ok) S.sb = sb.data;
    if (manifest.ok) applyManifest(manifest.data);
    if (video.ok && video.data.video_url) S.video = video.data;
    resumeJobs();
    if (window.Core) await window.Core.onRunOpened();
  }

  /** Pick up work that was still running when the page was left. */
  async function resumeJobs() {
    const id = S.run.id;
    const [v, sb, img, rn] = await Promise.all([api(runUrl('/voice/status')), api(runUrl('/storyboard/status')), api(runUrl('/images/status')), api(runUrl('/render/status'))]);
    if (!S.run || S.run.id !== id) return;
    if (v.ok && v.data.status === 'running') watchVoice();
    if (sb.ok && sb.data.status === 'running') watchStoryboard();
    if (img.ok && img.data.status === 'running') { S.imageJob = img.data; watchImages(); }
    else if (img.ok && ['interrupted', 'stopped_at_cap', 'error'].includes(img.data.status)) { S.imageJob = img.data; paintImageJob(); }
    if (rn.ok && rn.data.status === 'running') watchRender();
  }

  const draftKey = () => `cf_creator_script_${S.run.id}`;
  function readDraft() { try { return localStorage.getItem(draftKey()); } catch { return null; } }
  function writeDraft(text) { try { localStorage.setItem(draftKey(), text); } catch { /* private mode */ } }

  async function saveSettings(patch) {
    const res = await api(`/runs/${encodeURIComponent(S.run.id)}/settings`, { method: 'POST', body: patch });
    if (res.ok) S.settings = res.data.settings || S.settings;
    return res;
  }

  // ── One video: state helpers ──────────────────────────────────────────────

  const sbScenes = () => (S.sb && S.sb.storyboard && S.sb.storyboard.scenes) || [];
  const continuity = () => (S.sb && S.sb.storyboard && S.sb.storyboard.continuity) || [];
  const scriptWords = () => $('#script').value.trim().split(/\s+/).filter(Boolean).length;
  const hasAsset = scene => !!(S.manifest[String(scene.scene)] || {}).asset_url;
  const allAssets = () => sbScenes().length > 0 && sbScenes().every(hasAsset);
  const scriptOk = () => { const w = scriptWords(); return w > 0 && w <= S.cfg.script_max_words; };

  /** The first step that is not done: where a run opens. */
  function firstOpenStep() {
    if (!S.voice) return scriptWords() ? 1 : 0;
    if (!S.sb || !allAssets()) return 2;
    return 3;
  }
  function applyManifest(data) {
    S.manifest = {};
    ((data && data.manifest && data.manifest.entries) || (data && data.entries) || []).forEach(e => { S.manifest[String(e.scene_id)] = e; });
  }
  async function refreshManifest() { const res = await api(runUrl('/manifest')); if (res.ok) applyManifest(res.data); }
  async function reloadStoryboard() {
    const res = await api(runUrl('/storyboard'));
    if (res.ok) S.sb = res.data;
    await refreshManifest();
    paintStoryboard();
  }
  function setStep(i) { go(`#run/${encodeURIComponent(S.run.id)}/${STEPS[i]}`); }
  function next() { if (S.step < STEPS.length - 1) setStep(S.step + 1); }

  // ── One video: painting ───────────────────────────────────────────────────

  function paintRun() {
    $('#run-title').textContent = S.run.name;
    const done = [scriptOk() && !!S.voice, !!S.voice, !!S.sb && allAssets(), !!S.video, !!(S.meta && S.meta.title)];
    $('#steps').style.gridTemplateColumns = `repeat(${STEPS.length},1fr)`;
    $('#steps').innerHTML = STEP_NAMES.map((n, i) => `<button class="${i === S.step ? 'cur' : done[i] ? 'done' : ''}" onclick="Creator.setStep(${i})"><i>${i + 1}</i>${n}</button>`).join('');
    $$('.step').forEach(el => { el.style.display = +el.dataset.step === S.step ? 'block' : 'none'; });
    if (S.step !== 1) stopAudio();
    paintScript(); paintVoice(); paintStoryboard(); paintRender();
    if (window.Core) window.Core.afterPaint();
    if (S.right) paintRight();
  }

  /** The words are fixed once a generated voiceover exists; an uploaded recording has its own transcript editor. */
  const scriptLocked = () => !!S.voice && !(S.context && S.context.voice_source === 'uploaded');
  function paintScript() {
    const locked = scriptLocked();
    $('#script').readOnly = locked;
    $('#script').title = locked ? 'The script is locked once the voiceover exists. Use "Start a new video from this one" in the video settings to change it.' : '';
    const bar = $('#src-bar');
    if (bar) bar.classList.toggle('hidden', locked);
    if (locked) { const gb = $('#gen-box'); if (gb) gb.classList.remove('on'); }
    const w = scriptWords(), max = S.cfg.script_max_words;
    const wc = $('#script-wc');
    wc.textContent = `${w} of ${max} words`;
    wc.classList.toggle('over', w > max);
    $('#script-next').disabled = !scriptOk();
    err('#err-script', w > max ? `The script is ${w - max} words over the limit. Shorten it to go on.` : '');
  }
  function onScript() { writeDraft($('#script').value); paintScript(); }

  // ── Voice ─────────────────────────────────────────────────────────────────

  const PH_ICONS = {
    storyboard: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 10h18M9 5v14"/>',
    video: '<rect x="3" y="5" width="14" height="14" rx="2"/><path d="M17 10l4-2v8l-4-2"/>',
    voice: '<path d="M12 4v16M8 8v8M4 11v2M16 8v8M20 11v2"/>',
  };
  /** The empty state every step uses: a dashed frame, a small icon, what is missing and what will appear. */
  function placeholder(kind, title, hint) {
    return `<div class="ph"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">${PH_ICONS[kind]}</svg><b>${esc(title)}</b><span>${esc(hint)}</span></div>`;
  }
  function paintVoice() {
    const pick = $('#voice-pick');
    if (!pick.options.length) pick.innerHTML = S.cfg.voices.map(v => `<option value="${esc(v.id)}">${esc(v.label)}</option>`).join('');
    const saved = S.settings.voice, aliases = S.cfg.voice_aliases || {};
    const wanted = aliases[saved] || saved || S.cfg.default_voice;
    pick.value = [...pick.options].some(o => o.value === wanted) ? wanted : S.cfg.voices[0].id;
    pick.disabled = !!S.busy.voice;
    const gen = $('#vo-gen');
    gen.textContent = S.busy.voice ? 'Generating…' : (S.voice ? 'Re-generate' : 'Generate voiceover') + priceTag('voice');
    gen.disabled = !!S.busy.voice || !scriptOk();
    $('#vo-next').disabled = !S.voice || !!S.busy.voice;
    const track = $('#vo-track');
    track.classList.toggle('on', !!S.voice && !S.busy.voice);
    const ph = $('#vo-ph');
    if (!ph.innerHTML) ph.innerHTML = placeholder('voice', 'No voiceover yet', 'Choose a voice and generate it. You can listen here before you go on.');
    ph.classList.toggle('hidden', !!S.voice || !!S.busy.voice);
    if (S.voice && !S.busy.voice) {
      if (!$('#vo-wave').children.length) {
        $('#vo-wave').innerHTML = Array.from({ length: 64 }, (_, i) => `<i style="height:${18 + Math.round(Math.abs(Math.sin(i * 0.7) * Math.cos(i * 0.23)) * 82)}%"></i>`).join('');
      }
      paintAudio();
    }
    // What is missing is a hint beside the button, not an error box.
    $('#hint-voice').textContent = !scriptOk() && !S.voice && !S.busy.voice ? 'Write the script first.' : '';
    if (!S.busy.voiceErr) err('#err-voice', '');
  }
  async function saveVoice() { stopSample(); S.settings.voice = $('#voice-pick').value; await saveSettings({ voice: S.settings.voice }); }

  // A short recording of the chosen voice. The server makes it once per voice and keeps it.
  const PLAY_ICO = '<path d="M7 4l13 8-13 8z"/>', STOP_ICO = '<rect x="6" y="6" width="12" height="12" rx="2"/>';
  const sampleUrls = {};
  function stopSample() {
    if (S.sample) { S.sample.pause(); S.sample = null; }
    const ico = $('#voice-sample-ico'); if (ico) ico.innerHTML = PLAY_ICO;
  }
  async function playSample() {
    if (S.sample) { stopSample(); return; }
    const voice = $('#voice-pick').value, btn = $('#voice-sample');
    err('#err-voice', '');
    if (!sampleUrls[voice]) {
      btn.disabled = true;
      const res = await api(`/platform/creator/voice-samples/${encodeURIComponent(voice)}`);
      btn.disabled = false;
      if (!res.ok) { err('#err-voice', `No sample: ${why(res)}`); return; }
      sampleUrls[voice] = res.data.url;
    }
    stopAudio();
    const a = new Audio(sampleUrls[voice]);
    S.sample = a;
    a.addEventListener('ended', stopSample);
    a.addEventListener('error', () => { stopSample(); err('#err-voice', 'The sample could not be played.'); });
    $('#voice-sample-ico').innerHTML = STOP_ICO;
    a.play().catch(() => stopSample());
  }

  async function genVoice() {
    if (S.sb && !await confirmBox('Re-generate the voiceover?', 'The storyboard was made for the current voiceover. After this you will have to create the storyboard again.', 'Re-generate')) return;
    err('#err-voice', ''); clearJob('#job-voice'); stopAudio();
    const voice = $('#voice-pick').value;
    if (S.settings.voice !== voice) { S.settings.voice = voice; await saveSettings({ voice }); }
    const res = await api('/platform/workers/voice', { method: 'POST', body: { run_id: S.run.id, script: $('#script').value.trim(), confirm_discard: true } });
    if (!res.ok) { failure('#job-voice', 'Voiceover was not started.', why(res), genVoice); return; }
    if (S.sb) S.sbStale = true;
    watchVoice();
  }
  /** Follow a running voice job to its end. */
  async function watchVoice() {
    const id = S.run.id;
    S.busy.voice = true; paintVoice();
    const stop = progress('#job-voice', 'Generating the voiceover…');
    const st = await poll(runUrl('/voice/status'), 3000, 200);
    stop();
    if (!S.run || S.run.id !== id) return;
    S.busy.voice = false;
    if (st.status === 'error') { paintVoice(); failure('#job-voice', 'Voiceover failed.', st.error || 'The voice service did not answer.', genVoice); return; }
    const res = await api(runUrl('/voice'));
    if (!res.ok) { paintVoice(); failure('#job-voice', 'Voiceover failed.', why(res), genVoice); return; }
    S.voice = res.data; S.audio = null;
    paintRun();
  }

  function ensureAudio() {
    if (S.audio || !S.voice || !S.voice.mp3_url) return S.audio;
    S.audio = new Audio(S.voice.mp3_url);
    ['timeupdate', 'ended', 'pause', 'play', 'loadedmetadata'].forEach(ev => S.audio.addEventListener(ev, paintAudio));
    return S.audio;
  }
  function toggleVo() { const a = ensureAudio(); if (!a) return; if (a.paused) a.play().catch(() => err('#err-voice', 'The voiceover could not be played.')); else a.pause(); }
  function stopAudio() { if (S.audio) { S.audio.pause(); } if (S.sample) stopSample(); }
  function paintAudio() {
    const a = S.audio, total = (a && isFinite(a.duration) && a.duration) || (S.voice && S.voice.total_duration_s) || 0;
    const pos = a ? a.currentTime : 0;
    const bars = $$('#vo-wave i'), k = total ? Math.round(bars.length * pos / total) : 0;
    bars.forEach((b, i) => b.classList.toggle('p', i < k));
    const t = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
    $('#vo-time').textContent = `${t(pos)} / ${t(total)}`;
    $('#vo-ico').innerHTML = a && !a.paused ? '<path d="M6 4h4v16H6zM14 4h4v16h-4z"/>' : '<path d="M7 4l13 8-13 8z"/>';
  }

  // ── Storyboard ────────────────────────────────────────────────────────────

  function paintStoryboard() {
    const scenes = sbScenes(), busy = !!S.busy.sb || !!S.busy.images;
    const create = $('#sb-create'), assets = $('#sb-assets');
    create.textContent = S.busy.sb ? 'Creating…' : (S.sb ? 'Re-create storyboard' : 'Create storyboard') + priceTag('storyboard');
    create.className = 'btn ' + (S.sb && !S.sbStale ? 'quiet' : 'accent');
    create.disabled = busy || !S.voice;
    const missing = scenes.filter(s => !hasAsset(s)).length;
    assets.textContent = S.busy.images ? 'Creating…' : scenes.length && !missing ? 'Re-create assets' : 'Create assets';
    assets.className = 'btn ' + (scenes.length && !missing ? 'quiet' : 'accent');
    assets.disabled = busy || !S.sb || S.sbStale;
    $('#sb-next').disabled = busy || !allAssets() || S.sbStale;
    const total = scenes.reduce((a, s) => a + (s.duration_s || 0), 0);
    $('#sc-meta').textContent = scenes.length ? `${plural(scenes.length, 'scene')} · ${clock((S.voice && S.voice.total_duration_s) || total)}${missing ? ` · ${missing} without an image` : ''}` : '';
    $('#hint-sb').textContent = !S.voice ? 'Generate the voiceover first. The scenes are cut on its timing.'
      : S.sbStale ? 'The voiceover changed. Create the storyboard again so the scenes match it.' : '';
    if (!S.busy.sbErr) err('#err-sb', '');
    paintContinuity();
    const box = $('#scenes');
    if (!scenes.length) { box.innerHTML = placeholder('storyboard', 'No storyboard yet', 'The scenes appear here once you create the storyboard from your script and voiceover.'); if (window.Core) window.Core.afterStoryboard(); return; }
    const byId = Object.fromEntries(continuity().map(e => [e.id, e]));
    const jobScenes = (S.imageJob && S.imageJob.status === 'running' && S.imageJob.scenes) || {};
    let offset = 0;
    box.innerHTML = scenes.map((s, i) => {
      const id = String(s.scene), start = s.scene_start_ms != null ? s.scene_start_ms / 1000 : offset;
      const dur = s.duration_s || 0; offset = start + dur;
      const canSplit = s.start_word != null && s.end_word != null && !busy;
      const words = String(s.voiceover_line || '').split(' ').map((w, j) => j && canSplit
        ? `<span class="w" title="Split the scene before this word" onclick="Creator.openSplit(event,'${esc(id)}',${s.start_word + j})">${esc(w)}</span>` : esc(w)).join(' ');
      const chips = (s.flags || []).filter(f => FLAGS[f]).map(f => `<button class="chip flag" title="${esc(FLAGS[f][1])}">${esc(FLAGS[f][0])}</button>`);
      (s.entities || []).forEach(eid => { if (byId[eid]) chips.push(`<button class="chip ent" title="${esc(byId[eid].description)}">${esc(byId[eid].name)}</button>`); });
      if (s.on_screen_text) chips.push('<button class="chip">On-screen text</button>');
      const motion = MOTIONS.find(m => m[0] === s.motion_effect);
      if (motion) chips.push(`<button class="chip">${motion[1]}</button>`);
      const entry = S.manifest[id] || {};
      const thumb = entry.asset_url ? ` style="background-image:url('${esc(entry.asset_url)}')"` : '';
      const generating = jobScenes[id] === 'running' || jobScenes[id] === 'pending';
      const open = S.openScene === id;
      return `<div class="sc${open ? ' open' : ''}${generating ? ' busy' : ''}" data-scene="${esc(id)}">
        <div class="sc-row" onclick="Creator.toggleScene('${esc(id)}')">
          <div class="sc-thumb"${thumb}><button class="pencil" title="Change this scene's image" aria-label="Change the image of scene ${esc(id)}" onclick="event.stopPropagation();Creator.openModal('${esc(id)}')"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg></button></div>
          <div class="sc-body">
            <div class="sc-top"><span class="sc-no">Scene ${i + 1}</span><span class="sc-time">${clock(start)} – ${clock(start + dur)}</span><span class="sc-dur">${dur.toFixed(1)}s</span></div>
            <div class="sc-vo">${words}</div>
            <div class="sc-chips">${chips.join('')}${i < scenes.length - 1 && canSplit ? `<button class="sc-merge" onclick="event.stopPropagation();Creator.mergeScene('${esc(id)}')">Merge with next</button>` : ''}</div>
          </div>
        </div>
        ${open ? `<div class="sc-detail" style="display:block"><div class="row3">
          <div class="field wide"><span class="lbl">Image prompt</span><textarea rows="2" onchange="Creator.patchScene('${esc(id)}',{ai_prompt:this.value})">${esc(s.ai_prompt || '')}</textarea>
            <div class="m-line" style="margin-top:8px"><button class="btn sm" onclick="Creator.writePrompt('${esc(id)}', this)"${S.busy.prompt ? ' disabled' : ''}>${S.busy.prompt === id ? 'Writing…' : s.ai_prompt ? 'Rewrite with the director' : 'Write with the director'}</button></div></div>
          <label class="field"><span class="lbl">Motion effect</span><select onchange="Creator.patchScene('${esc(id)}',{motion_effect:this.value})">${MOTIONS.map(m => `<option value="${m[0]}"${m[0] === s.motion_effect ? ' selected' : ''}>${m[1]}</option>`).join('')}${s.motion_effect && !motion ? `<option value="${esc(s.motion_effect)}" selected>${esc(s.motion_effect)}</option>` : ''}</select></label>
          <label class="field"><span class="lbl">On-screen text</span><input type="text" maxlength="120" value="${esc(s.on_screen_text || '')}" placeholder="None" onchange="Creator.patchScene('${esc(id)}',this.value.trim()?{on_screen_text:this.value.trim()}:{clear_on_screen_text:true})"></label>
        </div></div>` : ''}
      </div>`;
    }).join('');
    if (window.Core) window.Core.afterStoryboard();
  }
  function toggleScene(id) { S.openScene = S.openScene === id ? null : id; closeSplit(); paintStoryboard(); }

  async function patchScene(id, fields) {
    const res = await api(runUrl(`/storyboard/scenes/${encodeURIComponent(id)}`), { method: 'PATCH', body: fields });
    if (!res.ok) { err('#err-sb', `That change was not saved: ${why(res)}`); return false; }
    await reloadStoryboard();
    return true;
  }

  /** The Visual Director writes this scene's image prompt with its usual rules (one model call). */
  async function writePrompt(id, btn) {
    if (S.busy.prompt) return;
    err('#err-sb', '');
    S.busy.prompt = id;
    if (btn) { btn.disabled = true; btn.textContent = 'Writing…'; }
    const res = await api(runUrl(`/storyboard/scenes/${encodeURIComponent(id)}/write-prompt`), { method: 'POST' });
    S.busy.prompt = null;
    if (!res.ok) { err('#err-sb', `The prompt was not written: ${why(res)}`); paintStoryboard(); return null; }
    S.sb = res.data;
    await refreshManifest();
    paintStoryboard();
    return res.data.ai_prompt || '';
  }
  async function writePromptInModal() {
    const btn = $('#m-write'), msg = $('#m-msg');
    btn.disabled = true; btn.textContent = 'Writing…'; msg.textContent = '';
    const prompt = await writePrompt(S.modalScene);
    btn.disabled = false; btn.textContent = 'Write with the director';
    if (prompt == null) { msg.textContent = 'The prompt was not written. See the message above the scenes.'; return; }
    $('#m-ai').value = prompt;
    paintModalEntities();
    msg.textContent = 'Written. Click Generate to make the image.';
  }

  function openSplit(event, id, atWord) {
    event.stopPropagation();
    closeSplit();
    const el = event.currentTarget, rect = el.getBoundingClientRect(), pop = $('#split-pop');
    el.classList.add('picked');
    S.split = { id, atWord, el };
    pop.style.left = `${Math.min(rect.left, window.innerWidth - 120)}px`;
    pop.style.top = `${rect.bottom + 4}px`;
    pop.classList.add('on');
  }
  function closeSplit() { if (S.split && S.split.el) S.split.el.classList.remove('picked'); S.split = null; $('#split-pop').classList.remove('on'); }
  async function boundary(path, body) {
    err('#err-sb', '');
    const res = await api(runUrl('/storyboard' + path), { method: 'POST', body });
    if (!res.ok) { err('#err-sb', why(res)); return; }
    S.sb = res.data; S.openScene = null;
    await refreshManifest();
    paintRun();
  }
  async function confirmSplit() { if (!S.split) return; const { id, atWord } = S.split; closeSplit(); await boundary(`/scenes/${encodeURIComponent(id)}/split`, { at_word: atWord }); }
  async function mergeScene(id) {
    const scenes = sbScenes(), nextScene = scenes[scenes.findIndex(s => String(s.scene) === id) + 1];
    if (!nextScene) return;
    if (nextScene.on_screen_text && !await confirmBox('Merge these two scenes?', `The second scene's on-screen text ("${nextScene.on_screen_text}") will be dropped.`, 'Merge')) return;
    await boundary(`/scenes/${encodeURIComponent(id)}/merge`);
  }

  /** Re-creating throws away scene changes and the images made for them: ask first. */
  async function askCreateSb() {
    if (S.sb && !S.sbStale) {
      const made = sbScenes().some(hasAsset);
      if (!await confirmBox('Re-create the storyboard?', `Your scene changes will be lost${made ? ', and the images you created will no longer be used' : ''}. The script and voiceover stay as they are.`, 'Re-create')) return;
    }
    createSb();
  }
  async function createSb() {
    err('#err-sb', ''); clearJob('#job-sb');
    const res = await api('/platform/workers/storyboard', { method: 'POST', body: {
      run_id: S.run.id, script: $('#script').value.trim(), format_track: S.run.format === '16:9' ? 'landscape' : 'portrait',
    } });
    if (!res.ok) { failure('#job-sb', 'Storyboard was not started.', why(res), createSb); return; }
    watchStoryboard();
  }
  async function watchStoryboard() {
    const id = S.run.id;
    S.busy.sb = true; paintStoryboard();
    const stop = progress('#job-sb', 'Planning the scenes…');
    const st = await poll(runUrl('/storyboard/status'), 3000, 200);
    stop();
    if (!S.run || S.run.id !== id) return;
    S.busy.sb = false;
    if (st.status === 'error') { paintStoryboard(); failure('#job-sb', 'Storyboard was not created.', st.error || 'The planning step stopped. Your script and voiceover are safe.', createSb); return; }
    S.sbStale = false; S.imageJob = null; S.openScene = null; S.manifest = {};
    await reloadStoryboard();
    paintRun();
  }

  // ── Images: the estimate first, then the job ──────────────────────────────

  /** Show what creating the images will cost before anything is made. */
  async function planAssets(sceneIds) {
    err('#err-sb', '');
    const all = !sceneIds && allAssets();
    const q = sceneIds ? `?scene_ids=${encodeURIComponent(sceneIds.join(','))}` : all ? `?scene_ids=${encodeURIComponent(sbScenes().map(s => s.scene).join(','))}` : '';
    const res = await api(runUrl('/images/plan' + q));
    if (!res.ok) { err('#err-sb', why(res)); return; }
    const p = res.data;
    if (p.job_active) { err('#err-sb', 'Images are already being created for this video.'); return; }
    const skipped = (p.without_prompt || []).length ? `<p style="margin-top:8px">${plural(p.without_prompt.length, 'scene')} without an image prompt will be skipped.</p>` : '';
    if (!p.count) { await confirmBox('Nothing to create', `Every scene with a prompt already has an image.${skipped}`, 'OK', true); return; }
    const short = p.affordable < p.count;
    const html = `<div class="plan-grid"><div><b>${p.count}</b><span>${p.count === 1 ? 'image' : 'images'}</span></div>
      <div><b>~${money(p.estimated_cost_usd)}</b><span>estimated</span></div>
      <div><b>${money(p.remaining_usd)}</b><span>left of ${money(p.cap_usd)}</span></div>
      ${S.billing && S.billing.enabled ? `<div><b>${p.estimated_credits}</b><span>credits of your ${S.billing.balance}</span></div>` : ''}</div>
      <p>About $${Number(p.cost_per_image_usd).toFixed(3)} per image. The cost is an estimate.</p>${skipped}
      ${short ? `<p style="margin-top:8px">The limit for this video allows ${p.affordable} of ${p.count}. Creation stops there and says how many are left.</p>` : ''}`;
    if (!p.affordable) { await confirmBox('The limit for this video is reached', html, 'OK', true); return; }
    if (!await confirmBox(all ? 'Create every image again?' : 'Create the images?', html, `Create ${plural(Math.min(p.count, p.affordable), 'image')}`, true)) return;
    const body = {};
    if (sceneIds) body.scene_ids = sceneIds; else if (all) body.scene_ids = sbScenes().map(s => String(s.scene));
    const start = await api(runUrl('/images/generate'), { method: 'POST', body });
    if (!start.ok) { failure('#job-sb', 'Images were not started.', why(start), () => planAssets(sceneIds)); return; }
    if (start.data.job) S.imageJob = start.data.job;
    loadBilling();
    watchImages();
  }
  async function watchImages() {
    const id = S.run.id;
    S.busy.images = true; paintStoryboard();
    const stop = progress('#job-sb', () => S.imageJob && S.imageJob.total ? `Creating images… ${S.imageJob.done || 0} of ${S.imageJob.total}` : 'Creating images…');
    for (;;) {
      await sleep(3000);
      const res = await api(runUrl('/images/status'));
      if (!S.run || S.run.id !== id) { stop(); return; }
      if (!res.ok) continue;
      S.imageJob = res.data;
      await refreshManifest();
      paintStoryboard();
      if (res.data.status !== 'running') break;
    }
    stop();
    S.busy.images = false;
    loadBilling();
    await reloadStoryboard();
    paintRun();
    paintImageJob();
  }
  /** Say how a finished image job ended when it did not make everything. */
  function paintImageJob() {
    const job = S.imageJob;
    if (!job || job.status === 'running' || job.status === 'none') return;
    const failed = job.failed || [];
    const left = Object.entries(job.scenes || {}).filter(([, st]) => st === 'not_started').map(([sid]) => sid);
    if (job.status === 'complete' && !failed.length) { clearJob('#job-sb'); return; }
    const head = { stopped_at_cap: job.message || 'Stopped at the limit for this video.', interrupted: job.message || 'Creation was interrupted.',
      error: `Creation failed: ${job.message || 'unknown error'}`, complete: `Created ${job.done} of ${job.total} images.` }[job.status] || '';
    const retryIds = [...failed.map(f => String(f.scene)), ...left];
    const box = $('#job-sb');
    box.className = 'job on err';
    box.innerHTML = `<span><b>${esc(head)}</b> ${failed.map(f => `Scene ${esc(f.scene)}: ${esc(f.reason || 'failed')}.`).join(' ')} ${left.length ? `${plural(left.length, 'scene')} not started.` : ''} The images already made are kept.</span>${retryIds.length ? '<button class="btn sm">Retry</button>' : ''}`;
    if (retryIds.length) box.querySelector('button').onclick = () => planAssets(retryIds);
  }

  // ── Scene image modal ─────────────────────────────────────────────────────

  function openModal(id) {
    const scene = sbScenes().find(s => String(s.scene) === id);
    if (!scene) return;
    S.modalScene = id;
    $('#m-title').textContent = `Scene ${sbScenes().indexOf(scene) + 1} — edit image`;
    $('#m-ai').value = scene.ai_prompt || '';
    $('#m-msg').textContent = '';
    $('#m-gen').disabled = false; $('#m-gen').textContent = 'Generate';
    paintModalEntities();
    $('#modal').classList.add('on');
  }
  function paintModalEntities() {
    const scene = sbScenes().find(s => String(s.scene) === S.modalScene) || {};
    const used = new Set(scene.entities || []);
    $('#m-ents-sec').classList.toggle('hidden', !continuity().length);
    $('#m-ents').innerHTML = continuity().map(e => `<button class="pick${used.has(e.id) ? ' on' : ''}" data-id="${esc(e.id)}" title="${esc(e.description)}" aria-pressed="${used.has(e.id)}" onclick="Creator.toggleEntity(this)"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12l5 5 9-10"/></svg>${esc(e.name)}</button>`).join('');
  }
  function closeModal() { $('#modal').classList.remove('on'); S.modalScene = null; }
  async function toggleEntity(btn) {
    btn.classList.toggle('on');
    const ok = await patchScene(S.modalScene, { entities: $$('#m-ents .pick.on').map(b => b.dataset.id) });
    if (!ok) btn.classList.toggle('on');
  }
  async function genSceneImage() {
    const prompt = $('#m-ai').value.trim(), msg = $('#m-msg'), btn = $('#m-gen'), id = S.modalScene;
    if (!prompt) { msg.textContent = 'Write a prompt first.'; return; }
    btn.disabled = true; btn.textContent = 'Generating… up to a minute'; msg.textContent = '';
    const res = await api(runUrl(`/scenes/${encodeURIComponent(id)}/generate`), { method: 'POST', body: { prompt } });
    btn.disabled = false; btn.textContent = 'Generate';
    if (!res.ok) { msg.textContent = `Not generated: ${why(res)}`; return; }
    msg.textContent = res.data.spend ? `Generated. ${money(res.data.spend.spent_usd)} of ${money(res.data.spend.cap_usd)} used for this video.` : 'Generated.';
    await reloadStoryboard();
    paintRun();
  }
  async function uploadSceneImage(input) {
    const file = input.files && input.files[0], msg = $('#m-msg'), id = S.modalScene;
    input.value = '';
    if (!file) return;
    if (!IMAGE_TYPES.includes(file.type)) { msg.textContent = 'Choose a JPG, PNG or WebP image.'; return; }
    msg.textContent = 'Uploading…';
    const form = new FormData(); form.append('file', file);
    const res = await api(runUrl(`/scenes/${encodeURIComponent(id)}/upload`), { method: 'POST', form });
    if (!res.ok) { msg.textContent = `Not uploaded: ${why(res)}`; return; }
    msg.textContent = 'Uploaded.';
    await reloadStoryboard();
    paintRun();
  }

  // ── Characters, props and settings ────────────────────────────────────────

  const usedIn = id => sbScenes().filter(s => (s.entities || []).includes(id)).length;
  function paintContinuity(msg) {
    const link = $('#ct-link'), box = $('#ct-box');
    link.classList.toggle('hidden', !S.sb);
    if (!S.sb) { box.classList.remove('on'); return; }
    const list = continuity();
    link.textContent = `Characters, props and settings (${list.length})`;
    box.innerHTML = `<div class="ct-cards">${list.map(e => `<button class="ct-card" onclick="Creator.openEntry('${esc(e.id)}')" title="${esc(e.description)}"><b>${esc(e.name)}</b><span>${KINDS[e.kind] || esc(e.kind)}</span></button>`).join('')}
      <button class="ct-card add" onclick="Creator.openEntry('')">+ Add</button></div>
      <p class="vd-note" style="margin:12px 0 0">Each description is added to the image prompt of every scene that uses it.</p><div class="ct-msg">${esc(msg || '')}</div>`;
  }
  function openEntry(id) {
    S.entryId = id;
    const e = continuity().find(c => c.id === id) || { kind: 'character', name: '', description: '' }, n = id ? usedIn(id) : 0;
    $('#e-title').textContent = id ? e.name : 'New character, prop or setting';
    $('#e-kind').innerHTML = Object.entries(KINDS).map(([v, l]) => `<option value="${v}"${v === e.kind ? ' selected' : ''}>${l}</option>`).join('');
    $('#e-name').value = e.name; $('#e-desc').value = e.description;
    $('#e-used').textContent = id ? (n ? `Used in ${plural(n, 'scene')}. Remove it from ${n === 1 ? 'that scene' : 'those scenes'} to delete it.` : 'Not used in any scene.') : '';
    $('#e-save').textContent = id ? 'Save' : 'Add';
    $('#e-ai-lib').classList.toggle('hidden', !id);
    $('#e-del').classList.toggle('hidden', !id || n > 0);
    $('#e-msg').textContent = '';
    $('#emodal').classList.add('on');
  }
  function closeEntry() { $('#emodal').classList.remove('on'); }
  async function entryCall(method, path, body, done) {
    const res = await api(runUrl('/storyboard/continuity' + path), { method, body });
    if (!res.ok) { $('#e-msg').textContent = why(res); return; }
    S.sb = res.data;
    closeEntry();
    await refreshManifest();
    paintStoryboard();
    paintContinuity(done(res.data));
  }
  async function saveEntry() {
    const body = { kind: $('#e-kind').value, name: $('#e-name').value.trim(), description: $('#e-desc').value.trim() };
    if (!body.name || !body.description) { $('#e-msg').textContent = 'Give it a name and a description.'; return; }
    if (!S.entryId) { await entryCall('POST', '', body, () => 'Added. Click the pencil on a scene to use it there.'); return; }
    await entryCall('PATCH', '/' + encodeURIComponent(S.entryId), body, data => {
      const n = (data.newly_out_of_date || []).length;
      return n ? `Saved. ${plural(n, 'scene image is', 'scene images are')} now out of date.` : 'Saved.';
    });
  }
  async function deleteEntry() { await entryCall('DELETE', '/' + encodeURIComponent(S.entryId), undefined, () => 'Deleted.'); }

  // ── Render ────────────────────────────────────────────────────────────────

  const captionChoice = () => (S.settings.subtitles === 'none' || !S.settings.subtitles ? 'none' : S.settings.caption_style === 'punch' ? 'punch' : 'standard');
  function paintRender() {
    const ready = allAssets() && !S.sbStale, busy = !!S.busy.render;
    $('#cap-pick').value = captionChoice();
    $('#cap-pick').disabled = busy;
    const music = $('#music-pick');
    if (S.musicKey && !music.querySelector('[value=track]')) music.insertAdjacentHTML('afterbegin', '<option value="track"></option>');
    if (S.musicKey) { music.querySelector('[value=track]').textContent = S.musicName || 'Your track'; music.value = 'track'; }
    music.disabled = busy;
    const pv = $('#preview');
    pv.className = 'preview' + (S.run.format === '16:9' ? ' wide' : '') + (S.video ? ' has-video' : '');
    if (S.video) { if (pv.dataset.url !== S.video.video_url) { pv.innerHTML = `<video controls preload="metadata" src="${esc(S.video.video_url)}"></video>`; pv.dataset.url = S.video.video_url; } }
    else { pv.innerHTML = placeholder('video', 'No video yet', 'The rendered video plays here.'); pv.dataset.url = ''; }
    const length = S.video && S.video.duration_s ? clock(S.video.duration_s) : S.voice && S.voice.total_duration_s ? clock(S.voice.total_duration_s) : '';
    $('#render-meta').textContent = S.video ? `Rendered · ${S.run.format}${length ? ' · ' + length : ''}` : ready ? `${S.run.format}${length ? ' · ≈ ' + length : ''}` : '';
    // Render first and always blue (it becomes Re-render once a video exists); Download beside it, outlined.
    const label = busy ? 'Rendering…' : (S.video ? 'Re-render video' : 'Render video') + priceTag('render');
    $('#render-foot').innerHTML = `<button class="btn accent" id="render-btn" onclick="Creator.renderVideo()"${busy || !ready ? ' disabled' : ''}>${label}</button>`
      + (S.video ? '<button class="btn outline" onclick="Creator.downloadVideo(this)">Download video</button>' : '')
      + (!ready && !busy ? '<span class="foot-hint">Create the images on the Storyboard step first.</span>' : '');
  }
  /** Download the rendered video through a blob: `<a download>` is ignored for a presigned (cross-origin) URL. */
  async function downloadVideo(btn) {
    const label = btn.textContent;
    btn.disabled = true; btn.textContent = 'Downloading…';
    err('#err-render', '');
    try {
      const r = await fetch(S.video.video_url);
      if (!r.ok) throw new Error(`Error ${r.status}`);
      const blobUrl = URL.createObjectURL(await r.blob());
      const a = document.createElement('a');
      a.href = blobUrl; a.download = `${S.run.name.replace(/[\\/:*?"<>|]+/g, ' ').trim() || 'video'}.mp4`;
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(blobUrl);
    } catch (e) { err('#err-render', `The video was not downloaded: ${e.message}. Reload the page and try again.`); }
    finally { btn.disabled = false; btn.textContent = label; }
  }
  async function saveCaptions() {
    const v = $('#cap-pick').value;
    const patch = v === 'none' ? { subtitles: 'none' } : { subtitles: 'TikTok', caption_style: v };
    Object.assign(S.settings, patch);
    const res = await saveSettings(patch);
    if (!res.ok) err('#err-render', `Captions were not saved: ${why(res)}`);
  }
  function onMusicPick() {
    const v = $('#music-pick').value;
    if (v === 'upload') { $('#music-pick').value = S.musicKey ? 'track' : 'none'; $('#music-file').click(); }
    else if (v === 'none') { S.musicKey = null; S.musicName = null; const o = $('#music-pick [value=track]'); if (o) o.remove(); }
  }
  async function uploadMusic(input) {
    const file = input.files && input.files[0];
    input.value = '';
    if (!file) return;
    err('#err-render', '');
    const status = $('#music-status'), pick = $('#music-pick');
    status.textContent = `Uploading ${file.name}…`; pick.disabled = true;
    const form = new FormData(); form.append('file', file);
    const res = await api(runUrl('/music'), { method: 'POST', form });
    pick.disabled = !!S.busy.render;
    if (!res.ok) { status.textContent = ''; err('#err-render', `The track was not uploaded: ${why(res)}`); return; }
    S.musicKey = res.data.file_key; S.musicName = file.name;
    status.textContent = `✓ ${file.name} uploaded — it will be used when you render.`;
    paintRender();
  }
  async function renderVideo() {
    err('#err-render', ''); clearJob('#job-render');
    // A video that was uploaded rather than rendered here is never replaced silently (P13b-S4).
    const uploaded = !!(S.video && S.video.source && S.video.source !== 'ffmpeg');
    if (uploaded && !await confirmBox('Replace the uploaded video?', 'This video was uploaded, not rendered here. Rendering replaces it.', 'Render and replace')) return;
    const cap = captionChoice();
    const res = await api('/platform/workers/render', { method: 'POST', body: {
      run_id: S.run.id, format_track: S.run.format === '16:9' ? 'landscape' : 'portrait',
      captions: cap !== 'none', caption_style: cap === 'punch' ? 'punch' : 'standard', music_enabled: !!S.musicKey,
      confirm_overwrite: uploaded,
    } });
    if (!res.ok) { failure('#job-render', 'Render was not started.', why(res), renderVideo); return; }
    watchRender();
  }
  async function watchRender() {
    const id = S.run.id;
    S.busy.render = true; paintRender();
    const stop = progress('#job-render', 'Rendering the video…');
    const st = await poll(runUrl('/render/status'), 4000, 225);
    stop();
    if (!S.run || S.run.id !== id) return;
    S.busy.render = false;
    if (st.status === 'error') { paintRender(); failure('#job-render', 'Render failed.', `${st.error || 'The video was not produced.'} Your storyboard and images are safe.`, renderVideo); return; }
    S.video = st;
    paintRun();
  }

  // ── Confirm box ───────────────────────────────────────────────────────────

  let confirmDone = null;
  /** Ask before something that cannot be undone or costs money. Resolves true on OK. `html` text is trusted markup built here. */
  function confirmBox(title, text, okLabel, html) {
    $('#c-title').textContent = title;
    if (html) $('#c-text').innerHTML = text; else $('#c-text').textContent = text;
    $('#c-ok').textContent = okLabel;
    $('#cmodal').classList.add('on');
    return new Promise(resolve => {
      confirmDone = resolve;
      $('#c-ok').onclick = () => { confirmDone = null; $('#cmodal').classList.remove('on'); resolve(true); };
    });
  }
  function closeConfirm() { $('#cmodal').classList.remove('on'); if (confirmDone) { const d = confirmDone; confirmDone = null; d(false); } }

  // ── Start ─────────────────────────────────────────────────────────────────

  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    if (S.split) closeSplit();
    else if ($('#cmodal').classList.contains('on')) closeConfirm();
    else if ($('#emodal').classList.contains('on')) closeEntry();
    else if ($('#modal').classList.contains('on')) closeModal();
    else if (S.right) { S.right = null; paintRight(); }
  });
  document.addEventListener('mousedown', e => {
    if (S.right && !e.target.closest('#right') && !e.target.closest('#right-open')) { S.right = null; paintRight(); }
    if (S.split && !e.target.closest('#split-pop') && !e.target.closest('.w')) closeSplit();
  });
  window.addEventListener('scroll', () => { if (S.split) closeSplit(); }, true);
  $$('#new-ar button').forEach(b => b.addEventListener('click', () => $$('#new-ar button').forEach(x => x.classList.toggle('on', x === b))));

  initPanels();

  async function start() {
    const res = await api('/platform/creator/config');
    if (!res.ok) { err('#runs-err', `The page could not start: ${why(res)}`); return; }
    S.cfg = res.data;
    await paintAccount();
    window.addEventListener('hashchange', route);
    route();
  }

  // What core.js (the Super screens and controls) builds on. Everything the server decides stays on the server.
  window.CFApp = {
    S, STEPS, STEP_NAMES, $, $$, esc, sleep, plural, money, clock, api, why, err, progress, failure, clearJob, poll,
    runUrl, go, show, route, confirmBox, saveSettings, paintRun, paintStoryboard, paintVoice, paintScript, paintRender,
    reloadStoryboard, refreshManifest, applyManifest, sbScenes, hasAsset, allAssets, scriptWords, scriptOk,
    watchVoice, watchStoryboard, createSb, renderVideo, genVoice, planAssets, paintRight, firstOpenStep, watchRender,
    watchImages, patchScene, openRun, stopAudio, paintContinuity, writeDraft, readDraft, onScript, addHelp, setHelp, loadBilling, priceTag,
  };
  window.Creator = {
    playSample, startFromThis, deleteRun, toggleLibrary, pickLibrary, saveToAssets, toggleLeft, closePanels, logOut, toggleViewAs, openRight, saveStyle, addCharRow, createRun, setStep, next, onScript,
    saveVoice, genVoice, toggleVo, askCreateSb, planAssets, toggleScene, patchScene, openSplit, confirmSplit, mergeScene,
    writePrompt, writePromptInModal, openModal, closeModal, toggleEntity, genSceneImage, uploadSceneImage, openEntry, closeEntry, saveEntry, deleteEntry,
    saveCaptions, onMusicPick, uploadMusic, renderVideo, downloadVideo, closeConfirm,
  };
  start();
})();
