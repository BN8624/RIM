# runs/<timestamp>/ 결과를 읽기 전용으로 제공하는 표준 라이브러리 기반 정적 서버.
from __future__ import annotations

import shutil
import socket
import subprocess
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

# 어떤 경우에도 제공하지 않는 경로/파일 (읽기 전용 결과 서버 보안 요구사항 §5, §12)
_DENIED_PREFIXES = ("debug/raw", "debug/prompts")
_DENIED_BASENAMES = {".env", "llm_calls.jsonl"}


def _is_denied(rel: str) -> bool:
    """run_dir 기준 상대 경로(POSIX, 소문자 아님)가 차단 대상인지 판단한다."""
    rel = rel.strip("/")
    if not rel:
        return False
    parts = PurePosixPath(rel).parts
    base = parts[-1]
    # .env 계열: .env는 차단, .env.example만 허용
    if base == ".env" or (base.startswith(".env") and base != ".env.example"):
        return True
    if base in _DENIED_BASENAMES:
        return True
    # 경로 어디에서든 (검색 결과의 repos/<name>/debug/raw 포함) 차단 시퀀스를 찾는다
    for prefix in _DENIED_PREFIXES:
        pp = prefix.split("/")
        for i in range(len(parts) - len(pp) + 1):
            if list(parts[i : i + len(pp)]) == pp:
                return True
    return False


class ReadOnlyHandler(SimpleHTTPRequestHandler):
    """GET/HEAD만 허용하고, run_dir 밖 접근·traversal·secret 파일을 차단하는 핸들러."""

    def __init__(self, *args, directory: str | None = None, **kwargs):
        self._root = Path(directory).resolve()
        super().__init__(*args, directory=directory, **kwargs)

    # 표준 로그를 조용히 (테스트 잡음 방지). 필요 시 주석 해제.
    def log_message(self, fmt, *args):  # noqa: A002
        pass

    def _reject(self, code: int, msg: str) -> None:
        self.send_error(code, msg)

    def _check(self) -> bool:
        """요청 경로가 허용되는지 검사한다. 거부 시 응답을 보내고 False를 반환한다."""
        raw = urlsplit(self.path).path
        rel = unquote(raw)
        if ".." in rel.split("/"):
            self._reject(403, "path traversal blocked")
            return False
        if _is_denied(rel):
            self._reject(403, "not available")
            return False
        # translate_path로 실제 대상 경로를 구해 root 밖이면 거부 (심볼릭/이중 인코딩 방어)
        target = Path(self.translate_path(self.path)).resolve()
        try:
            target.relative_to(self._root)
        except ValueError:
            self._reject(403, "outside run directory")
            return False
        return True

    def do_GET(self) -> None:  # noqa: N802
        if self._check():
            super().do_GET()

    def do_HEAD(self) -> None:  # noqa: N802
        if self._check():
            super().do_HEAD()

    # GET/HEAD 이외 메서드는 상위 클래스에 정의돼 있지 않아 501로 거부된다 (읽기 전용).

    def send_head(self):
        """디렉터리 요청 시 index 대신 viewer.html을 우선 제공한다."""
        target = Path(self.translate_path(self.path))
        if target.is_dir() and (target / "viewer.html").exists():
            raw = urlsplit(self.path).path
            if not raw.endswith("/"):
                self.send_response(301)
                self.send_header("Location", raw + "/")
                self.end_headers()
                return None
            self.path = raw.rstrip("/") + "/viewer.html"
        return super().send_head()


def make_server(run_dir: str | Path, host: str = "127.0.0.1", port: int = 8787) -> HTTPServer:
    run_dir = Path(run_dir).resolve()
    if not run_dir.is_dir():
        raise FileNotFoundError(f"run 디렉터리가 아님: {run_dir}")
    handler = partial(ReadOnlyHandler, directory=str(run_dir))
    return HTTPServer((host, port), handler)


def _candidate_ips() -> dict[str, list[str]]:
    """머신의 후보 IP를 수집한다. Tailscale(100.64.0.0/10)과 LAN을 분리한다."""
    tailscale: list[str] = []
    lan: list[str] = []

    def add(ip: str) -> None:
        if not ip or ip.startswith("127."):
            return
        try:
            first, second = (int(x) for x in ip.split(".")[:2])
        except ValueError:
            return
        # Tailscale CGNAT 대역 100.64.0.0 ~ 100.127.255.255
        if first == 100 and 64 <= second <= 127:
            if ip not in tailscale:
                tailscale.append(ip)
        elif ip not in lan:
            lan.append(ip)

    # 1) tailscale CLI가 있으면 가장 정확하다 (인터페이스가 gethostname으로 안 잡히는 경우 대비)
    ts = shutil.which("tailscale")
    if ts:
        try:
            out = subprocess.run([ts, "ip", "-4"], capture_output=True, text=True, timeout=3)
            for line in out.stdout.splitlines():
                add(line.strip())
        except (OSError, subprocess.SubprocessError):
            pass

    # 2) 로컬 인터페이스에서 LAN/기타 IP 수집
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            add(info[4][0])
    except OSError:
        pass
    return {"tailscale": tailscale, "lan": lan}


def _startup_message(run_dir: Path, host: str, port: int) -> str:
    lines = [
        "RIM viewer server started.",
        f"Run directory: {run_dir}",
        "Local:",
        f"  http://127.0.0.1:{port}/",
    ]
    if host not in ("127.0.0.1", "localhost"):
        ips = _candidate_ips()
        if ips["tailscale"] or ips["lan"]:
            lines.append("Tailscale / LAN:")
            for ip in ips["tailscale"]:
                lines.append(f"  http://{ip}:{port}/   (Tailscale 추정)")
            for ip in ips["lan"]:
                lines.append(f"  http://{ip}:{port}/   (LAN)")
            lines.append("  or http://<machine-name>:{}/  (Tailscale MagicDNS)".format(port))
        else:
            lines.append("If you use Tailscale, open http://<your-tailscale-ip>:{}/ from iPhone Safari.".format(port))
        lines.append("Open this from iPhone Safari through Tailscale.")
    lines.append("Press Ctrl+C to stop.")
    return "\n".join(lines)


def serve(run_dir: str | Path, host: str = "127.0.0.1", port: int = 8787) -> None:
    run_dir = Path(run_dir).resolve()
    server = make_server(run_dir, host, port)
    print(_startup_message(run_dir, host, port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nRIM viewer server stopped.")
    finally:
        server.server_close()
