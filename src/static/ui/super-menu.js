/*
 * Super's left menu for the Creator pages (P-AUTH S7, P-CORE S1; D118).
 *
 * Loaded by creator.js only when /auth/me reports an effective Super account, so a Basic
 * user's page never contains it. Every entry is a screen of this same page (core.js);
 * the server gates the calls those screens make, so hiding the menu is a convenience.
 */
(function () {
  const icon = d => `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
  const ITEMS = [
    { label: 'Projects', href: '#projects', nav: 'projects', svg: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>' },
  ];
  const LIBRARIES = [
    ['videos', 'Videos'], ['audio', 'Audio'], ['footage', 'Footage'], ['ai', 'AI generations'], ['music', 'Music & SFX'],
  ];
  const SETTINGS = [
    { label: 'Integrations', href: '#settings/integrations', nav: 'settings/integrations', svg: '<path d="M9 7V3m6 4V3M7 7h10v4a5 5 0 0 1-10 0zM12 16v5"/>' },
    { label: 'Defaults', href: '#settings/defaults', nav: 'settings/defaults', svg: '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/>' },
  ];
  /** Fill the (hidden) #super-menu container. */
  function mount(container) {
    const link = i => `<a class="nav-btn" data-nav="${i.nav}" href="${i.href}" style="text-decoration:none">${icon(i.svg)}${i.label}</a>`;
    container.innerHTML = '<div class="menu-label">Workspace</div>'
      + ITEMS.map(link).join('')
      + '<div class="menu-label" style="margin-top:12px">Libraries</div>'
      + LIBRARIES.map(([k, l]) => `<a class="nav-btn sm" data-nav="library/${k}" href="#library/${k}" style="text-decoration:none">${icon('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18"/>')}${l}</a>`).join('')
      + '<div class="menu-label" style="margin-top:12px">Settings</div>'
      + SETTINGS.map(link).join('');
    container.classList.remove('hidden');
  }
  window.SuperMenu = { mount };
})();
