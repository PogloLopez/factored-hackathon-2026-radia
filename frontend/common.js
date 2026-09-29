// Utilidades compartidas de la web de demostración.
// Sin lógica de negocio: solo llama a la API C8 y pinta lo que devuelve.
"use strict";

const Radia = (() => {
  const STORAGE_KEY = "radia.auth";
  // Respaldo en memoria si sessionStorage no está disponible (modo privado, etc.).
  let memoryAuth = null;

  const PRODUCT_LABELS = {
    CC_BASIC: "Tarjeta de crédito básica",
    CC_GOLD: "Tarjeta de crédito oro",
    CC_BLACK: "Tarjeta de crédito black",
    PERSONAL_LOAN: "Préstamo personal",
    MORTGAGE: "Crédito hipotecario",
  };

  const LEVEL_LABELS = {
    automatic: "Automático",
    analyst: "Revisión de analista",
    advisor: "Asesor en vivo",
    analyst_and_advisor: "Analista y luego asesor",
    not_eligible: "No elegible",
  };

  const STATE_LABELS = {
    idle: "En conversación",
    awaiting_confirmation: "Esperando tu confirmación",
    done: "Acción completada",
    handoff: "Traspasado a una persona",
  };

  const STATUS_LABELS = {
    pending: "Pendiente",
    approved: "Aprobado",
    rejected: "Rechazado",
    info_requested: "Información pedida",
  };

  const ROLE_PAGES = {
    customer: "/web/customer.html",
    analyst: "/web/analyst.html",
    advisor: "/web/advisor.html",
  };

  // --- Token: solo en memoria de la pestaña, nunca en la URL ---------------

  // Devuelve false si el navegador no permite sessionStorage: la sesión no
  // sobreviviría al cambio de página y el login quedaría en un bucle mudo.
  function saveAuth(auth) {
    memoryAuth = auth;
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(auth));
      return true;
    } catch {
      return false;
    }
  }

  function loadAuth() {
    if (memoryAuth) return memoryAuth;
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY);
      memoryAuth = raw ? JSON.parse(raw) : null;
    } catch {
      memoryAuth = null;
    }
    return memoryAuth;
  }

  function clearAuth() {
    memoryAuth = null;
    try {
      sessionStorage.clear();
    } catch {
      // Nada que limpiar.
    }
  }

  function storeGet(key) {
    try {
      return sessionStorage.getItem(key);
    } catch {
      return null;
    }
  }

  function storeSet(key, value) {
    try {
      if (value === null) sessionStorage.removeItem(key);
      else sessionStorage.setItem(key, value);
    } catch {
      // Sin sessionStorage: se pierde al recargar, no pasa nada grave.
    }
  }

  // Exige sesión con el rol de la página. Si no, vuelve al login.
  function requireRole(role) {
    const auth = loadAuth();
    if (!auth || auth.role !== role) {
      window.location.replace("/");
      return null;
    }
    const logout = document.getElementById("logout");
    if (logout) {
      logout.addEventListener("click", () => {
        clearAuth();
        window.location.replace("/");
      });
    }
    return auth;
  }

  // --- API -----------------------------------------------------------------

  class ApiError extends Error {
    constructor(status, detail) {
      super(detail);
      this.status = status;
    }
  }

  // El detalle de FastAPI es texto o una lista de errores de validación.
  function formatDetail(detail) {
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((d) => {
          const field = Array.isArray(d.loc) ? d.loc.slice(1).join(".") : "";
          return field ? `${field}: ${d.msg}` : d.msg;
        })
        .join(" · ");
    }
    return "Error inesperado.";
  }

  async function api(method, path, body) {
    const headers = { Accept: "application/json" };
    const auth = loadAuth();
    if (auth) headers.Authorization = `Bearer ${auth.access_token}`;
    if (body !== undefined) headers["Content-Type"] = "application/json";

    let response;
    try {
      response = await fetch(path, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch {
      throw new ApiError(0, "No hay conexión con el servidor.");
    }

    let data = null;
    try {
      data = await response.json();
    } catch {
      data = null;
    }
    if (!response.ok) {
      const detail = data && data.detail !== undefined ? formatDetail(data.detail) : response.statusText;
      // Token vencido o inválido en una página interna: de vuelta al login.
      if (response.status === 401 && auth) {
        clearAuth();
        window.location.replace("/");
      }
      throw new ApiError(response.status, `${response.status}: ${detail}`);
    }
    return data;
  }

  // --- Pintado seguro (textContent, nunca innerHTML con datos) --------------

  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (value === null || value === undefined || value === false) continue;
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else node.setAttribute(key, value === true ? "" : value);
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined) continue;
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  function showError(target, error) {
    target.textContent = error instanceof Error ? error.message : String(error);
    target.hidden = false;
  }

  function clearError(target) {
    target.textContent = "";
    target.hidden = true;
  }

  function usd(amount) {
    if (amount === null || amount === undefined) return "—";
    return new Intl.NumberFormat("es-419", {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: 2,
    }).format(amount);
  }

  function dateTime(value) {
    if (!value) return "—";
    const date = new Date(value);
    return Number.isNaN(date.getTime())
      ? value
      : date.toLocaleString("es-419", { dateStyle: "medium", timeStyle: "short" });
  }

  function label(map, value) {
    return map[value] || value || "—";
  }

  function list(items, empty) {
    if (!items || items.length === 0) return el("p", { class: "muted", text: empty });
    return el("ul", {}, items.map((item) => el("li", { text: item })));
  }

  // Par término / valor para listas <dl>.
  function pair(term, value) {
    return [el("dt", { text: term }), el("dd", {}, value)];
  }

  // Expediente C9 del caso: lo comparten la bandeja del analista y el asesor.
  function renderCaseFile(c) {
    const d = c.policy_decision;
    const decision = d
      ? el(
          "dl",
          { class: "facts" },
          pair("Producto", label(PRODUCT_LABELS, d.product_code)),
          pair("Nivel de atención", label(LEVEL_LABELS, d.attention_level)),
          pair("Puntaje", d.score === null ? "—" : `${d.score} (banda ${d.band})`),
          pair("Exposición", d.exposure),
          pair("Cupo ofrecido", usd(d.offered_limit_usd)),
          pair("Rango de negociación", `${usd(d.negotiation_min_usd)} a ${usd(d.negotiation_max_usd)}`),
          pair("Alternativa", d.alternative_product_code ? label(PRODUCT_LABELS, d.alternative_product_code) : "—"),
          pair("Preferencial", d.preferential ? "Sí" : "No"),
          pair("Razones", d.reasons.join(", ") || "—"),
          pair("Versión de política", d.policy_version),
        )
      : el("p", { class: "muted", text: "Sin decisión de política adjunta." });

    const alerts = d && d.alerts.length ? d.alerts : [];
    const breakdown = Object.entries(c.score_breakdown || {}).map(([k, v]) => `${k}: ${v}`);

    return el(
      "div",
      { class: "case-file" },
      el(
        "dl",
        { class: "facts" },
        pair("Cliente", c.customer_id),
        pair("Prioridad", c.priority === "high" ? "Alta" : "Normal"),
        pair("Estado", label(STATUS_LABELS, c.status)),
        pair("Motivo", c.trigger_reason),
        pair("Creado", dateTime(c.created_at)),
      ),
      el("p", {}, el("strong", { text: "Solicitud: " }), c.request_summary),
      el("h4", { text: "Hechos verificados" }),
      list(c.verified_facts, "Sin hechos verificados."),
      el("h4", { text: "Decisión de política (sintética)" }),
      decision,
      el("h4", { text: "Alertas" }),
      alerts.length ? el("ul", { class: "alerts" }, alerts.map((a) => el("li", { text: a }))) : el("p", { class: "muted", text: "Sin alertas." }),
      el("h4", { text: "Desglose del puntaje" }),
      list(breakdown, "Sin desglose."),
      el("h4", { text: "Acciones hechas" }),
      list(c.actions_taken, "Ninguna."),
      el("h4", { text: "Preguntas abiertas" }),
      list(c.open_questions, "Ninguna."),
    );
  }

  return {
    ROLE_PAGES,
    PRODUCT_LABELS,
    LEVEL_LABELS,
    STATE_LABELS,
    STATUS_LABELS,
    ApiError,
    api,
    saveAuth,
    loadAuth,
    clearAuth,
    storeGet,
    storeSet,
    requireRole,
    el,
    showError,
    clearError,
    usd,
    dateTime,
    label,
    list,
    pair,
    renderCaseFile,
  };
})();
