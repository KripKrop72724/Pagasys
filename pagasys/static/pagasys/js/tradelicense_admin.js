window.addEventListener('load', function () {
  const companyField = document.getElementById('id_company');
  function setup() {
    const fromBox = document.getElementById('id_branches_from');
    const toBox = document.getElementById('id_branches_to');
    if (!companyField || !fromBox) return;
    const allOptions = [
      ...fromBox.querySelectorAll('option'),
      ...(toBox ? Array.from(toBox.querySelectorAll('option')) : []),
    ];

    function filterOptions() {
      const comp = companyField.value;
      allOptions.forEach(opt => {
        const match = !comp || opt.dataset.company === comp;
        if (toBox && !match && toBox.contains(opt)) {
          opt.selected = false;
          fromBox.appendChild(opt);
        }
        opt.hidden = !match;
        opt.disabled = !match;
      });
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
