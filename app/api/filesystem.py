"""Read-only local filesystem browser endpoints.

The browser is intentionally limited to loopback clients because the API
reveals directory names on the machine running OneRad.  It never creates,
moves, edits, or deletes files.

Docker deployments:
  Set ``ONERAD_ALLOW_REMOTE_FS=1`` to relax the loopback restriction
  (the browser runs on the host, so requests arrive from the Docker
  bridge IP rather than 127.0.0.1).

  Set ``ONERAD_FS_ROOTS`` to a colon-separated list of host directories
  that have been bind-mounted into the container so the path-picker can
  surface them (e.g. ``ONERAD_FS_ROOTS=/data/input:/data/output``).
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import string
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query, Request, status


router = APIRouter()
_LIST_TIMEOUT_SECONDS = 5.0


def _allow_remote_fs() -> bool:
    return os.environ.get("ONERAD_ALLOW_REMOTE_FS", "") == "1"


def _custom_fs_roots() -> List[str]:
    """Parse ONERAD_FS_ROOTS into a list of existing directory paths."""
    raw = os.environ.get("ONERAD_FS_ROOTS", "").strip()
    if not raw:
        return []
    sep = ";" if os.name == "nt" else ":"
    roots: List[str] = []
    for part in raw.split(sep):
        part = part.strip()
        if not part:
            continue
        try:
            p = Path(part).expanduser().resolve(strict=False)
            if p.is_dir():
                roots.append(str(p))
        except (OSError, RuntimeError, ValueError):
            continue
    return roots


def _is_loopback(host: str) -> bool:
    """Return whether *host* represents a loopback client.

    Starlette's TestClient uses ``testclient`` as the synthetic peer name, so
    it is allowed for endpoint tests.

    When ``ONERAD_ALLOW_REMOTE_FS=1`` every client is considered loopback
    (used in Docker deployments).
    """

    if _allow_remote_fs():
        return True
    if host in {"localhost", "testclient"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _require_loopback(request: Request) -> None:
    client_host = request.client.host if request.client else ""
    if not _is_loopback(client_host):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="文件系统浏览仅允许从运行 OneRad 的本机访问（Docker 部署请设置 ONERAD_ALLOW_REMOTE_FS=1）",
        )


def _resolved_path(raw_path: str) -> Path:
    if not raw_path or "\x00" in raw_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="路径不能为空或包含非法字符",
        )
    try:
        return Path(raw_path).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"无法解析路径: {exc}",
        ) from exc


def _root_candidates() -> List[Dict[str, str]]:
    candidates: List[Dict[str, str]] = []

    # 1) Custom roots from ONERAD_FS_ROOTS (Docker bind-mounts, etc.)
    for custom_path in _custom_fs_roots():
        candidates.append({"name": f"📂 {custom_path}", "path": custom_path})

    # 2) Standard OS roots
    home = Path.home().resolve(strict=False)
    if home.exists():
        candidates.append({"name": "主目录", "path": str(home)})

    if os.name == "nt":
        for letter in string.ascii_uppercase:
            drive = Path(f"{letter}:\\")
            try:
                if drive.exists():
                    candidates.append({"name": f"本地磁盘 ({letter}:)", "path": str(drive)})
            except OSError:
                continue
    else:
        candidates.append({"name": "根目录", "path": "/"})

    seen = set()
    roots = []
    for item in candidates:
        key = os.path.normcase(os.path.normpath(item["path"]))
        if key not in seen:
            seen.add(key)
            roots.append(item)
    return roots


def _breadcrumbs(path: Path) -> List[Dict[str, str]]:
    parts = path.parts
    if not parts:
        return []

    current = Path(parts[0])
    crumbs = [{"name": parts[0], "path": str(current)}]
    for part in parts[1:]:
        current = current / part
        crumbs.append({"name": part, "path": str(current)})
    return crumbs


def _list_directory(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(str(path))
    if not path.is_dir():
        raise NotADirectoryError(str(path))

    entries: List[Dict[str, Any]] = []
    for entry in path.iterdir():
        try:
            is_dir = entry.is_dir()
        except OSError:
            is_dir = False
        entries.append({
            "name": entry.name,
            "path": str(entry.resolve(strict=False)),
            "is_dir": is_dir,
        })
    entries.sort(key=lambda item: (not item["is_dir"], item["name"].casefold()))

    parent = None if path.parent == path else str(path.parent)
    return {
        "path": str(path),
        "parent": parent,
        "breadcrumbs": _breadcrumbs(path),
        "entries": entries,
    }


@router.get("/roots", response_model=Dict[str, Any])
def list_roots(request: Request) -> Dict[str, Any]:
    """Return browseable filesystem roots for the local machine."""

    _require_loopback(request)
    return {"roots": _root_candidates()}


@router.get("/entries", response_model=Dict[str, Any])
async def list_entries(
    request: Request,
    path: str = Query(..., min_length=1),
) -> Dict[str, Any]:
    """List one directory without mutating the filesystem."""

    _require_loopback(request)
    resolved = _resolved_path(path)
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_list_directory, resolved),
            timeout=_LIST_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="目录读取超时，请检查磁盘或网络路径是否可用",
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"目录不存在: {resolved}",
        ) from exc
    except NotADirectoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"路径不是目录: {resolved}",
        ) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"没有权限读取目录: {resolved}",
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"无法读取目录: {exc}",
        ) from exc
