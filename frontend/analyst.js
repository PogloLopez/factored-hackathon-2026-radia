// Bandeja del analista: GET /analyst/cases y POST /analyst/cases/{id}/decision.
"use strict";

(() => {
  const auth = Radia.requireRole("analyst");
  if (!auth) return;
  const { el } = Radia;

  const casesBox = document.getElementById("cases");
  const status = document.getElementById("list-status");
  const listError = document.getElementById("list-error");
  const result = document.getElementById("result");

  const DECISIONS = [
    { value: "approve", text: "Aprobar", secondary: false },
    { value: "reject", text: "Rechazar", secondary: true },
    { value: "request_info", text: "Pedir información", secondary: true },
  ];
  const DECISION_TEXT = { approve: "aprobado", reject: "rechazado", request_info: "con información pedida" };

  function renderCase(c) {
    const noteId = `note-${c.case_id}`;
    const errorBox = el("div", { class: "error", role: "alert", hidden: true });
    const note = el("textarea", { id: noteId, maxlength: "1000" });
    const buttons = DECISIONS.map((d) =>
      el("button", { type: "button", class: d.secondary ? "secondary" : null, text: d.text }),
    );

    buttons.forEach((button, i) => {
      button.addEventListener("click", async () => {
        Radia.clearError(errorBox);
        buttons.forEach((b) => (b.disabled = true));
        try {
          const response = await Radia.api("POST", `/analyst/cases/${encodeURIComponent(c.case_id)}/decision`, {
            decision: DECISIONS[i].value,
            note: note.value.trim() || null,
          });
          result.textContent = `Caso ${response.case.case_id} ${DECISION_TEXT[response.decision]}.`;
          result.hidden = false;
          await load();
          result.focus();
        } catch (err) {
          Radia.showError(errorBox, err);
          buttons.forEach((b) => (b.disabled = false));
        }
      });
    });

    return el(
      "article",
      { class: c.priority === "high" ? "card highlighted" : "card", "aria-labelledby": `title-${c.case_id}` },
      el("h2", { id: `title-${c.case_id}` }, `Caso ${c.case_id}`, c.priority === "high" ? " · prioridad alta" : ""),
      Radia.renderCaseFile(c),
      el("label", { for: noteId, text: "Nota (opcional)" }),
      note,
      errorBox,
      el("div", { class: "actions" }, buttons),
    );
  }

  async function load() {
    Radia.clearError(listError);
    status.textContent = "Cargando casos…";
    try {
      const data = await Radia.api("GET", "/analyst/cases");
      casesBox.replaceChildren(...data.cases.map(renderCase));
      status.textContent = data.cases.length
        ? `${data.cases.length} caso(s) por revisar.`
        : "No hay casos pendientes.";
    } catch (err) {
      status.textContent = "";
      Radia.showError(listError, err);
    }
  }

  result.setAttribute("tabindex", "-1");
  document.getElementById("refresh").addEventListener("click", () => {
    result.hidden = true;
    load();
  });
  load();
})();
