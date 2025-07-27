function initEmployeeAdmin() {
  const isSuperEl = document.getElementById('id_is_superuser');
  const groupsField = document.getElementById('id_groups');
  const visaTypeEl = document.getElementById('id_visa_type');
  const licenseField = document.getElementById('id_trade_license');

  if (isSuperEl && groupsField) {
    const row = groupsField.closest('.form-row');
    function toggleGroupField() {
      const isSuper = isSuperEl.checked;
      if (row) row.style.display = isSuper ? 'none' : '';
      groupsField.disabled = isSuper;
    }
    isSuperEl.addEventListener('change', toggleGroupField);
    toggleGroupField();
  }

  function toggleLicenseField() {
    if (!visaTypeEl || !licenseField) return;
    const personal = visaTypeEl.value === 'personal';
    const licRow = licenseField.closest('.form-row');
    if (licRow) licRow.style.display = personal ? 'none' : '';
    licenseField.disabled = personal;
  }

  if (visaTypeEl && licenseField) {
    visaTypeEl.addEventListener('change', toggleLicenseField);
    toggleLicenseField();
  }
}

window.addEventListener('load', initEmployeeAdmin);
window.addEventListener('DOMContentLoaded', initEmployeeAdmin);
