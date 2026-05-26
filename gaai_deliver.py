"""
gaai_deliver.py - GAAI Delivery Entrypoint with Platform Detection

On Windows (sys.platform == 'win32'):
    Reads active.backlog.yaml, launches claude -p subprocesses for refined stories.
On Linux/macOS:
    Delegates to daemon-start.sh with all args passed through.
On other platforms:
    Exits 1 with error message.
"""

import sys
import subprocess
from pathlib import Path

import yaml


CLAUDE_SUBPROCESS_ARGS = ["--dangerously-skip-permissions"]

_PROJECT_ROOT = Path(__file__).absolute().parent
_BACKLOG_PATH = _PROJECT_ROOT / ".gaai" / "project" / "contexts" / "backlog" / "active.backlog.yaml"
_DAEMON_SCRIPT = _PROJECT_ROOT / ".gaai" / "core" / "scripts" / "daemon-start.sh"


def _read_refined_stories():
    if not _BACKLOG_PATH.exists():
        sys.stderr.write("ERROR: cannot read active.backlog.yaml: file not found\n")
        sys.exit(1)
    try:
        with open(_BACKLOG_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        sys.stderr.write("ERROR: cannot read active.backlog.yaml: {}\n".format(str(exc)))
        sys.exit(1)
    items = data.get("items", []) if data else []
    return [item for item in items if item.get("status") == "refined"]


def _build_story_input(story):
    artefact_rel = story.get("artefact", "")
    artefact_path = _PROJECT_ROOT / ".gaai" / "project" / "contexts" / artefact_rel.lstrip("contexts/")
    if artefact_path.exists():
        story_content = artefact_path.read_text(encoding="utf-8")
    else:
        story_content = "Story: {} - {}".format(story.get("id", "unknown"), story.get("title", ""))
    return (
        "You are a GAAI Delivery Agent. Deliver the following story according to GAAI governance rules.\n\n"
        + story_content
    )


def _run_windows(args):
    stories = _read_refined_stories()
    if not stories:
        print("No refined stories found in active backlog.")
        return 0

    for story in stories:
        story_id = story.get("id", "unknown")
        print("Delivering story: {}".format(story_id))
        story_input = _build_story_input(story)
        cmd = ["claude", "-p"] + CLAUDE_SUBPROCESS_ARGS
        proc = subprocess.run(
            cmd,
            input=story_input,
            text=True,
            encoding="utf-8",
        )
        if proc.returncode != 0:
            sys.stderr.write("ERROR: subprocess failed for story {}\n".format(story_id))
            return 1

    return 0


def _run_unix(args):
    if not _DAEMON_SCRIPT.exists():
        sys.stderr.write("ERROR: daemon-start.sh not found at {}\n".format(str(_DAEMON_SCRIPT)))
        sys.exit(1)
    proc = subprocess.run(["bash", str(_DAEMON_SCRIPT)] + args)
    return proc.returncode


def main():
    args = sys.argv[1:]

    if sys.platform == "win32":
        sys.exit(_run_windows(args))
    elif sys.platform in ("linux", "darwin") or sys.platform.startswith("linux"):
        sys.exit(_run_unix(args))
    else:
        sys.stderr.write("ERROR: unsupported platform: {}\n".format(sys.platform))
        sys.exit(1)


if __name__ == "__main__":
    main()
