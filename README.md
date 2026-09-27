# Radia · Factored AI & Data Hackathon 2026

Sistema de atención AI-first para productos de crédito de un banco simulado de LATAM. Detalle en [propuesta](docs/propuesta/propuesta.md).

## Equipo

| Persona | Rol | Carpeta |
| --- | --- | --- |
| Pablo López | Data Engineer | `src/radia/etl/` |
| Isabella Loaiza | Data Scientist | `src/radia/ml/` |
| Edwin García | AI Engineer | `src/radia/backend/` |
| Esteban Arias | Fullstack Dev | `frontend/` |

## Estructura

```text
src/radia/
  contracts/   contratos entre piezas
  etl/         pipeline bronze, silver, gold
  ml/          modelos
  backend/     api, orquestador, política, tools
  eval/        evaluación
frontend/      web
tests/         pruebas y fixtures
docs/          concurso, datos, propuesta
.claude/       harness
```

## Setup

```bash
cp .env.example .env   # nunca commitear
uv sync
```
