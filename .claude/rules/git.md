# Git

- Ramas: `main` (entregas) ← `develop` (integración) ← `feat/<scope>-<tema>`, `fix/...`, `docs/...`
- Nunca commit, merge ni push directo a `main` o `develop`. Todo entra por PR.
- **Commits atómicos.** Un cambio lógico por commit. Si el mensaje necesita "y", son dos commits.
- Formato: `tipo(scope): descripción en español`
  - Ej: `feat(etl): se realiza la ingesta de transactions a bronze`
  - Tipos: `feat` `fix` `refactor` `test` `docs` `chore` `ci`
  - Scopes: `etl` `ml` `api` `agent` `policy` `front` `contracts` `eval` `infra`
- Actualizar tu rama: `git fetch origin && git rebase origin/develop`
- Tras rebase: `git push --force-with-lease` (solo en tu rama)
- PR a `develop`: 1 aprobación. Merge con **Rebase and merge**.
- `develop` → `main`: solo en hitos (D4, D6, D9), por PR.
- Después de cada commit: agentes `reviewer` y `tester` sobre ese commit.
