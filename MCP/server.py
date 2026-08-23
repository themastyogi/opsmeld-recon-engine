"""
Opsmeld Reconciliation Engine - Server Launcher
One-command web management console launcher.
"""

from web.app import create_server


def main():
    base_port = 8000
    server = None
    port = base_port
    for try_port in range(base_port, base_port + 10):
        try:
            server = create_server(host="0.0.0.0", port=try_port)
            port = try_port
            break
        except OSError:
            continue

    if not server:
        print("Error: Could not bind server to any port in range 8000-8010.")
        return

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
