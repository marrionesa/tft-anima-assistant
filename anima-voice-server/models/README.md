# Modelos de voz

El motor Piper necesita un modelo para sintetizar voz. Los **pesos** (`.onnx`, ~73 MB) no se
versionan en este repositorio; la **configuración** (`.onnx.json`) sí, porque es pequeña y
determina cómo se interpreta el modelo.

## Descarga

```bash
cd anima-voice-server
curl -L -o models/es_ES-sharvard-medium.onnx \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/sharvard/medium/es_ES-sharvard-medium.onnx
```

El `.onnx.json` correspondiente ya está en este directorio. Si descargases otra voz, trae
también su JSON:

```bash
curl -L -o models/<voz>.onnx.json \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/<ruta>/<voz>.onnx.json
```

## Integridad

```
40febfb1679c69a4505ff311dc136e121e3419a13a290ef264fdf43ddedd0fb1  es_ES-sharvard-medium.onnx
7438c9b699c72b0c3388dae1b68d3f364dc66a2150fe554a1c11f03372957b2c  es_ES-sharvard-medium.onnx.json
```

Comprobar tras la descarga:

```bash
sha256sum -c <<'EOF'
40febfb1679c69a4505ff311dc136e121e3419a13a290ef264fdf43ddedd0fb1  models/es_ES-sharvard-medium.onnx
7438c9b699c72b0c3388dae1b68d3f364dc66a2150fe554a1c11f03372957b2c  models/es_ES-sharvard-medium.onnx.json
EOF
```

## Otros idiomas

Los catálogos completos están en [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices).
ANIMA está ajustada al español (`language="es"` en Whisper, voz `es_ES` en Piper), pero
`voice_service.py` acepta cualquier modelo mediante `PIPER_MODEL`.
