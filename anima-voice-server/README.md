<div align="center">

<img src="../docs/branding/anima-mark-compact.png" alt="ANIMA" width="120">

# ANIMA · Motor de voz local

**Oído y voz de ANIMA, ejecutándose en tu CPU.** Whisper transcribe lo que dices,
Piper responde con una voz española natural. Nada sale del equipo.

[![faster-whisper](https://img.shields.io/badge/faster--whisper-1.2-35e6ce?style=flat-square&labelColor=00151c)](https://github.com/SYSTRAN/faster-whisper)
[![Piper](https://img.shields.io/badge/Piper-1.8-35e6ce?style=flat-square&labelColor=00151c)](https://github.com/rhasspy/piper)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-9af7e9?style=flat-square&labelColor=00151c)](https://fastapi.tiangolo.com/)

</div>

---

Un único archivo, `voice_service.py`, expone dos endpoints sobre FastAPI: uno convierte audio en texto y el otro convierte texto en audio. La Chat API los consume por debajo, así que el navegador nunca habla directamente con este servicio.

| Método | Ruta | Entrada | Salida |
|---|---|---|---|
| `POST` | `/transcribe` | Audio crudo en el body | JSON `{ok, text, language}` |
| `POST` | `/speak` | JSON `{text}` | WAV (`audio/wav`) |
| `GET` | `/health` | — | Estado de los modelos cargados |

El parámetro opcional `?partial=true` en `/transcribe` sirve para la transcripción en vivo: baja el `beam_size` a 1 y desactiva el filtro VAD para responder rápido mientras hablas. La PWA lo pide cada 1,8 s durante el turno; al cerrarse por silencio, la transcripción definitiva usa calidad completa (`beam_size=5`).

Con `partial=true` un audio sin voz devuelve `{"ok": true, "text": "", "partial": true}` en lugar de un `422`: el silencio es normal en mitad de una frase y no debe tratarse como error.

## Instalación

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### El modelo de voz

Piper necesita su modelo ONNX (~73 MB). No se versiona: descárgalo en `models/`. La configuración `.onnx.json` sí está en el repositorio.

```bash
mkdir -p models
curl -L -o models/es_ES-sharvard-medium.onnx \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/sharvard/medium/es_ES-sharvard-medium.onnx
```

Verificación de integridad (`sha256`):

```
40febfb1679c69a4505ff311dc136e121e3419a13a290ef264fdf43ddedd0fb1  models/es_ES-sharvard-medium.onnx
7438c9b699c72b0c3388dae1b68d3f364dc66a2150fe554a1c11f03372957b2c  models/es_ES-sharvard-medium.onnx.json
```

Más detalles —incluidas otras voces— en [`models/README.md`](models/README.md). Whisper no requiere descarga manual: `faster-whisper` baja su modelo la primera vez que transcribe algo y lo deja en la caché de Hugging Face.

### Arrancar

```bash
WHISPER_MODEL=small WHISPER_DEVICE=cpu WHISPER_COMPUTE_TYPE=int8 \
  uvicorn voice_service:app --host 127.0.0.1 --port 8001
```

> [!IMPORTANT]
> El servicio escucha en `127.0.0.1` deliberadamente. No hay autenticación: exponerlo a la LAN permitiría a cualquiera consumir tu CPU. Todo el tráfico pasa por la Chat API, que sí está pensada para la red local.

## Configuración

Todo por variables de entorno, con valores por defecto sensatos:

| Variable | Por defecto | Para qué |
|---|---|---|
| `WHISPER_MODEL` | `small` | `tiny`, `base`, `small`, `medium`, `large-v3`. Más grande = más preciso y más lento. |
| `WHISPER_DEVICE` | `cpu` | `cpu` o `cuda` si tienes GPU NVIDIA. |
| `WHISPER_COMPUTE_TYPE` | `int8` | `int8` en CPU; `float16` en GPU. |
| `PIPER_MODEL` | `models/es_ES-sharvard-medium.onnx` | Ruta al modelo de voz. |
| `PIPER_SPEAKER` | `1` | Índice de hablante dentro del modelo. |
| `LOG_LEVEL` | `INFO` | Verbosidad. |

`small` en `int8` es el equilibrio razonable para CPU: transcribe español con soltura y deja el equipo usable. Con GPU, `medium` y `float16` dan un salto claro de calidad.

> [!NOTE]
> El servicio **no** lee `.env` por sí solo: toma las variables del entorno del proceso. Copia [`.env.example`](.env.example) como referencia y expórtalas antes de arrancar, o pásalas en la misma línea de comandos como en el ejemplo anterior.

## Comprobar que funciona

```bash
curl http://127.0.0.1:8001/health
```

```json
{
  "ok": true,
  "piper_model_available": true,
  "piper_model": "/ruta/anima-voice-server/models/es_ES-sharvard-medium.onnx",
  "piper_speaker": "1",
  "whisper_model": "small",
  "whisper_device": "cpu",
  "whisper_loaded": false
}
```

Si `piper_model_available` es `false`, la ruta no coincide: revisa `PIPER_MODEL` o coloca el archivo en `models/`.

Probar la síntesis de voz sin pasar por el navegador:

```bash
curl -X POST http://127.0.0.1:8001/speak \
  -H 'Content-Type: application/json' \
  -d '{"text":"Hola, soy ANIMA."}' \
  --output prueba.wav
```

Y la transcripción con cualquier audio en español:

```bash
curl -X POST http://127.0.0.1:8001/transcribe \
  -H 'Content-Type: audio/wav' \
  --data-binary @prueba.wav
```

## Detalles de implementación

- **Whisper se carga una sola vez**, con doble comprobación bajo lock: la primera transcripción paga el coste de carga (~2 s con `small`), las siguientes son inmediatas.
- **La transcripción corre en un hilo aparte** (`run_in_threadpool`) para no bloquear el event loop de FastAPI mientras el modelo trabaja.
- **El audio va a un archivo temporal** y se borra en un `finally`, incluso si la transcripción falla. Límite de 25 MB por petición.
- **Piper se invoca como subproceso** con un timeout de 90 s. Cada llamada es independiente; si una falla, la siguiente no se ve afectada.
- **Se fija `language="es"`** con `vad_filter` activo: descarta silencios y evita que el modelo "invente" texto en grabaciones vacías.
- Un audio sin voz devuelve `422` con un mensaje claro en lugar de una cadena vacía.

## Problemas frecuentes

<details>
<summary><b>La primera transcripción tarda muchísimo</b></summary>

Es la carga del modelo. Con `small` son un par de segundos; con `medium` o `large-v3` puede ser bastante más. Si vas a usarlo de forma intensiva, mantén el servicio levantado en lugar de arrancarlo por petición.

</details>

<details>
<summary><b>«No encuentro el modelo Piper»</b></summary>

`PIPER_MODEL` apunta a una ruta relativa al directorio de trabajo. Arranca `uvicorn` desde `anima-voice-server/` o pasa una ruta absoluta en la variable.

</details>

<details>
<summary><b>Transcribe mal o mezcla idiomas</b></summary>

Sube de `small` a `medium` si tu CPU lo aguanta. También ayuda hablar cerca del micrófono: `vad_filter` descarta lo que considera ruido de fondo, y una señal débil se recorta más de la cuenta.

</details>

<details>
<summary><b>El WAV suena metálico o entrecortado</b></summary>

Prueba otro `PIPER_SPEAKER` (0 o 2, según el modelo). El modelo `es_ES-sharvard-medium` incluye varias voces y la 1 no siempre es la mejor para todos los textos.

</details>

## Notas

El mismo `voice_service.py` existe en otros dos sitios del monorepo —`../anima-ollama-tft/server/voice_service.py` y `../anima-ollama-tft/voice/voice_service.py`—. Esta es la copia canónica; las otras dos son funcionalmente equivalentes (solo difieren en comentarios con modelos alternativos). Consolidarlas en un único módulo importable es trabajo pendiente.

<div align="center">
<sub>Parte del monorepo <a href="../README.md">ANIMA</a> · volver a la raíz</sub>
</div>
