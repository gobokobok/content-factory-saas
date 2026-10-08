/* Shell: left panel + breadcrumbs, shared by every page (P-UX build).
 *
 * A page has this skeleton and calls CFShell.mount(...) once:
 *   <body class="cf-body"><div class="cf-shell" id="cf-shell">
 *     <aside class="cf-nav" id="cf-nav"></aside><div class="cf-scrim" onclick="CFShell.closeNav()"></div>
 *     <div class="cf-main"><nav class="cf-crumbs" id="cf-crumbs"></nav> …page… </div></div></body>
 */
(function () {
  const ICON = {
    projects: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    videos: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m10 9 5 3-5 3z"/>',
    audio: '<path d="M4 10v4M8 6v12M12 9v6M16 4v16M20 10v4"/>',
    footage: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m3 16 5-5 4 4 3-3 6 6"/><circle cx="15.5" cy="8.5" r="1.5"/>',
    ai: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M18 6l-2.5 2.5M8.5 15.5 6 18"/>',
    music: '<path d="M9 18V5l11-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/>',
    integrations: '<path d="M9 7V3M15 7V3M6 7h12v4a6 6 0 0 1-12 0zM12 17v4"/>',
    defaults: '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
    fold: '<path d="m14 7-5 5 5 5"/><path d="M19 5v14"/>',
    out: '<path d="M10 5H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h4M15 8l4 4-4 4M19 12H9"/>',
  };
  const LIBS = [['videos', 'Videos'], ['audio', 'Audio'], ['footage', 'Footage'], ['ai', 'AI generations'], ['music', 'Music & SFX']];
  const ico = n => `<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON[n]}</svg>`;
  const esc = v => String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const KEY = 'cf_nav_fold';
  let cfg = { active: '', project: null, projectTab: '', crumbs: [], foldDefault: null, remember: true };

  function read() { try { return localStorage.getItem(KEY); } catch { return null; } }
  function write(v) { try { localStorage.setItem(KEY, v); } catch { /* private mode */ } }

  /** Whether the panel is folded on this page: a page default (the run) overrides the remembered choice. */
  let override = null;
  function folded() {
    if (override !== null) return override;
    if (cfg.foldDefault === 'folded') return true;
    return read() === '1';
  }

  function item(href, icon, label, on, extra) {
    return `<a class="cf-item${on ? ' cf-on' : ''}" href="${href}" title="${esc(label)}">${icon ? ico(icon) : ''}<span class="cf-lbl">${esc(label)}</span>${extra || ''}</a>`;
  }

  function renderNav() {
    const p = cfg.project, a = cfg.active;
    const sub = (tab, label) => {
      const href = `/project?id=${encodeURIComponent(p.id)}${tab === 'overview' ? '' : '&tab=' + tab}`;
      return `<a class="cf-item${cfg.projectTab === tab ? ' cf-on' : ''}" href="${href}"><span class="cf-lbl">${label}</span></a>`;
    };
    document.getElementById('cf-nav').innerHTML = `
      <div class="cf-nav-head">
        <div class="cf-brand-mark" aria-hidden="true"></div>
        <div class="cf-brand-name">CF <span>Studio</span></div>
        <button class="cf-icon-btn cf-fold-btn" onclick="CFShell.toggleFold()" aria-label="Fold or unfold the panel" title="Fold / unfold"><span class="cf-fold-ico" style="display:inline-flex">${ico('fold')}</span></button>
      </div>
      <div class="cf-nav-scroll">
        <div class="cf-group">Projects</div>
        ${item('/', 'projects', 'All projects', a === 'projects')}
        ${p ? `<div class="cf-sub"><a class="cf-item cf-proj" href="/project?id=${encodeURIComponent(p.id)}"><span class="cf-lbl">${esc(p.name)}</span></a>
          ${sub('overview', 'Overview')}${sub('ideas', 'Ideas')}${sub('runs', 'Runs')}${sub('settings', 'Settings')}</div>` : ''}
        <div class="cf-group">Libraries</div>
        ${LIBS.map(([k, l]) => item(`/library?kind=${k}`, k, l, a === 'lib:' + k)).join('')}
        <div class="cf-group">Settings</div>
        ${item('/settings?tab=integrations', 'integrations', 'Integrations', a === 'settings:integrations')}
        ${item('/settings?tab=defaults', 'defaults', 'Defaults', a === 'settings:defaults')}
      </div>
      <div class="cf-nav-foot"><button class="cf-item" onclick="CFShell.logOut()" title="Log out">${ico('out')}<span class="cf-lbl">Log out</span></button></div>`;
  }

  function renderCrumbs() {
    const c = cfg.crumbs;
    const menu = `<button class="cf-icon-btn cf-menu-btn" aria-label="Open navigation" onclick="CFShell.openNav()"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 7h16M4 12h16M4 17h16"/></svg></button>`;
    document.getElementById('cf-crumbs').innerHTML = menu + c.map(([label, href], i) => {
      const last = i === c.length - 1;
      const el = href && !last ? `<a href="${href}">${esc(label)}</a>` : `<span class="${last ? 'cf-here' : ''}">${esc(label)}</span>`;
      return (i ? '<span class="cf-sep">/</span>' : '') + el;
    }).join('');
  }

  function apply() { document.getElementById('cf-shell').classList.toggle('cf-folded', folded()); }

  window.CFShell = {
    /** Draw the panel and breadcrumbs. cfg: {active, project:{id,name}, projectTab, crumbs:[[label,href]], foldDefault}. */
    mount(options) { cfg = { ...cfg, ...options }; renderNav(); renderCrumbs(); apply(); document.body.classList.add('cf-body'); },
    /** Update the breadcrumbs / project once they are known (a page loads them asynchronously). */
    update(options) { cfg = { ...cfg, ...options }; renderNav(); renderCrumbs(); apply(); },
    toggleFold() {
      const next = !folded();
      if (cfg.foldDefault === 'folded') override = next;   // in a run the choice is not remembered
      else write(next ? '1' : '0');
      apply();
    },
    openNav() { document.body.classList.add('cf-nav-open'); },
    closeNav() { document.body.classList.remove('cf-nav-open'); },
    async logOut() { await fetch('/auth/logout', { method: 'POST' }); window.location.href = '/login'; },
  };
  document.addEventListener('keydown', e => { if (e.key === 'Escape') window.CFShell.closeNav(); });
})();
