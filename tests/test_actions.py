import pytest
from pathlib import Path
from app.actions import execute_plan


def test_execute_copy_and_mkdir(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("hello")

    plan = [
        {"action": "mkdir", "target": "backup", "reason": "创建备份目录"},
        {"action": "copy", "source": "src/a.txt", "target": "backup/a.txt", "reason": "备份文件"},
    ]
    results = execute_plan(plan, str(tmp_path))
    assert results[0]["success"] is True
    assert results[1]["success"] is True
    assert (tmp_path / "backup" / "a.txt").read_text() == "hello"


def test_rejects_delete_action(tmp_path):
    plan = [{"action": "delete", "source": "x.txt", "reason": "删除"}]
    results = execute_plan(plan, str(tmp_path))
    assert results[0]["success"] is False


def test_target_exists_without_overwrite(tmp_path):
    (tmp_path / "a.txt").write_text("existing")
    (tmp_path / "b.txt").write_text("new")
    plan = [{"action": "copy", "source": "b.txt", "target": "a.txt", "reason": "覆盖"}]
    results = execute_plan(plan, str(tmp_path))
    assert results[0]["success"] is False
    assert "exists" in results[0]["error"].lower()


def test_execute_move(tmp_path):
    (tmp_path / "a.txt").write_text("move me")
    plan = [{"action": "move", "source": "a.txt", "target": "moved/a.txt", "reason": "移动文件"}]
    results = execute_plan(plan, str(tmp_path))
    assert results[0]["success"] is True
    assert not (tmp_path / "a.txt").exists()
    assert (tmp_path / "moved" / "a.txt").read_text() == "move me"


def test_execute_rename(tmp_path):
    (tmp_path / "old.txt").write_text("rename me")
    plan = [{"action": "rename", "source": "old.txt", "target": "new.txt", "reason": "重命名文件"}]
    results = execute_plan(plan, str(tmp_path))
    assert results[0]["success"] is True
    assert not (tmp_path / "old.txt").exists()
    assert (tmp_path / "new.txt").read_text() == "rename me"


def test_execute_copy_overwrite_file(tmp_path):
    (tmp_path / "a.txt").write_text("old")
    (tmp_path / "b.txt").write_text("new")
    plan = [
        {
            "action": "copy",
            "source": "b.txt",
            "target": "a.txt",
            "overwrite": True,
            "reason": "覆盖文件",
        }
    ]
    results = execute_plan(plan, str(tmp_path))
    assert results[0]["success"] is True
    assert (tmp_path / "a.txt").read_text() == "new"


def test_execute_copy_directory(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "x.txt").write_text("inside dir")
    plan = [{"action": "copy", "source": "src", "target": "dst", "reason": "复制目录"}]
    results = execute_plan(plan, str(tmp_path))
    assert results[0]["success"] is True
    assert (tmp_path / "dst").is_dir()
    assert (tmp_path / "dst" / "x.txt").read_text() == "inside dir"


def test_backup_created_on_overwrite(tmp_path):
    (tmp_path / "a.txt").write_text("original")
    (tmp_path / "b.txt").write_text("replacement")
    plan = [
        {
            "action": "copy",
            "source": "b.txt",
            "target": "a.txt",
            "overwrite": True,
            "reason": "覆盖并备份",
        }
    ]
    results = execute_plan(plan, str(tmp_path))
    assert results[0]["success"] is True
    backup_dirs = list((tmp_path / ".onerad_backup").iterdir())
    assert len(backup_dirs) == 1
    assert (backup_dirs[0] / "a.txt").read_text() == "original"


def test_missing_source_fails(tmp_path):
    plan = [{"action": "copy", "source": "missing.txt", "target": "dest.txt", "reason": "复制不存在的文件"}]
    results = execute_plan(plan, str(tmp_path))
    assert results[0]["success"] is False


def test_path_outside_sandbox_fails(tmp_path):
    (tmp_path / "a.txt").write_text("safe")
    plan = [{"action": "copy", "source": "../a.txt", "target": "b.txt", "reason": "越界路径"}]
    results = execute_plan(plan, str(tmp_path))
    assert results[0]["success"] is False


def test_execute_mkdir_nested(tmp_path):
    plan = [{"action": "mkdir", "target": "a/b/c", "reason": "创建嵌套目录"}]
    results = execute_plan(plan, str(tmp_path))
    assert results[0]["success"] is True
    assert (tmp_path / "a" / "b" / "c").is_dir()


def test_execute_move_into_existing_directory(tmp_path):
    (tmp_path / "a.txt").write_text("move into dir")
    (tmp_path / "dst").mkdir()
    plan = [
        {"action": "move", "source": "a.txt", "target": "dst", "reason": "移动到现有目录"}
    ]
    results = execute_plan(plan, str(tmp_path))
    assert results[0]["success"] is True
    assert not (tmp_path / "a.txt").exists()
    assert (tmp_path / "dst" / "a.txt").read_text() == "move into dir"


def test_execute_copy_directory_with_overwrite(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "x.txt").write_text("new")
    dst = tmp_path / "dst"
    dst.mkdir()
    (dst / "x.txt").write_text("old")
    (dst / "y.txt").write_text("extra")
    plan = [
        {
            "action": "copy",
            "source": "src",
            "target": "dst",
            "overwrite": True,
            "reason": "覆盖目录",
        }
    ]
    results = execute_plan(plan, str(tmp_path))
    assert results[0]["success"] is True
    assert (tmp_path / "dst" / "x.txt").read_text() == "new"
    assert not (tmp_path / "dst" / "y.txt").exists()
    backup_dirs = list((tmp_path / ".onerad_backup").iterdir())
    assert len(backup_dirs) == 1
    assert (backup_dirs[0] / "dst" / "x.txt").read_text() == "old"
    assert (backup_dirs[0] / "dst" / "y.txt").read_text() == "extra"


def test_execute_rename_overwrite(tmp_path):
    (tmp_path / "old.txt").write_text("source content")
    (tmp_path / "new.txt").write_text("target original")
    plan = [
        {
            "action": "rename",
            "source": "old.txt",
            "target": "new.txt",
            "overwrite": True,
            "reason": "重命名覆盖",
        }
    ]
    results = execute_plan(plan, str(tmp_path))
    assert results[0]["success"] is True
    assert not (tmp_path / "old.txt").exists()
    assert (tmp_path / "new.txt").read_text() == "source content"
    backup_dirs = list((tmp_path / ".onerad_backup").iterdir())
    assert len(backup_dirs) == 1
    assert (backup_dirs[0] / "new.txt").read_text() == "target original"
