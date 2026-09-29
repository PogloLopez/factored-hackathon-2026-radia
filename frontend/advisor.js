// Consola del asesor: GET /advisor/sessions y POST /advisor/sessions/{id}/messages.
// El rango lo valida la API: un monto fuera de rango vuelve como 422 y se muestra.
"use strict";

(() => {
  const auth = Radia.requireRole("advisor");
  if (!auth) return;
  const { el, pair } = Radia;

  const sessionsBox = document.getElementById("sessions");
  const status = document.getElementById("list-status");
  const listError = document.getElementById("list-error");

  function renderMessages(messages) {
    if (!messages.length) return el("p", { class: "muted", text: "Sin mensajes enviados." });
    return el(
      "ul",
      {},
      messages.map((m) =>
        el(
          "li",
          {},
          `${Radia.dateTime(m.sent_at)}: ${m.message}`,
          m.proposed_amount_usd ? ` (monto propuesto ${Radia.usd(m.proposed_amount_usd)})` : "",
        ),
      ),
    );
  }

  function renderSession(session) {
    const c = session.case;
    const d = c.policy_decision;
    const id = c.case_id;
    const closed = c.status === "approved" || c.status === "rejected";

    const messageInput = el("textarea", { id: `msg-${id}`, name: "message", maxlength: "2000", required: true });
    const amountInput = el("input", {
      id: `amount-${id}`,
      name: "amount",
      type: "number",
      step: "0.01",
      inputmode: "decimal",
      "aria-describedby": `range-${id}`,
    });
    const errorBox = el("div", { class: "error", role: "alert", hidden: true });
    const okBox = el("div", { class: "success", role: "status", hidden: true });
    const submit = el("button", { type: "submit", text: "Enviar mensaje", disabled: closed });

    // novalidate: la API decide si el monto es válido y responde 422 si no.
    const form = el(
      "form",
      { novalidate: true },
      el("label", { for: `msg-${id}`, text: "Mensaje al cliente" }),
      messageInput,
      el("label", { for: `amount-${id}`, text: "Monto propuesto en USD (opcional)" }),
      amountInput,
      el(
        "p",
        { id: `range-${id}`, class: "hint" },
        d ? `Rango permitido: ${Radia.usd(d.negotiation_min_usd)} a ${Radia.usd(d.negotiation_max_usd)}.` : "Sin rango de negociación.",
      ),
      errorBox,
      okBox,
      el("div", { class: "actions" }, submit),
    );

    const messagesBox = el("div", {}, renderMessages(session.messages));

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      Radia.clearError(errorBox);
      okBox.hidden = true;
      const raw = amountInput.value.trim();
      const amount = raw === "" ? null : Number(raw);
      // Con texto no numérico (p. ej. "12500,50") el navegador deja value en ""
      // y marca badInput: sin este chequeo el monto se perdería sin aviso.
      if (amountInput.validity.badInput || (raw !== "" && !Number.isFinite(amount))) {
        Radia.showError(errorBox, "El monto debe ser un número (usa punto decimal, p. ej. 12500.50).");
        amountInput.focus();
        return;
      }
      submit.disabled = true;
      try {
        const sent = await Radia.api("POST", `/advisor/sessions/${encodeURIComponent(id)}/messages`, {
          message: messageInput.value.trim(),
          proposed_amount_usd: amount,
        });
        session.messages.push(sent);
        messagesBox.replaceChildren(renderMessages(session.messages));
        messageInput.value = "";
        amountInput.value = "";
        okBox.textContent = "Mensaje enviado.";
        okBox.hidden = false;
      } catch (err) {
        Radia.showError(errorBox, err);
        (err.status === 422 && raw !== "" ? amountInput : messageInput).focus();
      } finally {
        submit.disabled = closed;
      }
    });

    return el(
      "article",
      { class: c.priority === "high" ? "card highlighted" : "card", "aria-labelledby": `title-${id}` },
      el("h2", { id: `title-${id}` }, `Caso ${id}`, closed ? " · cerrado" : ""),
      el(
        "dl",
        { class: "facts" },
        pair("Rango de negociación", d ? `${Radia.usd(d.negotiation_min_usd)} a ${Radia.usd(d.negotiation_max_usd)}` : "—"),
        pair("Cupo ofrecido", d ? Radia.usd(d.offered_limit_usd) : "—"),
      ),
      el("details", {}, el("summary", { text: "Expediente completo" }), Radia.renderCaseFile(c)),
      el("h3", { text: "Mensajes enviados" }),
      messagesBox,
      form,
    );
  }

  async function load() {
    Radia.clearError(listError);
    status.textContent = "Cargando sesiones…";
    try {
      const data = await Radia.api("GET", "/advisor/sessions");
      sessionsBox.replaceChildren(...data.sessions.map(renderSession));
      status.textContent = data.sessions.length
        ? `${data.sessions.length} sesión(es) traspasada(s).`
        : "No hay sesiones traspasadas.";
    } catch (err) {
      status.textContent = "";
      Radia.showError(listError, err);
    }
  }

  document.getElementById("refresh").addEventListener("click", load);
  load();
})();
