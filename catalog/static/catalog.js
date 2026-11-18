document.addEventListener('change', event => {
  if (event.target.matches('select[data-autosubmit]')) event.target.form.submit();
});

document.addEventListener('click', event => {
  const button = event.target.closest('[data-confirm]');
  if (button && !window.confirm(button.getAttribute('data-confirm'))) event.preventDefault();
});

// Remember scroll position across the post/redirect cycle.
document.addEventListener('submit', () => {
  sessionStorage.setItem('catalog:scroll', JSON.stringify({ y: scrollY, path: location.pathname }));
});

window.addEventListener('load', () => {
  const saved = sessionStorage.getItem('catalog:scroll');
  if (!saved) return;
  sessionStorage.removeItem('catalog:scroll');
  try {
    const { y, path } = JSON.parse(saved);
    if (path === location.pathname) scrollTo(0, y);
  } catch (e) {}
});

// Editing is explicit: Save appears only when a form has unsaved changes,
// Enter never submits an edit form, and each form submits at most once.
document.addEventListener('DOMContentLoaded', () => {
  const snapshot = form => JSON.stringify([...new FormData(form)].sort());
  const baseline = new Map();
  const hasUnsavedChanges = () =>
    [...document.querySelectorAll('form[method="post"]')].some(
      form => !form.dataset.sent && baseline.has(form) && baseline.get(form) !== snapshot(form)
    );
  const syncSaveButton = form => {
    const button = form.querySelector('button.save');
    if (!button) return;
    button.style.display = baseline.get(form) !== snapshot(form) ? '' : 'none';
  };
  for (const form of document.querySelectorAll('form[method="post"]')) {
    baseline.set(form, snapshot(form));
    form.addEventListener('submit', event => {
      if (form.dataset.sent) {
        event.preventDefault();
        return;
      }
      form.dataset.sent = '1';
    });
    if (form.querySelector('button.save')) {
      syncSaveButton(form);
      form.addEventListener('input', () => syncSaveButton(form));
      form.addEventListener('change', () => syncSaveButton(form));
    }
  }
  addEventListener('beforeunload', event => {
    if (hasUnsavedChanges()) {
      event.preventDefault();
      event.returnValue = '';
    }
  });
  document.addEventListener(
    'click',
    event => {
      const link = event.target.closest('a[href]');
      if (!link || link.target === '_blank' || link.getAttribute('href').charAt(0) === '#' || !hasUnsavedChanges()) return;
      if (!window.confirm('You have unsaved changes. Leave without saving?')) event.preventDefault();
    },
    true
  );
  document.addEventListener('keydown', event => {
    const target = event.target;
    const form = target.closest && target.closest('form');
    const isEditSubmit =
      event.key === 'Enter' &&
      form &&
      (form.getAttribute('action') || '').indexOf('change/propose') > -1 &&
      target.tagName !== 'TEXTAREA' &&
      target.tagName !== 'BUTTON';
    if (isEditSubmit) event.preventDefault();
  });
});
