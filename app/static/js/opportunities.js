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

(function () {
  var fieldSelect = document.getElementById('opportunities-sort-field');
  var dirSelect = document.getElementById('opportunities-sort-dir');
  var sortBar = document.getElementById('opportunities-sort-bar');
  if (!fieldSelect || !dirSelect || !sortBar) return;

  function fieldType() {
    var option = fieldSelect.options[fieldSelect.selectedIndex];
    return option ? option.getAttribute('data-type') || 'text' : 'text';
  }

  function populateDirectionOptions(preserveDir) {
    var type = fieldType();
    var current = preserveDir ? sortBar.getAttribute('data-sort-dir') || 'asc' : dirSelect.value;
    dirSelect.innerHTML = '';
    var options =
      type === 'boolean'
        ? [
            { value: 'desc', label: 'Yes first' },
            { value: 'asc', label: 'No first' },
          ]
        : [
            { value: 'asc', label: 'A \u2192 Z' },
            { value: 'desc', label: 'Z \u2192 A' },
          ];
    options.forEach(function (opt) {
      var el = document.createElement('option');
      el.value = opt.value;
      el.textContent = opt.label;
      if (opt.value === current) el.selected = true;
      dirSelect.appendChild(el);
    });
    if (!dirSelect.value && options.length) {
      dirSelect.value = options[0].value;
    }
  }

  function navigateSort() {
    var sort = fieldSelect.value;
    var dir = dirSelect.value;
    window.location.href = '/opportunities?sort=' + encodeURIComponent(sort) + '&dir=' + encodeURIComponent(dir) + '&page=1';
  }

  populateDirectionOptions(true);

  fieldSelect.addEventListener('change', function () {
    populateDirectionOptions(false);
    navigateSort();
  });

  dirSelect.addEventListener('change', navigateSort);
})();
