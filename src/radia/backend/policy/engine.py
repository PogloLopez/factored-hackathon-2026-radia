"""Motor de la política sintética de elegibilidad (C7).

`RulesPolicy.decide` es una función pura: misma entrada, misma decisión. No lee
archivos ni el reloj; las reglas se cargan una vez al construir la clase.

Orden (ver [[propuesta]], sección 4):
1. Exclusiones: cliente no activo o mora vigente alta. No elegible, sin cupo.
   Si pide humano o disputa, va al asesor (sin cupo).
2. Exposición: la del producto; un monto pedido sobre el tope la sube un nivel.
3. Nivel base: matriz banda x exposición. Sin puntaje, analista (missing_data).
4. Excepciones: suman analista y/o asesor. Nunca bajan el nivel.
5. Cupo: predicción recortada al tope del producto. Sin predicción no hay
   automático.

Un nivel se ve como dos banderas, analista y asesor. Las excepciones solo
prenden banderas, así nunca bajan el nivel. `not_eligible` va aparte: solo
una disputa o un pedido de humano lo llevan al asesor, siempre sin cupo.
"""

from radia.backend.policy.rules import (
    DEFAULT_RULES_PATH,
    EXPOSURE_ORDER,
    PolicyRules,
    load_rules,
)
from radia.contracts.common import AttentionLevel, Band, Exposure, ProductCode
from radia.contracts.policy import PolicyDecision, PolicyInput

# Nivel -> (analista, asesor). `not_eligible` no está: se trata aparte.
_FLAGS: dict[AttentionLevel, tuple[bool, bool]] = {
    AttentionLevel.AUTOMATIC: (False, False),
    AttentionLevel.ANALYST: (True, False),
    AttentionLevel.ADVISOR: (False, True),
    AttentionLevel.ANALYST_AND_ADVISOR: (True, True),
}
_LEVEL = {flags: level for level, flags in _FLAGS.items()}


