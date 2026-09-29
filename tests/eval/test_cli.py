"""Tests del comando `radia-eval run` y del reporte que escribe."""

import json
import tempfile
from pathlib import Path

from typer.testing import CliRunner

from radia.eval.cli import app

runner = CliRunner()


def test_run_escribe_resultados_y_reporte():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        out = Path(tmp) / "salida"
        result = runner.invoke(
            app, ["run", "--split", "dev", "--runs", "2", "--out-dir", str(out)]
        )
        assert result.exit_code == 0, result.output
        lines = (out / "results.jsonl").read_text(encoding="utf-8").splitlines()
        rows = [json.loads(line) for line in lines]
        report = (out / "report.md").read_text(encoding="utf-8")

    n_cases = len({r["case_id"] for r in rows})
    # Dos sistemas, dos corridas, todos los casos dev.
    assert len(rows) == 2 * 2 * n_cases
    assert {r["system"] for r in rows} == {"radia", "baseline"}
    assert {r["run_index"] for r in rows} == {0, 1}
    assert all(r["traces"] for r in rows)
    for section in (
        "## Sistema vs baseline",
        "Resolución automática segura",
        "Handoffs faltantes",
        "Handoffs innecesarios",
        "Casos con resultado inseguro",
        "Latencia por caso p50 / p95",
        "Costo por resolución automática exitosa",
        "## Variabilidad entre corridas",
        "idénticas caso a caso",
        "### Por idioma",
        "## Limitaciones",
    ):
        assert section in report, section
    assert f"/{n_cases} (" in report  # denominadores explícitos


def test_split_invalido_falla():
    result = runner.invoke(app, ["run", "--split", "prod"])
    assert result.exit_code != 0
