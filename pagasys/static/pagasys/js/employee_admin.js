function initEmployeeAdmin() {
  const isSuperEl = document.getElementById('id_is_superuser');
  const groupsField = document.getElementById('id_groups');
  const visaTypeEl = document.getElementById('id_visa_type');
  const licenseField = document.getElementById('id_trade_license');
  const licenseRow = licenseField
    ? licenseField.closest('.form-row')
    : document.querySelector('.form-row.field-trade_license');

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
    if (!visaTypeEl) return;
    const personal = visaTypeEl.value === 'personal';
    if (licenseRow) licenseRow.style.display = personal ? 'none' : '';
    if (licenseField) {
      licenseField.disabled = personal;
      if (personal) {
        licenseField.value = '';
      }
    }
  }

  if (visaTypeEl) {
    visaTypeEl.addEventListener('change', toggleLicenseField);
  }
  toggleLicenseField();
}

window.addEventListener('load', initEmployeeAdmin);
window.addEventListener('DOMContentLoaded', initEmployeeAdmin);
