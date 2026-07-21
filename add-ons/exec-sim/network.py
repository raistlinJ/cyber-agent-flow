import socket
import threading
from urllib.parse import urlparse
import config

_core_url_proxy_started = False

def _pipe_socket(src: socket.socket, dst: socket.socket):
    try:
        while True:
            data = src.recv(4096)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        for sock in (src, dst):
            try:
                sock.close()
            except OSError:
                pass


def _proxy_connection(client_sock: socket.socket, target_host: str, target_port: int):
    try:
        upstream = socket.create_connection((target_host, target_port), timeout=10)
    except OSError as e:
        print(f"[proxy] Could not reach {target_host}:{target_port}: {e}")
        client_sock.close()
        return
    threading.Thread(target=_pipe_socket, args=(client_sock, upstream), daemon=True).start()
    threading.Thread(target=_pipe_socket, args=(upstream, client_sock), daemon=True).start()


def start_core_url_proxy():
    """SSH -R reverse tunnels bind loopback-only on this host (GatewayPorts
    is off), so TARGET_URL (e.g. http://localhost:9090) isn't reachable from
    outside this box even though it's listening — unlike DASHBOARD_PORT,
    which binds 0.0.0.0 directly. Re-expose it on a 0.0.0.0-bound port so it
    gets picked up the same way the dashboard does."""
    global _core_url_proxy_started
    if _core_url_proxy_started:
        return

    parsed = urlparse(config.TARGET_URL)
    target_host = parsed.hostname
    target_port = parsed.port
    if target_host not in ("localhost", "127.0.0.1") or not target_port:
        return  # not a local loopback target — nothing to proxy

    _core_url_proxy_started = True

    def _serve():
        # Prefer exposing the exact same port; if something (like the
        # loopback-bound tunnel itself) already holds it, fall back to
        # nearby ports until one binds.
        for candidate_port in [target_port] + list(range(target_port + 1, target_port + 10)):
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                srv.bind(("0.0.0.0", candidate_port))
            except OSError:
                srv.close()
                continue
            srv.listen(20)
            print(f"[proxy] {config.TARGET_URL.rstrip('/')} (loopback-only) also reachable at "
                  f"http://localhost:{candidate_port}/")
            while True:
                try:
                    client, _ = srv.accept()
                except OSError:
                    break
                threading.Thread(target=_proxy_connection,
                                 args=(client, target_host, target_port), daemon=True).start()
            return
        print(f"[proxy] Could not find a free port near {target_port} to expose {config.TARGET_URL}")

    threading.Thread(target=_serve, daemon=True).start()
