"""
Opsmeld Reconciliation Engine - Server Launcher
One-command web management console launcher.
"""

from web.app import create_server


def main():
    port = 8000
    server = create_server(host="0.0.0.0", port=port)
    print(f"============================================================")
    print(f"  Opsmeld Reconciliation Engine Web Management Console")
    print(f"  Running at: http://localhost:{port}")
    print(f"  Settings:   http://localhost:{port}/settings")
    print(f"============================================================")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down Opsmeld server...")
        server.server_close()


if __name__ == "__main__":
    main()
