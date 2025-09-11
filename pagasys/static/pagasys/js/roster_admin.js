function initRosterAdmin() {
  const branchEl = document.getElementById('id_branch');
  const employeesEl = document.getElementById('id_employees');
  if (!employeesEl) return;

  const selectAllBtn = document.createElement('button');
  selectAllBtn.type = 'button';
  selectAllBtn.textContent = 'Select all';
  employeesEl.parentNode.insertBefore(selectAllBtn, employeesEl);
  selectAllBtn.addEventListener('click', () => {
    Array.from(employeesEl.options).forEach((opt) => {
      if (!opt.hidden) opt.selected = true;
    });
  });

  function filterEmployees() {
    const branchId = branchEl ? branchEl.value : '';
    Array.from(employeesEl.options).forEach((opt) => {
      const match = !branchId || opt.dataset.branch === branchId;
      opt.hidden = !match;
      if (!match) opt.selected = false;
    });
  }

  if (branchEl) {
    branchEl.addEventListener('change', filterEmployees);
  }
  filterEmployees();
}

window.addEventListener('load', initRosterAdmin);
window.addEventListener('DOMContentLoaded', initRosterAdmin);
