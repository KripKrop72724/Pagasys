function initEmployeeAdmin() {
  const isSuperEl = document.getElementById('id_is_superuser');
  const groupsField = document.getElementById('id_groups');
  const visaTypeEl = document.getElementById('id_visa_type');
  const licenseField = document.getElementById('id_trade_license');
  const licenseRow = licenseField
    ? licenseField.closest('.form-row, .grp-row')
    : document.querySelector(
        '.form-row.field-trade_license, .grp-row.field-trade_license'
      );
  const paymentStatusEl = document.getElementById('id_payment_status');
  const wpsField = document.getElementById('id_wps_account_number');
  const wpsRow = wpsField
    ? wpsField.closest('.form-row, .grp-row')
    : document.querySelector(
        '.form-row.field-wps_account_number, .grp-row.field-wps_account_number'
      );

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

  function togglePaymentFields() {
    if (!paymentStatusEl) return;
    const wps = paymentStatusEl.value === 'wps';
    if (wpsRow) wpsRow.style.display = wps ? '' : 'none';
    if (wpsField) {
      wpsField.disabled = !wps;
      if (!wps) wpsField.value = '';
    }
  }

  function handleVisaType() {
    if (!visaTypeEl) return;
    const personal = visaTypeEl.value === 'personal';
    const visit = visaTypeEl.value === 'visit';
    if (licenseRow) licenseRow.style.display = personal || visit ? 'none' : '';
    if (licenseField) {
      licenseField.disabled = personal || visit;
      if (personal || visit) {
        licenseField.value = '';
      }
    }
    if (paymentStatusEl) {
      paymentStatusEl.disabled = visit;
      if (visit) {
        paymentStatusEl.value = 'cash';
      }
    }
    togglePaymentFields();
  }

  if (visaTypeEl) {
    visaTypeEl.addEventListener('change', handleVisaType);
  }
  if (paymentStatusEl) {
    paymentStatusEl.addEventListener('change', togglePaymentFields);
  }
  handleVisaType();
}

window.addEventListener('load', initEmployeeAdmin);
window.addEventListener('DOMContentLoaded', initEmployeeAdmin);
