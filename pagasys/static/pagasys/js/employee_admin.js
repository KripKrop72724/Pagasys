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
  const wpsIdField = document.getElementById('id_wps_id');
  const wpsIdRow = wpsIdField
    ? wpsIdField.closest('.form-row, .grp-row')
    : document.querySelector('.form-row.field-wps_id, .grp-row.field-wps_id');
  const c3Field = document.getElementById('id_c3_id');
  const c3Row = c3Field
    ? c3Field.closest('.form-row, .grp-row')
    : document.querySelector('.form-row.field-c3_id, .grp-row.field-c3_id');

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
    const pv = personal || visit;
    if (licenseRow) licenseRow.style.display = pv ? 'none' : '';
    if (licenseField) {
      licenseField.disabled = pv;
      if (pv) {
        licenseField.value = '';
      }
    }
    if (paymentStatusEl) {
      paymentStatusEl.disabled = pv;
      if (pv) {
        paymentStatusEl.value = 'cash';
      }
    }
    if (wpsIdRow) wpsIdRow.style.display = pv ? 'none' : '';
    if (wpsIdField) {
      wpsIdField.disabled = pv;
      if (pv) wpsIdField.value = '';
    }
    if (c3Row) c3Row.style.display = pv ? 'none' : '';
    if (c3Field) {
      c3Field.disabled = pv;
      if (pv) c3Field.value = '';
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
