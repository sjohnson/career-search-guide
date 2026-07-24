document.addEventListener('click', function (event) {
  var cell = event.target.closest('.notes-truncate');
  if (!cell) return;
  var row = cell.closest('.opp-row');
  if (row) {
    row.classList.toggle('notes-expanded');
    cell.classList.toggle('notes-truncate');
  }
});

document.addEventListener('keydown', function (event) {
  if (event.key !== 'Enter' && event.key !== ' ') return;
  var cell = event.target.closest('.notes-truncate');
  if (!cell) return;
  event.preventDefault();
  var row = cell.closest('.opp-row');
  if (row) {
    row.classList.toggle('notes-expanded');
    cell.classList.toggle('notes-truncate');
  }
});

function openAppDialog(dialog) {
  if (!dialog || typeof dialog.showModal !== 'function') return;
  if (dialog.open) {
    dialog.close();
  }
  dialog.removeAttribute('open');
  dialog.showModal();
}

function closeAppModal() {
  var container = document.getElementById('opportunity-modal-container');
  if (!container) return;
  var dialog = container.querySelector('dialog');
  if (dialog && dialog.open) {
    dialog.close();
  }
  container.innerHTML = '';
}

window.closeAppModal = closeAppModal;

document.body.addEventListener('htmx:afterSwap', function (event) {
  if (event.detail.target.id !== 'opportunity-modal-container') return;
  var dialog = event.detail.target.querySelector('dialog');
  if (dialog) {
    openAppDialog(dialog);
  }
});

document.body.addEventListener('htmx:beforeSwap', function (event) {
  if (event.detail.target.id !== 'opportunity-modal-container') return;
  var existing = event.detail.target.querySelector('dialog');
  if (existing && existing.open) {
    existing.close();
  }
});
