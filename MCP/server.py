import sys, os, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from web.app import create_server


def main():
    port_env = os.environ.get("PORT") or os.environ.get("WEBSITES_PORT") or "8000"
    try:
        port = int(port_env)
    except ValueError:
        port = 8000

    try:
        server = create_server(host="0.0.0.0", port=port)
    except OSError as e:
        print(f"Port {port} busy, attempting bind to 0.0.0.0:{port}...")
        server = create_server(host="0.0.0.0", port=port)

    print(f"============================================================")
    print(f"  Opsmeld Reconciliation Engine Web Management Console")
    print(f"  Running at: http://127.0.0.1:{port}")
    print(f"  Running at: http://localhost:{port}")
    print(f"  Settings:   http://127.0.0.1:{port}/settings")
    print(f"============================================================")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down Opsmeld server...")
        server.server_close()


if __name__ == "__main__":
    main()
