import logging
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

BASE_DIR = Path(__file__).resolve().parent
#VOICE_MODEL = Path(os.getenv("PIPER_MODEL", BASE_DIR / "models" / "es_ES-carlfm-x_low.onnx")).expanduser()
#VOICE_MODEL = Path(os.getenv("PIPER_MODEL", BASE_DIR / "models" / "es_ES-mls_9972-low.onnx")).expanduser()
#VOICE_MODEL = Path(os.getenv("PIPER_MODEL", BASE_DIR / "models" / "es_ES-mls_10246-low.onnx")).expanduser()

VOICE_MODEL = Path(os.getenv("PIPER_MODEL", BASE_DIR / "models" / "es_ES-sharvard-medium.onnx")).expanduser()
VOICE_SPEAKER = os.getenv("PIPER_SPEAKER", "1")
WHISPER_MODEL_NAME = os.getenv("WHISPER_MODEL", "small")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
MAX_AUDIO_BYTES = 25 * 1024 * 1024

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("anima-voice")
app = FastAPI(title="ANIMA Voice Engine", version="1.0.0")
_whisper = None
_whisper_lock = threading.Lock()


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


def get_whisper_model():
    global _whisper
    if _whisper is None:
        with _whisper_lock:
            if _whisper is None:
                from faster_whisper import WhisperModel
                logger.info("Loading Whisper model %s on %s", WHISPER_MODEL_NAME, WHISPER_DEVICE)
                _whisper = WhisperModel(
                    WHISPER_MODEL_NAME,
                    device=WHISPER_DEVICE,
                    compute_type=WHISPER_COMPUTE_TYPE,
                )
                logger.info("Whisper model loaded")
    return _whisper


def _transcribe_file(path: Path, partial: bool = False) -> dict:
    model = get_whisper_model()
    segments, info = model.transcribe(
        str(path),
        language="es",
        # Las transcripciones parciales se piden cada ~1,8 s mientras hablas:
        # con beam_size=1 y sin VAD son mucho más rápidas, a costa de precisión.
        # La transcripción final del turno siempre usa calidad completa.
        beam_size=1 if partial else 5,
        vad_filter=not partial,
        condition_on_previous_text=False,
    )
    text = " ".join(segment.text.strip() for segment in segments).strip()
    if not text:
        if partial:
            # En modo parcial el silencio es normal: no es un error.
            return {"ok": True, "text": "", "language": info.language, "partial": True}
        raise ValueError("No he detectado ninguna frase en el audio")
    return {"ok": True, "text": text, "language": info.language}


def _make_speech(text: str) -> bytes:
    if not VOICE_MODEL.is_file():
        raise FileNotFoundError(f"No encuentro el modelo Piper: {VOICE_MODEL}")
    with tempfile.TemporaryDirectory(prefix="anima-piper-") as tmp:
        output = Path(tmp) / "reply.wav"
        command = [
            sys.executable, "-m", "piper",
            "-m", str(VOICE_MODEL),
            "-s", str(VOICE_SPEAKER),
            "-f", str(output),
            "--", text,
        ]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        if result.returncode != 0 or not output.is_file():
            message = (result.stderr or result.stdout or "Piper no ha generado el WAV").strip()
            raise RuntimeError(message[-1500:])
        return output.read_bytes()


@app.get("/health")
async def health():
    return {
        "ok": True,
        "piper_model_available": VOICE_MODEL.is_file(),
        "piper_model": str(VOICE_MODEL),
        "piper_speaker": VOICE_SPEAKER,
        "whisper_model": WHISPER_MODEL_NAME,
        "whisper_device": WHISPER_DEVICE,
        "whisper_loaded": _whisper is not None,
    }


@app.post("/transcribe")
async def transcribe(request: Request, partial: bool = False):
    audio = await request.body()
    if not audio:
        raise HTTPException(status_code=400, detail="No se ha recibido audio")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="El audio supera el límite de 25 MB")

    mime = request.headers.get("content-type", "audio/webm").split(";", 1)[0].strip().lower()
    extensions = {
        "audio/webm": ".webm",
        "audio/mp4": ".mp4",
        "audio/ogg": ".ogg",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/mpeg": ".mp3",
        "audio/3gpp": ".3gp",
    }
    suffix = extensions.get(mime, ".webm")
    try:
        with tempfile.NamedTemporaryFile(prefix="anima-audio-", suffix=suffix, delete=False) as handle:
            handle.write(audio)
            audio_path = Path(handle.name)
        try:
            return await run_in_threadpool(_transcribe_file, audio_path, partial)
        finally:
            audio_path.unlink(missing_ok=True)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Audio transcription failed")
        raise HTTPException(status_code=500, detail="No se pudo transcribir el audio") from exc


@app.post("/speak")
async def speak(req: SpeakRequest):
    try:
        audio = await run_in_threadpool(_make_speech, req.text)
        return Response(content=audio, media_type="audio/wav", headers={"Cache-Control": "no-store"})
    except Exception as exc:
        logger.exception("Speech synthesis failed")
        raise HTTPException(status_code=500, detail="No se pudo generar la respuesta de voz") from exc
