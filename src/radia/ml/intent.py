"""Clasificador de intención: del texto del cliente al motivo del contacto.

Etiqueta real del dataset: `call_center_interactions.reason_category`, unida a lo
que dijo el cliente en `call_transcripts.customer_text`. Sirve al orquestador
para entender la solicitud (crédito o no) y evaluar esa comprensión con
etiquetas, no a ojo.

- Split por cliente, igual que el modelo de cupo.
- Modelo: TF-IDF (palabras y bigramas, sin tildes) + regresión logística.
- Baselines: clase mayoritaria y palabras clave aprendidas de train.
- Métricas: accuracy y F1 macro, global y por acento (fairness).
- Con datos mock el código corre, pero las métricas no significan nada.
"""

from collections import Counter
from dataclasses import dataclass
from typing import Self

import mlflow
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score
from sklearn.pipeline import Pipeline, make_pipeline

from radia.ml.dataset import split_by_customer

TEXT = "text"
LABEL = "label"
GROUPS = ("accent",)


def build_intent_table(
    interactions: pd.DataFrame,
    transcripts: pd.DataFrame,
    label: str = "reason_category",
) -> pd.DataFrame:
    """Una fila por transcripción con texto del cliente y etiqueta de su interacción."""
    calls = transcripts[
        ["interaction_id", "customer_id", "customer_text", "detected_accent"]
    ]
    reasons = interactions[["interaction_id", label]]
    # Una etiqueta por interacción. Duplicados multiplicarían filas y podrían
    # cruzar train y test: mejor fallar (Silver ya deja una fila por PK).
    table = calls.merge(
        reasons, on="interaction_id", how="inner", validate="many_to_one"
    )
    table = table.rename(
        columns={"customer_text": TEXT, label: LABEL, "detected_accent": "accent"}
    )
    table[TEXT] = table[TEXT].astype("string").str.strip()
    table = table[table[TEXT].fillna("").str.len() > 0]
    table = table[table[LABEL].notna()]
    # El diccionario trae el acento en minúsculas; se normaliza por si acaso.
    table["accent"] = table["accent"].astype("string").str.lower().fillna("unknown")
    return table.reset_index(drop=True)


class IntentModel:
    version = "intent-tfidf-logreg-0.1.0"

    def __init__(self, seed: int = 0) -> None:
        self._pipe: Pipeline = make_pipeline(
            TfidfVectorizer(
                strip_accents="unicode",
                lowercase=True,
                ngram_range=(1, 2),
                min_df=2,
                sublinear_tf=True,
            ),
            LogisticRegression(
                max_iter=1000, class_weight="balanced", random_state=seed
            ),
        )

    def fit(self, table: pd.DataFrame) -> Self:
        self._pipe.fit(table[TEXT], table[LABEL])
        return self

    def predict(self, texts: pd.Series) -> np.ndarray:
        return self._pipe.predict(texts)


class MajorityBaseline:
    version = "intent-majority-0.1.0"

    def fit(self, table: pd.DataFrame) -> Self:
        self.label_ = table[LABEL].mode().iloc[0]
        return self

    def predict(self, texts: pd.Series) -> np.ndarray:
        return np.full(len(texts), self.label_, dtype=object)


class KeywordBaseline:
    """Por clase, las `k` palabras más propias de esa clase en train.

    Predice la clase con más palabras clave en el texto; sin coincidencias, la
    mayoritaria. Es el baseline "reglas a mano" pero sin sesgo del autor.
    """

    version = "intent-keywords-0.1.0"

    def __init__(self, k: int = 20) -> None:
        self.k = k

    # Un solo analizador, mismas reglas que el TF-IDF del modelo.
    _analyzer = staticmethod(
        TfidfVectorizer(strip_accents="unicode", lowercase=True).build_analyzer()
    )

    @classmethod
    def _tokens(cls, text: object) -> set[str]:
        return set(cls._analyzer(text)) if isinstance(text, str) else set()

    def fit(self, table: pd.DataFrame) -> Self:
        by_class: dict[str, Counter[str]] = {}
        for label, texts in table.groupby(LABEL)[TEXT]:
            counts: Counter[str] = Counter()
            for text in texts:
                counts.update(self._tokens(text))
            by_class[label] = counts
        total: Counter[str] = sum(by_class.values(), Counter())
        self.keywords_: dict[str, set[str]] = {}
        for label, counts in by_class.items():
            n = sum(counts.values())
            rest = sum(total.values()) - n
            # Log-odds suavizado: palabra frecuente aquí y rara en el resto.
            score = {
                w: np.log((c + 1) / (n + 1)) - np.log((total[w] - c + 1) / (rest + 1))
                for w, c in counts.items()
            }
            top = sorted(score, key=score.__getitem__, reverse=True)[: self.k]
            self.keywords_[label] = set(top)
        # Orden de desempate: la clase más frecuente en train gana. La clase por
        # defecto sale del mismo orden para que nunca se contradigan.
        self.priority_ = list(table[LABEL].value_counts().index)
        self.default_ = self.priority_[0]
        return self

    def predict(self, texts: pd.Series) -> np.ndarray:
        out = []
        for text in texts:
            tokens = self._tokens(text)
            hits = {lbl: len(tokens & self.keywords_[lbl]) for lbl in self.priority_}
            best = max(hits, key=hits.__getitem__)  # max se queda con el primero
            out.append(best if hits[best] > 0 else self.default_)
        return np.array(out, dtype=object)


