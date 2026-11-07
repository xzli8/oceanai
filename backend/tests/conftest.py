import os
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

BACKEND = Path(__file__).resolve().parent.parent


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Env:
    def __init__(self, base_url: str, db: str):
        self.base_url = base_url
        self.db = db

    def client(self, actor: str | None = None, tenant: int | None = None, **kw) -> httpx.Client:
        headers = {}
        if actor:
            headers["X-Actor"] = actor
        if tenant is not None:
            headers["X-Tenant-Id"] = str(tenant)
        return httpx.Client(base_url=self.base_url, headers=headers, timeout=120, trust_env=False, **kw)

    def sql(self, query: str, params=()):
        conn = sqlite3.connect(self.db)
        try:
            return conn.execute(query, params).fetchall()
        finally:
            conn.close()

    def tenant_id(self, name: str) -> int:
        return self.sql("SELECT id FROM tenants WHERE name = ?", (name,))[0][0]

    def course_id(self, tenant: str, title: str) -> int:
        return self.sql("SELECT c.id FROM courses c JOIN tenants t ON t.id = c.tenant_id"
                        " WHERE t.name = ? AND c.title = ?", (tenant, title))[0][0]


@pytest.fixture
def env(tmp_path):
    """Fresh seeded DB + real uvicorn process per test (real HTTP concurrency, real WAL behavior)."""
    db = str(tmp_path / "test.db")
    proc_env = {**os.environ, "CERT_DB_PATH": db}
    subprocess.run([sys.executable, "-m", "app.seed"], cwd=BACKEND, env=proc_env, check=True,
                   capture_output=True)
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--log-level", "warning"],
        cwd=BACKEND, env=proc_env,
    )
    base = f"http://127.0.0.1:{port}"
    try:  # always reap the server, even if startup or the test raises something unexpected
        for _ in range(100):
            if proc.poll() is not None:
                raise RuntimeError("server exited during startup")
            try:
                httpx.get(base + "/api/actors", timeout=1, trust_env=False)
                break
            except httpx.HTTPError:
                time.sleep(0.1)
        else:
            raise RuntimeError("server did not start")
        e = Env(base, db)
        e.proc_env = proc_env
        yield e
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
