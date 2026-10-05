"use strict";

document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("login-form");
  const password = document.getElementById("password");
  const reveal = document.getElementById("reveal");
  const capsHint = document.getElementById("caps-hint");
  const submit = document.getElementById("submit");

  reveal.addEventListener("click", () => {
    const visible = password.type === "text";
    password.type = visible ? "password" : "text";
    reveal.setAttribute("aria-pressed", String(!visible));
    reveal.setAttribute("aria-label", visible ? "Mostra password" : "Nascondi password");
    password.focus();
  });

  const updateCaps = event => {
    if (typeof event.getModifierState === "function") {
      capsHint.hidden = !event.getModifierState("CapsLock");
    }
  };
  password.addEventListener("keydown", updateCaps);
  password.addEventListener("keyup", updateCaps);
  password.addEventListener("blur", () => { capsHint.hidden = true; });

  form.addEventListener("submit", event => {
    let valid = true;
    form.querySelectorAll("input[required]").forEach(input => {
      const empty = !input.value.trim();
      input.closest(".field").classList.toggle("is-invalid", empty);
      if (empty && valid) {
        input.focus();
        valid = false;
      }
    });
    if (!valid) {
      event.preventDefault();
      return;
    }
    submit.classList.add("is-loading");
    submit.querySelector(".submit-label").textContent = "Accesso in corso…";
  });

  form.querySelectorAll("input").forEach(input => {
    input.addEventListener("input", () => input.closest(".field").classList.remove("is-invalid"));
  });

  // Spettro decorativo: barre con ampiezza e tempo pseudo-casuali.
  const spectrum = document.getElementById("spectrum");
  if (spectrum && spectrum.offsetParent !== null) {
    const bars = 48;
    const fragment = document.createDocumentFragment();
    for (let i = 0; i < bars; i += 1) {
      const bar = document.createElement("span");
      const center = 1 - Math.abs(i - bars / 2) / (bars / 2);
      const hi = 0.35 + center * 0.55 + Math.random() * 0.1;
      bar.style.setProperty("--hi", hi.toFixed(2));
      bar.style.setProperty("--lo", (0.08 + Math.random() * 0.12).toFixed(2));
      bar.style.setProperty("--d", `${(1.1 + Math.random() * 1.2).toFixed(2)}s`);
      bar.style.setProperty("--delay", `${(-Math.random() * 2).toFixed(2)}s`);
      fragment.appendChild(bar);
    }
    spectrum.appendChild(fragment);
  }
});
