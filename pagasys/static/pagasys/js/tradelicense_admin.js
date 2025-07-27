window.addEventListener('load', function () {
  const companyField = document.getElementById('id_company');
  const fromBox = document.getElementById('id_branches_from');
  const toBox = document.getElementById('id_branches_to');
  if (!companyField || !fromBox) return;
  const allOptions = Array.from(fromBox.options);

  function filterOptions() {
    const comp = companyField.value;
    allOptions.forEach(opt => {
      const match = !comp || opt.dataset.company === comp;
      opt.hidden = !match;
      opt.disabled = !match;
      if (!match && opt.selected) {
        opt.selected = false;
      }
    });
    if (toBox) {
      Array.from(toBox.options).forEach(opt => {
        if (comp && opt.dataset.company !== comp) {
          opt.selected = false;
          opt.remove();
        }
      });
    }
  }

  companyField.addEventListener('change', filterOptions);
  filterOptions();
});
