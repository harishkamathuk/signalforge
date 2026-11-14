"""SF-283 post-merge CLI contract: malformed evidence always fails closed.

Synthetic unit tests only. No historical, private, or protected inputs.
"""

from __future__ import annotations

import json
from decimal import DivisionByZero, InvalidOperation, Overflow

import pytest

from scripts import scenario_report_saved as cli


def _arguments(tmp_path, *, with_other=False):
    paths = []
    for name in ("result", "source", "strict"):
        target = tmp_path / f"{name}.json"
        target.write_bytes(b"synthetic-only")
        paths.append(target)

    args = [
        "--result", str(paths[0]),
        "--source-companion", str(paths[1]),
        "--strict-companion", str(paths[2]),
    ]
    if with_other:
        for name in ("other-result", "other-source", "other-strict"):
            target = tmp_path / f"{name}.json"
            target.write_bytes(b"synthetic-only")
            args.extend([
                "--other-result" if name == "other-result" else
                "--other-source-companion" if name == "other-source" else
                "--other-strict-companion",
                str(target),
            ])
    return args


@pytest.mark.parametrize("exception", [
    Overflow("synthetic Decimal overflow"),
    InvalidOperation("synthetic invalid Decimal"),
    DivisionByZero("synthetic Decimal divide by zero"),
    ValueError("synthetic malformed saved value"),
    AttributeError("synthetic missing saved field"),
])
def test_sf283_cli_withholds_arithmetic_and_malformed_report_failures(
    tmp_path, monkeypatch, capsys, exception,
):
    """No uncaught traceback or point metrics when saved report arithmetic fails."""
    def broken_report(*_args):
        raise exception

    monkeypatch.setattr(cli, "report_from_saved_bytes", broken_report)
    exit_code = cli.main(_arguments(tmp_path))
    captured = capsys.readouterr()

    assert exit_code == 2
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "status": "WITHHELD",
        "reason": "SAVED_EVIDENCE_INVALID_OR_UNAVAILABLE",
    }
    assert "synthetic" not in captured.out
    assert "metrics" not in captured.out


def test_sf283_cli_withholds_profile_comparison_arithmetic_failure(
    tmp_path, monkeypatch, capsys,
):
    """A second saved profile must not bypass the same sanitized failure boundary."""
    def qualified_report(*_args):
        return {"status": "COMPLETE_PERSISTED_REPORTABILITY",
                "profile_id": "REFERENCE_RAW"}

    def broken_comparison(*_args):
        raise Overflow("synthetic cross-profile arithmetic overflow")

    monkeypatch.setattr(cli, "report_from_saved_bytes", qualified_report)
    monkeypatch.setattr(cli, "compare_profile_reports", broken_comparison)

    exit_code = cli.main(_arguments(tmp_path, with_other=True))
    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "status": "WITHHELD",
        "reason": "SAVED_EVIDENCE_INVALID_OR_UNAVAILABLE",
    }
