#!/usr/bin/env python3
"""End-to-end smoke test for the Vue + FastAPI OneRad stack.

This script starts the FastAPI server, exercises the API and SSE endpoints,
verifies the built frontend is served, and cleans up after itself.
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.error import HTTPError

BASE_URL = "http://127.0.0.1:8000"
ROOT = Path(__file__).resolve().parent
VENV_PYTHON = ROOT / ".." / ".." / ".venv" / "Scripts" / "python.exe"
SMOKE_DATA_DIR = ROOT / "smoke_data"


def _http(method, path, data=None, headers=None, timeout=10):
    url = f"{BASE_URL}{path}"
    req_headers = {"Accept": "application/json"}
    if headers:
        req_headers.update(headers)
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        req_headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, method=method, headers=req_headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8"), dict(resp.headers)


def _start_server():
    env = os.environ.copy()
    env["ONERAD_DATA_DIR"] = str(SMOKE_DATA_DIR)
    # Ensure we don't accidentally pick up a real API key for the smoke test.
    env.pop("DEEPSEEK_API_KEY", None)
    env.pop("OPENAI_API_KEY", None)

    proc = subprocess.Popen(
        [
            str(VENV_PYTHON),
            str(ROOT / "main.py"),
            "--host", "127.0.0.1",
            "--port", "8000",
            "--base-url", "https://api.deepseek.com/v1",
            "--model", "deepseek-chat",
        ],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    # Wait for the server to accept connections.
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            status, _, _ = _http("GET", "/")
            if status == 200:
                return proc
        except Exception:
            if proc.poll() is not None:
                out = proc.stdout.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"Server exited early with code {proc.returncode}.\n{out}")
            time.sleep(0.5)
    raise RuntimeError("Server did not start within 30 seconds")


def _stop_server(proc):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    # Give the OS a moment to release SQLite file handles before cleanup.
    time.sleep(0.5)


def _cleanup_smoke_data():
    for _ in range(3):
        shutil.rmtree(SMOKE_DATA_DIR, ignore_errors=True)
        if not SMOKE_DATA_DIR.exists():
            return
        time.sleep(0.5)
    # Last resort: try without ignore_errors so the user sees any problem.
    shutil.rmtree(SMOKE_DATA_DIR, ignore_errors=True)


def _check(name, passed, details=""):
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] {name}")
    if details:
        print(f"       {details}")
    return passed


def main():
    # Clean up any stale smoke data from previous runs.
    shutil.rmtree(SMOKE_DATA_DIR, ignore_errors=True)
    SMOKE_DATA_DIR.mkdir(parents=True, exist_ok=True)

    proc = None
    results = []
    try:
        print("Starting FastAPI server...")
        proc = _start_server()
        results.append(_check("Backend startup", True, "server listening on 127.0.0.1:8000"))

        # 2. API health/static check
        try:
            status, body, _ = _http("GET", "/")
            results.append(_check("GET / returns 200", status == 200, f"status={status}"))
        except Exception as exc:
            results.append(_check("GET / returns 200", False, str(exc)))

        try:
            status, body, _ = _http("GET", "/api/projects")
            projects = json.loads(body) if body else []
            results.append(_check("GET /api/projects returns JSON list", status == 200 and isinstance(projects, list), f"status={status}, body preview={body[:120]}"))
        except Exception as exc:
            results.append(_check("GET /api/projects returns JSON list", False, str(exc)))

        # 3. Project CRUD flow
        temp_project_dir = SMOKE_DATA_DIR / "test_project"
        temp_project_dir.mkdir(parents=True, exist_ok=True)
        project_id = None
        try:
            status, body, _ = _http("POST", "/api/projects", {
                "name": "smoke-test-project",
                "path": "test_project",
                "description": "created by smoke_test.py",
            })
            project = json.loads(body) if body else {}
            project_id = project.get("id")
            results.append(_check("POST /api/projects creates project", status == 201 and bool(project_id), f"status={status}, id={project_id}"))
        except Exception as exc:
            results.append(_check("POST /api/projects creates project", False, str(exc)))

        if project_id:
            try:
                status, body, _ = _http("GET", f"/api/projects/{project_id}")
                fetched = json.loads(body) if body else {}
                results.append(_check("GET /api/projects/{id}", status == 200 and fetched.get("id") == project_id, f"status={status}"))
            except Exception as exc:
                results.append(_check("GET /api/projects/{id}", False, str(exc)))

            try:
                status, body, _ = _http("PUT", f"/api/projects/{project_id}/config", {
                    "image_dir": str(temp_project_dir / "images"),
                    "clinical_path": "",
                    "output_dir": str(temp_project_dir / "outputs"),
                    "modality": "auto",
                    "covariates": "",
                    "model": "deepseek-chat",
                    "api_key": "",
                })
                results.append(_check("PUT /api/projects/{id}/config", status == 200, f"status={status}"))
            except Exception as exc:
                results.append(_check("PUT /api/projects/{id}/config", False, str(exc)))

        # 4. Frontend static assets
        try:
            status, body, _ = _http("GET", "/")
            has_app_div = '<div id="app">' in body
            results.append(_check("Frontend HTML contains #app", status == 200 and has_app_div, f"status={status}, has_div={has_app_div}"))
        except Exception as exc:
            results.append(_check("Frontend HTML contains #app", False, str(exc)))

        try:
            dist_dir = ROOT / "frontend" / "dist" / "assets"
            assets = list(dist_dir.iterdir()) if dist_dir.exists() else []
            first_asset = next((a.name for a in assets if a.is_file()), None)
            if first_asset:
                status, _, _ = _http("GET", f"/assets/{first_asset}")
                results.append(_check("Frontend asset reachable", status == 200, f"asset={first_asset}, status={status}"))
            else:
                results.append(_check("Frontend asset reachable", False, "no assets found"))
        except Exception as exc:
            results.append(_check("Frontend asset reachable", False, str(exc)))

        # 5. SSE pipeline
        run_id = None
        if project_id:
            try:
                status, body, _ = _http("POST", f"/api/projects/{project_id}/runs", {
                    "image_dir": str(temp_project_dir / "images"),
                    "clinical_path": "",
                    "output_dir": str(temp_project_dir / "outputs"),
                    "modality": "auto",
                    "covariates": "",
                    "model": "deepseek-chat",
                    "api_key": "",
                })
                run_data = json.loads(body) if body else {}
                run_id = run_data.get("run_id")
                results.append(_check("POST /api/projects/{id}/run starts run", status == 202 and bool(run_id), f"status={status}, run_id={run_id}"))
            except Exception as exc:
                results.append(_check("POST /api/projects/{id}/run starts run", False, str(exc)))

        if run_id:
            try:
                req = urllib.request.Request(f"{BASE_URL}/api/runs/{run_id}/events", headers={"Accept": "text/event-stream"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    content_type = resp.headers.get("Content-Type", "")
                    chunk = resp.read(2048).decode("utf-8", errors="replace")
                    passed = resp.status == 200 and "text/event-stream" in content_type and chunk.strip() != ""
                    results.append(_check("SSE /api/runs/{id}/events opens and emits", passed, f"status={resp.status}, content-type={content_type}, bytes_read={len(chunk)}"))
            except Exception as exc:
                results.append(_check("SSE /api/runs/{id}/events opens and emits", False, str(exc)))

        # 6. Agent chat endpoint
        thread_id = None
        if project_id:
            try:
                status, body, _ = _http("POST", f"/api/agent/threads?project_id={project_id}")
                thread_data = json.loads(body) if body else {}
                thread_id = thread_data.get("thread_id")
                results.append(_check("POST /api/agent/threads creates thread", status == 201 and bool(thread_id), f"status={status}, thread_id={thread_id}"))
            except Exception as exc:
                results.append(_check("POST /api/agent/threads creates thread", False, str(exc)))

        if thread_id:
            try:
                status, body, _ = _http("GET", f"/api/agent/threads/{thread_id}")
                thread_state = json.loads(body) if body else {}
                required_keys = {"messages", "interrupt_type", "operation_log", "pending_plan"}
                has_keys = required_keys.issubset(thread_state.keys())
                results.append(_check("GET /api/agent/threads/{id} state payload", status == 200 and has_keys, f"status={status}, keys={list(thread_state.keys())}"))
            except Exception as exc:
                results.append(_check("GET /api/agent/threads/{id} state payload", False, str(exc)))

            try:
                req = urllib.request.Request(f"{BASE_URL}/api/agent/threads/{thread_id}/events", headers={"Accept": "text/event-stream"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    content_type = resp.headers.get("Content-Type", "")
                    passed = resp.status == 200 and "text/event-stream" in content_type
                    results.append(_check("SSE /api/agent/threads/{id}/events opens", passed, f"status={resp.status}, content-type={content_type}"))
            except Exception as exc:
                results.append(_check("SSE /api/agent/threads/{id}/events opens", False, str(exc)))

        # Delete the test project if we created one.
        if project_id:
            try:
                status, _, _ = _http("DELETE", f"/api/projects/{project_id}")
                results.append(_check("DELETE /api/projects/{id}", status in (200, 204), f"status={status}"))
            except Exception as exc:
                results.append(_check("DELETE /api/projects/{id}", False, str(exc)))

    finally:
        print("\nStopping server...")
        if proc is not None:
            _stop_server(proc)
        # Clean up temporary smoke data.
        _cleanup_smoke_data()
        # Clean up stray logs from manual runs if present.
        for stale in (ROOT / "server.log", ROOT / "server.pid"):
            try:
                stale.unlink()
            except FileNotFoundError:
                pass

    print("\n=== Smoke Test Report ===")
    all_passed = all(results)
    for r in results:
        pass
    print(f"\nTotal: {len(results)} checks, {sum(results)} passed, {len(results) - sum(results)} failed")
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
