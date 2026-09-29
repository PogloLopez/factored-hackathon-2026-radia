// Cliente: cuenta resumida y ofertas vigentes (GET /customers/me/offers).
"use strict";

(() => {
  const auth = Radia.requireRole("customer");
  if (!auth) return;
  const { el, pair } = Radia;

  const summary = document.getElementById("summary");
  const offersBox = document.getElementById("offers");
  const status = document.getElementById("offers-status");
  const error = document.getElementById("offers-error");

  function renderSummary(offers) {
    summary.replaceChildren(
      ...pair("Cliente", auth.customer_id),
      ...pair("Sesión vence", Radia.dateTime(auth.expires_at)),
      ...pair("Ofertas vigentes", String(offers.length)),
    );
  }

  function renderOffer(offer, highlighted) {
    const title = el("h3", {}, Radia.label(Radia.PRODUCT_LABELS, offer.product_code));
    return el(
      "article",
      { class: highlighted ? "card highlighted" : "card", "aria-label": highlighted ? "Oferta sugerida" : null },
      highlighted ? el("p", {}, el("span", { class: "badge", text: "Sugerida para ti" })) : null,
      title,
      el(
        "dl",
        { class: "facts" },
        pair("Cupo", Radia.usd(offer.offered_limit_usd)),
        pair("Atención", Radia.label(Radia.LEVEL_LABELS, offer.attention_level)),
        offer.alternative_product_code
          ? pair("Alternativa", Radia.label(Radia.PRODUCT_LABELS, offer.alternative_product_code))
          : [],
        offer.preferential ? pair("Trato", "Preferencial") : [],
        pair("Vence", Radia.dateTime(offer.expires_at)),
      ),
      offer.reasons.length ? el("p", { class: "muted" }, "Razones: ", offer.reasons.join(", ")) : null,
    );
  }

  async function load() {
    try {
      const data = await Radia.api("GET", "/customers/me/offers");
      renderSummary(data.offers);
      // La sugerida primero; el orden del resto lo da la API.
      const sorted = [...data.offers].sort(
        (a, b) => (b.offer_id === data.highlighted_offer_id) - (a.offer_id === data.highlighted_offer_id),
      );
      offersBox.replaceChildren(...sorted.map((o) => renderOffer(o, o.offer_id === data.highlighted_offer_id)));
      status.textContent = data.offers.length
        ? `${data.offers.length} oferta(s) vigente(s).`
        : "No tienes ofertas vigentes. Puedes preguntar en el chat por qué.";
    } catch (err) {
      renderSummary([]);
      status.textContent = "";
      Radia.showError(error, err);
    }
  }

  load();
})();
