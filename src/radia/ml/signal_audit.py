"""Auditoría de señal: ¿qué etiquetas del dataset se pueden predecir?

Antes de entrenar un modelo hay que saber si la etiqueta depende de algo. Cada
chequeo compara un modelo con un baseline trivial sobre los mismos datos:

- AUC de un gradient boosting con validación cruzada (0.5 = azar).
- Contra una tabla de tasas por una sola columna, cuando la señal viene de ahí.

Lee Silver (y `campaign_sends` crudo, que no tiene spec). Todo es reproducible:
`uv run radia-ml audit` vuelve a calcular cada cifra del reporte.
"""

from collections.abc import Callable
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict

from radia.config import Settings
from radia.etl.bronze import sql_literal
from radia.etl.silver import silver_path

SEED = 0
SAMPLE = 150_000  # filas por chequeo: la señal se ve igual y corre en minutos
NEGATIVE_SENTIMENT = ("Negativo", "Muy Negativo")


def _categorical(x: pd.DataFrame) -> pd.DataFrame:
    x = x.copy()
    for col in x.columns:
        if not pd.api.types.is_numeric_dtype(x[col]) or pd.api.types.is_bool_dtype(
            x[col]
        ):
            values = x[col].astype("string").fillna("NA")
            # El boosting admite hasta 255 categorías: las raras van a "OTRAS".
            top = values.value_counts().index[:250]
            x[col] = values.where(values.isin(top), "OTRAS").astype("category")
    return x


def cv_auc(x: pd.DataFrame, y: pd.Series, folds: int = 3) -> float:
    """AUC fuera de muestra de un gradient boosting. 0.5 es azar."""
    y = y.astype(bool)
    if y.nunique() < 2:
        raise ValueError("la etiqueta tiene una sola clase")
    model = HistGradientBoostingClassifier(
        categorical_features="from_dtype", max_iter=150, random_state=SEED
    )
    cv = StratifiedKFold(folds, shuffle=True, random_state=SEED)
    proba = cross_val_predict(model, _categorical(x), y, cv=cv, method="predict_proba")
    return float(roc_auc_score(y, proba[:, 1]))


def rate_table_auc(groups: pd.Series, y: pd.Series) -> float:
    """AUC de predecir con la tasa de la etiqueta por grupo (ajustada en otra mitad)."""
    rng = np.random.default_rng(SEED)
    train = rng.random(len(y)) < 0.5
    rates = y[train].astype(float).groupby(groups[train]).mean()
    score = groups[~train].map(rates).fillna(y[train].mean())
    return float(roc_auc_score(y[~train].astype(bool), score))


def _either_direction(auc: float) -> float:
    return float(max(auc, 1 - auc))


def _con(settings: Settings, tables: tuple[str, ...]) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    # USING SAMPLE con semilla solo repite la misma muestra con un hilo y orden fijo.
    con.execute("SET threads = 1")
    con.execute("SET preserve_insertion_order = true")
    for t in tables:
        path = silver_path(settings, t)
        if not path.exists():
            raise FileNotFoundError(f"falta Silver de {t}: {path}")
        con.execute(
            f"CREATE VIEW {t} AS SELECT * FROM read_parquet({sql_literal(path)})"
        )
    return con


def audit_limit(settings: Settings) -> dict:
    """Cupo: correlación con cada feature y cuantiles por familia contra el modelo."""
    from radia.etl.offers import read_parquet
    from radia.ml.dataset import (
        NUMERIC_FEATURES,
        TARGET,
        build_training_table,
        split_by_customer,
    )
    from radia.ml.limit_model import QuantileLimitModel
    from radia.ml.metrics import limit_metrics

    gold = settings.data_dir / "gold"
    table = build_training_table(
        read_parquet(gold / "customer_features.parquet"),
        read_parquet(gold / "limit_labels.parquet"),
    )
    table = table[table["monthly_income_usd"] > 0]
    corr = table[[*NUMERIC_FEATURES, TARGET]].corr(method="spearman")[TARGET]
    train, test = split_by_customer(table, seed=SEED)
    q = train.groupby("product_family", observed=True)[TARGET].quantile([0.1, 0.5, 0.9])
    q = q.unstack()
    family = test["product_family"].astype(str)
    naive = pd.DataFrame(
        {
            "lower": family.map(q[0.1]),
            "pred": family.map(q[0.5]),
            "upper": family.map(q[0.9]),
            "y_true": test[TARGET],
        }
    )
    model = QuantileLimitModel(seed=SEED).fit(train)
    pred = model.predict_table(test).assign(y_true=test[TARGET])
    return {
        "max_abs_spearman": float(corr.drop(TARGET).abs().max()),
        "model_mae_usd": limit_metrics(pred)["mae_usd"],
        "family_quantiles_mae_usd": limit_metrics(naive)["mae_usd"],
        "model_median_ape": limit_metrics(pred)["median_ape"],
        "family_quantiles_median_ape": limit_metrics(naive)["median_ape"],
    }


