// Confirm dialogs and auto-submitting selects.
document.addEventListener('click', event => {
  const button = event.target.closest('[data-confirm]');
  if (button && !window.confirm(button.getAttribute('data-confirm'))) event.preventDefault();
});
document.addEventListener('change', event => {
  if (event.target.matches('select[data-autosubmit]')) event.target.form.submit();
});

// Save/Cancel appear only when a form has unsaved changes.
document.addEventListener('DOMContentLoaded', () => {
  const show = (el, on) => {
    el.style.display = on ? '' : 'none';
  };
  const dirty = form => {
    const clone = form.cloneNode(true);
    clone.reset();
    return JSON.stringify([...new FormData(form)].sort()) !== JSON.stringify([...new FormData(clone)].sort());
  };
  const sync = form => {
    const changed = dirty(form);
    const save = form.querySelector('button.save');
    if (save) show(save, changed);
    for (const cancel of form.querySelectorAll('button.cancel:not(.attr-toggle)')) show(cancel, changed);
  };
  for (const form of document.querySelectorAll('form[method="post"]')) {
    form.addEventListener('input', () => sync(form));
    form.addEventListener('change', () => sync(form));
    form.addEventListener('submit', () => (form.dataset.sent = '1'));
    form.addEventListener('click', event => {
      if (!event.target.closest('button.cancel')) return;
      form.reset();
      sync(form);
    });
    sync(form);
  }
});

// Flash messages fade out after a few seconds.
document.addEventListener('DOMContentLoaded', () => {
  for (const msg of document.querySelectorAll('.msg')) {
    setTimeout(() => {
      msg.classList.add('msg-hide');
      setTimeout(() => msg.remove(), 400);
    }, 5000);
  }
});

// MARC fields: one inline editor row open at a time.
document.addEventListener('click', event => {
  const toggle = event.target.closest('.attr-toggle');
  if (!toggle) return;
  const row = document.getElementById(toggle.getAttribute('data-target'));
  if (!row) return;
  const open = row.hidden;
  for (const editor of document.querySelectorAll('tr.attr-editor')) editor.hidden = true;
  row.hidden = !open;
});
