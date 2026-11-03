ANIMA VOICE - integración local

Contenido:
- app.py: añade /api/voice/transcribe y /api/voice/speak como proxy hacia 127.0.0.1:8001.
- static/: interfaz PWA con botón de micrófono y reproducción de la respuesta hablada.
- voice_service.py: servicio local de Whisper + Piper.

Requisitos en ~/DEV/anima-voice-server/.venv:
  faster-whisper, piper-tts, fastapi, uvicorn[standard]

Arranque del motor de voz (solo loopback):
  cd ~/DEV/anima-voice-server
  source .venv/bin/activate
  WHISPER_MODEL=small WHISPER_DEVICE=cpu WHISPER_COMPUTE_TYPE=int8 \
    python -m uvicorn voice_service:app --host 127.0.0.1 --port 8001

El modelo Piper esperado es models/es_ES-sharvard-medium.onnx y speaker 1.
La PWA requiere HTTPS (o localhost) para conceder acceso al micrófono desde el móvil.

La interfaz envía el audio al ASR local, pasa el texto por el endpoint /api/chat existente
y pide el audio de la respuesta a Piper. El endpoint /api/chat sigue realizando el
broadcast response por el WebSocket existente, por lo que el TFT continúa recibiendo texto.
