"""Tests del job de ofertas vigentes (C6) con mocks de C1 y C3 y la política real."""

import json
import tempfile
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from radia.backend.policy.engine import RulesPolicy
from radia.config import Settings
from radia.contracts.common import AttentionLevel, ProductCode
from radia.contracts.data import validate
from radia.contracts.data.active_offers import ActiveOffers
from radia.contracts.data.gold_features import make_gold_features
from radia.contracts.data.internal_score import make_internal_scores
from radia.etl import cli
from radia.etl.offers import build_offers, read_parquet, run_offers_job, write_parquet
from radia.ml.baseline import IncomeMultipleBaseline

GENERATED_AT = datetime(2026, 6, 17, 6, 0, tzinfo=UTC)
POLICY = RulesPolicy()


@pytest.fixture(scope="module")
def inputs():
    features = make_gold_features(n=300, seed=1)
    return features, make_internal_scores(features, seed=1)


@pytest.fixture(scope="module")
def offers(inputs):
    features, scores = inputs
    return build_offers(
        features, scores, IncomeMultipleBaseline(), POLICY, GENERATED_AT
    )


def test_salida_cumple_c6(offers):
    validate(ActiveOffers, offers)
    assert offers["synthetic_policy"].all()
    assert (offers["policy_version"] == POLICY.version).all()


def test_una_fila_por_cliente_y_producto(inputs, offers):
    features, _ = inputs
    assert len(offers) == len(features) * len(ProductCode)
    assert not offers.duplicated(["customer_id", "product_code"]).any()
    assert set(offers["product_code"]) == {p.value for p in ProductCode}


def test_sin_puntaje_nunca_automatico(offers):
    no_score = offers[offers["score"].isna()]
    assert len(no_score) > 0
    assert (no_score["attention_level"] != AttentionLevel.AUTOMATIC).all()


def test_no_elegible_sin_cupo(offers):
    not_eligible = offers[offers["attention_level"] == AttentionLevel.NOT_ELIGIBLE]
    assert len(not_eligible) > 0
    limits = ["offered_limit_usd", "negotiation_min_usd", "negotiation_max_usd"]
    assert not_eligible[limits].isna().all().all()


def test_hay_ofertas_automaticas_con_cupo(offers):
    auto = offers[offers["attention_level"] == AttentionLevel.AUTOMATIC]
    assert len(auto) > 0
    assert auto["offered_limit_usd"].notna().all()
    assert (auto["limit_model_version"] == IncomeMultipleBaseline.version).all()


def test_determinismo(inputs, offers):
    features, scores = inputs
    again = build_offers(
        features, scores, IncomeMultipleBaseline(), RulesPolicy(), GENERATED_AT
    )
    pd.testing.assert_frame_equal(offers, again)
    assert offers["offer_id"].is_unique


def test_offer_id_cambia_con_la_corrida(inputs, offers):
    features, scores = inputs
    later = build_offers(
        features,
        scores,
        IncomeMultipleBaseline(),
        POLICY,
        GENERATED_AT + timedelta(days=1),
    )
    assert set(offers["offer_id"]).isdisjoint(later["offer_id"])


def test_cupo_no_supera_tope_del_producto(offers):
    caps = {
        code.value: rule.max_limit_usd for code, rule in POLICY.rules.products.items()
    }
    cap = offers["product_code"].map(caps)
    for col in ["offered_limit_usd", "negotiation_min_usd", "negotiation_max_usd"]:
        has = offers[col].notna()
        assert (offers.loc[has, col] <= cap[has]).all(), col


def test_vencimiento(offers):
    assert (offers["generated_at"] == pd.Timestamp("2026-06-17 06:00")).all()
    assert (offers["expires_at"] - offers["generated_at"] == pd.Timedelta(days=7)).all()


def test_generated_at_se_normaliza_a_utc(inputs, offers):
    features, scores = inputs
    bogota = timezone(timedelta(hours=-5))
    same_instant = GENERATED_AT.astimezone(bogota)
    other = build_offers(
        features, scores, IncomeMultipleBaseline(), POLICY, same_instant, ttl_days=3
    )
    assert (other["generated_at"] == offers["generated_at"]).all()
    assert (other["expires_at"] - other["generated_at"] == pd.Timedelta(days=3)).all()


