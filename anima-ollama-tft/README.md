<div align="center">

<img src="../docs/branding/anima-mark-compact.png" alt="ANIMA" width="120">

# ANIMA · Chat API + PWA + TFT

**El cerebro HTTP y la cara visible del asistente:** un backend FastAPI que habla con Ollama,
una PWA instalable con voz, y el firmware que dibuja las respuestas en una pantalla física.

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-35e6ce?style=flat-square&labelColor=00151c)](https://fastapi.tiangolo.com/)
[![Python](https://img.shields.io/badge/Python-3.12-35e6ce?style=flat-square&labelColor=00151c)](https://www.python.org/)
[![PlatformIO](https://img.shields.io/badge/PlatformIO-ESP8266-9af7e9?style=flat-square&labelColor=00151c)](https://platformio.org/)

</div>

---

Este directorio contiene las tres piezas que dan forma a ANIMA del lado del usuario: el servidor que traduce mensajes a Ollama, la interfaz web que se instala en el móvil y el firmware que enciende la pantalla de la mesa.

```
anima-ollama-tft/
├── server/
│   ├── app.py                 # FastAPI: chat, voz, WebSocket, estáticos
│   ├── requirements.txt
│   ├── .env.example           # Plantilla de configuración
│   └── static/                # PWA: index.html, manifest, service worker
│       ├── branding/          # Logotipo y wallpaper oficiales
│       └── icons/             # Iconos 180/192/512 para instalar
└── firmware/
    ├── platformio.ini
    ├── include/                # secrets.example.h + cabeceras de pantallas y splash
    ├── src/                    # main.cpp (render TFT) + idle_anim.h (reposo RLE)
    ├── assets/                 # Arte base y vista previa del salvapantallas
    └── tools/make_idle_anim.py # Regenera idle_anim.h desde el arte base
```

## El servidor

`app.py` concentra toda la superficie HTTP del asistente: cuatro rutas funcionales, un canal WebSocket y el servicio de la PWA. El diseño es deliberadamente delgado: no guarda estado, no tiene base de datos y no conserva el historial — el historial vive en el `localStorage` de cada dispositivo.

| Método | Ruta | Función |
|---|---|---|
| `POST` | `/api/chat` | Mensaje + historial → respuesta de Ollama |
| `POST` | `/api/voice/transcribe` | Audio → texto (proxy a la Voice API) |
| `POST` | `/api/voice/speak` | Texto → WAV (proxy a la Voice API) |
| `GET` | `/health` | Estado de Ollama y disponibilidad del modelo |
| `WS` | `/ws` | Push de estado y respuestas a la TFT |
| `GET` | `/` · `/manifest.webmanifest` · `/sw.js` | La PWA y sus metadatos |
| `GET` | `/icons/{name}` · `/branding/{name}` | Iconos e imágenes de marca (lista blanca) |

Dos detalles de comportamiento que conviene conocer antes de tocar el código:

- **Las peticiones al modelo se serializan con un `asyncio.Lock`.** Ollama atiende una petición a la vez en la práctica; sin el lock, dos móviles podían intercalar respuestas y dejar la TFT mostrando el estado equivocado.
- **Las respuestas se envían a la TFT por WebSocket, pero la PWA las pinta desde el HTTP.** Así el chat no duplica mensajes cuando también recibe el broadcast.

## Puesta en marcha

```bash
cd server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app:app --host 0.0.0.0 --port 8000
```

### Configuración

Todo se ajusta desde `server/.env`:

| Variable | Por defecto | Para qué |
|---|---|---|
| `OLLAMA_URL` | `http://127.0.0.1:11434` | Endpoint de Ollama. Déjalo en loopback si Ollama corre en el mismo PC. |
| `OLLAMA_MODEL` | `qwen2.5-coder:14b` | El modelo a usar. Debe existir en `ollama list`. |
| `OLLAMA_TIMEOUT` | `300` | Segundos de espera. Generoso a propósito: un 14B en CPU tarda. |
| `VOICE_SERVICE_URL` | `http://127.0.0.1:8001` | Dónde escucha la Voice API. |
| `LOG_LEVEL` | `INFO` | Verbosidad del log. |

> [!IMPORTANT]
> Si Ollama no corre en el mismo equipo que este servidor, cambia `OLLAMA_URL` por la IP correspondiente **y** arranca Ollama con `OLLAMA_HOST=0.0.0.0`. Por defecto Ollama solo escucha en loopback.

### Comprobar que está vivo

```bash
curl http://127.0.0.1:8000/health
```

```json
{
  "ok": true,
  "ollama": "connected",
  "model": "qwen2.5-coder:14b",
  "model_available": true,
  "available_models": ["qwen2.5-coder:14b"]
}
```

Si `model_available` sale en `false`, el modelo está mal escrito o no se ha descargado: `ollama pull <modelo>`.

## La PWA

`static/index.html` es una aplicación completa en un solo archivo: sin build, sin `node_modules`, sin framework. Se sirve tal cual y se cachea mediante `sw.js`.

**Lo que incluye:**

- Chat con historial local (últimos 100 mensajes, último 20 como contexto para el modelo).
- **Modo conversación**: pantalla completa de voz con conversación continua, detección de silencio e interrupción.
- Instalación como app, con los iconos oficiales 180/192/512.
- Shell cacheada: la interfaz abre sin red; enviar mensajes sí requiere conexión.

**Instalar en el móvil.** El service worker y el micrófono exigen un contexto seguro, así que `http://192.168.x.x:8000` no basta. Tienes dos caminos:

- **`http://localhost:8000` en el propio PC** — sirve para probar.
- **HTTPS con un proxy inverso** — necesario para instalar la PWA y usar el micrófono desde el móvil. Con Caddy y un certificado de confianza local es cuestión de minutos.

Desde Android (Chrome) o iPhone (Safari → Compartir → Añadir a pantalla de inicio) se instala como cualquier app.

### Voz

El botón de micrófono abre el **modo conversación**: una pantalla completa con el rostro de ANIMA en un portal circular, anillos y ondas que siguen tu volumen real. El chat queda oculto para que la conversación se sienta como una llamada y no como un formulario.

**El ciclo es continuo, sin pulsar nada entre turnos:**

1. Hablas. El grabador corta el audio cada 1,8 s para ir mostrando la transcripción en vivo.
2. Cuando callas **3 segundos**, el turno se cierra solo y se envía.
3. ANIMA responde en texto y en voz, y al terminar vuelve a escuchar automáticamente.

**Interrumpir a ANIMA.** Mientras responde, el micrófono sigue activo: si hablas con voz sostenida (~330 ms por encima de un umbral alto), el audio se corta al instante y empieza un turno nuevo. El umbral es más exigente que el de escucha para no confundir el eco del altavoz con una intervención. También tienes el botón cuadrado de parar.

**Controles de la pantalla:**

| Control | Qué hace |
|---|---|
| Micrófono central | Silencia o reactiva el micro sin salir del modo voz |
| Botón cuadrado | Corta la respuesta y vuelve a escuchar |
| Aspa / `Esc` | Cierra el modo voz y libera el micrófono |

La conversación del modo voz se guarda en el mismo historial que el chat de texto, así que al salir sigue el hilo completo.

**Si te olvidas con el micro abierto**, el popup avisa a los 12 segundos («¿Sigues ahí?») y se cierra solo a los 20, devolviéndote al chat y liberando el micrófono. Mientras no detectes voz tampoco se envía ninguna transcripción, así que el silencio no consume el motor de voz.

### Pruebas

El motor de voz tiene una pequeña suite que se ejecuta con Node, sin navegador ni micrófono:

```bash
node tests/modo-conversacion.test.mjs   # ciclo normal, silencio de 3 s, interrupción
node tests/inactividad.test.mjs         # apertura olvidada: 0 peticiones y cierre automático
```

Simulan el DOM y las APIs del navegador y ejecutan el JavaScript real de `index.html`, así que detectan regresiones sin tener que probar a mano.

Si la Voice API no está levantada, el chat sigue funcionando por texto: los endpoints de voz devuelven `503` y la interfaz muestra un aviso, sin romper la conversación.

## El firmware

`firmware/src/main.cpp` dibuja el estado del asistente en una TFT ST7735 de 1,8" (160×128) conectada a una NodeMCU ESP8266.

| Pantalla TFT | Señal | Pin NodeMCU |
|---|---|---|
| CS | Chip select | D1 |
| DC | Data/command | D2 |
| RST | Reset | D0 |

```bash
cd firmware
cp include/secrets.example.h include/secrets.h   # WiFi y IP del PC
pio run --target upload
pio device monitor
```

`secrets.h` está en `.gitignore`: nunca se sube. Rellena `WIFI_SSID`, `WIFI_PASSWORD`, `BRIDGE_HOST` (la IP LAN del PC, que obtienes con `hostname -I`) y `BRIDGE_PORT` (8000 por defecto).

La placa pinta tres marcos fijos —`ANIMA // BOOT` (arranque), `ANIMA // SYSTEM` (estado) y `ANIMA // RESPONSE` (respuesta)— y mantiene la conexión con un ping cada 20 s y reconexión automática cada 3 s. Cuando ANIMA piensa, la pantalla dice `Pensando...`; cuando responde, hace wrap del texto a 25 caracteres por línea y muestra las últimas 10 líneas.

### Modo reposo

Si no pasa nada por el WebSocket, la TFT entra en reposo en dos fases: a los 10 segundos muestra la pantalla estática de reposo y a los 25 el salvapantallas: la cara frontal de ANIMA con el neón respirando, la cabecera `ANIMA` y el badge `LOCAL` con el icono WiFi. Cualquier evento (mensaje, estado, reconexión) la despierta y restaura la pantalla de estado al instante.

El GIF original pesa 8,4 MB con 160 cuadros —no cabe en la flash de la NodeMCU ni de broma. La animación que se muestra está **sintetizada**: un único cuadro base (el promedio del GIF, que limpia el parpadeo del neón) más el pulso de brillo calculado en el generador, en 4 fases comprimidas en RLE. Total: **46 KB de flash** en lugar de 8,4 MB, y el bucle corre con `millis()` sin bloquear el WebSocket.

Para regenerar la animación (por ejemplo, con otro arte base):

```bash
python3 anima-ollama-tft/firmware/tools/make_idle_anim.py
```

Lee `firmware/assets/anima_reposo_base.png` y reescribe `firmware/src/idle_anim.h`. La vista previa ampliada queda en `firmware/assets/preview_tft.gif`, para ver en el PC cómo va a quedar sin flashear.

> [!NOTE]
> El firmware se compila y flashea con PlatformIO. Si `pio` falla al arrancar con un `AttributeError` sobre `resultcallback`, es una incompatibilidad conocida entre PlatformIO 4.x y versiones recientes de `click`: instala PlatformIO dentro de un entorno virtual (`pip install platformio`) en lugar de usar el paquete del sistema.

## Problemas frecuentes

<details>
<summary><b>La TFT se queda en «WS desconectado»</b></summary>

Casi siempre es la IP. Comprueba `BRIDGE_HOST` en `secrets.h` contra `hostname -I` en el PC, y asegúrate de que el servidor escucha en `0.0.0.0` y no solo en `127.0.0.1`. Si tienes UFW activo, abre el puerto para tu subred:

```bash
sudo ufw allow from 192.168.0.0/24 to any port 8000 proto tcp
```

</details>

<details>
<summary><b>El botón del micrófono no aparece o no graba</b></summary>

Falta un contexto seguro. El navegador solo concede micrófono por HTTPS o en `localhost`. Sirve la app por HTTPS (aunque sea con un certificado autofirmado de confianza local) para usarla desde el móvil.

</details>

<details>
<summary><b>`/health` responde 503</b></summary>

El servidor está bien; Ollama no. Verifica con `curl http://127.0.0.1:11434/api/tags` y arráncalo con `ollama serve` si hace falta.

</details>

<details>
<summary><b>Las respuestas tardan muchísimo</b></summary>

Un modelo de 14B en CPU es lento por naturaleza. Baja a un 7B/8B o sube `OLLAMA_TIMEOUT` si las peticiones se cortan antes de terminar.

</details>

## Notas

- `server/voice_service.py` y `voice/voice_service.py` son copias locales del motor de voz. La versión canónica y mantenida es [`../anima-voice-server/voice_service.py`](../anima-voice-server/voice_service.py), que además soporta la transcripción progresiva (`?partial=true`).
- La PWA no usa framework ni bundler a propósito: se puede editar en caliente y el service worker cachea una versión nueva al cambiar `CACHE` en `sw.js`.

<div align="center">
<sub>Parte del monorepo <a href="../README.md">ANIMA</a> · volver a la raíz</sub>
</div>