@dataclass(frozen=True)
class IntentEvaluation:
    overall: dict[str, float]
    by_group: dict[str, pd.DataFrame]


def intent_metrics(
    y_true: pd.Series, y_pred: np.ndarray, labels: list[str] | None = None
) -> dict[str, float]:
    """`labels`: las clases de train. Fijas, una clase ausente en test cuenta como
    F1 0 en vez de desaparecer del promedio y maquillar el F1 macro."""
    if len(y_true) == 0:
        raise ValueError("sin filas para evaluar")
    f1 = f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)
    return {
        "n": float(len(y_true)),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "f1_macro": float(f1),
    }


def evaluate_intent(
    test: pd.DataFrame, y_pred: np.ndarray, labels: list[str] | None = None
) -> IntentEvaluation:
    pred = pd.Series(y_pred, index=test.index)
    by_group = {}
    for g in GROUPS:
        rows = {
            key: intent_metrics(part[LABEL], pred.loc[part.index].to_numpy(), labels)
            for key, part in test.groupby(g, sort=True)
        }
        by_group[g] = pd.DataFrame.from_dict(rows, orient="index").rename_axis(g)
    return IntentEvaluation(intent_metrics(test[LABEL], y_pred, labels), by_group)


def make_mock_calls(n: int = 2000, seed: int = 0) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Mock de interacciones y transcripciones. Solo para construir código."""
    rng = np.random.default_rng(seed)
    phrases = {
        "Transactional": ["quiero hacer una transferencia", "necesito ver mi saldo"],
        "Product": ["quiero una tarjeta de credito", "me interesa un prestamo"],
        "Technical": ["la app no me deja entrar", "olvide mi clave"],
        "Commercial": ["quiero saber de promociones", "que beneficios tengo"],
        "Complaint": ["quiero poner una queja", "me cobraron de mas"],
    }
    labels = rng.choice(list(phrases), size=n)
    ids = [f"INT{i:07d}" for i in range(n)]
    interactions = pd.DataFrame({"interaction_id": ids, "reason_category": labels})
    transcripts = pd.DataFrame(
        {
            "interaction_id": ids,
            "customer_id": [f"MOCK{i:06d}" for i in rng.integers(0, n // 2, size=n)],
            "customer_text": [
                f"hola {rng.choice(phrases[lbl])} por favor" for lbl in labels
            ],
            "detected_accent": rng.choice(
                ["Mexican", "Colombian", "Argentine"], size=n
            ),
        }
    )
    return interactions, transcripts


def run_intent_experiment(
    interactions: pd.DataFrame,
    transcripts: pd.DataFrame,
    *,
    seed: int = 0,
    test_size: float = 0.2,
    data_source: str = "mock",
) -> dict[str, IntentEvaluation]:
    """Entrena, evalúa modelo y baselines, y registra todo en el run activo de MLflow."""
    if mlflow.active_run() is None:
        raise RuntimeError("se exige un run activo: usar `with mlflow.start_run()`")
    table = build_intent_table(interactions, transcripts)
    if table.empty:
        raise ValueError("sin transcripciones con texto y etiqueta")
    train, test = split_by_customer(table, test_size=test_size, seed=seed)
    # Clases de train fijas: una clase ausente en test cuenta como F1 0.
    labels = sorted(train[LABEL].unique())
    systems = {
        "model": IntentModel(seed=seed),
        "baseline_majority": MajorityBaseline(),
        "baseline_keywords": KeywordBaseline(),
    }
    evaluations = {
        name: evaluate_intent(test, sys.fit(train).predict(test[TEXT]), labels)
        for name, sys in systems.items()
    }
    mlflow.log_params(
        {
            "data_source": data_source,
            "seed": seed,
            "test_size": test_size,
            "n_train": len(train),
            "n_test": len(test),
            "n_classes": len(labels),
            "classes": labels,
            **{f"{name}_version": sys.version for name, sys in systems.items()},
        }
    )
    for name, ev in evaluations.items():
        mlflow.log_metrics({f"{name}_{k}": v for k, v in ev.overall.items()})
        for group, df in ev.by_group.items():
            mlflow.log_text(df.to_csv(), f"by_group/{name}_{group}.csv")
    return evaluations