def test_generated_at_sin_zona_falla(inputs):
    features, scores = inputs
    with pytest.raises(ValueError, match="zona horaria"):
        build_offers(
            features,
            scores,
            IncomeMultipleBaseline(),
            POLICY,
            datetime(2026, 6, 17),  # noqa: DTZ001
        )


def test_ingreso_cero_es_dato_faltante():
    features = make_gold_features(n=5, seed=2)
    features["monthly_income_usd"] = 0.0
    scores = make_internal_scores(features, seed=2)
    out = build_offers(features, scores, IncomeMultipleBaseline(), POLICY, GENERATED_AT)
    assert out["offered_limit_usd"].isna().all()
    assert (out["attention_level"] != AttentionLevel.AUTOMATIC).all()
    eligible = out[out["attention_level"] != AttentionLevel.NOT_ELIGIBLE]
    assert (
        eligible["reasons_json"].map(lambda r: "missing_income" in json.loads(r)).all()
    )


def test_usa_la_ultima_fecha_de_corte():
    old = make_gold_features(n=4, seed=3, snapshot_date="2026-05-17")
    new = make_gold_features(n=4, seed=4, snapshot_date="2026-06-17")
    features = pd.concat([old, new], ignore_index=True)
    scores = make_internal_scores(features, seed=3)
    out = build_offers(features, scores, IncomeMultipleBaseline(), POLICY, GENERATED_AT)
    assert len(out) == 4 * len(ProductCode)
    # El puntaje de cada oferta es el del corte nuevo, no el viejo.
    newest = scores[scores["snapshot_date"] == pd.Timestamp("2026-06-17")]
    expected = dict(zip(newest["customer_id"], newest["score"], strict=True))
    for customer_id, score in zip(out["customer_id"], out["score"], strict=True):
        assert (pd.isna(score) and pd.isna(expected[customer_id])) or (
            score == expected[customer_id]
        )


@pytest.fixture
def gold_settings():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        settings = Settings(_env_file=None, data_dir=Path(tmp))
        (settings.data_dir / "gold").mkdir()
        yield settings


def _write_inputs(settings: Settings) -> None:
    features = make_gold_features(n=20, seed=5)
    gold = settings.data_dir / "gold"
    write_parquet(features, gold / "customer_features.parquet")
    write_parquet(
        make_internal_scores(features, seed=5), gold / "internal_score.parquet"
    )


def test_job_escribe_c6(gold_settings):
    _write_inputs(gold_settings)
    path = run_offers_job(gold_settings, generated_at=GENERATED_AT)
    assert path == gold_settings.data_dir / "gold" / "active_offers.parquet"
    written = validate(ActiveOffers, read_parquet(path))
    assert len(written) == 20 * len(ProductCode)


def test_job_sin_insumo_falla_claro(gold_settings):
    with pytest.raises(FileNotFoundError, match="customer_features"):
        run_offers_job(gold_settings)


def test_cli_offers(gold_settings, monkeypatch):
    monkeypatch.setattr(cli, "get_settings", lambda: gold_settings)
    runner = CliRunner()
    missing = runner.invoke(cli.app, ["offers"])
    assert missing.exit_code == 1
    _write_inputs(gold_settings)
    result = runner.invoke(cli.app, ["offers"])
    assert result.exit_code == 0, result.output
    assert "active_offers.parquet" in result.output


def test_trazabilidad_de_corte_puntaje_y_exposicion():
    features = make_gold_features(n=5, seed=8)
    scores = make_internal_scores(features, seed=8)
    out = build_offers(features, scores, IncomeMultipleBaseline(), POLICY, GENERATED_AT)
    assert (out["snapshot_date"] == features["snapshot_date"].iloc[0]).all()
    assert set(out["score_version"].dropna()) == set(scores["score_version"])
    assert out["exposure"].notna().all()
