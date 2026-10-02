"""Tests de la auditoría de señal con DataFrames sintéticos (sin datos reales)."""

import numpy as np
import pandas as pd
import pytest

from radia.config import Settings
from radia.etl.offers import write_parquet
from radia.etl.silver import silver_path
from radia.ml import signal_audit
from radia.ml.signal_audit import (
    _categorical,
    _con,
    _either_direction,
    audit_calls,
    audit_campaigns,
    audit_intent,
    cv_auc,
    rate_table_auc,
    run_audit,
)

N = 2000


def _rng():
    return np.random.default_rng(42)


def test_cv_auc_cerca_de_azar_con_etiqueta_independiente():
    rng = _rng()
    x = pd.DataFrame({"a": rng.normal(size=N), "b": rng.normal(size=N)})
    y = pd.Series(rng.random(N) < 0.3)
    assert abs(cv_auc(x, y) - 0.5) < 0.08


def test_cv_auc_cerca_de_uno_con_etiqueta_determinada_por_feature():
    rng = _rng()
    a = rng.normal(size=N)
    x = pd.DataFrame({"a": a, "ruido": rng.normal(size=N)})
    assert cv_auc(x, pd.Series(a > 0)) > 0.95


def test_cv_auc_una_sola_clase_lanza_value_error():
    x = pd.DataFrame({"a": np.arange(50.0)})
    with pytest.raises(ValueError, match="una sola clase"):
        cv_auc(x, pd.Series([True] * 50))


def test_rate_table_auc_alto_cuando_la_etiqueta_depende_del_grupo():
    rng = _rng()
    groups = pd.Series(rng.choice(["a", "b", "c", "d"], size=N))
    p = groups.map({"a": 0.05, "b": 0.3, "c": 0.7, "d": 0.95}).to_numpy()
    y = pd.Series(rng.random(N) < p)
    assert rate_table_auc(groups, y) > 0.7


def test_rate_table_auc_cerca_de_azar_sin_dependencia():
    rng = _rng()
    groups = pd.Series(rng.choice(["a", "b", "c", "d"], size=N))
    y = pd.Series(rng.random(N) < 0.4)
    assert abs(rate_table_auc(groups, y) - 0.5) < 0.08


def test_categorical_agrupa_en_otras_mas_alla_de_250_categorias():
    # 300 categorías: las 250 más frecuentes se conservan, el resto va a OTRAS.
    values = [f"c{i}" for i in range(300) for _ in range(300 - i)]
    out = _categorical(pd.DataFrame({"cat": values}))["cat"]
    assert out.dtype == "category"
    assert out.nunique() == 251
    assert "OTRAS" in set(out)
    assert (out == "OTRAS").sum() == sum(300 - i for i in range(250, 300))


def test_categorical_deja_numericas_intactas_y_no_muta_la_entrada():
    x = pd.DataFrame({"num": [1.0, 2.0, 3.0], "txt": ["a", None, "b"]})
    out = _categorical(x)
    pd.testing.assert_series_equal(out["num"], x["num"])
    assert "NA" in set(out["txt"])
    assert x["txt"].isna().any()


def test_run_audit_anota_error_cuando_falta_gold(tmp_path):
    out = run_audit(_settings(tmp_path), ["limit"])
    assert "falta Gold" in out["limit"]["error"]


def test_run_audit_anota_error_cuando_falta_silver(tmp_path):
    s = Settings(_env_file=None, data_dir=tmp_path / "data")
    names = ["delinquency", "intent", "calls", "transactions", "churn"]
    out = run_audit(s, names)
    assert list(out) == names
    for name in names:
        assert "error" in out[name]


def _settings(tmp_path):
    return Settings(
        _env_file=None, data_dir=tmp_path / "data", raw_dir=tmp_path / "raw"
    )


def test_either_direction_refleja_auc_bajo_y_conserva_auc_alto():
    assert _either_direction(0.3) == pytest.approx(0.7)
    assert _either_direction(0.8) == 0.8


def test_con_fija_un_solo_hilo(tmp_path):
    s = _settings(tmp_path)
    write_parquet(pd.DataFrame({"customer_id": [1]}), silver_path(s, "customers"))
    con = _con(s, ("customers",))
    assert int(con.execute("SELECT current_setting('threads')").fetchone()[0]) == 1


def test_con_falta_silver_lanza_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError, match="falta Silver"):
        _con(_settings(tmp_path), ("customers",))


def test_audit_campaigns_sin_csv_lanza_file_not_found(tmp_path):
    s = _settings(tmp_path)
    (s.raw_dir / "data" / "campaign_sends").mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match="campaign_sends"):
        audit_campaigns(s)
    assert "error" in run_audit(s, ["campaigns"])["campaigns"]


def test_audit_campaigns_sin_marketing_campaigns_lanza_file_not_found(tmp_path):
    s = _settings(tmp_path)
    sends = s.raw_dir / "data" / "campaign_sends"
    sends.mkdir(parents=True)
    (sends / "a.csv").write_text("campaign_id,customer_id\n1,1\n")
    write_parquet(pd.DataFrame({"customer_id": [1]}), silver_path(s, "customers"))
    with pytest.raises(FileNotFoundError, match="marketing_campaigns"):
        audit_campaigns(s)
    out = run_audit(s, ["campaigns"])
    assert "marketing_campaigns" in out["campaigns"]["error"]


def test_audit_intent_sin_textos_frecuentes_devuelve_nan(tmp_path):
    s = _settings(tmp_path)
    ids = list(range(10))
    write_parquet(
        pd.DataFrame(
            {"interaction_id": ids, "customer_text": [f"t{i % 3}" for i in ids]}
        ),
        silver_path(s, "call_transcripts"),
    )
    write_parquet(
        pd.DataFrame(
            {"interaction_id": ids, "reason_category": ["Queja", "Saldo"] * 5}
        ),
        silver_path(s, "call_center_interactions"),
    )
    out = audit_intent(s)
    assert out["rows"] == 10
    assert out["distinct_texts"] == 3
    assert np.isnan(out["max_gap_label_share_vs_overall"])


def test_audit_calls_excluye_was_resolved_nulo(tmp_path, monkeypatch):
    monkeypatch.setattr(signal_audit, "SAMPLE", 1000)
    s = _settings(tmp_path)
    rng = _rng()
    n = 90
    resolved = pd.array(rng.random(n) < 0.5, dtype="boolean")
    resolved[:10] = pd.NA
    df = pd.DataFrame(
        {
            "interaction_type": rng.choice(["Inbound", "Outbound"], n),
            "channel": rng.choice(["Phone", "Chat"], n),
            "reason_category": rng.choice(["Queja", "Saldo", "Tarjeta"], n),
            "wait_time_seconds": rng.integers(0, 300, n),
            "customer_detected_accent": rng.choice(["MX", "CO"], n),
            "was_resolved": resolved,
            "requires_followup": rng.random(n) < 0.5,
            "was_escalated": rng.random(n) < 0.5,
            "detected_sentiment": rng.choice(["Negativo", "Neutro"], n),
        }
    )
    write_parquet(df, silver_path(s, "call_center_interactions"))
    out = audit_calls(s)
    assert out["resolved_first_contact"]["n"] == 80
    for name in ("negative_sentiment", "requires_followup", "escalated"):
        assert out[name]["n"] == n
        assert out["resolved_first_contact"]["n"] < out[name]["n"]
