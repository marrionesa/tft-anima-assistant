import asyncio
import logging
import os
from pathlib import Path
from typing import Literal

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
load_dotenv(BASE_DIR / ".env")

# Ollama runs on this same PC. Keep its API bound to localhost where possible.
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:14b")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "300"))
VOICE_SERVICE_URL = os.getenv("VOICE_SERVICE_URL", "http://127.0.0.1:8001").rstrip("/")

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("anima")

app = FastAPI(title="ANIMA Local", version="1.0.0")
clients: set[WebSocket] = set()
clients_lock = asyncio.Lock()
chat_lock = asyncio.Lock()


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    history: list[HistoryMessage] = Field(default_factory=list, max_length=30)


class VoiceSpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


async def broadcast(data: dict) -> None:
    async with clients_lock:
        targets = list(clients)
    dead: list[WebSocket] = []
    for ws in targets:
        try:
            await ws.send_json(data)
        except Exception:
            dead.append(ws)
    if dead:
        async with clients_lock:
            for ws in dead:
                clients.discard(ws)


@app.get("/health")
async def health():
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{OLLAMA_URL}/api/tags")
            response.raise_for_status()
            models = [item.get("name", "") for item in response.json().get("models", [])]
        return {
            "ok": True,
            "ollama": "connected",
            "model": OLLAMA_MODEL,
            "model_available": OLLAMA_MODEL in models,
            "available_models": models,
        }
    except Exception as exc:
        logger.warning("Health check failed: %s", exc)
        return JSONResponse(
            status_code=503,
            content={"ok": False, "ollama": "disconnected", "model": OLLAMA_MODEL},
        )


@app.post("/api/chat")
async def chat(req: ChatRequest):
    message = req.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="El mensaje está vacío")

    # A single local model handles requests sequentially. This prevents two phones
    # from interleaving requests and producing confusing TFT state notifications.
    async with chat_lock:
        await broadcast({"type": "status", "value": "thinking"})
        conversation = [
            {"role": item.role, "content": item.content}
            for item in req.history[-20:]
        ]
        conversation.append({"role": "user", "content": message})

        try:
            async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
                response = await client.post(
                    f"{OLLAMA_URL}/api/chat",
                    json={
                        "model": OLLAMA_MODEL,
                        "messages": conversation,
                        "stream": False,
                    },
                )
                response.raise_for_status()
                answer = (
                    response.json().get("message", {}).get("content", "").strip()
                    or "No he recibido una respuesta del modelo."
                )

            # The ESP8266 listens to this event and renders the response on the TFT.
            await broadcast({"type": "response", "text": answer})
            return {"ok": True, "answer": answer}

        except httpx.HTTPStatusError as exc:
            detail = f"Ollama respondió con HTTP {exc.response.status_code}"
            logger.exception("Ollama HTTP error")
            await broadcast({"type": "error", "text": "Error consultando Ollama"})
            raise HTTPException(status_code=502, detail=detail) from exc
        except Exception as exc:
            logger.exception("Ollama request failed")
            await broadcast({"type": "error", "text": "Error consultando Ollama"})
            raise HTTPException(
                status_code=502,
                detail="No se pudo conectar con Ollama. Comprueba que esté activo.",
            ) from exc


@app.post("/api/voice/transcribe")
async def voice_transcribe(request: Request):
    """Forward raw browser-recorded audio to the local ASR service."""
    audio = await request.body()
    if not audio:
        raise HTTPException(status_code=400, detail="No se ha recibido audio")
    if len(audio) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="El audio supera el límite de 25 MB")
    content_type = request.headers.get("content-type", "audio/webm")
    partial = request.query_params.get("partial", "false").lower() in {"1", "true", "yes"}
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(
                f"{VOICE_SERVICE_URL}/transcribe",
                params={"partial": "true" if partial else "false"},
                content=audio,
                headers={"Content-Type": content_type},
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        detail = "El servicio de reconocimiento no pudo procesar el audio"
        try:
            detail = exc.response.json().get("detail", detail)
        except Exception:
            pass
        raise HTTPException(status_code=502, detail=detail) from exc
    except Exception as exc:
        logger.exception("Voice transcription service unavailable")
        raise HTTPException(
            status_code=503,
            detail="El servicio de voz no está disponible. Comprueba que escucha en el puerto 8001.",
        ) from exc


@app.post("/api/voice/speak")
async def voice_speak(req: VoiceSpeakRequest):
    """Forward response text to local Piper and return generated WAV audio."""
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{VOICE_SERVICE_URL}/speak",
                json={"text": req.text},
            )
            response.raise_for_status()
            return Response(
                content=response.content,
                media_type="audio/wav",
                headers={"Cache-Control": "no-store"},
            )
    except httpx.HTTPStatusError as exc:
        logger.exception("Voice synthesis service returned an error")
        raise HTTPException(status_code=502, detail="No se pudo generar el audio") from exc
    except Exception as exc:
        logger.exception("Voice synthesis service unavailable")
        raise HTTPException(
            status_code=503,
            detail="El servicio de voz no está disponible. Comprueba que escucha en el puerto 8001.",
        ) from exc


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    async with clients_lock:
        clients.add(ws)
    await ws.send_json({"type": "status", "value": "connected"})
    try:
        while True:
            # ESP8266 sends a periodic ping; browser clients may remain idle.
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        async with clients_lock:
            clients.discard(ws)


@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse(STATIC_DIR / "index.html", media_type="text/html")


@app.get("/manifest.webmanifest")
async def manifest():
    return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js")
async def service_worker():
    # Service workers must be served from the app root to control the full scope.
    return FileResponse(
        STATIC_DIR / "sw.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )


@app.get("/icons/{name}")
async def pwa_icon(name: str):
    allowed = {"anima-192.png", "anima-512.png", "anima-180.png"}
    if name not in allowed:
        raise HTTPException(status_code=404)
    return FileResponse(STATIC_DIR / "icons" / name, media_type="image/png")


@app.get("/branding/{name}")
async def branding_asset(name: str):
    # Lista blanca explícita: evita servir cualquier archivo del directorio.
    allowed = {"anima-mark.webp", "anima-wallpaper.webp", "anima-face.webp"}
    if name not in allowed:
        raise HTTPException(status_code=404)
    return FileResponse(STATIC_DIR / "branding" / name, media_type="image/webp")
