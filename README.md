<div align="center">

<img src="docs/branding/anima-banner.png" alt="ANIMA — asistente personal local" width="100%">

**Asistente personal de voz y chat que corre entero en tu propia red.**
Sin nube, sin claves de API, sin telemetría.

[![Python](https://img.shields.io/badge/Python-3.12-35e6ce?style=flat-square&labelColor=00151c)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-35e6ce?style=flat-square&labelColor=00151c)](https://fastapi.tiangolo.com/)
[![Ollama](https://img.shields.io/badge/Ollama-local-35e6ce?style=flat-square&labelColor=00151c)](https://ollama.com/)
[![License](https://img.shields.io/badge/License-MIT-9af7e9?style=flat-square&labelColor=00151c)](LICENSE)
[![Estado](https://img.shields.io/badge/Estado-listo%20para%20publicar-35e6ce?style=flat-square&labelColor=00151c)](#estado-del-proyecto)

</div>

---

**ANIMA** es un asistente personal que habla y escucha en español, y que además tiene cuerpo: una pantalla TFT física en tu mesa muestra lo que está pensando. Todo el cómputo ocurre en tu PC. El teléfono es solo una ventana; el modelo nunca sale de tu casa.

| | |
|---|---|
| 🗣️ **Habla y escucha** | Pulsa el micrófono y mantén una conversación continua: ANIMA detecta cuándo callas y responde sola. |
| 🧠 **Modelo local** | Ollama sirve el LLM en `127.0.0.1:11434`. Tú eliges el modelo en un `.env`. |
| ✋ **Interrumpible** | Habla mientras responde y se calla al instante: nunca te quedas esperando a que termine. |
| 📱 **PWA instalable** | Se añade a la pantalla de inicio del móvil como cualquier app. |
| 📺 **Cuerpo físico** | Una NodeMCU con TFT ST7735 renderiza estado y respuestas en tiempo real. |
| 🏠 **Solo tu red** | El ASR y el LLM escuchan únicamente en loopback. Nada se expone a Internet. |


## Demostración — ANIMA en funcionamiento

<div align="">

<a href="docs/demo/demo-anima-tft.mp4">
  <img
    src="docs/demo/demo-anima-tft-poster.jpg"
    alt="ANIMA funcionando con su pantalla TFT física"
    width="50%%"
  >
</a>

**ANIMA · Asistente de IA local con voz y pantalla TFT ESP8266**

*Demostración en hardware real: inteligencia artificial local, interacción por voz y pantalla física.*

[▶ Ver demostración completa](docs/demo/demo-anima-tft.mp4)

</div>

## Anatomía del sistema

<div align="center">
<img src="docs/branding/arquitectura.png" alt="Diagrama de arquitectura: PWA y NodeMCU contra Chat API, que habla con Voice API y Ollama" width="100%">
</div>

El **Chat API** es el único componente que el móvil y la placa conocen. Traduce entre el mundo HTTP/WebSocket de los clientes y los servicios internos, y serializa las peticiones al modelo para que dos dispositivos no se pisen.

## Contenido del monorepo

Tres piezas independientes que se ejecutan juntas. Cada una tiene su propio README con el detalle de instalación.

| Directorio | Qué es | Arranque |
|---|---|---|
| [`anima-ollama-tft/`](anima-ollama-tft/) | Chat API FastAPI, PWA instalable y firmware ESP8266 para la TFT | `uvicorn app:app --port 8000` |
| [`anima-voice-server/`](anima-voice-server/) | Motor de voz local: Whisper para transcribir, Piper para hablar | `uvicorn voice_service:app --port 8001` |
| [`anima-stack.py`](anima-stack.py) | Lanzador único que levanta y supervisa los tres servicios | `python3 anima-stack.py` |

## Empezar paso a paso

### Requisitos

- **Python 3.12** o superior
- **[Ollama](https://ollama.com/)** instalado y con un modelo descargado
- **Linux** (probado en Pop!_OS). En macOS funciona igual; en Windows necesitas WSL para el motor de voz.

```bash
# 1. El modelo que ANIMA usa por defecto (~9 GB)
ollama pull qwen2.5-coder:14b

# 2. Preparar los dos entornos virtuales (solo la primera vez)
python3 -m venv anima-ollama-tft/server/.venv \
  && anima-ollama-tft/server/.venv/bin/pip install -r anima-ollama-tft/server/requirements.txt

python3 -m venv anima-voice-server/.venv \
  && anima-voice-server/.venv/bin/pip install -r anima-voice-server/requirements.txt

# 3. Descargar el modelo de voz Piper (73 MB)
mkdir -p anima-voice-server/models
curl -L -o anima-voice-server/models/es_ES-sharvard-medium.onnx \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/sharvard/medium/es_ES-sharvard-medium.onnx

# 4. Levantar todo el stack de una vez
python3 anima-stack.py
```

El lanzador arranca Ollama si no está activo, la Chat API en el puerto 8000 y la Voice API en el 8001, unifica los logs en una sola terminal y reutiliza los servicios que ya estuvieran corriendo en lugar de duplicarlos. Después, abre <http://127.0.0.1:8000>.

> [!NOTE]
> `anima-stack.py` comprueba que ambos entornos virtuales existen antes de arrancar: por eso los pasos 2 y 3 van antes. Si prefieres arrancar cada servicio a mano, sigue las instrucciones de [`anima-ollama-tft/README.md`](anima-ollama-tft/README.md) y [`anima-voice-server/README.md`](anima-voice-server/README.md).

> [!TIP]
> El lanzador deduce la ruta del proyecto a partir de su propia ubicación, así que funciona en cualquier carpeta donde clones el repositorio. Si necesitas apuntar a otra copia, exporta `ANIMA_ROOT` antes de ejecutarlo.

### Instalación manual, paso a paso

<details>
<summary><b>Chat API + PWA</b> (puerto 8000)</summary>

```bash
cd anima-ollama-tft/server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # ajusta OLLAMA_MODEL si usas otro modelo
uvicorn app:app --host 0.0.0.0 --port 8000
```

Comprueba que responde:

```bash
curl http://127.0.0.1:8000/health
# {"ok":true,"ollama":"connected","model":"qwen2.5-coder:14b","model_available":true,...}
```

</details>

<details>
<summary><b>Voice API</b> (puerto 8001)</summary>

```bash
cd anima-voice-server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Descargar el modelo de voz Piper (73 MB); el .onnx.json ya está en el repo
curl -L -o models/es_ES-sharvard-medium.onnx \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/sharvard/medium/es_ES-sharvard-medium.onnx

WHISPER_MODEL=small WHISPER_DEVICE=cpu WHISPER_COMPUTE_TYPE=int8 \
  uvicorn voice_service:app --host 127.0.0.1 --port 8001
```

Whisper se descarga su propio modelo la primera vez que transcribe algo.

</details>

<details>
<summary><b>Firmware de la TFT</b> (NodeMCU ESP8266)</summary>

```bash
cd anima-ollama-tft/firmware
cp include/secrets.example.h include/secrets.h   # pon tu WiFi y la IP del PC
pio run --target upload                          # PlatformIO
```

La placa se conecta a `ws://IP_DEL_PC:8000/ws` y se reconecta sola cada 3 s si el PC se apaga.

</details>

## Cómo se hablan las piezas

El contrato entre componentes es pequeño a propósito:

| Canal | Ruta | Para qué |
|---|---|---|
| HTTP | `POST /api/chat` | Enviar mensaje + historial, recibir respuesta |
| HTTP | `POST /api/voice/transcribe` | Audio del navegador → texto (Whisper) |
| HTTP | `POST /api/voice/speak` | Texto → WAV (Piper) |
| HTTP | `GET /health` | ¿Está Ollama arriba y el modelo disponible? |
| WebSocket | `/ws` | Notificar a la TFT: `status` y `response` |

Ejemplo del contrato de chat:

```bash
curl -X POST http://127.0.0.1:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Responde solo: ANIMA online"}'
```

```json
{ "ok": true, "answer": "ANIMA online" }
```

Los eventos que recibe la placa por el WebSocket:

```json
{ "type": "status",   "value": "thinking" }
{ "type": "response", "text": "ANIMA online" }
{ "type": "error",    "text": "Error consultando Ollama" }
```

## Seguridad y privacidad

Este proyecto está pensado para tu red doméstica, y su configuración por defecto refleja esa intención:

- **Ollama y Whisper escuchan solo en `127.0.0.1`.** No son accesibles desde otros dispositivos de la red, ni siquiera desde el móvil.
- **El único puerto abierto en LAN es el 8000.** Es el que necesita el teléfono y la placa.
- **No hay telemetría ni servicios externos.** La única conexión saliente es la descarga inicial de modelos.
- **Los secretos están fuera del repositorio.** Ni `.env` ni `secrets.h` se versionan; sus plantillas `.example` sí.

> [!WARNING]
> No expongas los puertos 8000 ni 11434 directamente a Internet. Para acceder desde fuera de casa, usa una VPN. Si necesitas HTTPS para instalar la PWA desde el móvil, pon un proxy inverso (Caddy, Nginx) delante del 8000 — el micrófono del navegador exige un contexto seguro.

## Estado del proyecto

ANIMA funciona de extremo a extremo: chat, voz y pantalla física. Lo que hay es honesto sobre lo que es — un proyecto personal, no un producto.

| Área | Estado |
|---|---|
| Chat con contexto e historial local | ✅ Funcional |
| Voz (ASR + TTS en español) | ✅ Funcional |
| Modo conversación con turnos por silencio | ✅ Funcional |
| Interrupción de ANIMA al hablar | ✅ Funcional |
| PWA instalable con shell offline | ✅ Funcional |
| Firmware TFT con reconexión | ✅ Funcional |
| Modo reposo de la TFT (reposo estático + salvapantallas animado) | ✅ Funcional |
| Tests automatizados | ✅ 17 pruebas con Node (`node tests/*.test.mjs`): 13 del modo conversación y 4 de inactividad |
| Autenticación | ⚠️ Asume red doméstica de confianza |

<details>
<summary><b>Detalles conocidos a tener en cuenta</b></summary>

- **HTTPS para el micrófono.** Los navegadores solo conceden acceso al micrófono en contextos seguros. Por `http://127.0.0.1` funciona; por `http://192.168.x.x` el botón de voz no aparecerá.
- **Un modelo a la vez.** La Chat API serializa las peticiones con un lock: si dos móviles preguntan a la vez, la segunda espera. Es deliberado, para que la TFT no muestre estados contradictorios.
- **La interrupción exige voz sostenida.** Al hablar mientras ANIMA responde se necesita superar un umbral más alto durante ~330 ms. Es a propósito: con un umbral bajo, el eco del altavoz cortaría la respuesta sola en equipos sin cancelación de eco.
- **Hay tres copias de `voice_service.py`** (`anima-voice-server/`, `anima-ollama-tft/server/` y `anima-ollama-tft/voice/`): hoy son funcionalmente equivalentes y la canónica es la de `anima-voice-server`; unificarlas es trabajo pendiente. Ver la nota al final de [`anima-voice-server/README.md`](anima-voice-server/README.md).
- **`qwen2.5-coder:14b` es el valor por defecto**, pero está pensado para programar. Para conversación general, `llama3.1:8b` o `mistral-nemo` responden mejor y ocupan menos.

</details>

## Stack

<div align="center">

| Capa | Tecnología |
|:--|:--|
| Backend | Python 3.12 · FastAPI · Uvicorn · httpx |
| LLM | Ollama (`qwen2.5-coder:14b` por defecto) |
| Voz | faster-whisper (ASR) · Piper (TTS) |
| Frontend | HTML/CSS/JS sin build · Service Worker · Web App Manifest |
| Firmware | C++ · PlatformIO · ESP8266 · Adafruit ST7735 |
| Marca | Paleta `#00151c` · `#35e6ce` · `#9af7e9` |

</div>

## Identidad visual

El material de marca vive en [`docs/branding/`](docs/branding/), y los originales que consume la PWA están en [`anima-ollama-tft/server/static/branding/`](anima-ollama-tft/server/static/branding/) e [`icons/`](anima-ollama-tft/server/static/icons/).

| Archivo | Uso |
|---|---|
| `anima-banner.png` | Cabecera de README (1600×400) |
| `anima-mark-compact.png` | Icono de cabecera para los READMEs de subproyecto |
| `anima-icon-256.png` | Avatar de repositorio / redes |
| `arquitectura.png` | Diagrama de arquitectura |

La paleta oficial: fondo `#00151c`, turquesa de marca `#35e6ce`, menta `#9af7e9`. El logotipo —un perfil femenino trazado con líneas de circuito— no se debe recolorear ni deformar. El diagrama se regenera con `python3 docs/branding/make-diagram.py`.

## Estructura del repositorio

```
anima-asisstant/
├── anima-stack.py                 # Lanzador unificado con supervisión
├── tests/                         # Pruebas Node de la PWA (sin navegador)
├── anima-ollama-tft/              # Chat API + PWA + firmware
│   ├── server/                    # FastAPI, estáticos, .env
│   │   ├── app.py                 # Rutas de chat, voz y WebSocket
│   │   └── static/                # PWA, branding e iconos
│   ├── voice/                     # Copia local del motor de voz
│   └── firmware/                  # PlatformIO para la NodeMCU
├── anima-voice-server/            # ASR + TTS locales (copia canónica)
│   ├── voice_service.py           # Endpoints /transcribe y /speak
│   └── models/                    # Modelos Piper (los pesos no se versionan)
└── docs/branding/                 # Material de marca y diagramas
```

## Licencia

MIT. Consulta [`LICENSE`](LICENSE) para el texto completo.

<div align="center">
<br>
<sub>ANIMA · hecha para funcionar en casa, con tu hardware y tus datos.</sub>
</div>
