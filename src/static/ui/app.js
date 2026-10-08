/* Helpers shared by the project, library and settings pages (P-UX build). */
const $ = id => document.getElementById(id);
const LANGS = { en: 'English', ru: 'Русский' };
const FORMATS = { '9:16': '9:16 Portrait', '16:9': '16:9 Landscape' };
const CAPTIONS = { standard: 'On — Standard', punch: 'On — Punch', none: 'Off' };
const PACES = { slow: 'Slow — ~145 wpm', normal: 'Normal — ~160 wpm', fast: 'Fast — ~172 wpm' };
const STYLES = { educational: 'Educational', emotional: 'Emotional' };

function esc(v) {
  return String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
function opts(map, value) {
  return Object.entries(map).map(([k, v]) => `<option value="${esc(k)}"${k === value ? ' selected' : ''}>${esc(v)}</option>`).join('');
}
function fmtDate(iso) {
  const d = new Date(iso);
  return isNaN(d) ? '' : d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}
async function api(url, opts) {
  const r = await fetch(url, opts);
  if (r.status === 401) { window.location.href = '/login'; throw new Error('Unauthorized'); }
  return r;
}
async function errorDetail(r) {
  const err = await r.json().catch(() => ({}));
  return typeof err.detail === 'string' ? err.detail : `Error ${r.status}`;
}
const jsonOpts = (method, body) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

function toast(msg) {
  const el = $('toast');
  if (!el) return;
  el.textContent = msg; el.classList.add('on');
  clearTimeout(toast.t); toast.t = setTimeout(() => el.classList.remove('on'), 3200);
}
function showErr(msg) {
  const el = $('error');
  if (!el) return;
  el.textContent = msg || ''; el.style.display = msg ? '' : 'none';
  if (msg) el.scrollIntoView({ block: 'nearest' });
}
function overlay(html, side) {
  $('overlay').innerHTML = `<div class="backdrop${side ? ' side' : ''}" onmousedown="if(event.target===this)closeOverlay()">${html}</div>`;
}
function closeOverlay() { $('overlay').innerHTML = ''; }
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeOverlay(); });

/** Tenant defaults (language, format, captions, spend cap); built-in values when the request fails. */
async function loadTenantDefaults() {
  try {
    const r = await api('/platform/tenant/defaults');
    if (r.ok) return await r.json();
  } catch { /* fall through */ }
  return { language: 'en', format: '9:16', captions: 'standard', spend_cap: 2 };
}

/** What a project sets, in tenant-default vocabulary: language, format, captions (only what it overrides). */
function projectOverrides(project) {
  const c = (project && project.config) || {}, rd = c.run_defaults || {}, out = {};
  if (c.language) out.language = c.language;
  if (rd.aspect_ratio) out.format = rd.aspect_ratio;
  if (rd.subtitles === 'none') out.captions = 'none';
  else if (rd.caption_style) out.captions = rd.caption_style;
  return out;
}
