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

document.body.addEventListener('htmx:afterSwap', function (event) {
  if (event.detail.target.id !== 'opportunity-modal-container') return;
  var oppDialog = document.getElementById('opportunity-modal');
  if (oppDialog && typeof oppDialog.showModal === 'function') {
    oppDialog.showModal();
    return;
  }
  var settingsDialog = document.getElementById('adzuna-settings-modal');
  if (settingsDialog && typeof settingsDialog.showModal === 'function') {
    settingsDialog.showModal();
  }
});
