#!/usr/bin/env python3
"""
Kronos Trading Bot — Dashboard Web

Lance le dashboard Flask sur http://localhost:5050
"""
import argparse
import logging
import os

from webapp.app import create_app


def main():
    parser = argparse.ArgumentParser(description="Kronos Dashboard")
    parser.add_argument("--host", default="127.0.0.1", help="Host")
    parser.add_argument("--port", type=int, default=5050, help="Port")
    parser.add_argument("--debug", action="store_true", help="Mode debug")
    parser.add_argument("--log-level", default="INFO")

    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    app = create_app()

    print(f"\n  ╔═══════════════════════════════════════════╗")
    print(f"  ║   KRONOS SIGNAL // GRID                  ║")
    print(f"  ║   Dashboard: http://{args.host}:{args.port:<5}        ║")
    print(f"  ╚═══════════════════════════════════════════╝\n")

    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()
