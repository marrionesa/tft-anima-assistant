#!/usr/bin/env python3
"""ANIMA unified local stack launcher (Ollama + Chat API + Voice API)."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import socket
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration.
#
# ROOT se deduce de la ubicación de este archivo para que el repositorio
# funcione al clonarlo en cualquier ruta. Si necesitas apuntar a otra copia,
# exporta ANIMA_ROOT antes de ejecutar el lanzador.
# ---------------------------------------------------------------------------
ROOT = Path(os.environ.get("ANIMA_ROOT") or Path(__file__).resolve().parent).expanduser()
CHAT_DIR = ROOT / "anima-ollama-tft" / "server"
VOICE_DIR = ROOT / "anima-voice-server"
VOICE_PYTHON = Path(os.environ.get("ANIMA_VOICE_PYTHON") or VOICE_DIR / ".venv" / "bin" / "python").expanduser()
USER_UVICORN = Path.home() / ".local" / "bin" / "uvicorn"

OLLAMA_URL = os.environ.get("ANIMA_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
CHAT_URL = os.environ.get("ANIMA_CHAT_URL", "http://127.0.0.1:8000")
VOICE_URL = os.environ.get("ANIMA_VOICE_URL", "http://127.0.0.1:8001")

POLL_SECONDS = 5
START_TIMEOUT = 45

# ANSI colors (disabled automatically when output is redirected).
USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
RESET = "\033[0m" if USE_COLOR else ""
COLORS = {
    "cyan": "\033[96m" if USE_COLOR else "",
    "blue": "\033[94m" if USE_COLOR else "",
    "green": "\033[92m" if USE_COLOR else "",
    "yellow": "\033[93m" if USE_COLOR else "",
    "red": "\033[91m" if USE_COLOR else "",
    "magenta": "\033[95m" if USE_COLOR else "",
    "dim": "\033[2m" if USE_COLOR else "",
    "bold": "\033[1m" if USE_COLOR else "",
}


def color(text: str, shade: str) -> str:
    return f"{COLORS.get(shade, '')}{text}{RESET}"


def log(tag: str, shade: str, message: str) -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"{color(stamp, 'dim')} {color('[' + tag + ']', shade):<20} {message}", flush=True)


def banner() -> None:
    print()
    print(color("╔══════════════════════════════════════════════════════════════╗", "cyan"))
    print(color("║                    ANIMA LOCAL CONTROL                       ║", "cyan"))
    print(color("║             Ollama · Chat API · Voice API                    ║", "cyan"))
    print(color("╚══════════════════════════════════════════════════════════════╝", "cyan"))
    print()
    print(f"  Proyecto : {ROOT}")
    print(f"  Chat API : {CHAT_URL}  (TCP 8000)")
    print(f"  Voice API: {VOICE_URL}  (TCP 8001)")
    print(f"  Ollama   : {OLLAMA_URL}  (TCP 11434)")
    print()


def http_json(url: str, timeout: float = 1.5) -> Optional[dict]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ANIMA-Stack/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = response.read()
            if response.status != 200:
                return None
            try:
                parsed = json.loads(data.decode("utf-8"))
                return parsed if isinstance(parsed, dict) else {"data": parsed}
            except (UnicodeDecodeError, json.JSONDecodeError):
                return {"ok": True}
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None


def tcp_port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


@dataclass
class Service:
    name: str
    tag: str
    shade: str
    url: str
    port: int
    process: Optional[asyncio.subprocess.Process] = None
    adopted: bool = False
    healthy: bool = False
    reader_task: Optional[asyncio.Task] = None
    last_state: str = "unknown"

    @property
    def managed(self) -> bool:
        return self.process is not None


async def stream_process(service: Service) -> None:
    assert service.process is not None and service.process.stdout is not None
    try:
        while True:
            raw = await service.process.stdout.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if line:
                log(service.tag, service.shade, line)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # Keep the supervisor alive if a log reader fails.
        log(service.tag, "red", f"Error leyendo logs: {exc}")


async def start_process(service: Service, command: list[str], cwd: Path,
                        env: Optional[dict[str, str]] = None) -> bool:
    if not cwd.is_dir():
        log(service.tag, "red", f"No existe el directorio: {cwd}")
        return False
    try:
        service.process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(cwd),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
        service.reader_task = asyncio.create_task(stream_process(service))
        log(service.tag, "green", f"Iniciado (PID {service.process.pid})")
        return True
    except FileNotFoundError as exc:
        log(service.tag, "red", f"No se encuentra el ejecutable: {exc.filename}")
    except Exception as exc:
        log(service.tag, "red", f"No se pudo iniciar: {exc}")
    return False


async def wait_healthy(service: Service, timeout: int = START_TIMEOUT) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = http_json(service.url)
        if result is not None:
            service.healthy = True
            return True
        if service.process is not None and service.process.returncode is not None:
            log(service.tag, "red", f"El proceso terminó con código {service.process.returncode}")
            return False
        await asyncio.sleep(0.5)
    return False


async def ensure_service(service: Service, command: list[str], cwd: Path,
                         env: Optional[dict[str, str]] = None) -> bool:
    # Reuse an already-running instance rather than starting a duplicate.
    if http_json(service.url) is not None:
        service.adopted = True
        service.healthy = True
        log(service.tag, "green", "Ya estaba activo; reutilizando instancia existente")
        return True

    host = "127.0.0.1"
    if tcp_port_open(host, service.port):
        log(service.tag, "red", f"El puerto {service.port} está ocupado, pero {service.url} no responde correctamente.")
        log(service.tag, "yellow", "No inicio otra instancia para evitar un conflicto. Revisa el proceso que ocupa ese puerto.")
        return False

    if not await start_process(service, command, cwd, env):
        return False
    if await wait_healthy(service):
        log(service.tag, "green", "Health check correcto")
        return True

    if service.process and service.process.returncode is None:
        log(service.tag, "red", f"No respondió en {START_TIMEOUT}s. Revisa los logs anteriores.")
    return False


async def maybe_attach_ollama_journal(ollama: Service) -> None:
    """If Ollama is a systemd service, mirror its journal into this terminal."""
    systemctl = shutil.which("systemctl")
    journalctl = shutil.which("journalctl")
    if not (systemctl and journalctl and ollama.adopted):
        return
    try:
        check = await asyncio.create_subprocess_exec(
            systemctl, "is-active", "--quiet", "ollama",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        if await check.wait() != 0:
            return
        # A journal follower is a log reader, not the Ollama server process.
        ollama.process = await asyncio.create_subprocess_exec(
            journalctl, "-fu", "ollama", "-o", "cat", "--no-pager",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
        ollama.reader_task = asyncio.create_task(stream_process(ollama))
        log("OLLAMA", "dim", "Mostrando también el journal de systemd")
    except Exception:
        # Lack of journal permissions must not prevent ANIMA from starting.
        return


async def service_state(service: Service) -> str:
    result = http_json(service.url)
    if result is not None:
        service.healthy = True
        return "OK" if service.managed else ("OK / existente" if service.adopted else "OK")
    service.healthy = False
    if service.process is not None and service.process.returncode is not None:
        return f"CAÍDO ({service.process.returncode})"
    return "SIN RESPUESTA"


async def shutdown(services: list[Service]) -> None:
    print()
    log("STACK", "yellow", "Cerrando servicios iniciados por este lanzador...")

    # Stop only processes created by this launcher. Adopted services are untouched.
    for service in reversed(services):
        proc = service.process
        if proc is None:
            continue
        # If the process is journalctl, it is safe to stop; if it is Ollama,
        # it was launched by this script only when not previously running.
        if proc.returncode is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await proc.wait()
        if service.reader_task:
            service.reader_task.cancel()

    readers = [s.reader_task for s in services if s.reader_task]
    if readers:
        await asyncio.gather(*readers, return_exceptions=True)
    log("STACK", "green", "Lanzador detenido. Los servicios externos siguen intactos.")


async def run() -> int:
    banner()

    required = [CHAT_DIR / "app.py", VOICE_DIR / "voice_service.py", VOICE_PYTHON]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        log("CHECK", "red", "Faltan archivos necesarios:")
        for path in missing:
            log("CHECK", "red", f"  {path}")
        log("CHECK", "yellow", f"Comprueba que el repositorio está completo en {ROOT}.")
        return 2

    uvicorn_found = str(USER_UVICORN) if USER_UVICORN.exists() else shutil.which("uvicorn")
    if not uvicorn_found:
        log("CHECK", "red", "No encuentro Uvicorn global (~/.local/bin/uvicorn o PATH).")
        return 2
    uvicorn = Path(uvicorn_found)

    ollama_bin = shutil.which("ollama")
    if not ollama_bin:
        log("OLLAMA", "red", "No encuentro el ejecutable 'ollama' en PATH.")
        return 2

    ollama = Service("Ollama", "OLLAMA", "magenta", f"{OLLAMA_URL}/api/tags", 11434)
    chat = Service("Chat API", "CHAT", "blue", f"{CHAT_URL}/health", 8000)
    voice = Service("Voice API", "VOICE", "cyan", f"{VOICE_URL}/health", 8001)
    services = [ollama, chat, voice]

    try:
        # Ollama first, so the chat backend can connect to it at startup.
        if not await ensure_service(ollama, [ollama_bin, "serve"], ROOT):
            return 1
        await maybe_attach_ollama_journal(ollama)

        # The chat app loads server/.env itself. Explicitly pass the same local
        # Ollama URL used by this launcher so an old .env value (for example,
        # a stale LAN IP) cannot point the backend at an address where Ollama is
        # not listening. Also bypass system proxies for loopback traffic.
        chat_env = os.environ.copy()
        chat_env["OLLAMA_URL"] = OLLAMA_URL
        local_no_proxy = {"localhost", "127.0.0.1", "::1"}
        for key in ("NO_PROXY", "no_proxy"):
            existing = {item.strip() for item in chat_env.get(key, "").split(",") if item.strip()}
            chat_env[key] = ",".join(sorted(existing | local_no_proxy))
        log("CHAT", "dim", f"Conectando Ollama mediante {OLLAMA_URL}")
        if not await ensure_service(
            chat,
            [str(uvicorn), "app:app", "--host", "0.0.0.0", "--port", "8000"],
            CHAT_DIR,
            chat_env,
        ):
            return 1

        voice_env = os.environ.copy()
        voice_env.update({
            "WHISPER_MODEL": os.environ.get("WHISPER_MODEL", "small"),
            "WHISPER_DEVICE": os.environ.get("WHISPER_DEVICE", "cpu"),
            "WHISPER_COMPUTE_TYPE": os.environ.get("WHISPER_COMPUTE_TYPE", "int8"),
        })
        voice_cmd = [str(VOICE_PYTHON), "-u", "-m", "uvicorn", "voice_service:app", "--host", "127.0.0.1", "--port", "8001"]
        if not await ensure_service(voice, voice_cmd, VOICE_DIR, voice_env):
            return 1

        print()
        log("STACK", "green", "ANIMA está levantada. Logs unificados abajo. Pulsa Ctrl+C para salir.")
        log("STACK", "dim", "Los servicios que ya existían se reutilizan; no se arrancan duplicados.")
        print()

        while True:
            states = []
            for service in services:
                state = await service_state(service)
                states.append(f"{service.name}: {state}")
            log("STATUS", "green" if all("OK" in s for s in states) else "yellow", " | ".join(states))

            # If a managed process dies, report it clearly. We intentionally do
            # not restart it in a loop, avoiding hidden crash/restart cycles.
            dead = [s for s in services if s.managed and s.process and s.process.returncode is not None]
            if dead:
                for service in dead:
                    log("STACK", "red", f"{service.name} terminó inesperadamente (código {service.process.returncode}).")
                return 1
            await asyncio.sleep(POLL_SECONDS)

    except asyncio.CancelledError:
        raise
    finally:
        await shutdown(services)


def main() -> None:
    try:
        code = asyncio.run(run())
    except KeyboardInterrupt:
        # asyncio.run cancels run(), whose finally block performs cleanup.
        code = 130
    raise SystemExit(code)


if __name__ == "__main__":
    main()
