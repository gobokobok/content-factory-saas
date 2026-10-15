/*
 * Super's left menu for the Creator pages (P-AUTH S7, P-CORE S1; D118).
 *
 * Loaded by creator.js for every session; a Basic one gets only the Libraries section. Every entry is a screen of this same page (core.js);
 * the server gates the calls those screens make, so hiding the menu is a convenience.
 */
(function () {
  const icon = d => `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
  const LIBRARIES = [['videos', 'Videos', '<rect x="3" y="5" width="14" height="14" rx="2"/><path d="M17 10l4-2v8l-4-2"/>'],
    ['images', 'Images', '<circle cx="12" cy="8" r="3.5"/><path d="M5 20a7 7 0 0 1 14 0"/>'],
    ['assets', 'AI assets', '<circle cx="9" cy="8" r="3"/><path d="M3 19a6 6 0 0 1 12 0"/><path d="M17 5h4M19 3v4M17 13h4M19 11v4"/>'],
    ['music', 'BG music', '<path d="M9 18V5l11-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/>']];
  const SETTINGS = [
    ['settings/integrations', '#settings/integrations', 'Integrations', '<path d="M9 7V3M15 7V3M6 7h12v4a6 6 0 0 1-12 0zM12 17v4"/>'],
    ['settings/defaults', '#settings/defaults', 'Defaults', '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>'],
  ];
  // The owner's own entry: balances, top-ups and usage of every account (P-BILL-1). Not shown to other Super accounts.
  const CREDITS = ['settings/credits', '#settings/credits', 'Credits', '<circle cx="12" cy="12" r="8.5"/><path d="M14.5 9.2c-.5-.8-1.4-1.2-2.5-1.2-1.5 0-2.5.8-2.5 2 0 3 5 1.6 5 4.2 0 1.2-1.1 2-2.5 2-1.1 0-2.1-.4-2.6-1.3M12 6.5V8m0 8v1.5"/>'];
  /** Fill the (hidden) #super-menu container: section headers and entries, one list, nothing pinned.
   *  A Basic session gets only Libraries; a Super session gets Projects, Libraries and Settings. */
  function mount(container, basic, owner) {
    const link = (nav, href, label, svg) => `<a class="nav-btn" data-nav="${nav}" href="${href}" style="text-decoration:none">${icon(svg)}${label}</a>`;
    const libraries = '<div class="sect">Libraries</div>' + LIBRARIES.map(([k, l, svg]) => link('library/' + k, '#library/' + k, l, svg)).join('');
    if (basic) { container.innerHTML = libraries; container.classList.remove('hidden'); return; }
    container.innerHTML = '<div class="sect">Projects</div>'
      + link('projects', '#projects', 'All projects', '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>')
      + '<div id="nav-project"></div>'
      + libraries
      + '<div class="sect">Settings</div>'
      + SETTINGS.concat(owner ? [CREDITS] : []).map(([nav, href, l, svg]) => link(nav, href, l, svg)).join('');
    container.classList.remove('hidden');
  }
  window.SuperMenu = { mount };
})();
