#!/usr/bin/env python3
"""
Kronos Trading Bot — Dashboard Web

Usage:
  python run_dashboard.py                      # local seulement (127.0.0.1:5050)
  python run_dashboard.py --remote             # accessible via Tailscale (0.0.0.0:5050)
"""
import argparse
import logging
import os
import socket
import subprocess

from webapp.app import create_app, AUTH_ENABLED


def get_tailscale_ip() -> str | None:
    try:
        result = subprocess.run(
            ["tailscale", "ip", "-4"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode == 0:
            return result.stdout.strip().splitlines()[0]
    except Exception:
        pass
    return None


def get_local_ip() -> str | None:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser(description="Kronos Dashboard")
    parser.add_argument("--host", default=None, help="Host (default: 127.0.0.1, ou 0.0.0.0 si --remote)")
    parser.add_argument("--port", type=int, default=5050, help="Port")
    parser.add_argument("--remote", action="store_true", help="Accessible à distance (bind 0.0.0.0, requiert auth)")
    parser.add_argument("--debug", action="store_true", help="Mode debug")
    parser.add_argument("--log-level", default="INFO")

    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.remote:
        if not AUTH_ENABLED:
            print("\n  ⚠️  ERREUR: --remote requiert une authentification.")
            print("  Crée un fichier .env avec:")
            print("      DASHBOARD_USER=ton_username")
            print("      DASHBOARD_PASSWORD=un_mot_de_passe_solide\n")
            return 1
        host = args.host or "0.0.0.0"
    else:
        host = args.host or "127.0.0.1"

    app = create_app()

    tailscale_ip = get_tailscale_ip() if args.remote else None
    local_ip = get_local_ip() if args.remote else None

    print(f"\n  ╔═══════════════════════════════════════════════╗")
    print(f"  ║   KRONOS SIGNAL // GRID                       ║")
    print(f"  ╠═══════════════════════════════════════════════╣")
    print(f"  ║   Local:     http://127.0.0.1:{args.port:<5}            ║")
    if args.remote:
        if local_ip:
            print(f"  ║   LAN:       http://{local_ip}:{args.port}".ljust(50) + "║")
        if tailscale_ip:
            print(f"  ║   Tailscale: http://{tailscale_ip}:{args.port}".ljust(50) + "║")
        else:
            print(f"  ║   Tailscale: NON CONFIGURÉ (lance: sudo tailscale up) ║"[:50] + "║")
    print(f"  ║   Auth:      {'ACTIVÉE' if AUTH_ENABLED else 'DÉSACTIVÉE (DEV ONLY)':<28}     ║")
    print(f"  ╚═══════════════════════════════════════════════╝\n")

    if not args.remote and not AUTH_ENABLED:
        print("  ℹ️  Pour accéder à distance: configure .env puis lance --remote\n")

    app.run(host=host, port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()
