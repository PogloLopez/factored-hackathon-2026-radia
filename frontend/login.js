// Login: POST /auth/login y redirección según el rol del token.
"use strict";

(() => {
  const form = document.getElementById("login-form");
  const error = document.getElementById("login-error");
  const submit = document.getElementById("login-submit");

  // Con sesión vigente, directo a su pantalla.
  const current = Radia.loadAuth();
  if (current && Radia.ROLE_PAGES[current.role]) {
    window.location.replace(Radia.ROLE_PAGES[current.role]);
    return;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    Radia.clearError(error);
    const username = form.username.value.trim();
    const password = form.password.value;
    if (!username || !password) {
      Radia.showError(error, "Escribe usuario y clave.");
      (username ? form.password : form.username).focus();
      return;
    }
    submit.disabled = true;
    try {
      const auth = await Radia.api("POST", "/auth/login", { username, password });
      if (!Radia.saveAuth(auth)) {
        Radia.showError(
          error,
          "Tu navegador bloquea el almacenamiento de la sesión. Habilítalo para esta página o usa otra ventana.",
        );
        return;
      }
      window.location.assign(Radia.ROLE_PAGES[auth.role]);
    } catch (err) {
      Radia.showError(error, err);
      form.password.focus();
    } finally {
      submit.disabled = false;
    }
  });
})();
