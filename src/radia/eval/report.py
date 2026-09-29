"""Corre la evaluación completa y escribe `results.jsonl` y `report.md`.

- Sistema (Radia) y baseline sobre los mismos casos, `runs` corridas cada uno.
- `results.jsonl`: un `CaseResult` por línea (sistema, corrida, caso), con sus
  traces C11. Sin texto del cliente.
- `report.md`: tabla sistema vs baseline con denominadores, variabilidad
  entre corridas, cortes, casos que fallan y limitaciones.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from radia.backend.agent.llm import LanguageModel
from radia.contracts.eval_case import EvalCase
from radia.eval.baseline import NaiveAssistant
from radia.eval.demo_customers import DEMO_PROFILES
from radia.eval.evidence import UNSAFE_BEHAVIORS, SystemName
from radia.eval.metrics import (
    CaseResult,
    Rate,
    SystemMetrics,
    failure_reasons,
    judge,
    runs_identical,
    slice_by,
    system_metrics,
)
from radia.eval.runner import EvalRunner

SLICES = {
    "category": "categoría",
    "language": "idioma",
    "segment": "segmento del cliente",
    "split": "split",
}


@dataclass(frozen=True)
class Evaluation:
    cases: list[EvalCase]
    runs: int
    results: list[CaseResult]

    def of(self, system: SystemName, run_index: int | None = None) -> list[CaseResult]:
        return [
            r
            for r in self.results
            if r.system == system and (run_index is None or r.run_index == run_index)
        ]

    def metrics(self, system: SystemName, run_index: int = 0) -> SystemMetrics:
        return system_metrics(self.of(system, run_index))


def evaluate(
    cases: Sequence[EvalCase], runs: int = 3, llm: LanguageModel | None = None
) -> Evaluation:
    """Corre sistema y baseline `runs` veces sobre los mismos casos."""
    if runs < 1:
        raise ValueError("runs debe ser al menos 1")
    runner = EvalRunner(llm)
    baseline = NaiveAssistant(runner)
    by_id = {c.case_id: c for c in cases}
    results = []
    for run_index in range(runs):
        for evidence in [
            *runner.run(cases, run_index),
            *baseline.run(cases, run_index),
        ]:
            results.append(judge(evidence, by_id[evidence.case_id]))
    return Evaluation(cases=list(cases), runs=runs, results=results)


def write_results(evaluation: Evaluation, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for result in evaluation.results:
            fh.write(result.model_dump_json() + "\n")


def write_outputs(
    evaluation: Evaluation, out_dir: Path, split: str, started_at: datetime
) -> tuple[Path, Path]:
    """Escribe `results.jsonl` y `report.md` en `out_dir`."""
    results_path = out_dir / "results.jsonl"
    report_path = out_dir / "report.md"
    write_results(evaluation, results_path)
    report_path.write_text(
        render_report(evaluation, split, started_at), encoding="utf-8"
    )
    return results_path, report_path


# --- Markdown -----------------------------------------------------------------


def _ms(value: float | None) -> str:
    return "no definido" if value is None else f"{value:,.2f} ms"


def _usd(value: float | None) -> str:
    return "no definido" if value is None else f"{value:,.6f} USD"


def _table(header: Sequence[str], rows: Sequence[Sequence[object]]) -> list[str]:
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return lines


def _versions(results: Sequence[CaseResult]) -> str:
    pairs = sorted({(r.llm_model, r.prompt_version) for r in results})
    return ", ".join(f"`{m}` / `{p}`" for m, p in pairs)


def _policy_versions(results: Sequence[CaseResult]) -> str:
    versions = sorted(
        {t.policy_version for r in results for t in r.traces if t.policy_version}
    )
    return ", ".join(f"`{v}`" for v in versions) or "ninguna citada"


def _main_table(ours: SystemMetrics, theirs: SystemMetrics) -> list[str]:
    def row(name: str, a: Rate, b: Rate, note: str) -> list[object]:
        return [name, a, b, note]

    rows = [
        row("Casos que pasan", ours.passed, theirs.passed, "todos los casos"),
        row(
            "Resolución automática segura",
            ours.safe_auto_resolution,
            theirs.safe_auto_resolution,
            "todos los casos en alcance",
        ),
        row(
            "Resolución automática segura (elegibles)",
            ours.safe_auto_resolution_eligible,
            theirs.safe_auto_resolution_eligible,
            "casos con nivel esperado automático",
        ),
        row(
            "Automatización intentada",
            ours.automation_attempted,
            theirs.automation_attempted,
            "todos los casos",
        ),
        row("Contención", ours.containment, theirs.containment, "todos los casos"),
        row(
            "Handoffs faltantes",
            ours.handoff_missed,
            theirs.handoff_missed,
            "casos que exigen handoff",
        ),
        row(
            "Handoffs innecesarios",
            ours.handoff_unnecessary,
            theirs.handoff_unnecessary,
            "casos resolubles sin humano",
        ),
        row(
            "Handoffs correctos (tipo y contexto)",
            ours.handoff_correct,
            theirs.handoff_correct,
            "casos que exigen handoff",
        ),
        row(
            "Expediente con contexto útil",
            ours.handoff_context_useful,
            theirs.handoff_context_useful,
            "casos con handoff",
        ),
        row(
            "Nivel de atención correcto",
            ours.level_ok,
            theirs.level_ok,
            "casos con nivel esperado",
        ),
        row(
            "**Casos con resultado inseguro**",
            ours.unsafe_cases,
            theirs.unsafe_cases,
            "todos los casos",
        ),
    ]
    for behavior in sorted(UNSAFE_BEHAVIORS):
        key = behavior.value
        rows.append(
            row(
                f"  inseguro: `{key}`",
                ours.unsafe_by_behavior[key],
                theirs.unsafe_by_behavior[key],
                "todos los casos",
            )
        )
    rows += [
        [
            "Latencia por caso p50 / p95",
            f"{_ms(ours.latency_p50_ms)} / {_ms(ours.latency_p95_ms)}",
            f"{_ms(theirs.latency_p50_ms)} / {_ms(theirs.latency_p95_ms)}",
            f"{ours.n_cases} casos",
        ],
        [
            "Latencia por turno p50 / p95",
            f"{_ms(ours.turn_latency_p50_ms)} / {_ms(ours.turn_latency_p95_ms)}",
            f"{_ms(theirs.turn_latency_p50_ms)} / {_ms(theirs.turn_latency_p95_ms)}",
            "todos los turnos",
        ],
        [
            "Costo total",
            _usd(ours.total_cost_usd),
            _usd(theirs.total_cost_usd),
            "LLM, ver supuestos",
        ],
        [
            "Costo por caso",
            _usd(ours.cost_per_case_usd),
            _usd(theirs.cost_per_case_usd),
            f"costo total / todos los casos ({ours.n_cases})",
        ],
        [
            "Costo por resolución automática exitosa",
            _usd(ours.cost_per_resolution_usd),
            _usd(theirs.cost_per_resolution_usd),
            (
                "costo total / resoluciones automáticas seguras (Radia "
                f"{ours.safe_auto_resolution.numerator}, baseline "
                f"{theirs.safe_auto_resolution.numerator})"
            ),
        ],
    ]
    return _table(["Métrica", "Radia", "Baseline", "Denominador"], rows)


def _variability(evaluation: Evaluation) -> list[str]:
    lines = []
    for system in SystemName:
        per_run = [evaluation.metrics(system, i) for i in range(evaluation.runs)]
        same = runs_identical(evaluation.of(system))
        verdict = "idénticas caso a caso" if same else "distintas en al menos un caso"
        lines.append(
            f"- **{system.value}**: {evaluation.runs} corrida(s), {verdict}. "
            f"Pasan por corrida: {', '.join(str(m.passed) for m in per_run)}. "
            f"Latencia p50 por corrida: "
            f"{', '.join(_ms(m.latency_p50_ms) for m in per_run)}."
        )
    lines.append(
        "- Con el modelo falso (reglas deterministas) las corridas son idénticas "
        "por construcción. Solo varía la latencia. La variabilidad real se mide "
        "con un LLM real."
    )
    return lines


def _slices(evaluation: Evaluation) -> list[str]:
    lines = []
    ours = evaluation.of(SystemName.RADIA, 0)
    theirs = evaluation.of(SystemName.BASELINE, 0)
    for field, title in SLICES.items():
        base = {row.key: row for row in slice_by(theirs, field)}
        rows = [
            [
                row.key,
                row.n,
                row.passed,
                row.unsafe,
                row.containment,
                base[row.key].passed,
                base[row.key].unsafe,
            ]
            for row in slice_by(ours, field)
        ]
        lines += [f"### Por {title}", ""]
        lines += _table(
            [
                title.capitalize(),
                "n",
                "Radia pasa",
                "Radia inseguro",
                "Radia contención",
                "Baseline pasa",
                "Baseline inseguro",
            ],
            rows,
        )
        lines.append("")
    return lines


def _failures(results: Sequence[CaseResult]) -> list[str]:
    failed = [r for r in results if not r.passed]
    if not failed:
        return ["Ningún caso falla en esta corrida."]
    rows = [[r.case_id, r.category, "; ".join(r.reasons)] for r in failed]
    return _table(["Caso", "Categoría", "Motivos"], rows)


def _reasons(results: Sequence[CaseResult]) -> list[str]:
    counts = failure_reasons(results)
    if not counts:
        return ["Sin motivos de falla."]
    return _table(["Motivo", "Casos"], counts.most_common())


def render_report(evaluation: Evaluation, split: str, started_at: datetime) -> str:
    cases = evaluation.cases
    ours_all = evaluation.of(SystemName.RADIA)
    theirs_all = evaluation.of(SystemName.BASELINE)
    ours = evaluation.metrics(SystemName.RADIA)
    theirs = evaluation.metrics(SystemName.BASELINE)
    categories = Counter(c.category.value for c in cases)
    languages = Counter(c.language.value for c in cases)
    failures = Counter(
        c.inject_failure.value if c.inject_failure else "ninguna" for c in cases
    )
    no_session = sum(c.customer_id is None for c in cases)

    lines = [
        f"# Evaluación de Radia: split `{split}`",
        "",
        (
            "> Medición **offline** sobre casos escritos por el equipo y clientes demo "
            "sintéticos. Es una simulación, no una mejora medida en producción."
        ),
        "",
        "## Configuración",
        "",
        f"- Fecha de la corrida (UTC): {started_at:%Y-%m-%d %H:%M:%S}.",
        (
            f"- Casos: {len(cases)} del split `{split}`. Corridas por configuración: "
            f"{evaluation.runs}."
        ),
        f"- Modelo y prompt de Radia: {_versions(ours_all)}.",
        f"- Modelo y prompt del baseline: {_versions(theirs_all)}.",
        f"- Versión de política citada en los traces: {_policy_versions(ours_all)}.",
        "- Contrato de casos C10 y tracing C11: `radia.contracts`.",
        "",
        "## Muestra",
        "",
        f"- Por categoría: {dict(sorted(categories.items()))}.",
        f"- Por idioma: {dict(sorted(languages.items()))}.",
        f"- Falla inyectada: {dict(sorted(failures.items()))}.",
        f"- Sin sesión autenticada: {no_session}.",
        (
            "- Etiquetas: comportamiento esperado escrito a mano por caso "
            "(nivel de atención, `must`, `must_not`). Sin revisión de un segundo "
            "anotador."
        ),
        "",
        "## Sistema vs baseline (corrida 0)",
        "",
        "Formato: casos que cumplen / denominador (porcentaje).",
        "",
        *_main_table(ours, theirs),
        "",
        (
            "Cero resultados inseguros observados en una muestra chica **no** "
            "demuestra riesgo cero."
        ),
        "",
        "## Variabilidad entre corridas",
        "",
        *_variability(evaluation),
        "",
        "## Cortes (corrida 0)",
        "",
        *_slices(evaluation),
        "## Casos que fallan en Radia (corrida 0)",
        "",
        *_failures(evaluation.of(SystemName.RADIA, 0)),
        "",
        "## Motivos de falla (corrida 0)",
        "",
        "### Radia",
        "",
        *_reasons(evaluation.of(SystemName.RADIA, 0)),
        "",
        "### Baseline",
        "",
        *_reasons(evaluation.of(SystemName.BASELINE, 0)),
        "",
        "## Supuestos de latencia y costo",
        "",
        (
            "- Latencia: reloj de pared medido por el runner alrededor de cada "
            "mensaje y confirmación, en proceso, sin red ni API HTTP."
        ),
        (
            "- Costo: tokens reportados por el LLM por los precios de "
            "`GroqLanguageModel` (provisionales). El modelo falso no gasta: costo 0."
        ),
        (
            "- El baseline es una simulación determinista sin LLM: su costo y "
            "latencia no representan a un LLM real."
        ),
        (
            '- Costo por resolución: "no definido" si no hay resoluciones '
            "automáticas exitosas."
        ),
        "",
        "## Limitaciones",
        "",
        (
            "- **Modelo falso.** La comprensión es por reglas (`FakeLanguageModel`). "
            "No mide la calidad de un LLM real ni su variabilidad."
        ),
        (
            f"- **Clientes demo sintéticos.** {len(DEMO_PROFILES)} clientes escritos "
            "a mano, uno por "
            "celda de la política y excepción. No son clientes del dataset."
        ),
        (
            "- **Pesos provisionales.** Puntaje, bandas y topes de la política son "
            "provisionales hasta el checkpoint de Pablo."
        ),
        (
            "- **Tasas de cambio fijas.** Montos en moneda local se convierten con "
            "tasas redondas de fixture."
        ),
        (
            "- **Sin sesión.** Se simula la puerta de autenticación de la API: "
            "rechaza antes del orquestador."
        ),
        (
            "- **Confirmación automática.** El runner acepta toda confirmación "
            "pedida para medir la acción de punta a punta."
        ),
        (
            "- **Muestra chica.** Cortes por idioma y segmento con pocos casos: "
            "las diferencias no son concluyentes."
        ),
        ("- **Portugués e inglés.** Pocos casos; la cobertura de idiomas es limitada."),
        (
            "- **Baseline simulado.** Un LLM libre real puede portarse distinto; el "
            "baseline sirve para mostrar qué pasa sin política ni permisos."
        ),
        "",
    ]
    return "\n".join(lines)
