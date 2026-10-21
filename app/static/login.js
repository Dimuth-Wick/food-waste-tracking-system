// Sign-in page: show/hide password, Caps Lock hint, "Signing in" state, lock countdown, and the picture's
// gentle lean toward the mouse. The form works without any of this.
(() => {
  const form = document.getElementById("login-form");
  if (!form) return;
  const username = form.querySelector("#username");
  const password = form.querySelector("#password");
  const submit = form.querySelector(".submit");
  const label = form.querySelector(".submit-label");
  const reveal = form.querySelector(".reveal-password");
  const caps = form.querySelector(".caps-hint");
  const error = form.querySelector(".login-error");
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Start where typing is needed: the username, or the password when the username came back filled in.
  (username.value ? password : username).focus({ preventScroll: true });

  // Show and hide the password. The button only exists when scripts run.
  reveal.hidden = false;
  reveal.addEventListener("click", () => {
    const showing = password.type === "text";
    password.type = showing ? "password" : "text";
    reveal.setAttribute("aria-pressed", String(!showing));
    reveal.setAttribute("aria-label", showing ? "Show password" : "Hide password");
    password.focus();
  });

  // Warn when Caps Lock is on while typing the password.
  const checkCaps = (event) => {
    if (typeof event.getModifierState === "function") caps.hidden = !event.getModifierState("CapsLock");
  };
  password.addEventListener("keydown", checkCaps);
  password.addEventListener("keyup", checkCaps);
  password.addEventListener("blur", () => { caps.hidden = true; });

  // One click, one sign-in: show progress and ignore a second press.
  let sending = false;
  const idle = () => {
    sending = false;
    submit.classList.remove("is-loading");
    submit.disabled = false;
    submit.removeAttribute("aria-busy");
    label.textContent = "Sign in";
  };
  form.addEventListener("submit", (event) => {
    if (sending) { event.preventDefault(); return; }
    if (!username.value.trim() || !password.value) return;   // the server explains what is missing
    sending = true;
    submit.classList.add("is-loading");
    submit.setAttribute("aria-busy", "true");
    label.textContent = "Signing in…";
  });
  window.addEventListener("pageshow", (event) => { if (event.persisted) idle(); });   // back button

  // After too many wrong passwords: count down, then let people try again.
  if (error && error.dataset.wait) {
    let left = Number(error.dataset.wait);
    const text = error.textContent.replace(/Try again in .*$/, "");
    submit.disabled = true;
    const tick = () => {
      if (left <= 0) {
        error.textContent = "You can try again now.";
        submit.disabled = false;
        return;
      }
      const minutes = Math.floor(left / 60), seconds = String(left % 60).padStart(2, "0");
      error.textContent = `${text}Try again in ${minutes}:${seconds}.`;
      left -= 1;
      setTimeout(tick, 1000);
    };
    tick();
  }

  // The picture leans a little toward the mouse (not on touch screens, not for reduced motion).
  const stage = document.querySelector(".stage");
  if (stage && !reduced && window.matchMedia("(hover: hover) and (pointer: fine)").matches) {
    let frame = 0, x = 0, y = 0;
    window.addEventListener("pointermove", (event) => {
      x = event.clientX / window.innerWidth - 0.5;
      y = event.clientY / window.innerHeight - 0.5;
      if (!frame) frame = requestAnimationFrame(() => {
        frame = 0;
        stage.style.setProperty("--px", (x * 2).toFixed(3));
        stage.style.setProperty("--py", (y * 2).toFixed(3));
      });
    }, { passive: true });
  }
})();
