# Git

- Ramas: `main` (entregas) ← `develop` (integración) ← `feat/<scope>-<tema>`, `fix/...`, `docs/...`, `chore/...`
- Nunca commit, merge ni push directo a `main` o `develop`. Todo entra por PR.
- **Commits atómicos.** Un cambio lógico por commit. Si el mensaje necesita "y", son dos commits.
- Formato: `tipo(scope): descripción en español`
  - Ej: `feat(etl): se realiza la ingesta de transactions a bronze`
  - Tipos: `feat` `fix` `refactor` `test` `docs` `chore` `ci`
  - Scopes: `etl` `ml` `api` `agent` `policy` `front` `contracts` `eval` `infra`
- Actualizar tu rama: `git fetch origin && git rebase origin/develop`
- Tras rebase: `git push --force-with-lease` (solo en tu rama)
- Después de **cada** commit: agentes `reviewer` y `tester` sobre ese commit. Sus hallazgos se corrigen antes del siguiente commit.

## Compuertas de un PR a `develop`

Aprobación humana no obligatoria mientras se trabaje en solitario. Se mergea con **Rebase and merge** cuando todo esto está en verde:

1. `reviewer` con veredicto `OK` en cada commit del PR.
2. `tester` sin fallas en cada commit con código.
3. CI en verde (ruff y pytest).
4. `/code-review` sobre el PR completo, con los hallazgos corregidos o respondidos en el PR.

Las compuertas 1, 2 y 4 las dispara el mismo agente que escribe el código, así que no son independientes. La garantía dura es externa: el hook bloquea commit, merge y push directos a `main`/`develop`, y la protección de rama en GitHub exige CI en verde para mergear.

Si vuelve el equipo, se exige de nuevo 1 aprobación humana, y los PR que tocan `src/radia/contracts/` vuelven a necesitar al productor y al consumidor.

## Checkpoints humanos

Se para y se pide confirmación a Pablo en:

- Manifiesto de S3 (archivos y tamaño) antes de la primera descarga.
- Congelamiento de contratos v1.
- Números de política: pesos del puntaje, bandas y topes.
- Cada `develop` → `main`: solo en hitos (D4, D6, D9), por PR.
- Todo lo irreversible o público: deploy, gasto en LLM, envío.
