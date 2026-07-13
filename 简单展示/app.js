const views = [...document.querySelectorAll('.view')];
const breadcrumb = document.getElementById('breadcrumb-current');
const toast = document.querySelector('.toast');
let toastTimer;

function refreshIcons() {
  if (window.lucide) window.lucide.createIcons();
}

function showToast(message) {
  clearTimeout(toastTimer);
  toast.textContent = message;
  toast.classList.add('show');
  toastTimer = setTimeout(() => toast.classList.remove('show'), 1800);
}

function showView(id, updateHash = true) {
  const target = document.getElementById(`view-${id}`) || document.getElementById('view-parsing');
  views.forEach(view => view.classList.toggle('active', view === target));
  document.querySelectorAll('.nav-item').forEach(item => {
    item.classList.toggle('active', item.dataset.view === id);
  });
  breadcrumb.textContent = target.dataset.title;
  if (updateHash) history.replaceState(null, '', `#${id}`);
  document.querySelector('.workspace').scrollIntoView({ block: 'start' });
  window.scrollTo(0, 0);
  refreshIcons();
}

function switchTab(group, tabId) {
  const root = document.querySelector(`[data-tabs="${group}"]`);
  if (!root) return;
  root.querySelectorAll('[data-tab]').forEach(button => {
    button.classList.toggle('active', button.dataset.tab === tabId);
  });
  const scope = root.parentElement;
  scope.querySelectorAll(':scope > .tab-pane').forEach(pane => {
    pane.classList.toggle('active', pane.dataset.pane === tabId);
  });
  refreshIcons();
}

document.addEventListener('click', event => {
  const viewButton = event.target.closest('[data-view]');
  if (viewButton) {
    showView(viewButton.dataset.view);
    return;
  }

  const toggle = event.target.closest('.module-toggle');
  if (toggle) {
    toggle.closest('.nav-module').classList.toggle('open');
    refreshIcons();
    return;
  }

  const tabButton = event.target.closest('[data-tab]');
  if (tabButton) {
    switchTab(tabButton.closest('[data-tabs]').dataset.tabs, tabButton.dataset.tab);
    return;
  }

  const openTab = event.target.closest('[data-open-tab]');
  if (openTab) {
    switchTab('parsing-tabs', openTab.dataset.openTab);
    return;
  }

  const scrollButton = event.target.closest('[data-scroll]');
  if (scrollButton) {
    const section = document.getElementById(scrollButton.dataset.scroll);
    if (section) {
      section.open = true;
      section.scrollIntoView({ behavior: 'smooth', block: 'start' });
      document.querySelectorAll('.stepper button').forEach(button => button.classList.toggle('active', button === scrollButton));
    }
    return;
  }

  const toastButton = event.target.closest('[data-toast]');
  if (toastButton) {
    showToast(toastButton.dataset.toast);
    return;
  }

  const drawerButton = event.target.closest('[data-open-drawer]');
  if (drawerButton) {
    const drawer = document.getElementById(drawerButton.dataset.openDrawer);
    drawer.classList.add('open');
    drawer.setAttribute('aria-hidden', 'false');
    document.querySelector('.drawer-backdrop').classList.add('open');
    refreshIcons();
    return;
  }

  if (event.target.closest('.drawer-close') || event.target.classList.contains('drawer-backdrop')) {
    document.querySelectorAll('.drawer').forEach(drawer => {
      drawer.classList.remove('open');
      drawer.setAttribute('aria-hidden', 'true');
    });
    document.querySelector('.drawer-backdrop').classList.remove('open');
  }
});

document.addEventListener('keydown', event => {
  if (event.key === 'Escape') {
    document.querySelectorAll('.drawer').forEach(drawer => drawer.classList.remove('open'));
    document.querySelector('.drawer-backdrop').classList.remove('open');
  }
});

const initialView = (location.hash || '#parsing').slice(1);
showView(initialView, false);
refreshIcons();
