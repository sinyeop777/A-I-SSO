"""
백엔드 서버 일괄 실행 스크립트
  - auth.py            → http://localhost:8000  (Google 로그인 API)
  - document_transform.py → http://localhost:8001  (문서 변환 API)
실행: python run_servers.py
종료: Ctrl+C
"""

import subprocess
import sys
import signal
import os
import socket
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def resolve_python_executable():
    # 실행 주체가 시스템 Python이어도 프로젝트 .venv를 우선 사용한다.
    venv_python = os.path.join(BASE_DIR, ".venv", "Scripts", "python.exe")
    if os.path.exists(venv_python):
        return venv_python
    return sys.executable


PYTHON = resolve_python_executable()

# 개별 FastAPI 서버 실행 정의.
# required=True 서버가 종료되면 전체를 종료하고,
# required=False 서버는 실패해도 나머지를 유지한다.
SERVERS = [
    {
        "name": "auth",
        "app": "backend.auth:app",
        "port": 8000,
        "required": True,
    },
    {
        "name": "document_transform",
        "app": "backend.document_transform:app",
        "port": 8001,
        "required": False,
    },
    {
        "name": "cctv",
        "app": "backend.cctv:app",
        "port": 8003,
        "required": False,
    },
]

processes = []


def is_port_available(host: str, port: int) -> bool:
    # 실행 전에 포트 바인딩 가능 여부를 빠르게 점검한다.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def shutdown(sig=None, frame=None):
    # 모든 하위 서버 프로세스를 안전하게 종료한다.
    print("\n[run_servers] 서버를 종료합니다...")
    for item in processes:
        p = item["proc"]
        p.terminate()
    for item in processes:
        p = item["proc"]
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
    sys.exit(0)


if __name__ == "__main__":
    # Ctrl+C(SIGINT) 또는 SIGTERM 수신 시 공통 종료 핸들러를 사용한다.
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print("[run_servers] 백엔드 서버를 시작합니다.\n")
    print(f"[run_servers] Python 인터프리터: {PYTHON}\n")
    started_endpoints = []
    for server in SERVERS:
        host = "127.0.0.1"
        port = server["port"]

        # 포트가 점유된 경우 사용 가능한 포트를 동적으로 할당
        while not is_port_available(host, port):
            port += 1
        server["port"] = port

        if not is_port_available(host, port):
            msg = f"[run_servers] {server['name']} 포트 {port} 사용 불가(점유/권한)."
            if server["required"]:
                print(msg + " 필수 서버이므로 실행을 중단합니다.")
                sys.exit(1)
            print(msg + " 선택 서버이므로 건너뜁니다.")
            continue

        cmd = [
            PYTHON,
            "-m",
            "uvicorn",
            server["app"],
            "--reload",
            "--port",
            str(port),
            "--host",
            host,
        ]

        # 각 서버를 독립 프로세스로 실행한다.
        p = subprocess.Popen(cmd, cwd=BASE_DIR)
        processes.append({"proc": p, "name": server["name"], "required": server["required"]})
        started_endpoints.append((server["name"], host, port))
        print(f"  ✓ {server['name']} 서버 실행 중 (PID {p.pid}, {host}:{port})")

    if started_endpoints:
        print("")
        for name, host, port in started_endpoints:
            print(f"  {name:<18} → http://{host}:{port}")
    print("\n  종료하려면 Ctrl+C 를 누르세요.\n")

    # 필수 서버(auth)만 감시 대상으로 두고, 선택 서버 실패는 경고 후 계속 동작한다.
    while True:
        alive = []
        for item in processes:
            p = item["proc"]
            if p.poll() is not None:
                if item["required"]:
                    print(f"[run_servers] 필수 서버 {item['name']}({p.pid})가 종료됐습니다. 전체 종료.")
                    shutdown()
                else:
                    print(f"[run_servers] 선택 서버 {item['name']}({p.pid})가 종료되었습니다. 다른 서버는 계속 실행합니다.")
                    continue
            alive.append(item)

        processes = alive

        if not processes:
            print("[run_servers] 실행 중인 서버가 없어 종료합니다.")
            sys.exit(0)

        time.sleep(1)
