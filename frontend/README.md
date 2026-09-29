# frontend/

**Dueño: Esteban (Fullstack Dev).**

Web de demostración mínima. Consume la API C8 tal cual: sin lógica de negocio en el front.

## Stack

- HTML, CSS y JavaScript sin build. Sin Node ni `package.json`.
- La sirve la misma app FastAPI (`StaticFiles`): un solo proceso.
- Por qué: deploy simple y nada que compilar. El jurado califica comportamiento, no diseño.

## Cómo levantar

```bash
uv run uvicorn radia.backend.api.main:app
```

- Web: http://localhost:8000/ (login).
- Páginas en `/web/...`. API en las mismas rutas de siempre.
- Documentación de la API: http://localhost:8000/docs
- LLM: `FakeLanguageModel`. No llama a ningún LLM real.
- Sin la carpeta `frontend/`, la app levanta solo la API.

## Credenciales de demo

Públicas a propósito. NO son reales ni secretas. Detalle en `src/radia/backend/README.md`.

| Usuario | Clave | Rol |
| --- | --- | --- |
| `DEMO000001` ... `DEMO000018` | `radia-demo` | cliente |
| `analyst.demo` | `radia-demo` | analista |
| `advisor.demo` | `radia-demo` | asesor |

Clientes útiles: `DEMO000001` (automático), `DEMO000008` (analista), `DEMO000018` (asesor), `DEMO000003` (analista y luego asesor).

## Pantallas

| Página | Rol | Endpoints | Qué hace |
| --- | --- | --- | --- |
| `index.html` (`/`) | todos | `POST /auth/login` | Login. Lleva a la pantalla del rol |
| `customer.html` | cliente | `GET /customers/me/offers` | Cuenta resumida y ofertas vigentes. Destaca la sugerida. Aviso de política sintética |
| `chat.html` | cliente | `POST /chat/messages`, `POST /chat/confirm` | Mensajes, estado, botones Sí/No si hay confirmación pendiente, número de solicitud o de caso |
| `analyst.html` | analista | `GET /analyst/cases`, `POST /analyst/cases/{id}/decision` | Casos pendientes con expediente. Aprobar, rechazar o pedir información |
| `advisor.html` | asesor | `GET /advisor/sessions`, `POST /advisor/sessions/{id}/messages` | Sesiones traspasadas, expediente, rango de negociación y mensaje con monto. Muestra el 422 si sale del rango |

Archivos comunes: `common.js` (token, llamadas a la API, pintado del expediente) y `styles.css`.

## Prueba a mano

1. Entrar con `DEMO000008`. En el chat: "Quiero un préstamo personal". Anotar el número de caso.
2. Cerrar sesión. Entrar con `analyst.demo`: el caso aparece en la bandeja.
3. Entrar con `DEMO000001`. En el chat: "Quiero una tarjeta básica". Pulsar Sí: sale el número de solicitud.
4. Entrar con `DEMO000018` y pedir la tarjeta oro. Luego con `advisor.demo`: enviar un monto fuera del rango muestra el 422.

## Reglas

- Token solo en la pestaña (`sessionStorage`, con respaldo en memoria). Nunca en la URL.
- Datos pintados con `textContent`, nunca con `innerHTML`.
- Errores de la API visibles (`role="alert"`), con el código y el detalle.
- Accesibilidad: labels en todo campo, foco visible, contraste alto.
- Si hace falta una librería, por CDN confiable y solo si simplifica de verdad.

Endpoints y ejemplos de respuesta en [[trabajo_en_paralelo]]. Qué vive el cliente en [[propuesta]], sección 3.
