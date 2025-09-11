function initRosterAdmin() {
  const branchEl = document.getElementById('id_branch');
  const employeesEl =
    document.getElementById('id_employees_from') ||
    document.getElementById('id_employees');
  const sourceEl = document.getElementById('id_employees');
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

  if (sourceEl && sourceEl !== employeesEl) {
    const branchMap = new Map();
    Array.from(sourceEl.options).forEach((opt) => {
      branchMap.set(opt.value, opt.dataset.branch);
    });
    Array.from(employeesEl.options).forEach((opt) => {
      const branchId = branchMap.get(opt.value);
      if (branchId !== undefined) opt.dataset.branch = branchId;
    });
  }

  if (branchEl) {
    branchEl.addEventListener('change', filterEmployees);
  }
  filterEmployees();
}

window.addEventListener('load', initRosterAdmin);
window.addEventListener('DOMContentLoaded', initRosterAdmin);
