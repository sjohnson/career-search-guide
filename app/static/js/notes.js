document.addEventListener('click', function (event) {
  var cell = event.target.closest('.notes-truncate');
  if (!cell) return;
  var row = cell.closest('tr');
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
  var row = cell.closest('tr');
  if (row) {
    row.classList.toggle('notes-expanded');
    cell.classList.toggle('notes-truncate');
  }
});
