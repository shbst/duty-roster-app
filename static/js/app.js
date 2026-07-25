const navButton = document.querySelector(".nav-toggle");
const nav = document.querySelector(".main-nav");
if (navButton && nav) {
  navButton.addEventListener("click", () => {
    const open = nav.classList.toggle("open");
    navButton.setAttribute("aria-expanded", String(open));
  });
}

document.querySelectorAll("form[data-confirm]").forEach((form) => {
  form.addEventListener("submit", (event) => {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  });
});

document.querySelectorAll(".duty-slot-option input").forEach((input) => {
  input.addEventListener("change", () => {
    input.closest(".duty-slot-option").classList.toggle("selected", input.checked);
  });
});
