# roadmap

Detalle por persona: [[propuesta]], sección 7.

## Hitos

- [x] D0 sáb 26 sep. Propuesta, docs y harness
- [x] D1 dom 27. Contratos a código (v0)
- [ ] D2 lun 28. Datos base. Contratos v1. Hecho: S3 con manifiesto, bronze, silver, política v0, baseline de cupo. Falta: descarga aprobada y perfilado
- [ ] D3 mar 29. Puntaje y baselines
- [ ] D4 mié 30. Camino automático completo. `develop` → `main`
- [ ] D5 jue 1 oct. Revisión humana y casos difíciles
- [ ] D6 vie 2. Feature freeze. `develop` → `main`
- [ ] D7 sáb 3. Evaluación
- [ ] D8 dom 4. Docs y slides
- [ ] D9 lun 5. Envío. `develop` → `main`

## Pendientes

Pipeline completo en `develop`, probado con fixtures sintéticos:
`radia-etl manifest → download → bronze → silver → gold → score → offers`.

Checkpoints de Pablo:

- [ ] Aprobar la descarga del manifiesto (2184 objetos, 1.25 GB, o 924 MB sin `campaign_sends`). Ver `src/radia/etl/README.md`
- [ ] Pesos del puntaje (`src/radia/etl/score_weights_v0.yaml`, provisionales, rango validado [150, 950])
- [ ] Umbrales de bandas y topes por exposición (`src/radia/backend/policy/rules_v0.yaml`, provisionales)
- [ ] Congelar contratos v1 tras perfilar los datos reales

Trabajo:

- [x] Remoto público
- [x] Protección de `main` y `develop` en GitHub (PR + CI obligatorio, 0 aprobaciones mientras se trabaja en solitario)
- [x] Contratos v0 a código
- [x] Packaging de `src/radia` en `pyproject.toml`
- [x] Acceso a S3 con manifiesto y descarga idempotente
- [x] Bronze y silver con reporte de calidad
- [x] Motor de política v0 (C7)
- [x] Baseline de cupo (C4)
- [x] Gold (C1, C2 de cupo) y puntaje (C3)
- [x] Job de ofertas vigentes (C6). Contratos C6/C7 en 0.2.0 con trazabilidad
- [ ] Clientes demo en `tests/fixtures/`, tras la descarga
- [ ] Orquestador, tools y API (C8). LLM: Groq
- [ ] Casos de evaluación (C10) y runner
- [ ] Frontend mínimo
