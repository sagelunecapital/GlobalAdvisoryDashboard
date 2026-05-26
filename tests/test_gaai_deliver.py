"""
Tests for gaai_deliver.py -- covers all ACs for E07S01.
All network/subprocess calls are mocked; no real claude invocations.
"""

import sys
import inspect
import subprocess
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock, patch, mock_open, PropertyMock

import pytest

import importlib.util

_MODULE_PATH = Path(__file__).parent.parent / "gaai_deliver.py"
_spec = importlib.util.spec_from_file_location("gaai_deliver", _MODULE_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


# ---------------------------------------------------------------------------
# AC3: CLAUDE_SUBPROCESS_ARGS is a module-level list containing '--dangerously-skip-permissions'
# ---------------------------------------------------------------------------

class TestAC3SubprocessArgs:
    def test_constant_exists(self):
        assert hasattr(_mod, "CLAUDE_SUBPROCESS_ARGS")

    def test_constant_is_list(self):
        assert isinstance(_mod.CLAUDE_SUBPROCESS_ARGS, list)

    def test_constant_contains_required_flag(self):
        assert "--dangerously-skip-permissions" in _mod.CLAUDE_SUBPROCESS_ARGS

    def test_constant_is_module_level(self):
        src = inspect.getsource(_mod)
        assert "CLAUDE_SUBPROCESS_ARGS" in src


# ---------------------------------------------------------------------------
# AC6: pathlib.Path used for all path construction -- no string-based paths
# ---------------------------------------------------------------------------

class TestAC6PathlibOnly:
    def test_no_os_path_join(self):
        src = inspect.getsource(_mod)
        assert "os.path.join" not in src

    def test_no_os_getcwd(self):
        src = inspect.getsource(_mod)
        assert "os.getcwd" not in src

    def test_project_root_uses_pathlib(self):
        assert isinstance(_mod._PROJECT_ROOT, Path)

    def test_backlog_path_uses_pathlib(self):
        assert isinstance(_mod._BACKLOG_PATH, Path)

    def test_daemon_script_uses_pathlib(self):
        assert isinstance(_mod._DAEMON_SCRIPT, Path)


# ---------------------------------------------------------------------------
# AC7: All print/stderr output is ASCII-only (no Unicode characters)
# ---------------------------------------------------------------------------

class TestAC7AsciiOutput:
    def test_source_has_no_unicode_in_strings(self):
        src = inspect.getsource(_mod)
        try:
            src.encode("ascii")
        except UnicodeEncodeError:
            pytest.fail("gaai_deliver.py contains non-ASCII characters")


# ---------------------------------------------------------------------------
# AC1: Windows path -- reads backlog, launches subprocesses, exits correctly
# ---------------------------------------------------------------------------

SAMPLE_BACKLOG_YAML = """
items:
  - id: E99S01
    status: refined
    title: "Test story"
    artefact: contexts/artefacts/stories/E99S01.story.md
  - id: E99S02
    status: done
    title: "Already done"
    artefact: contexts/artefacts/stories/E99S02.story.md
"""


def _make_fake_path(exists=True, content=""):
    """Return a MagicMock that behaves like a Path with controllable exists/read_text."""
    p = MagicMock(spec=Path)
    p.exists.return_value = exists
    p.read_text.return_value = content
    p.__str__ = lambda self: "/fake/path"
    p.__truediv__ = lambda self, other: _make_fake_path(exists=False, content="")
    return p


class TestAC1WindowsPath:
    def test_reads_only_refined_stories(self):
        fake_backlog = _make_fake_path(exists=True)
        with patch.object(_mod, "_BACKLOG_PATH", fake_backlog):
            with patch("builtins.open", mock_open(read_data=SAMPLE_BACKLOG_YAML)):
                stories = _mod._read_refined_stories()
        assert len(stories) == 1
        assert stories[0]["id"] == "E99S01"

    def test_exits_1_if_backlog_missing(self):
        fake_backlog = _make_fake_path(exists=False)
        with patch.object(_mod, "_BACKLOG_PATH", fake_backlog):
            with pytest.raises(SystemExit) as exc_info:
                _mod._read_refined_stories()
        assert exc_info.value.code == 1

    def test_exits_1_if_backlog_invalid_yaml(self):
        fake_backlog = _make_fake_path(exists=True)
        with patch.object(_mod, "_BACKLOG_PATH", fake_backlog):
            with patch("builtins.open", mock_open(read_data=": invalid: {{{yaml")):
                with pytest.raises(SystemExit) as exc_info:
                    _mod._read_refined_stories()
        assert exc_info.value.code == 1

    def test_no_refined_stories_returns_0(self):
        empty_backlog_yaml = "items:\n  - id: E1\n    status: done\n    title: Done\n"
        fake_backlog = _make_fake_path(exists=True)
        with patch.object(_mod, "_BACKLOG_PATH", fake_backlog):
            with patch("builtins.open", mock_open(read_data=empty_backlog_yaml)):
                result = _mod._run_windows([])
        assert result == 0

    def test_subprocess_success_returns_0(self):
        fake_backlog = _make_fake_path(exists=True)
        fake_artefact = _make_fake_path(exists=False)
        with patch.object(_mod, "_BACKLOG_PATH", fake_backlog):
            with patch("builtins.open", mock_open(read_data=SAMPLE_BACKLOG_YAML)):
                with patch.object(_mod, "_build_story_input", return_value="story input"):
                    with patch("subprocess.run") as mock_run:
                        mock_run.return_value = MagicMock(returncode=0)
                        result = _mod._run_windows([])
        assert result == 0

    def test_subprocess_failure_returns_1(self):
        fake_backlog = _make_fake_path(exists=True)
        with patch.object(_mod, "_BACKLOG_PATH", fake_backlog):
            with patch("builtins.open", mock_open(read_data=SAMPLE_BACKLOG_YAML)):
                with patch.object(_mod, "_build_story_input", return_value="story input"):
                    with patch("subprocess.run") as mock_run:
                        mock_run.return_value = MagicMock(returncode=1)
                        result = _mod._run_windows([])
        assert result == 1

    def test_subprocess_called_with_claude_p_and_args(self):
        single_story = (
            "items:\n"
            "  - id: E99S01\n"
            "    status: refined\n"
            "    title: Test story\n"
            "    artefact: contexts/artefacts/stories/E99S01.story.md\n"
        )
        fake_backlog = _make_fake_path(exists=True)
        with patch.object(_mod, "_BACKLOG_PATH", fake_backlog):
            with patch("builtins.open", mock_open(read_data=single_story)):
                with patch.object(_mod, "_build_story_input", return_value="story input"):
                    with patch("subprocess.run") as mock_run:
                        mock_run.return_value = MagicMock(returncode=0)
                        _mod._run_windows([])
        call_args = mock_run.call_args[0][0]
        assert "claude" in call_args
        assert "-p" in call_args
        assert "--dangerously-skip-permissions" in call_args

    def test_subprocess_not_invoked_with_daemon_script(self):
        fake_backlog = _make_fake_path(exists=True)
        with patch.object(_mod, "_BACKLOG_PATH", fake_backlog):
            with patch("builtins.open", mock_open(read_data=SAMPLE_BACKLOG_YAML)):
                with patch.object(_mod, "_build_story_input", return_value="story input"):
                    with patch("subprocess.run") as mock_run:
                        mock_run.return_value = MagicMock(returncode=0)
                        _mod._run_windows([])
        for call in mock_run.call_args_list:
            cmd = call[0][0]
            assert "daemon-start.sh" not in str(cmd)
            assert "delivery-daemon.sh" not in str(cmd)


# ---------------------------------------------------------------------------
# AC2: Linux/macOS delegates to daemon-start.sh with all args passed through
# ---------------------------------------------------------------------------

class TestAC2UnixPath:
    def test_delegates_to_daemon_script(self):
        fake_daemon = _make_fake_path(exists=True)
        with patch.object(_mod, "_DAEMON_SCRIPT", fake_daemon):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                _mod._run_unix(["--start", "--interval", "30"])
        call_args = mock_run.call_args[0][0]
        assert "--start" in call_args
        assert "--interval" in call_args
        assert "30" in call_args

    def test_args_passed_through_unchanged(self):
        fake_daemon = _make_fake_path(exists=True)
        with patch.object(_mod, "_DAEMON_SCRIPT", fake_daemon):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                _mod._run_unix(["--status"])
        call_args = mock_run.call_args[0][0]
        assert "--status" in call_args

    def test_passes_returncode_through(self):
        fake_daemon = _make_fake_path(exists=True)
        with patch.object(_mod, "_DAEMON_SCRIPT", fake_daemon):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=42)
                result = _mod._run_unix([])
        assert result == 42


