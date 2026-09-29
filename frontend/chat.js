// Chat del cliente: POST /chat/messages y POST /chat/confirm.
// El estado, la confirmación y las referencias salen tal cual de la API.
"use strict";

(() => {
  const auth = Radia.requireRole("customer");
  if (!auth) return;
  const { el } = Radia;
  const CHAT_KEY = "radia.chat";

  const messagesBox = document.getElementById("messages");
  const stateLabel = document.getElementById("chat-state");
  const appRef = document.getElementById("application-ref");
  const caseRef = document.getElementById("case-ref");
  const confirmBox = document.getElementById("confirm-box");
  const confirmSummary = document.getElementById("confirm-summary");
  const yes = document.getElementById("confirm-yes");
  const no = document.getElementById("confirm-no");
  const error = document.getElementById("chat-error");
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  const send = document.getElementById("chat-send");
  const reset = document.getElementById("chat-reset");

  // Vista de la conversación. Se guarda en la pestaña para sobrevivir a recargas.
  const empty = () => ({ session_id: null, messages: [], last: null });
  let chat = empty();
  try {
    chat = JSON.parse(Radia.storeGet(CHAT_KEY)) || empty();
  } catch {
    chat = empty();
  }

  function persist() {
    Radia.storeSet(CHAT_KEY, JSON.stringify(chat));
  }

  function render() {
    messagesBox.replaceChildren(
      ...chat.messages.map((m) =>
        el(
          "li",
          { class: m.from },
          el("span", { class: "who", text: m.from === "user" ? "Tú" : "Radia" }),
          m.text,
        ),
      ),
    );

    const last = chat.last;
    stateLabel.textContent = last ? Radia.label(Radia.STATE_LABELS, last.state) : "Sin conversación";

    appRef.hidden = !(last && last.application_reference);
    appRef.textContent = appRef.hidden ? "" : `Número de solicitud: ${last.application_reference}`;
    caseRef.hidden = !(last && last.handoff_case_id);
    caseRef.textContent = caseRef.hidden ? "" : `Número de caso: ${last.handoff_case_id}`;

    const pending = last && last.pending_confirmation;
    confirmBox.hidden = !pending;
    confirmSummary.textContent = pending ? pending.summary : "";
  }

  function setBusy(busy) {
    for (const button of [send, yes, no, reset]) button.disabled = busy;
    input.disabled = busy;
  }

  function applyReply(reply) {
    chat.session_id = reply.session_id;
    chat.last = reply;
    chat.messages.push({ from: "bot", text: reply.reply });
    persist();
    render();
  }

  function handleError(err) {
    Radia.showError(error, err);
    // 404: la sesión ya no existe (reinicio del servidor). Se empieza otra.
    if (err instanceof Radia.ApiError && err.status === 404) {
      chat.session_id = null;
      chat.last = null;
      persist();
      render();
      error.textContent += " Se abrirá una conversación nueva con tu próximo mensaje.";
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    Radia.clearError(error);
    const message = input.value.trim();
    if (!message) {
      Radia.showError(error, "Escribe un mensaje.");
      input.focus();
      return;
    }
    chat.messages.push({ from: "user", text: message });
    render();
    input.value = "";
    setBusy(true);
    try {
      applyReply(await Radia.api("POST", "/chat/messages", { session_id: chat.session_id, message }));
    } catch (err) {
      handleError(err);
    } finally {
      setBusy(false);
      (chat.last && chat.last.pending_confirmation ? yes : input).focus();
    }
  });

  async function confirm(accept) {
    const pending = chat.last && chat.last.pending_confirmation;
    if (!pending) return;
    Radia.clearError(error);
    chat.messages.push({ from: "user", text: accept ? "Sí" : "No" });
    render();
    setBusy(true);
    try {
      applyReply(
        await Radia.api("POST", "/chat/confirm", {
          session_id: chat.session_id,
          confirmation_id: pending.confirmation_id,
          accept,
        }),
      );
    } catch (err) {
      handleError(err);
    } finally {
      setBusy(false);
      input.focus();
    }
  }

  yes.addEventListener("click", () => confirm(true));
  no.addEventListener("click", () => confirm(false));

  reset.addEventListener("click", () => {
    Radia.clearError(error);
    chat = empty();
    persist();
    render();
    input.focus();
  });

  render();
})();