class RulesPolicy:
    """Política de reglas versionadas en YAML. Cumple `EligibilityPolicy`."""

    def __init__(self, rules: PolicyRules | None = None) -> None:
        self.rules = rules if rules is not None else load_rules(DEFAULT_RULES_PATH)
        self.version = self.rules.policy_version

    def decide(self, policy_input: PolicyInput) -> PolicyDecision:
        rules = self.rules
        inp = policy_input
        req = inp.request
        product = rules.products[req.product_code]
        reasons: list[str] = []
        alerts: list[str] = []

        exposure = product.exposure
        if (
            req.requested_amount_usd is not None
            and req.requested_amount_usd > product.max_limit_usd
        ):
            exposure = _raise_exposure(exposure)
            reasons.append("requested_amount_above_product_max")

        band = rules.band_for(inp.score) if inp.score is not None else None
        preferential = inp.segment in rules.overrides.to_advisor.preferential_segments
        advisor_reasons = self._advisor_reasons(inp, exposure, preferential)

        def build(level: AttentionLevel, **extra) -> PolicyDecision:
            return PolicyDecision(
                customer_id=inp.customer_id,
                product_code=req.product_code,
                attention_level=level,
                score=inp.score,
                band=band,
                exposure=exposure,
                preferential=preferential,
                reasons=_dedup(reasons),
                alerts=_dedup(alerts),
                policy_version=self.version,
                **extra,
            )

        # 1. Exclusiones. La decisión de riesgo es final (nunca hay cupo), pero
        # pedir humano o disputar siempre llega al asesor (propuesta, sección 4).
        exclusion_reasons = self._exclusion_reasons(inp)
        if exclusion_reasons:
            reasons[:0] = exclusion_reasons
            human = [r for r in advisor_reasons if r in _HUMAN_REQUESTS]
            # El resto (p. ej. trato preferencial) viaja como alerta para el orquestador.
            alerts.extend(r for r in advisor_reasons if r not in _HUMAN_REQUESTS)
            if human:
                reasons.extend(human)
                return build(AttentionLevel.ADVISOR)
            return build(AttentionLevel.NOT_ELIGIBLE)

        # 2 y 3. Nivel base.
        if band is None:
            reasons.extend(["missing_data", "missing_score"])
            base = AttentionLevel.ANALYST
        else:
            reasons.extend([f"band_{band}", f"exposure_{exposure}"])
            base = rules.matrix[band][exposure]

        analyst_reasons = self._analyst_reasons(inp)

        # No elegible por matriz: solo lo cambia una disputa o un pedido de humano,
        # que van al asesor sin cupo. Las razones de analista viajan como alertas
        # para que el asesor las vea. El trato preferencial no cambia la decisión
        # de riesgo (propuesta, sección 4), así que no rescata un no elegible.
        if base == AttentionLevel.NOT_ELIGIBLE:
            alternative = (
                self._alternative(band, exposure, req.product_code) if band else None
            )
            advisor_reasons = [
                r for r in advisor_reasons if r != "preferential_segment_exposure"
            ]
            if not advisor_reasons:
                alerts.extend(analyst_reasons)
                return build(base, alternative_product_code=alternative)
            reasons.extend(advisor_reasons)
            alerts.extend(analyst_reasons)
            return build(AttentionLevel.ADVISOR, alternative_product_code=alternative)

        # 4. Excepciones: solo prenden banderas.
        analyst, advisor = _FLAGS[base]
        analyst = analyst or bool(analyst_reasons)
        advisor = advisor or bool(advisor_reasons)
        reasons.extend(analyst_reasons + advisor_reasons)

        # 5. Cupo recortado al tope del producto.
        pred = inp.limit_prediction
        if pred is None:
            if not (analyst or advisor):
                reasons.append("missing_limit_prediction")
                analyst = True
            else:
                alerts.append("missing_limit_prediction")
            return build(_LEVEL[analyst, advisor])

        cap = product.max_limit_usd
        if pred.upper_usd > cap:
            alerts.append("limit_capped_to_product_max")
        return build(
            _LEVEL[analyst, advisor],
            offered_limit_usd=min(pred.suggested_limit_usd, cap),
            negotiation_min_usd=min(pred.lower_usd, cap),
            negotiation_max_usd=min(pred.upper_usd, cap),
            limit_model_version=pred.model_version,
        )

    def _exclusion_reasons(self, inp: PolicyInput) -> list[str]:
        excl = self.rules.exclusions
        found = []
        if inp.customer_status not in excl.customer_status_not_in:
            found.append(f"customer_status_{inp.customer_status.value.lower()}")
        if inp.max_days_past_due > excl.max_current_days_past_due:
            found.append("days_past_due_above_limit")
        return found

    def _analyst_reasons(self, inp: PolicyInput) -> list[str]:
        cfg = self.rules.overrides.to_analyst
        found = []
        if inp.monthly_income_usd is None:
            found.extend(["missing_data", "missing_income"])
        if inp.score is not None and any(
            abs(inp.score - t) <= cfg.score_gray_zone_points
            for t in self.rules.band_thresholds()
        ):
            found.append("score_in_gray_zone")
        declared = inp.request.declared_monthly_income_usd
        registered = inp.monthly_income_usd
        if declared is not None and registered is not None:
            diff_pct = abs(declared - registered) / registered * 100
            if diff_pct > cfg.declared_income_differs_pct:
                found.append("declared_income_mismatch")
        risk = inp.risk_estimate
        if risk is not None and risk.prob_delinquent_30p >= cfg.prob_delinquent_30p_gte:
            found.append("risk_model_discrepancy")
        return found

    def _advisor_reasons(
        self, inp: PolicyInput, exposure: Exposure, preferential: bool
    ) -> list[str]:
        cfg = self.rules.overrides.to_advisor
        found = []
        if inp.request.customer_requests_human:
            found.append("customer_requests_human")
        if inp.request.customer_disputes_rejection:
            found.append("customer_disputes_rejection")
        if preferential and exposure in cfg.preferential_exposure_in:
            found.append("preferential_segment_exposure")
        return found

    def _alternative(
        self, band: Band, exposure: Exposure, requested: ProductCode
    ) -> ProductCode | None:
        """Producto de menor exposición que la matriz permite para la banda.

        Nunca el mismo producto pedido: si el monto subió la exposición, el
        producto base puede caer bajo el filtro y la sugerencia sería absurda.
        """
        rank = EXPOSURE_ORDER.index
        candidates = [
            (
                rank(rule.exposure),
                rule.max_limit_usd,
                list(ProductCode).index(code),
                code,
            )
            for code, rule in self.rules.products.items()
            if code != requested
            and rank(rule.exposure) < rank(exposure)
            and self.rules.matrix[band][rule.exposure] != AttentionLevel.NOT_ELIGIBLE
        ]
        return min(candidates)[-1] if candidates else None


_HUMAN_REQUESTS = frozenset({"customer_requests_human", "customer_disputes_rejection"})


def _raise_exposure(exposure: Exposure) -> Exposure:
    i = EXPOSURE_ORDER.index(exposure)
    return EXPOSURE_ORDER[min(i + 1, len(EXPOSURE_ORDER) - 1)]


def _dedup(codes: list[str]) -> list[str]:
    return list(dict.fromkeys(codes))