# ---------------------------------------------------------------------------
# AC4: Exit codes -- 0 on clean exit, 1 on error; unsupported platform exits 1
# ---------------------------------------------------------------------------

class TestAC4ExitCodes:
    def test_unsupported_platform_exits_1(self, capsys):
        with patch.object(sys, "platform", "freebsd"):
            with pytest.raises(SystemExit) as exc_info:
                _mod.main()
        assert exc_info.value.code == 1

    def test_unsupported_platform_message_contains_platform(self, capsys):
        with patch.object(sys, "platform", "freebsd"):
            with pytest.raises(SystemExit):
                _mod.main()
        captured = capsys.readouterr()
        assert "freebsd" in captured.err

    def test_unsupported_platform_message_is_ascii(self, capsys):
        with patch.object(sys, "platform", "haiku"):
            with pytest.raises(SystemExit):
                _mod.main()
        captured = capsys.readouterr()
        try:
            captured.err.encode("ascii")
        except UnicodeEncodeError:
            pytest.fail("stderr output contains non-ASCII characters")


# ---------------------------------------------------------------------------
# AC5: daemon-start.sh not found on Linux/macOS exits 1 with error message
# ---------------------------------------------------------------------------

class TestAC5DaemonNotFound:
    def test_exits_1_if_daemon_not_found(self):
        fake_daemon = _make_fake_path(exists=False)
        with patch.object(_mod, "_DAEMON_SCRIPT", fake_daemon):
            with pytest.raises(SystemExit) as exc_info:
                _mod._run_unix([])
        assert exc_info.value.code == 1

    def test_error_message_contains_daemon_name(self, capsys):
        fake_daemon = _make_fake_path(exists=False)
        with patch.object(_mod, "_DAEMON_SCRIPT", fake_daemon):
            with pytest.raises(SystemExit):
                _mod._run_unix([])
        captured = capsys.readouterr()
        assert "daemon-start.sh" in captured.err

    def test_error_message_is_ascii(self, capsys):
        fake_daemon = _make_fake_path(exists=False)
        with patch.object(_mod, "_DAEMON_SCRIPT", fake_daemon):
            with pytest.raises(SystemExit):
                _mod._run_unix([])
        captured = capsys.readouterr()
        try:
            captured.err.encode("ascii")
        except UnicodeEncodeError:
            pytest.fail("stderr output contains non-ASCII characters")
