# etl/

**Dueño: Pablo (Data Engineer).**

Pipeline Bronze, Silver y Gold sobre el dataset de S3, puntaje interno determinístico y job de ofertas vigentes.

## Entrega a otros

- Features Gold (C1) y etiquetas (C2) para Isabella.
- Puntaje interno (C3) para la política y la bandeja del analista.
- Tabla de ofertas vigentes (C6), materializada llamando a la política de Edwin (C7).

## Reglas

- Ningún dato se versiona. Las salidas locales van en `data/local/`, que está en el `.gitignore`.
- Toda tabla Gold se valida contra su contrato antes de publicarse.
- Las credenciales de S3 se leen de `.env`. Ver `.env.example`.

Detalle en [[propuesta]] y [[trabajo_en_paralelo]].
