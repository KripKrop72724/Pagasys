const branchCompanyMap = {};
document.addEventListener('DOMContentLoaded', function () {
  const original = document.getElementById('id_branches');
  if (original) {
    original.querySelectorAll('option').forEach(opt => {
      branchCompanyMap[opt.value] = opt.dataset.company;
    });
  }
});

window.addEventListener('load', function () {
  const companyField = document.getElementById('id_company');

  function setup() {
    const fromBox = document.getElementById('id_branches_from');
    const toBox = document.getElementById('id_branches_to');
    if (!companyField || !fromBox) return;

    function filterOne(opt) {
      const comp = companyField.value;
      const company = branchCompanyMap[opt.value];
      const match = !comp || company === comp;
      if (!match && opt.selected) {
        opt.selected = false;
      }
      opt.hidden = !match;
      opt.disabled = !match;
    }

    function filterOptions() {
      Array.from(fromBox.options).forEach(filterOne);
      if (toBox) {
        Array.from(toBox.options).forEach(filterOne);
      }
    }

    companyField.addEventListener('change', filterOptions);
    filterOptions();
  }

  if (!document.getElementById('id_branches_from')) {
    setTimeout(setup, 0);
  } else {
    setup();
  }
});
