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
  // Compare against the server-rendered values, not whatever the browser
  // restored into the fields; otherwise restored edits never look dirty.
  const defaultSnapshot = form => {
    const clone = form.cloneNode(true);
    clone.reset();
    return JSON.stringify([...new FormData(clone)].sort());
  };
  const baseline = new Map();
  const dirtyForms = new Set();
  // Warn only on edits the user actually made in this visit. Comparing values
  // against a baseline also trips on browser-restored state, which is why a
  // plain Enter in a search box used to nag about unsaved changes.
  const hasUnsavedChanges = () => [...dirtyForms].some(form => !form.dataset.sent);
  const show = (el, on) => {
    const wasHidden = el.style.display === 'none';
    el.style.display = on ? '' : 'none';
    if (on && wasHidden && el.animate) el.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 120 });
  };
  const syncSaveButton = form => {
    // Compare values, not "was touched": toggling a checkbox back to its saved
    // state must hide Save and Cancel again.
    const dirty = baseline.get(form) !== snapshot(form);
    if (dirty) dirtyForms.add(form);
    else dirtyForms.delete(form);
    const button = form.querySelector('button.save');
    if (button) show(button, dirty);
    // Row-level Cancel joins Save only when there is an actual edit to undo.
    // The MARC editor Cancel stays available so it can close the editor too.
    for (const cancel of form.querySelectorAll('button.cancel:not(.attr-toggle)')) {
      show(cancel, dirty);
    }
  };
  const syncAll = () => {
    for (const form of document.querySelectorAll('form[method="post"]')) syncSaveButton(form);
  };
  for (const form of document.querySelectorAll('form[method="post"]')) {
    baseline.set(form, defaultSnapshot(form));
    form.addEventListener('submit', event => {
      if (form.dataset.sent) {
        event.preventDefault();
        return;
      }
      form.dataset.sent = '1';
    });
    form.addEventListener('input', () => syncSaveButton(form));
    form.addEventListener('change', () => syncSaveButton(form));
  }
  syncAll();
  // Cancel always restores the server-rendered values and clears dirty state.
  document.addEventListener('click', event => {
    const button = event.target.closest('button.cancel');
    if (!button) return;
    const form = button.closest('form');
    if (!form) return;
    form.reset();
    dirtyForms.delete(form);
    syncSaveButton(form);
  });
  // Chrome restores edited values on back/forward without firing input events.
  addEventListener('pageshow', syncAll);
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


// MARC fields: Edit opens one inline editor row at a time; Cancel closes it.
document.addEventListener('click', event => {
  const toggle = event.target.closest('.attr-toggle');
  if (!toggle) return;
  const id = toggle.getAttribute('data-target');
  const row = document.getElementById(id);
  if (!row) return;
  const open = row.hidden;
  for (const editor of document.querySelectorAll('tr.attr-editor')) editor.hidden = true;
  row.hidden = !open;
});
