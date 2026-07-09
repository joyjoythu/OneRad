import pytest
from pathlib import Path
from app.agent.safety import Sandbox, validate_plan


def test_resolve_relative_path(tmp_path):
    sandbox = Sandbox(tmp_path)
    resolved = sandbox.resolve("sub/file.txt")
    assert resolved == (tmp_path / "sub" / "file.txt").resolve()


def test_rejects_path_outside_sandbox(tmp_path):
    sandbox = Sandbox(tmp_path)
    with pytest.raises(ValueError, match="outside project sandbox"):
        sandbox.resolve("../outside.txt")


def test_rejects_absolute_path_outside_sandbox(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    sandbox = Sandbox(root)
    with pytest.raises(ValueError, match="outside project sandbox"):
        sandbox.resolve("/etc/passwd")


def test_is_within(tmp_path):
    sandbox = Sandbox(tmp_path)
    assert sandbox.is_within("inside.txt") is True
    assert sandbox.is_within("../outside.txt") is False


def test_resolve_absolute_path_inside_sandbox(tmp_path):
    sandbox = Sandbox(tmp_path)
    inside = tmp_path / "inside.txt"
    resolved = sandbox.resolve(str(inside))
    assert resolved == inside.resolve()


def test_resolve_must_exist(tmp_path):
    sandbox = Sandbox(tmp_path)
    with pytest.raises(FileNotFoundError):
        sandbox.resolve("missing.txt", must_exist=True)


def test_rejects_symlink_escape(tmp_path):
    sandbox = Sandbox(tmp_path)
    symlink = tmp_path / "escape_link"
    target = tmp_path / ".." / "outside"
    try:
        symlink.symlink_to(target)
    except OSError as exc:
        # On Windows, creating symlinks requires elevated privileges
        # or Developer Mode. Skip the test when that is not available.
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Symlink creation requires elevated privileges on Windows")
        raise
    with pytest.raises(ValueError, match="outside project sandbox"):
        sandbox.resolve(symlink)


def test_is_within_returns_false_for_nonexistent(tmp_path):
    sandbox = Sandbox(tmp_path)
    # Inside nonexistent path should return True (is_within does not enforce must_exist).
    assert sandbox.is_within("nonexistent_inside.txt") is True
    # Outside nonexistent path should return False without leaking must_exist errors.
    assert sandbox.is_within("../nonexistent_outside.txt") is False


def test_validate_plan_accepts_allowed_actions(tmp_path):
    sandbox = Sandbox(tmp_path)
    plan = [
        {"action": "mkdir", "target": "new_dir", "reason": "create dir"},
        {"action": "copy", "source": "a.txt", "target": "b.txt"},
        {"action": "move", "source": "b.txt", "target": "c.txt"},
        {"action": "rename", "source": "c.txt", "target": "d.txt"},
    ]
    validated = validate_plan(plan, sandbox)
    assert len(validated) == 4
    assert all(item["action"] in {"mkdir", "copy", "move", "rename"} for item in validated)


def test_validate_plan_rejects_unsupported_action(tmp_path):
    sandbox = Sandbox(tmp_path)
    plan = [{"action": "delete", "source": "a.txt"}]
    with pytest.raises(ValueError, match="unsupported action 'delete'"):
        validate_plan(plan, sandbox)


def test_validate_plan_requires_source_target(tmp_path):
    sandbox = Sandbox(tmp_path)
    plan = [{"action": "copy", "source": "a.txt"}]
    with pytest.raises(ValueError, match="'copy' requires source and target"):
        validate_plan(plan, sandbox)


def test_validate_plan_rejects_outside_paths(tmp_path):
    sandbox = Sandbox(tmp_path)
    plan = [{"action": "copy", "source": "../outside.txt", "target": "inside.txt"}]
    with pytest.raises(ValueError, match="outside project sandbox"):
        validate_plan(plan, sandbox)


def test_validate_plan_respects_overwrite_flag(tmp_path):
    sandbox = Sandbox(tmp_path)
    plan = [{"action": "copy", "source": "a.txt", "target": "b.txt", "overwrite": True}]
    validated = validate_plan(plan, sandbox)
    assert validated[0]["overwrite"] is True

    plan_no_flag = [{"action": "copy", "source": "a.txt", "target": "b.txt"}]
    validated_no_flag = validate_plan(plan_no_flag, sandbox)
    assert validated_no_flag[0]["overwrite"] is False


def test_validate_plan_rejects_invalid_source_target_type(tmp_path):
    sandbox = Sandbox(tmp_path)
    plan = [{"action": "copy", "source": 123, "target": "b.txt"}]
    with pytest.raises(ValueError, match="source/target must be a path string"):
        validate_plan(plan, sandbox)

    plan = [{"action": "copy", "source": "a.txt", "target": ["list"]}]
    with pytest.raises(ValueError, match="source/target must be a path string"):
        validate_plan(plan, sandbox)