def audit_delinquency(settings: Settings) -> dict:
    """Mora > 30: ¿se explica con un sorteo independiente por producto?"""
    con = _con(settings, ("products", "customers"))
    df = con.execute(
        """
        SELECT p.customer_id, COALESCE(p.days_past_due, 0) > 30 AS late,
               c.credit_score, c.estimated_monthly_income AS income
        FROM products p JOIN customers c USING (customer_id)
        WHERE p.product_type IN ('Credit Card', 'Personal Loan', 'Mortgage')
        """
    ).df()
    p = float(df["late"].mean())
    by_customer = df.groupby("customer_id")["late"].agg(["any", "size"])
    observed = by_customer.groupby("size")["any"].mean()
    expected = 1 - (1 - p) ** observed.index.to_numpy()
    big = by_customer["size"].value_counts().loc[observed.index] >= 1000
    score = df["credit_score"].notna()
    return {
        "rate_per_product": p,
        "max_gap_vs_random_draw": float(
            np.abs(observed - expected)[big.to_numpy()].max()
        ),
        # max(AUC, 1 - AUC): un puntaje alto puede significar menos mora, y un
        # AUC < 0.5 también sería señal. 0.5 en ambos sentidos es azar.
        "auc_credit_score": _either_direction(
            roc_auc_score(df.loc[score, "late"], df.loc[score, "credit_score"])
        ),
    }


def audit_intent(settings: Settings) -> dict:
    """Texto del cliente vs categoría: ¿cambia la categoría según el texto?"""
    con = _con(settings, ("call_transcripts", "call_center_interactions"))
    df = con.execute(
        """
        SELECT t.customer_text AS text, i.reason_category AS label
        FROM call_transcripts t JOIN call_center_interactions i USING (interaction_id)
        """
    ).df()
    overall = df["label"].value_counts(normalize=True)
    per_text = pd.crosstab(df["text"], df["label"], normalize="index")
    frequent = df["text"].value_counts()
    frequent = frequent[frequent >= 1000].index
    # Sin textos frecuentes no hay con qué comparar: el desvío queda nulo.
    gap = (
        (per_text.loc[frequent] - overall).abs().to_numpy().max()
        if len(frequent)
        else float("nan")
    )
    return {
        "rows": len(df),
        "distinct_texts": int(df["text"].nunique()),
        "max_gap_label_share_vs_overall": float(gap),
    }


def audit_calls(settings: Settings) -> dict:
    """Desenlaces de la llamada: modelo con info al inicio vs tasa por categoría."""
    con = _con(settings, ("call_center_interactions",))
    df = con.execute(
        f"""
        SELECT interaction_type, channel, reason_category, wait_time_seconds,
               customer_detected_accent, was_resolved, requires_followup,
               was_escalated, detected_sentiment
        FROM call_center_interactions USING SAMPLE {SAMPLE} ROWS (reservoir, {SEED})
        """
    ).df()
    targets: dict[str, pd.Series] = {
        "resolved_first_contact": df["was_resolved"].fillna(False).astype(bool),
        "negative_sentiment": df["detected_sentiment"].isin(NEGATIVE_SENTIMENT),
        "requires_followup": df["requires_followup"].astype(bool),
        "escalated": df["was_escalated"].astype(bool),
    }
    features = df[
        [
            "interaction_type",
            "channel",
            "reason_category",
            "wait_time_seconds",
            "customer_detected_accent",
        ]
    ]
    out = {}
    for name, y in targets.items():
        out[name] = {
            "rate": float(y.mean()),
            "model_auc": cv_auc(features, y),
            "category_table_auc": rate_table_auc(df["reason_category"], y),
        }
    rates = pd.DataFrame(targets).groupby(df["reason_category"]).mean()
    out["rates_by_category"] = rates.round(4).to_dict(orient="index")
    return out


