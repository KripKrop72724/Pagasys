document.addEventListener('DOMContentLoaded', function () {
  const isSuperEl = document.getElementById('id_is_superuser');
  const groupsField = document.getElementById('id_groups');
  if (!isSuperEl || !groupsField) return;

  const row = groupsField.closest('.form-row');

  function toggleGroupField() {
    const isSuper = isSuperEl.checked;
    if (row) row.style.display = isSuper ? 'none' : '';
    groupsField.disabled = isSuper;
  }

  isSuperEl.addEventListener('change', toggleGroupField);
  toggleGroupField();
});
