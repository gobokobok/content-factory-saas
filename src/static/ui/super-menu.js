/*
 * Super's left menu for the Creator pages (P-AUTH S7, D118).
 *
 * Loaded by creator.js only when /auth/me reports an effective Super account, so a Basic
 * user's page never contains it. The links go to the existing pages until P-CORE rebuilds
 * them in this design. The server gates every one of those pages itself (a Basic session is
 * sent back to /create), so hiding the menu is a convenience, not the protection.
 */
(function () {
  const icon = d => `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
  const ITEMS = [
    { label: 'Projects', href: '/', svg: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>' },
    { label: 'Libraries', href: '/library?kind=videos', svg: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M9 4v16"/>' },
    { label: 'Integrations', href: '/settings?tab=integrations', svg: '<path d="M9 7V3m6 4V3M7 7h10v4a5 5 0 0 1-10 0zM12 16v5"/>' },
    { label: 'Defaults', href: '/settings?tab=defaults', svg: '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/>' },
  ];
  /** Fill the (hidden) #super-menu container and return the "Open in Studio" link. */
  function mount(container) {
    const link = (item, extra) => `<a class="nav-btn${extra || ''}" ${item.id ? `id="${item.id}"` : ''} href="${item.href}" style="text-decoration:none">${icon(item.svg)}${item.label}</a>`;
    container.innerHTML = '<div class="menu-label">Studio</div>'
      + ITEMS.map(i => link(i)).join('')
      + link({ id: 'open-studio', label: 'Open in Studio', href: '/studio', svg: '<path d="M14 4h6v6M20 4l-9 9M10 6H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4"/>' }, ' run-only hidden');
    container.classList.remove('hidden');
    return document.getElementById('open-studio');
  }
  window.SuperMenu = { mount };
})();
