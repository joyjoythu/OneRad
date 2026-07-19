import os
import string
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, status

router = APIRouter()


def _list_drives() -> List[str]:
    """Windows 下返回存在的盘符根路径；其它平台返回空列表。"""
    if sys.platform != "win32":
        return []
    return [
        f"{letter}:\\"
        for letter in string.ascii_uppercase
        if os.path.exists(f"{letter}:\\")
    ]


@router.get("/list", response_model=Dict[str, Any])
def list_directory(
    path: Optional[str] = Query(
        None, description="要列出的目录绝对路径；缺省为用户主目录"
    ),
) -> Dict[str, Any]:
    """List subdirectories of a directory for the in-app folder browser.

    只返回子目录（过滤隐藏目录），供创建项目时选择文件夹使用；
    只做只读列举，path 须为绝对路径。
    """
    if path:
        parsed = Path(path)
        if not parsed.is_absolute():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="path 必须是绝对路径",
            )
        directory = parsed.resolve()
    else:
        directory = Path.home()

    if not directory.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="目录不存在"
        )
    if not directory.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="该路径不是目录"
        )

    try:
        entries = sorted(directory.iterdir(), key=lambda p: p.name.lower())
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="没有访问该目录的权限"
        )

    dirs = [
        {"name": entry.name, "path": str(entry)}
        for entry in entries
        if entry.is_dir() and not entry.name.startswith(".")
    ]
    parent = directory.parent
    return {
        "path": str(directory),
        "parent": str(parent) if parent != directory else None,
        "dirs": dirs,
        "drives": _list_drives(),
    }
