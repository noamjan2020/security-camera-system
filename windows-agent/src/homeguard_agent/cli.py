from __future__ import annotations

import argparse
import logging

import uvicorn

from .config import Settings
from .instance_lock import SingleInstanceLock
from .logging_config import configure_logging, install_exception_hooks
from .runtime import Runtime

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(prog="homeguard-agent")
    parser.add_argument("command", choices=["init", "run", "token", "doctor"], nargs="?", default="run")
    parser.add_argument("--debug", action="store_true", help="Enable verbose diagnostic logging")
    args = parser.parse_args()
    settings = Settings(debug=args.debug or Settings().debug)
    settings.ensure_directories()
    configure_logging(settings.logs_dir, debug=settings.debug)
    install_exception_hooks()

    lock = SingleInstanceLock(settings.data_dir / "homeguard.lock")
    lock.acquire()
    runtime = Runtime(settings)
    try:
        if args.command == "init":
            print("HomeGuard initialized.")
            print(f"Data directory: {settings.data_dir.resolve()}")
            print("Use the Windows desktop app to pair a phone. Do not share the API credential.")
            return
        if args.command == "token":
            print(runtime.token)
            return
        if args.command == "doctor":
            print(f"Version: {runtime.VERSION}")
            print(f"Database integrity: {'OK' if runtime.database.integrity_check() else 'FAILED'}")
            print(f"Detector: {runtime.detector.name}")
            print(f"Emergency disabled: {runtime.state_store.snapshot().emergency_disabled}")
            print(f"Remote cloud enabled: {settings.remote_enabled}")
            return

        runtime.start()
        logger.info("Starting local API on %s:%s", settings.api_host, settings.api_port)
        uvicorn.run(
            runtime.app,
            host=settings.api_host,
            port=settings.api_port,
            log_level="debug" if settings.debug else "info",
            access_log=False,
        )
    finally:
        runtime.stop()
        lock.release()


if __name__ == "__main__":
    main()
