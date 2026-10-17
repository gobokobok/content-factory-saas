/* Run-flow controls for a Super session (Sprint P-CORE S5–S9, D118).
 *
 * Loaded by core.js. The Creator page already does the four steps for an animated video; this adds, for
 * Super only, what the Studio had on top of them:
 *   Script      — three sources: paste, generate from an idea with a length, from a voiceover
 *   Voice       — narration pace and style, voiceover upload, transcript editing, language check
 *   Storyboard  — realistic look: stock footage, asset type, search words, re-acquire, script view, SFX
 *   Render      — CapCut export and upload
 *   Metadata    — a fifth step: title, description, tags
 *   Settings    — look, language, cast; save a character to the project's assets
 *   Auto-advance, and the New video form with a project and the realistic look
 *
 * It draws what the server returns and calls the same Studio routes the Studio did; the server decides.
 */
(function () {
  'use strict';

  let A = null, H = null, started = false, BASIC = false;
  const CR = { src: null, sel: null, audioEl: null, auto: false, autoBusy: false, lastStep: null, cfgSfx: [], acquiring: false };

  const $ = sel => document.querySelector(sel);
  const qs = id => document.getElementById(id);
  const S = () => A.S;
  const esc = v => String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const rid = () => encodeURIComponent(S().run.id);
  const STRATEGIES = [['stock_image', 'Stock image'], ['stock_video', 'Stock video'], ['upload', 'Upload'], ['ai_image', 'AI image']];
  const ARROW = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>';

  /** True when the run's visuals are made from stock footage (not generated images). */
  function isStock() {
    const sb = S().sb && S().sb.storyboard;
    const mode = (sb && sb.visual_mode) || S().settings.visual_mode || 'ai_animation';
    return mode !== 'ai_animation';
  }
  const uploadedVoice = () => !!(S().context && S().context.voice_source === 'uploaded');
  const projectId = () => (S().context && S().context.project && S().context.project.project_id) || S().cfg.project_id;

  // ── DOM that only a Super session has ─────────────────────────────────────

  function mountDom() {
    const run = qs('s-run');
    if (!BASIC) {
      // Fifth step.
      A.STEPS.push('metadata'); A.STEP_NAMES.push('Metadata');
      const meta = document.createElement('div');
      meta.className = 'step';
      meta.dataset.step = '4';
      meta.innerHTML = `<div class="err-line" id="err-meta"></div>
        <div id="meta-out"></div>
        <div class="step-foot"><button class="btn accent" id="meta-gen" onclick="CoreRun.genMeta()">Generate metadata</button></div>
        <div class="job" id="job-meta"></div>`;
      run.appendChild(meta);
    }

    // Script: source bar, generate box, voiceover box.
    // Basic has no script generation or voiceover upload: its Script step is the plain text box.
    if (!BASIC) qs('script').insertAdjacentHTML('beforebegin', `
      <div class="core-src" id="src-bar" style="display:flex;gap:18px;flex-wrap:wrap;margin-bottom:14px">
        <button class="link" data-s="generate" onclick="CoreRun.setSource('generate')">Generate script with AI</button>
        ${BASIC ? '' : '<button class="link" data-s="upload" onclick="CoreRun.setSource(\'upload\')">Start from a voiceover</button>'}</div>
      <div class="gen-box" id="gen-box">
        <label class="field"><span class="lbl">Idea / topic</span><input type="text" id="gen-idea" maxlength="300" placeholder="Why starter homes disappeared from America"></label>
        <div style="display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap">
          <label class="field" style="margin:0"><span class="lbl">Duration</span>
            <select id="gen-dur" style="width:160px"><option value="30">30 seconds</option><option value="60">1 minute</option><option value="90" selected>1.5 minutes</option><option value="120">2 minutes</option><option value="180">3 minutes</option><option value="300">5 minutes</option><option value="600">10 minutes</option></select></label>
          <button class="btn accent" id="gen-btn" onclick="CoreRun.genScript()">Generate script</button>
        </div>
        <div class="job" id="job-gen"></div>
      </div>
      ${BASIC ? '' : `<div class="gen-box" id="up-box">
        <p class="meta" style="margin:0 0 12px" id="up-lang"></p>
        <div class="drop" id="up-drop" onclick="document.getElementById('up-file').click()">Drop your voiceover here, or click to choose (MP3, WAV, M4A)</div>
        <input type="file" id="up-file" class="hidden" accept="audio/mpeg,audio/wav,audio/mp4,audio/x-wav,audio/x-m4a,audio/webm,.mp3,.wav,.m4a" onchange="CoreRun.uploadVo(this)">
        <div class="job" id="job-up"></div>
        <div id="tr-box" style="margin-top:16px"></div>
      </div>`}`);
    if (!BASIC) {
      const warn = document.createElement('div');
      warn.className = 'job warn';
      warn.id = 'tr-warn';
      qs('up-box').appendChild(warn);
    }

    // Voice: narration pace and style, and the uploaded-voice note.
    qs('voice-pick').closest('.field').insertAdjacentHTML('afterend', `
      <div class="row" id="nar-row" style="max-width:520px">
        <label class="field"><span class="lbl">Pace</span><select id="nar-pace" onchange="CoreRun.saveNarration()"></select></label>
        <label class="field"><span class="lbl">Style</span><select id="nar-style" onchange="CoreRun.saveNarration()"></select></label>
      </div>
      ${BASIC ? '' : '<p class="meta hidden" id="vo-uploaded-note" style="margin:0 0 14px">Your uploaded voiceover is this video\'s voice. Generating a voiceover replaces it.</p>'}`);
    qs('nar-pace').innerHTML = Object.entries(H.PACES).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join('');
    qs('nar-style').innerHTML = Object.entries(H.NARR_STYLES).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join('');

    if (BASIC) return;

    // Storyboard toolbar.
    qs('scenes').insertAdjacentHTML('beforebegin', `
      <div id="sb-super" class="hidden">
        <div class="step-foot" style="margin:0 0 14px">
          <button class="btn accent" id="sb-acquire" onclick="CoreRun.acquire()">Acquire footage</button>
          <span class="meta" id="sb-acq-meta"></span>
        </div>
        <details class="gen-box on" id="sb-sv" style="display:block;padding:10px 16px"><summary style="cursor:pointer;font-size:13px;font-weight:600">Script view — move the scene boundaries as text</summary>
          <textarea id="sv-text" rows="10" style="min-height:160px" spellcheck="false" oninput="CoreRun.svInput()"></textarea>
          <div class="step-foot" style="margin-top:10px"><button class="btn sm" id="sv-apply" onclick="CoreRun.svApply()" disabled>Apply boundaries</button><span class="meta" id="sv-msg" style="margin-left:0"></span></div>
        </details>
      </div>`);
    qs('sb-assets').insertAdjacentHTML('afterend', '');

    // Render: CapCut.
    qs('render-foot').insertAdjacentHTML('afterend', `
      <div style="margin-top:22px" id="cc-box"><h3 style="font-size:13px">Edit in CapCut instead</h3>
        <div style="display:flex;gap:18px;flex-wrap:wrap"><button class="link" id="cc-export" onclick="CoreRun.ccExport(this)">Download CapCut package</button>
        <button class="link" id="cc-up" onclick="document.getElementById('cc-file').click()">Upload edited video</button></div>
        <input type="file" id="cc-file" class="hidden" accept="video/mp4" onchange="CoreRun.ccUpload(this)"><div class="m-msg" id="cc-msg"></div></div>`);

    // Auto-advance lives in the video settings; a small flag by the title shows when it is on.
    qs('run-title').insertAdjacentHTML('afterend', '<span class="meta hidden" id="auto-flag">Auto-advance on</span>');
    qs('run-title').parentElement.style.gap = '12px';

    // Save to project assets, in the character dialog.
    qs('e-save').insertAdjacentHTML('afterend', '<button class="btn sm" id="e-lib" onclick="CoreRun.saveToLibrary()">Save to project assets</button>');

    // Right panel: one Look, one Language and one Cast section replace the read-only rows of the Creator's panel.
    ['row-look', 'row-lang', 'row-chars'].forEach(id => qs(id).classList.add('hidden'));
  }

  // ── Script ────────────────────────────────────────────────────────────────

  function paintScriptSource() {
    if (BASIC) { qs('script-next').disabled = !A.scriptOk(); return; }
    const src = CR.src || (uploadedVoice() ? 'upload' : 'paste');
    qs('src-bar').querySelectorAll('button').forEach(b => { b.style.fontWeight = b.dataset.s === src ? '700' : ''; });
    qs('gen-box').classList.toggle('on', src === 'generate');
    if (!BASIC) qs('up-box').classList.toggle('on', src === 'upload');
    const ta = qs('script');
    ta.readOnly = !BASIC && src === 'upload' && uploadedVoice() && !!S().upload;
    if (BASIC) return finishScriptSource();
    qs('up-lang').textContent = `Language of this video: ${H.LANGS[S().run.language] || S().run.language}. The voiceover is transcribed in it. Its transcript becomes the script.`;
    if (!qs('gen-idea').value) qs('gen-idea').value = S().run.name || '';
    finishScriptSource();
  }
  /** The idea and the niche hint, then the Next button. */
  function finishScriptSource() {
    if (!qs('gen-idea').value) qs('gen-idea').value = S().run.name || '';
    qs('script-next').disabled = !A.scriptOk() && !(uploadedVoice() && S().upload);
  }

  async function setSource(src) {
    if (src === 'upload') {
      if (!uploadedVoice()) {
        const ok = await putVoiceSource('uploaded');
        if (!ok) return;
      }
      CR.src = 'upload';
    } else {
      if (src === 'generate' && CR.src === 'generate') src = 'paste';   // the blue link toggles the box
      if (uploadedVoice()) {
        // Generated or pasted text replaces an uploaded recording, after the user confirms.
        if (!await A.confirmBox('Replace the uploaded voiceover?', 'Your recording and the storyboard made from it are discarded. The transcript stays as text you can edit.', 'Replace')) return;
        const ok = await putVoiceSource('generated', true);
        if (!ok) return;
        await A.openRun(S().run.id);
        A.paintRun();
      }
      CR.src = src;
    }
    paintScriptSource();
  }

  /** PUT the voice source; asks first when it would discard something. Returns the answer or null. */
  async function putVoiceSource(source, confirmed) {
    const res = await H.call(`/platform/studio/runs/${rid()}/voice-source`, 'PUT', { voice_source: source, confirm_discard: !!confirmed });
    if (res.status === 409 && res.data.needs_confirmation && !confirmed) {
      if (!await A.confirmBox('Change the voice source?', res.data.detail || 'This discards work.', 'Continue')) return null;
      return putVoiceSource(source, true);
    }
    if (!res.ok) { A.err('#err-script', A.why(res)); return null; }
    S().context.voice_source = res.data.voice_source;
    return res.data;
  }

  async function genScript() {
    const idea = qs('gen-idea').value.trim();
    if (!idea) { A.err('#err-script', 'Say what the script is about.'); return; }
    A.err('#err-script', '');
    const body = { idea_title: idea, target_duration_seconds: parseInt(qs('gen-dur').value, 10), run_id: S().run.id };
    const points = (S().context && S().context.supporting_points) || [];
    if (points.length) body.supporting_points = points;
    qs('gen-btn').disabled = true;
    const stop = A.progress('#job-gen', 'Writing the script…');
    const res = await H.call('/platform/blocks/idea-to-script', 'POST', body);
    stop();
    qs('gen-btn').disabled = false;
    if (!res.ok) { A.failure('#job-gen', 'The script was not written.', A.why(res), genScript); return; }
    qs('script').value = res.data.script || '';
    A.onScript();
    A.paintRun();
    paintScriptSource();
    H.toast(`Script written in ${res.data.iterations} round${res.data.iterations === 1 ? '' : 's'}.`);
  }

  // ── Uploaded voiceover and its transcript ─────────────────────────────────

  async function uploadVo(input, confirmed) {
    const file = input.files && input.files[0];
    if (!file) return;
    A.err('#err-script', '');
    const form = new FormData(); form.append('file', file);
    const stop = A.progress('#job-up', `Uploading ${file.name}…`);
    const res = await A.api(`/platform/studio/runs/${rid()}/voice/upload${confirmed ? '?confirm_discard=true' : ''}`, { method: 'POST', form });
    stop();
    if (res.status === 409 && res.data.needs_confirmation && !confirmed) {
      if (await A.confirmBox('Replace the voiceover?', res.data.detail || 'The storyboard and its assets are discarded.', 'Replace')) return uploadVo(input, true);
      input.value = ''; return;
    }
    input.value = '';
    if (!res.ok) { A.failure('#job-up', 'The upload was not accepted.', A.why(res)); return; }
    await waitTranscript();
  }

  async function waitTranscript() {
    const stop = A.progress('#job-up', 'Transcribing the voiceover…');
    const st = await A.poll(A.runUrl('/voice/status'), 2000, 150);
    stop();
    if (st.status === 'error') { A.failure('#job-up', 'Transcription failed.', st.error || 'The service did not answer.'); return; }
    await loadTranscript();
    S().context.voice_source = 'uploaded';
    // The storyboard built on the earlier voice is gone server-side; reload what the run now has.
    await A.openRun(S().run.id);
    CR.src = 'upload';
    A.paintRun();
  }

  /** Read the transcript of an uploaded run and make it the run's script and voice. */
  async function loadTranscript() {
    const res = await A.api(A.runUrl('/transcript'));
    if (!res.ok || !res.data.words || !res.data.words.length) { S().upload = null; return false; }
    const d = res.data;
    S().upload = d;
    qs('script').value = d.text || '';
    S().voice = { total_duration_s: d.total_duration_s, mp3_url: d.audio_url, alignment_method: 'uploaded', word_count: d.words.length };
    S().audio = null;
    paintTranscript();
    return true;
  }

  function paintTranscript() {
    const d = S().upload, box = qs('tr-box');
    if (!d) { box.innerHTML = ''; qs('tr-warn').className = 'job warn'; return; }
    const editable = !!d.editable;
    box.innerHTML = `<audio id="tr-audio" controls ${d.audio_url ? `src="${esc(d.audio_url)}"` : ''} style="width:100%;margin-bottom:8px"></audio>
      <p class="meta" style="margin:0 0 8px">${d.words.length} words · ${(d.total_duration_s || 0).toFixed(1)} s. Click a word to hear it${editable ? '; shift-click to select several to edit' : ''}.</p>
      <div class="core-tr-words" id="tr-words">${d.words.map(w => `<span class="core-tr-word" data-i="${w.i}" onclick="CoreRun.trWord(event,${w.i})">${esc(w.word)}</span>`).join(' ')}</div>
      ${editable ? `<div class="m-line" style="margin-top:10px"><input type="text" id="tr-edit" placeholder="Click a word, then type what is actually said" disabled onkeydown="if(event.key==='Enter')CoreRun.trApply()">
        <button class="btn sm" id="tr-apply" onclick="CoreRun.trApply()" disabled>Apply</button></div><div class="meta" id="tr-note"></div>
        <details style="margin-top:12px"><summary style="cursor:pointer;font-size:13px;font-weight:600">Rebuild from text</summary>
          <p class="meta" style="margin:8px 0">Paste the corrected transcript. It is accepted only if it maps onto the spoken words.</p>
          <textarea id="tr-text" rows="5" style="min-height:100px">${esc(d.text || '')}</textarea>
          <div style="display:flex;gap:8px;margin-top:8px"><button class="btn sm" onclick="CoreRun.trRebuild(true)">Check</button><button class="btn sm accent" onclick="CoreRun.trRebuild(false)">Apply text</button></div>
          <div class="meta" id="tr-msg"></div></details>`
        : '<p class="meta" style="margin-top:10px">The storyboard exists, so the words are locked. To change them, upload the voiceover again — that discards the storyboard, its assets and scene edits.</p>'}`;
    CR.audioEl = qs('tr-audio');
    CR.audioEl.addEventListener('timeupdate', () => {
      const ms = CR.audioEl.currentTime * 1000;
      const cur = (S().upload.words.find(w => ms >= w.start_ms && ms < w.end_ms) || {}).i;
      document.querySelectorAll('#tr-words .core-tr-word').forEach(el => el.classList.toggle('playing', +el.dataset.i === cur));
    });
    paintLangWarning(d.language_warning, d.language);
  }

  function paintLangWarning(w, language) {
    const el = qs('tr-warn');
    if (!w || w.acknowledged) { el.className = 'job warn'; el.innerHTML = ''; return; }
    const guess = w.detected ? ` It looks like <b>${esc(w.detected)}</b>.` : '';
    el.className = 'job warn on';
    el.innerHTML = `<span>This audio may not be in <b>${esc(language)}</b> — ${esc(w.reason)}.${guess}</span>
      <button class="btn sm" onclick="CoreRun.setLanguage('${esc(language)}')">Keep ${esc(language)}</button>
      <select id="warn-lang" class="inline">${['en', 'ru'].map(l => `<option value="${l}"${l === (w.detected || language) ? ' selected' : ''}>${l}</option>`).join('')}</select>
      <button class="btn sm" onclick="CoreRun.setLanguage(document.getElementById('warn-lang').value)">Change language</button>`;
  }

  function trWord(event, i) {
    const d = S().upload, w = d.words[i];
    if (CR.audioEl) CR.audioEl.currentTime = w.start_ms / 1000;
    if (!d.editable) return;
    CR.sel = event.shiftKey && CR.sel ? { a: Math.min(CR.sel.a, i), b: Math.max(CR.sel.a, i) } : { a: i, b: i };
    document.querySelectorAll('#tr-words .core-tr-word').forEach(el => { const k = +el.dataset.i; el.classList.toggle('sel', k >= CR.sel.a && k <= CR.sel.b); });
    const input = qs('tr-edit');
    input.disabled = false; qs('tr-apply').disabled = false;
    input.value = d.words.slice(CR.sel.a, CR.sel.b + 1).map(x => x.word).join(' ');
    qs('tr-note').textContent = CR.sel.a === CR.sel.b ? `Word ${CR.sel.a + 1}` : `Words ${CR.sel.a + 1}–${CR.sel.b + 1}`;
    input.focus(); input.select();
  }
  async function patchTranscript(body) {
    A.err('#err-script', '');
    const res = await A.api(A.runUrl('/transcript'), { method: 'PATCH', body });
    if (!res.ok) { A.err('#err-script', A.why(res)); return null; }
    return res.data;
  }
  async function trApply() {
    if (!CR.sel) return;
    const data = await patchTranscript({ edits: [{ start: CR.sel.a, end: CR.sel.b, text: qs('tr-edit').value }] });
    if (data) { CR.sel = null; await loadTranscript(); A.paintRun(); }
  }
  async function trRebuild(dry) {
    const data = await patchTranscript({ text: qs('tr-text').value, dry_run: dry });
    if (!data) return;
    const lines = (data.changes || []).join('; ') || 'nothing';
    if (dry) { qs('tr-msg').textContent = `This changes: ${lines}.`; return; }
    await loadTranscript(); A.paintRun();
    const m = qs('tr-msg'); if (m) m.textContent = `Applied: ${lines}.`;
  }
  async function setLanguage(language) {
    const res = await H.call(`/platform/studio/runs/${rid()}/language`, 'PUT', { language });
    if (!res.ok) { A.err('#err-script', A.why(res)); return; }
    S().run.language = res.data.language;
    if (S().context) S().context.language = res.data.language;
    qs('tr-warn').className = 'job warn';
    if (res.data.transcript_stale) H.toast(`Language set to ${res.data.language} — upload the voiceover again to transcribe it in ${res.data.language}.`);
    A.paintRun();
    if (S().right === 'settings') A.paintRight();
  }

  // ── Voice ─────────────────────────────────────────────────────────────────

  function paintVoiceExtras() {
    const up = !BASIC && uploadedVoice() && !!S().upload;
    qs('nar-pace').value = S().settings.narration_pace || 'normal';
    qs('nar-style').value = S().settings.narration_style || 'educational';
    qs('nar-row').classList.toggle('hidden', up);
    qs('voice-pick').closest('.field').classList.toggle('hidden', up);
    if (!BASIC) qs('vo-uploaded-note').classList.toggle('hidden', !up);
    if (up && !S().busy.voice) {
      const gen = qs('vo-gen');
      gen.textContent = 'Replace with a generated voice';
      gen.className = 'btn quiet';
      gen.disabled = !A.scriptOk();
      qs('vo-next').disabled = false;
    }
  }
  async function saveNarration() {
    S().settings.narration_pace = qs('nar-pace').value;
    S().settings.narration_style = qs('nar-style').value;
    await A.saveSettings({ narration_pace: S().settings.narration_pace, narration_style: S().settings.narration_style });
  }

  // ── Storyboard: stock footage ─────────────────────────────────────────────

  function acquirePlan() {
    const scenes = A.sbScenes(), man = S().manifest;
    const strat = s => s.effective_asset_strategy || s.asset_strategy || (s.asset_tier === 'video' ? 'stock_video' : 'stock_image');
    const operatorFilled = s => ['upload', 'ai_image'].includes(strat(s));
    const stockAcquired = scenes.some(s => A.hasAsset(s) && !['operator_upload', 'ai_generated'].includes((man[String(s.scene)] || {}).source));
    const missing = scenes.filter(s => !A.hasAsset(s) && !operatorFilled(s));
    const awaiting = scenes.filter(s => !A.hasAsset(s) && operatorFilled(s));
    if (!stockAcquired) return { label: 'Acquire footage', onlyMissing: true, missing, awaiting, stockAcquired };
    if (missing.length) return { label: `Acquire ${missing.length} missing`, onlyMissing: true, missing, awaiting, stockAcquired };
    return { label: 'Re-acquire all', onlyMissing: false, missing, awaiting, stockAcquired };
  }

  async function acquire() {
    if (CR.acquiring) return;
    const plan = acquirePlan();
    if (!plan.onlyMissing && !await A.confirmBox('Acquire every scene again?', 'Footage you chose is replaced by a new search. Your uploads and generated images are kept.', 'Re-acquire all')) return;
    CR.acquiring = true;
    A.err('#err-sb', '');
    paintStoryboardExtras();
    const stop = A.progress('#job-sb', 'Finding footage…');
    const poll = setInterval(async () => { await A.refreshManifest(); A.paintStoryboard(); }, 3000);
    const res = await H.call('/platform/workers/acquisition', 'POST', { run_id: S().run.id, only_missing: plan.onlyMissing });
    clearInterval(poll); stop();
    CR.acquiring = false;
    if (!res.ok) { A.failure('#job-sb', 'Footage was not acquired.', A.why(res), acquire); paintStoryboardExtras(); return; }
    await A.reloadStoryboard();
    const m = res.data;
    const waiting = m.awaiting_upload ? `, ${m.awaiting_upload} waiting for your upload or image` : '';
    H.toast(`${m.acquired} found, ${m.failed} failed${waiting}.`);
    A.paintRun();
  }

  function sceneExtra(scene) {
    const id = esc(String(scene.scene));
    const strategy = scene.effective_asset_strategy || scene.asset_strategy || 'stock_image';
    const sfx = S().cfg.sfx_enabled && CR.cfgSfx.length ? `<label class="field"><span class="lbl">Sound effect</span><select onchange="CoreRun.patchSceneField('${id}',{sfx:this.value})">
        <option value="">None</option>${CR.cfgSfx.map(o => `<option value="${esc(o.key)}"${scene.sfx === o.key ? ' selected' : ''}>${esc(o.display_name)}</option>`).join('')}</select></label>` : '';
    return `<div class="core-extra row3" style="margin-top:12px;grid-column:1/-1">
      <label class="field"><span class="lbl">Asset type</span><select onchange="CoreRun.patchSceneField('${id}',{asset_strategy:this.value},true)">
        ${STRATEGIES.map(([k, l]) => `<option value="${k}"${k === strategy ? ' selected' : ''}>${l}</option>`).join('')}</select></label>
      <label class="field wide"><span class="lbl">Search words for stock footage</span>
        <div class="m-line"><input type="text" id="stk-${id}" maxlength="120" value="${esc(scene.primary_stk || '')}" placeholder="search words" onchange="CoreRun.patchSceneField('${id}',{primary_stk:this.value.trim()||undefined})">
        <button class="btn sm" onclick="CoreRun.reacquireScene('${id}', this)">Find again</button></div></label>
      <label class="field"><span class="lbl">Your own file</span>
        <input type="file" accept="video/mp4,video/webm,image/jpeg,image/png,image/webp" onchange="CoreRun.uploadSceneFile('${id}', this)"></label>
      ${sfx}</div>`;
  }

  /** Add the stock controls to the scene that is open, and show or hide the toolbar. */
  function paintStoryboardExtras() {
    const stock = isStock() && !!S().sb;
    qs('sb-super').classList.toggle('hidden', !S().sb);
    qs('sb-acquire').classList.toggle('hidden', !stock);
    qs('sb-assets').classList.toggle('hidden', stock);
    qs('ct-link').classList.toggle('hidden', stock || !S().sb);
    if (stock) {
      const plan = acquirePlan(), busy = CR.acquiring || S().busy.sb;
      const b = qs('sb-acquire');
      b.textContent = CR.acquiring ? 'Acquiring…' : plan.label;
      b.disabled = busy || !S().sb || S().sbStale || A.sbScenes().length === 0;
      b.className = 'btn ' + (plan.stockAcquired && !plan.missing.length ? 'quiet' : 'accent');
      qs('sb-acq-meta').textContent = plan.awaiting.length ? `${plan.awaiting.length} scene${plan.awaiting.length === 1 ? '' : 's'} wait for an upload or an AI image` : '';
    }
    // Script view text, unless the user is editing it.
    const tx = qs('sv-text');
    if (tx && document.activeElement !== tx) { tx.value = A.sbScenes().map(s => s.voiceover_line || '').join('\n\n'); svInput(); }
    // Stock controls inside the open scene.
    const open = S().openScene;
    document.querySelectorAll('.sc-detail .core-extra').forEach(n => n.remove());
    if (open && stock) {
      const scene = A.sbScenes().find(s => String(s.scene) === open);
      const detail = document.querySelector(`.sc[data-scene="${CSS.escape(open)}"] .sc-detail .row3`);
      if (scene && detail) detail.insertAdjacentHTML('beforeend', sceneExtra(scene));
    }
  }

  async function patchSceneField(id, fields, reload) {
    const ok = await A.patchScene(id, fields);
    if (ok && reload) A.paintRun();
  }
  async function reacquireScene(id, btn) {
    const q = qs(`stk-${id}`).value.trim();
    if (!q) { A.err('#err-sb', 'Write some search words first.'); return; }
    A.err('#err-sb', '');
    btn.disabled = true; btn.textContent = 'Searching…';
    const res = await H.call(`/platform/studio/runs/${rid()}/scenes/${encodeURIComponent(id)}/reacquire`, 'POST', { query: q });
    btn.disabled = false; btn.textContent = 'Find again';
    if (!res.ok) { A.err('#err-sb', `Nothing was found: ${A.why(res)}`); return; }
    await A.reloadStoryboard();
  }
  async function uploadSceneFile(id, input) {
    const file = input.files && input.files[0];
    if (!file) return;
    const form = new FormData(); form.append('file', file);
    A.err('#err-sb', '');
    const res = await A.api(A.runUrl(`/scenes/${encodeURIComponent(id)}/upload`), { method: 'POST', form });
    input.value = '';
    if (!res.ok) { A.err('#err-sb', `Not uploaded: ${A.why(res)}`); return; }
    await A.reloadStoryboard();
    A.paintRun();
  }

  // Script view: move scene boundaries as text.
  const paragraphs = t => t.trim().split(/\n\s*\n/).map(p => p.trim().split(/\s+/).filter(Boolean)).filter(p => p.length);
  function svInput() {
    const ta = qs('sv-text'), btn = qs('sv-apply'), msg = qs('sv-msg');
    if (!ta) return;
    const scenes = A.sbScenes();
    const typed = paragraphs(ta.value);
    const original = scenes.map(s => (s.voiceover_line || '').trim().split(/\s+/).filter(Boolean).join(' ')).join('\n');
    const same = typed.map(p => p.join(' ')).join('\n') === original;
    msg.textContent = same ? `${scenes.length} scenes — no boundary changes` : `${scenes.length} scenes → ${typed.length}`;
    btn.disabled = same;
  }
  async function svApply() {
    const text = qs('sv-text').value;
    const url = A.runUrl('/storyboard/boundaries');
    const prev = await A.api(url, { method: 'PUT', body: { script_text: text, dry_run: true } });
    if (!prev.ok) { A.err('#err-sb', A.why(prev)); return; }
    if (!await A.confirmBox('Apply these scene boundaries?', `${prev.data.summary}.`, 'Apply')) return;
    const res = await A.api(url, { method: 'PUT', body: { script_text: text } });
    if (!res.ok) { A.err('#err-sb', A.why(res)); return; }
    S().sb = res.data; S().openScene = null;
    await A.refreshManifest();
    A.paintRun();
  }

  // ── Render: CapCut ────────────────────────────────────────────────────────

  async function ccExport(btn) {
    const label = btn.textContent;
    btn.disabled = true; btn.textContent = 'Preparing the zip…';
    qs('cc-msg').textContent = '';
    try {
      const cap = S().settings.subtitles === 'none' || !S().settings.subtitles ? 'none' : S().settings.caption_style === 'punch' ? 'punch' : 'standard';
      const q = new URLSearchParams({
        format_track: S().run.format === '16:9' ? 'landscape' : 'portrait', captions: String(cap !== 'none'),
        caption_style: cap === 'punch' ? 'punch' : 'standard', music_enabled: String(!!S().musicKey),
      });
      const r = await fetch(`${A.runUrl('/export/capcut')}?${q}`);
      if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || `Error ${r.status}`); }
      const url = URL.createObjectURL(await r.blob());
      const a = document.createElement('a');
      a.href = url; a.download = `capcut_${S().run.id.slice(0, 8)}.zip`;
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
    } catch (e) { qs('cc-msg').textContent = `The package was not made: ${e.message}`; }
    finally { btn.disabled = false; btn.textContent = label; }
  }
  async function ccUpload(input, confirmed) {
    const file = input.files && input.files[0];
    if (!file) return;
    const btn = qs('cc-up'), label = btn.textContent;
    btn.disabled = true; btn.textContent = 'Uploading…';
    qs('cc-msg').textContent = '';
    const form = new FormData(); form.append('file', file);
    const res = await A.api(`${A.runUrl('/output/upload')}${confirmed ? '?confirm_overwrite=true' : ''}`, { method: 'POST', form });
    btn.disabled = false; btn.textContent = label;
    if (res.status === 409 && !confirmed) {
      if (await A.confirmBox('Replace the video?', res.data.detail || 'This video already has a render.', 'Replace')) return ccUpload(input, true);
      input.value = ''; return;
    }
    input.value = '';
    if (!res.ok) { qs('cc-msg').textContent = `Not uploaded: ${A.why(res)}`; return; }
    S().video = res.data;
    A.paintRun();
    qs('cc-msg').textContent = 'Uploaded. This is now the video.';
  }

  // ── Metadata ──────────────────────────────────────────────────────────────

  function paintMeta() {
    const m = S().meta, out = qs('meta-out');
    qs('meta-gen').textContent = m ? 'Generate again' : 'Generate metadata';
    qs('meta-gen').className = 'btn ' + (m ? 'quiet' : 'accent');
    if (!m) { out.innerHTML = '<div class="sb-empty">No metadata yet. Generate it once the script is final.</div>'; return; }
    const copy = id => `<button class="btn sm" onclick="CoreRun.copy('${id}')">Copy</button>`;
    out.innerHTML = `<div class="core-meta-out">
      <label class="field"><span class="lbl">Title</span><div class="m-line"><input type="text" id="meta-title" value="${esc(m.title || '')}">${copy('meta-title')}</div></label>
      <label class="field"><span class="lbl">Description</span><textarea id="meta-desc" rows="5">${esc(m.description || '')}</textarea><div style="margin-top:6px">${copy('meta-desc')}</div></label>
      <label class="field"><span class="lbl">Tags</span><div class="m-line"><input type="text" id="meta-tags" value="${esc((m.tags || []).join(', '))}">${copy('meta-tags')}</div></label></div>`;
  }
  async function copy(id) {
    const el = qs(id);
    try { await navigator.clipboard.writeText(el.value); H.toast('Copied.'); } catch { el.select(); H.toast('Press Ctrl+C to copy.'); }
  }
  async function genMeta() {
    A.err('#err-meta', '');
    qs('meta-gen').disabled = true;
    const stop = A.progress('#job-meta', 'Writing the metadata…');
    const res = await H.call('/platform/workers/metadata', 'POST', { run_id: S().run.id });
    stop();
    qs('meta-gen').disabled = false;
    if (!res.ok) { A.failure('#job-meta', 'Metadata was not written.', A.why(res), genMeta); return; }
    S().meta = res.data;
    A.paintRun();
  }

  // ── Run settings (right panel): look, language, cast ──────────────────────

  /** The video settings, in one order: Auto-advance, Format, Look, Language, Master style, Cast. */
  function paintSettingsExtras() {
    const auto = qs('core-auto'), top = qs('core-top'), castBox = qs('core-cast');
    if (!auto || !top || !castBox || !S().run) return;
    const stock = isStock(), locked = !!S().sb, voiced = !!S().voice;
    auto.innerHTML = `<div class="set-row"><div class="k">Auto-advance</div>
      <div class="seg" id="auto-seg"><button class="${CR.auto ? '' : 'on'}" onclick="CoreRun.setAuto(false)">Off</button><button class="${CR.auto ? 'on' : ''}" onclick="CoreRun.setAuto(true)">On</button></div></div>`;
    top.innerHTML = `<div class="set-row"><div class="k">Look</div>
        <div class="seg" id="set-look"><button class="${stock ? 'on' : ''}" onclick="CoreRun.setLook('realistic')">Realistic</button><button class="${stock ? '' : 'on'}" onclick="CoreRun.setLook('animated')">Animated</button></div></div>
      <div class="set-row"><div class="k">Language</div>
        <select ${voiced ? 'disabled title="Fixed once the voiceover exists"' : ''} onchange="CoreRun.setLanguage(this.value)">${Object.entries(H.LANGS).map(([k, v]) => `<option value="${k}"${k === S().run.language ? ' selected' : ''}>${esc(v)}</option>`).join('')}</select></div>`;
    if (stock) { castBox.innerHTML = ''; return; }

    const listed = S().settings.characters || [];
    const custom = CR.castCustom != null ? CR.castCustom : (S().settings.cast_mode || 'free') !== 'free';
    const fixed = locked;   // the storyboard already uses the cast; characters are added in its dialog
    const items = listed.map((c, i) => `<div class="cast-item"><input type="text" maxlength="80" value="${esc(c.name)}" placeholder="Name" ${fixed ? 'disabled' : ''} onchange="CoreRun.castSave()">
        <textarea maxlength="2400" placeholder="Age, hair, clothes — every detail that must stay the same" ${fixed ? 'disabled' : ''} onchange="CoreRun.castSave()">${esc(c.description)}</textarea>
        ${fixed ? '' : `<button class="icon-btn cast-x" onclick="CoreRun.castRemove(this)" title="Remove" aria-label="Remove character"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg></button>`}</div>`).join('');
    const max = (S().cfg && S().cfg.max_characters) || 6;
    castBox.innerHTML = `<div class="set-row"><div class="k">Cast</div>
        <div class="seg" id="set-cast"><button class="${custom ? '' : 'on'}" onclick="CoreRun.setCast('free')">AI Director</button><button class="${custom ? 'on' : ''}" onclick="CoreRun.setCast('custom')">Custom</button></div></div>
      ${custom ? `<div id="cast-list">${items}</div>
        ${fixed || listed.length >= max ? '' : `<div class="cast-links"><button class="link" onclick="CoreRun.castAdd()">+ Add a character</button><button class="link" onclick="CoreRun.castLibrary()">Select from library</button></div>
        <div class="gen-box" id="cast-lib" style="margin-top:10px"></div>`}` : ''}`;
  }
  async function setLook(look) {
    const stock = isStock();
    if ((look === 'realistic') === stock) return;
    const next = { look, image_source: look === 'realistic' ? 'stock' : 'ai' };
    let confirmReset = false;
    for (;;) {
      const res = await H.call(`/platform/studio/runs/${rid()}/visuals`, 'PUT', { ...next, confirm_reset: confirmReset });
      if (res.status === 409 && res.data.needs_confirmation && !confirmReset) {
        if (!await A.confirmBox('Change the look?', res.data.detail || 'This discards the storyboard.', 'Change and discard')) { paintSettingsExtras(); return; }
        confirmReset = true; continue;
      }
      if (!res.ok) { A.err('#err-script', A.why(res)); paintSettingsExtras(); return; }
      break;
    }
    await A.openRun(S().run.id);
    A.paintRun();
  }
  /** AI Director: the model invents the characters. Custom: only the characters listed in the panel. */
  async function setCast(mode) {
    CR.castCustom = mode === 'custom';
    if (mode === 'free') {
      S().settings.cast_mode = 'free';
      await A.saveSettings({ cast_mode: 'free' });
    }
    paintSettingsExtras();
  }
  /** Save the characters shown in the panel; a half-filled row is skipped, none left means AI Director. */
  async function castSave() {
    const rows = [...document.querySelectorAll('#cast-list .cast-item')];
    const characters = rows.map(r => ({ name: r.querySelector('input').value.trim(), description: r.querySelector('textarea').value.trim() }))
      .filter(c => c.name && c.description);
    const patch = { characters, cast_mode: characters.length ? 'listed' : 'free' };
    const res = await A.saveSettings(patch);
    if (!res.ok) { H.toast(`Not saved: ${A.why(res)}`); return; }
    CR.castCustom = true;
    paintSettingsExtras();
  }
  function castAdd() {
    const list = qs('cast-list');
    if (!list) return;
    list.insertAdjacentHTML('beforeend', `<div class="cast-item"><input type="text" maxlength="80" placeholder="Name" onchange="CoreRun.castSave()">
      <textarea maxlength="2400" placeholder="Age, hair, clothes — every detail that must stay the same" onchange="CoreRun.castSave()"></textarea>
      <button class="icon-btn cast-x" onclick="CoreRun.castRemove(this)" title="Remove" aria-label="Remove character"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg></button></div>`);
    list.lastElementChild.querySelector('input').focus();
  }
  /** Remove a character row (saved or not yet) and save what is left. */
  async function castRemove(btn) {
    btn.closest('.cast-item').remove();
    await castSave();
  }
  /** Show the AI assets library's characters; picking one adds it to this video's cast. */
  async function castLibrary() {
    const box = qs('cast-lib');
    if (!box || box.classList.toggle('on') === false) return;
    box.innerHTML = '<p class="meta">Loading…</p>';
    const res = await H.call('/platform/creator/assets');
    if (!res.ok) { box.innerHTML = `<p class="meta">${esc(A.why(res))}</p>`; return; }
    CR.libChars = res.data.items.filter(a => a.kind === 'character');
    box.innerHTML = CR.libChars.length
      ? CR.libChars.map((a, i) => `<button class="as-card" style="display:block;width:100%;text-align:left" onclick="CoreRun.castPick(${i})"><span class="n">${esc(a.name)}</span><p>${esc(a.description)}</p></button>`).join('')
      : '<p class="meta">No characters in the library yet.</p>';
  }
  async function castPick(i) {
    const a = (CR.libChars || [])[i];
    if (!a) return;
    const cur = S().settings.characters || [];
    if (cur.some(c => c.name.toLowerCase() === a.name.toLowerCase())) return;
    const next = [...cur, { name: a.name, description: a.description }];
    const res = await A.saveSettings({ characters: next, cast_mode: 'listed' });
    if (!res.ok) { H.toast(`Not saved: ${A.why(res)}`); return; }
    CR.castCustom = true;
    paintSettingsExtras();
  }
  async function saveToLibrary() {
    const id = S().entryId, msg = qs('e-msg');
    if (!id) { msg.textContent = 'Save it first, then add it to the project assets.'; return; }
    const res = await H.call(`/platform/projects/${encodeURIComponent(projectId())}/assets/from-run`, 'POST', { run_id: S().run.id, entry_id: id });
    msg.textContent = res.ok ? 'Saved to the project assets. Other videos in the project can use it.' : `Not saved: ${A.why(res)}`;
  }

  // ── Auto-advance ──────────────────────────────────────────────────────────

  function toggleAuto() { setAuto(!CR.auto); }
  function setAuto(on) {
    CR.auto = !!on;
    paintAuto();
    paintSettingsExtras();
    if (CR.auto) autoStep();
  }
  function paintAuto() {
    const flag = qs('auto-flag');
    if (flag) flag.classList.toggle('hidden', !CR.auto);
    if (S().right === 'settings' && S().run) paintSettingsExtras();
  }
  /** Start the next step that is ready. Stops at anything that costs money and asks (generated images) or fails. */
  function autoStep() {
    if (!CR.auto || CR.autoBusy || !S().run) return;
    const st = S();
    const busy = st.busy.voice || st.busy.sb || st.busy.images || st.busy.render || CR.acquiring;
    if (busy) return;
    // The step that is ready next, by name. Asking for the same one twice in a row means the last
    // attempt made no progress (it failed), so Auto-advance stops there instead of retrying forever.
    let name = null;
    if (!A.scriptOk() && !(uploadedVoice() && st.upload)) name = 'script';
    else if (!st.voice) name = 'voice';
    else if (!st.sb || st.sbStale) name = 'storyboard';
    else if (!A.allAssets()) name = isStock() ? 'footage' : 'images';
    else if (!st.video) name = 'render';
    else if (!st.meta) name = 'metadata';
    const stop = why => { CR.auto = false; CR.lastStep = null; paintAuto(); if (why) H.toast(why); };
    if (!name) return stop();
    if (name === 'script') return stop('Auto-advance needs the script first.');
    if (name === 'images') { stop(); A.planAssets(); return; }   // image generation always asks first
    if (CR.lastStep === name) return stop(`Auto-advance stopped: the ${name} step did not finish.`);
    CR.lastStep = name;
    CR.autoBusy = true;
    setTimeout(async () => {
      try {
        if (name === 'voice') await A.genVoice();
        else if (name === 'storyboard') await A.createSb();
        else if (name === 'footage') await acquire();
        else if (name === 'render') await A.renderVideo();
        else if (name === 'metadata') { await genMeta(); stop(); }
      } finally { CR.autoBusy = false; }
    }, 300);
  }

  // ── Host hooks ────────────────────────────────────────────────────────────

  function afterPaint() {
    if (!started || !S().run) return;
    paintScriptSource();
    paintVoiceExtras();
    if (BASIC) return;
    paintStoryboardExtras();
    paintMeta();
    paintAuto();
    if (S().step === 4 && !S().meta) { /* the step shows its own empty state */ }
    if (S().right === 'settings') paintSettingsExtras();
    autoStep();
  }
  function afterStoryboard() { if (started && !BASIC && S().run) paintStoryboardExtras(); }
  function afterSettings() { if (started && !BASIC && S().run) paintSettingsExtras(); }

  async function onRunOpened() {
    if (!started || BASIC) return;
    CR.src = null; CR.sel = null; CR.castCustom = null; S().upload = null;
    const st = S();
    const tasks = [];
    if (uploadedVoice()) tasks.push(loadTranscript());
    tasks.push(H.call(`/platform/studio/runs/${rid()}/metadata`).then(r => { if (r.ok && r.data && r.data.title) st.meta = r.data; }));
    if (st.cfg.sfx_enabled && !CR.cfgSfx.length) tasks.push(H.call('/platform/studio/sfx-library').then(r => { if (r.ok) CR.cfgSfx = r.data; }));
    await Promise.all(tasks);
  }

  // New video: project, look, defaults from the project.
  async function onNew(projectIdFromHash) {
    if (!started || BASIC) return;
    const nr = H.getNewRun();
    if (projectIdFromHash && nr.projectId !== decodeURIComponent(projectIdFromHash)) H.setNewRun({ projectId: decodeURIComponent(projectIdFromHash), itemIds: [], title: '', brief: '' });
    else if (!projectIdFromHash) H.setNewRun({ projectId: '', itemIds: [], title: '', brief: '' });
    const cur = H.getNewRun();
    const [pr, tenant] = await Promise.all([H.call('/platform/projects'), H.tenantDefaults()]);
    const projects = pr.ok ? pr.data : [];
    if (!qs('new-project')) {
      qs('new-title').closest('.field').insertAdjacentHTML('beforebegin', `<label class="field" id="new-project-f"><span class="lbl">Project</span><select id="new-project" style="max-width:360px" onchange="CoreRun.onProjectPick()"></select></label>`);
      const look = qs('new-look');
      look.querySelectorAll('button').forEach(b => { b.disabled = false; const soon = b.querySelector('.soon'); if (soon) soon.remove(); b.removeAttribute('title'); });
      look.querySelectorAll('button').forEach(b => b.addEventListener('click', () => { look.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b)); paintNewLook(); }));
      qs('new-create').onclick = createRun;
      const lock = document.querySelector('#s-new > p.meta:last-child');
      if (lock) lock.textContent = 'The video belongs to the project you choose; format, look and language are chosen now.';
    }
    const sel = qs('new-project');
    const current = cur.projectId || S().cfg.project_id;
    sel.innerHTML = projects.map(p => `<option value="${esc(p.project_id)}"${p.project_id === current ? ' selected' : ''}>${esc(p.name)}</option>`).join('')
      + (projects.some(p => p.project_id === current) ? '' : `<option value="${esc(current)}" selected>${esc(S().cfg.project_name || 'My videos')}</option>`);
    CR.projects = projects;
    qs('new-title').value = cur.title || '';
    onProjectPick(true);
    paintNewLook();
    const ideas = cur.itemIds.length;
    const note = qs('new-ideas-note') || (() => { const n = document.createElement('p'); n.id = 'new-ideas-note'; n.className = 'meta'; n.style.margin = '-12px 0 18px'; qs('new-title').closest('.field').after(n); return n; })();
    note.textContent = ideas ? `Made from ${ideas} idea${ideas === 1 ? '' : 's'} of the project.` : '';
  }
  /** Take language and format from the chosen project, else from the Defaults. */
  async function onProjectPick(keepTitle) {
    const t = await H.tenantDefaults();
    const p = (CR.projects || []).find(x => x.project_id === qs('new-project').value);
    const cfg = (p && p.config) || {}, rd = cfg.run_defaults || {};
    qs('new-lang').value = cfg.language || t.language || 'en';
    const fmt = rd.aspect_ratio || t.format || '9:16';
    document.querySelectorAll('#new-ar button').forEach(b => b.classList.toggle('on', b.dataset.v === fmt));
    if (!keepTitle) H.setNewRun({ ...H.getNewRun(), projectId: qs('new-project').value });
  }
  /** The master style and characters belong to the animated look only. */
  function paintNewLook() {
    const realistic = $('#new-look button.on') && $('#new-look button.on').dataset.v === 'realistic';
    qs('new-style').closest('.field').classList.toggle('hidden', realistic);
    qs('new-chars').closest('.field').classList.toggle('hidden', realistic);
  }

  async function createRun() {
    A.err('#new-err', '');
    const title = qs('new-title').value.trim();
    const cur = H.getNewRun();
    if (!title && !cur.itemIds.length) { A.err('#new-err', 'Say what the video is about.'); return; }
    const look = $('#new-look button.on').dataset.v;
    const characters = [];
    if (look === 'animated') {
      for (const row of document.querySelectorAll('#new-chars .char-row')) {
        const name = row.querySelector('input').value.trim(), description = row.querySelector('textarea').value.trim();
        if (!name && !description) continue;
        if (!name || !description) { A.err('#new-err', 'Give every character a name and a description, or remove the row.'); return; }
        characters.push({ name, description });
      }
    }
    const aspect = $('#new-ar button.on').dataset.v, language = qs('new-lang').value, pid = qs('new-project').value;
    const master = qs('new-style').value.trim();
    qs('new-create').disabled = true;
    let res;
    if (cur.itemIds.length) {
      // From ideas: the project's own route links them, then the run's look and cast are written to its settings.
      res = await H.call(`/platform/projects/${encodeURIComponent(pid)}/runs`, 'POST',
        { item_ids: cur.itemIds, title: title || null, brief: (cur.brief || '').trim() || null, language, aspect_ratio: aspect });
      if (res.ok) {
        const patch = look === 'realistic'
          ? { aspect_ratio: aspect, visual_mode: 'stock', look: 'realistic', subtitles: 'none' }
          : { aspect_ratio: aspect, visual_mode: 'ai_animation', look: 'animated', master_style: master, subtitles: 'none',
              cast_mode: characters.length ? 'listed' : 'free', characters };
        const saved = await H.call(`/runs/${encodeURIComponent(res.data.run_id)}/settings`, 'POST', patch);
        if (!saved.ok) { qs('new-create').disabled = false; A.err('#new-err', `The video was created but its settings were not saved: ${A.why(saved)}`); return; }
      }
    } else {
      res = await H.call('/platform/creator/runs', 'POST',
        { title, aspect_ratio: aspect, language, master_style: master, characters, look, project_id: pid });
    }
    qs('new-create').disabled = false;
    if (!res.ok) { A.err('#new-err', A.why(res)); return; }
    H.setNewRun({ projectId: '', itemIds: [], title: '', brief: '' });
    A.go(`#run/${encodeURIComponent(res.data.run_id)}/script`);
  }

  function init(app, core, basic) {
    A = app; H = core.helpers; BASIC = !!basic;
    if (!BASIC) {
      A.addHelp({
        script: ['Script', ['Paste the text the narrator will read, or generate one from an idea with "Generate script with AI".',
          '"Start from a voiceover" uses your own recording; its transcript becomes the script.',
          'The word limit keeps the video to a few minutes.',
          'Auto-advance (in the video settings) runs each step as soon as the one before it finishes. Image generation still asks first, and it stops at anything that fails.',
          'Look and cast, set in the video settings, apply the next time the storyboard is created.',
          'Once the voiceover exists the script is locked: a different script is a different video. Use "Start a new video from this one" in the video settings to change the words.']],
        render: ['Render', ['Choose captions and background music, then render the video.', 'When it is done you can play it here and download it.',
          'Edit in CapCut instead: download the timeline, the media and a CapCut guide as a zip, edit there, and upload the finished video back here.']],
        storyboard: ['Storyboard', ['Create the storyboard, check each scene, then create the images.',
          'Click a scene to change its image prompt, motion or on-screen text. Click the pencil to change its image.',
          'Click a word to split the scene there. "Merge with next" joins two scenes. A new scene has no image prompt: open it and click "Write with the director".',
          'Script view: one paragraph per scene. Move the blank lines to move the boundaries, then apply. Only the blank lines count; the words cannot change there.',
          'Creating images costs money. You see the estimate before anything is made.']],
      });
    }
    mountDom();
    started = true;
    window.CoreRun.afterPaint();   // the page may already be showing a run
  }

  window.CoreRun = {
    init, afterPaint, afterStoryboard, afterSettings, onRunOpened, onNew,
    setSource, genScript, uploadVo, trWord, trApply, trRebuild, setLanguage, saveNarration,
    acquire, patchSceneField, reacquireScene, uploadSceneFile, svInput, svApply,
    ccExport, ccUpload, genMeta, copy, setLook, setCast, castSave, castAdd, castRemove, castLibrary, castPick, saveToLibrary, toggleAuto, setAuto, onProjectPick,
  };
})();
