(function() {
  function toggleGroupField() {
    var superBox = document.querySelector('#id_is_superuser');
    var groupField = document.querySelector('#id_groups');
    if (!superBox || !groupField) return;
    var row = groupField.closest('.form-row') || groupField.closest('.form-group');
    if (superBox.checked) {
      if (row) row.style.display = 'none';
      groupField.disabled = true;
    } else {
      if (row) row.style.display = '';
      groupField.disabled = false;
    }
  }

  function init() {
    var superBox = document.querySelector('#id_is_superuser');
    if (!superBox) return;
    superBox.addEventListener('change', toggleGroupField);
    toggleGroupField();
  }

  if (document.readyState !== 'loading') {
    init();
  } else {
    document.addEventListener('DOMContentLoaded', init);
  }
})();
