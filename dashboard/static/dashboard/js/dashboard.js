(() => {
  "use strict";

  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!window.confirm(form.dataset.confirm)) {
        event.preventDefault();
      }
    });
  });

  document.querySelectorAll("[data-password-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const input = document.getElementById(button.dataset.passwordToggle);
      if (!input) return;
      const revealing = input.type === "password";
      input.type = revealing ? "text" : "password";
      button.setAttribute("aria-label", revealing ? "Hide API key" : "Show API key");
      const icon = button.querySelector("i");
      if (icon) icon.className = revealing ? "bi bi-eye-slash" : "bi bi-eye";
    });
  });

  const modeInputs = document.querySelectorAll('input[name="mode"]');
  const scheduleGroup = document.querySelector("[data-schedule-fields]");
  const syncScheduleVisibility = () => {
    if (!scheduleGroup) return;
    const selected = document.querySelector('input[name="mode"]:checked');
    const scheduled = selected && selected.value === "schedule";
    scheduleGroup.hidden = !scheduled;
    scheduleGroup.querySelectorAll("input, select").forEach((field) => {
      field.disabled = !scheduled;
    });
  };
  modeInputs.forEach((input) => input.addEventListener("change", syncScheduleVisibility));
  syncScheduleVisibility();

  document.querySelectorAll("[data-progress]").forEach((bar) => {
    const value = Math.max(0, Math.min(100, Number(bar.dataset.progress) || 0));
    window.requestAnimationFrame(() => {
      bar.style.width = `${value}%`;
      bar.setAttribute("aria-valuenow", String(value));
    });
  });
})();
