from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
PINNED_ACTION_PATTERN = re.compile(r"uses:\s+[^\s@]+@(?P<revision>[0-9a-f]{40})")


def test_all_github_actions_are_pinned_to_commit_revisions() -> None:
    workflow_texts = [
        path.read_text(encoding="utf-8") for path in sorted(WORKFLOWS.glob("*.yml"))
    ]
    uses_lines = [
        line.strip()
        for workflow_text in workflow_texts
        for line in workflow_text.splitlines()
        if "uses:" in line
    ]

    assert uses_lines
    assert all(PINNED_ACTION_PATTERN.search(line) for line in uses_lines)


def test_release_workflow_has_one_explicit_write_boundary() -> None:
    release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")

    assert "  workflow_dispatch:" in release
    assert "  push:" not in release
    assert release.count("contents: write") == 1
    assert "environment:\n      name: release" in release
    assert "DISTRIBUTION_REVIEWED" in release
    assert 'test "$DISTRIBUTION_REVIEWED" = "true"' in release


def test_release_rechecks_the_exact_green_main_revision_before_writing() -> None:
    release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")

    assert release.count('test "$main_sha" = "$GITHUB_SHA"') == 2
    assert release.count('.head_sha == \\"$GITHUB_SHA\\"') == 2
    assert release.count('.head_repository.full_name == \\"$GITHUB_REPOSITORY\\"') == 2
    assert release.count('.conclusion == \\"success\\"') == 2
    assert release.count('grep -q "HTTP 404"') == 2
    assert "--verify-tag" in release
    assert 'test "$tag_sha" = "$GITHUB_SHA"' in release


def test_test_workflow_avoids_tag_rebuild_and_uses_exact_firmware_pin() -> None:
    tests = (WORKFLOWS / "tests.yml").read_text(encoding="utf-8")
    firmware_requirements = (ROOT / "requirements-firmware.txt").read_text(
        encoding="utf-8"
    )

    assert "  push:\n    branches:" in tests
    assert "tags:" not in tests
    assert "needs: preflight" not in tests
    assert "Restore ESPHome toolchain cache" in tests
    assert "Restore incremental firmware build cache" in tests
    assert "esphome/.esphome/build/guestyterminal-display-1" in tests
    assert "            ${{ runner.os }}-esphome-\n" in tests
    assert "~/.platformio" not in tests
    assert "requirements-test-runner.txt" in tests
    assert "requirements-firmware.txt" in tests
    assert re.search(r"(?m)^esphome==\d+\.\d+\.\d+$", firmware_requirements)