def audit_transactions(settings: Settings) -> dict:
    con = _con(settings, ("transactions", "customers"))
    df = con.execute(
        f"""
        SELECT t.transaction_type, t.channel, t.amount_usd, t.currency,
               t.transaction_category, t.merchant_category, t.transaction_country,
               hour(t.transaction_date) AS hour, c.segment, c.country,
               c.credit_score, t.transaction_status
        FROM transactions t JOIN customers c USING (customer_id)
        USING SAMPLE {SAMPLE} ROWS (reservoir, {SEED})
        """
    ).df()
    x = df.drop(columns="transaction_status")
    y = df["transaction_status"].eq("Declined")
    return {"declined_rate": float(y.mean()), "declined_model_auc": cv_auc(x, y)}


def audit_churn(settings: Settings) -> dict:
    con = _con(settings, ("customers", "transactions", "call_center_interactions"))
    df = con.execute(
        """
        SELECT c.customer_status, c.segment, c.country, c.credit_score,
               c.estimated_monthly_income AS income, c.occupation,
               c.education_level, c.marital_status, c.accepts_marketing,
               COALESCE(tx.n, 0) AS n_tx, COALESCE(tx.declined, 0) AS declined,
               COALESCE(cc.n, 0) AS n_calls, COALESCE(cc.complaints, 0) AS complaints
        FROM customers c
        LEFT JOIN (SELECT customer_id, COUNT(*) AS n,
                          AVG((transaction_status = 'Declined')::INT) AS declined
                   FROM transactions GROUP BY 1) tx USING (customer_id)
        LEFT JOIN (SELECT customer_id, COUNT(*) AS n,
                          SUM((reason_category = 'Queja')::INT) AS complaints
                   FROM call_center_interactions GROUP BY 1) cc USING (customer_id)
        """
    ).df()
    y = df["customer_status"].isin(["Closed", "Inactive"])
    return {
        "churn_rate": float(y.mean()),
        "churn_model_auc": cv_auc(df.drop(columns="customer_status"), y),
    }


def audit_campaigns(settings: Settings) -> dict:
    """Conversión de campañas. `campaign_sends` no tiene spec: se lee crudo."""
    raw = settings.raw_dir / "data" / "campaign_sends"
    if not any(raw.glob("**/*.csv")):
        raise FileNotFoundError(f"falta campaign_sends crudo en {raw}")
    glob = sql_literal(Path(raw) / "**" / "*.csv")
    con = _con(settings, ("customers",))
    camp = settings.raw_dir / "data" / "marketing_campaigns.csv"
    if not camp.exists():
        raise FileNotFoundError(f"falta marketing_campaigns crudo en {camp}")
    df = con.execute(
        f"""
        SELECT s.send_channel, s.template_used, m.campaign_type, m.campaign_objective,
               m.promoted_product, m.target_segment,
               c.segment, c.country, c.credit_score, c.accepts_marketing,
               lower(s.had_conversion) = 'true' AS converted
        FROM read_csv({glob}, all_varchar = true, union_by_name = true) s
        LEFT JOIN read_csv({sql_literal(camp)}, all_varchar = true) m USING (campaign_id)
        JOIN customers c USING (customer_id)
        WHERE lower(s.was_delivered) = 'true'
        USING SAMPLE {SAMPLE} ROWS (reservoir, {SEED})
        """
    ).df()
    y = df.pop("converted").astype(bool)
    channel = df["send_channel"].astype("string").fillna("NA")
    return {
        "conversion_rate": float(y.mean()),
        "conversion_model_auc": cv_auc(df, y),
        "channel_table_auc": rate_table_auc(channel, y),
        "rate_by_channel": y.groupby(channel).mean().round(4).to_dict(),
    }


AUDITS: dict[str, Callable[[Settings], dict]] = {
    "limit": audit_limit,
    "delinquency": audit_delinquency,
    "intent": audit_intent,
    "calls": audit_calls,
    "transactions": audit_transactions,
    "churn": audit_churn,
    "campaigns": audit_campaigns,
}


def run_audit(settings: Settings, only: list[str] | None = None) -> dict:
    """Corre los chequeos pedidos. Uno que falla por datos faltantes queda anotado."""
    results = {}
    for name in only or list(AUDITS):
        try:
            results[name] = AUDITS[name](settings)
        except FileNotFoundError as err:
            results[name] = {"error": str(err)}
    return results
