"""Read-only future-only SF-283 persisted-evidence research reporting CLI.

Never runs a strategy, reads bars, selects historical artifacts or writes custody.
Produces complete scenario-conditioned research report or a sanitized failure.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from signalforge.research.scenario_reportability import (
    ReportabilityError,
    compare_profile_reports,
    report_from_saved_bytes,
)


def main(argv: list[str] | None = None) -> int:
    """Validate saved v2 and its exact hash-bound companions, then report to stdout."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--source-companion", type=Path, required=True)
    parser.add_argument("--strict-companion", type=Path, required=True)
    parser.add_argument("--other-result", type=Path)
    parser.add_argument("--other-source-companion", type=Path)
    parser.add_argument("--other-strict-companion", type=Path)
    args = parser.parse_args(argv)
    try:
        paths = (args.result, args.source_companion, args.strict_companion)
        if any(not p.is_file() or p.is_symlink() for p in paths):
            raise ReportabilityError("MISSING_OR_UNSAFE_SAVED_EVIDENCE")
        # The reporting path uses only saved bytes; no source bars or runtime objects.
        report = report_from_saved_bytes(
            args.result.read_bytes(),
            args.source_companion.read_bytes(),
            args.strict_companion.read_bytes(),
        )
        other_paths = (
            args.other_result,
            args.other_source_companion,
            args.other_strict_companion,
        )
        if any(p is not None for p in other_paths):
            if any(p is None or not p.is_file() or p.is_symlink() for p in other_paths):
                raise ReportabilityError("INCOMPLETE_OTHER_PROFILE_EVIDENCE")
            other = report_from_saved_bytes(
                args.other_result.read_bytes(),
                args.other_source_companion.read_bytes(),
                args.other_strict_companion.read_bytes(),
            )
            reference = report if report["profile_id"] == "REFERENCE_RAW" else other
            adverse = other if report["profile_id"] == "REFERENCE_RAW" else report
            report = compare_profile_reports(reference, adverse)
    except (ReportabilityError, OSError, TypeError, KeyError, OverflowError, RecursionError):
        # Never echo exception messages, source paths or partially computed metrics.
        print(json.dumps({"status": "WITHHELD", "reason": "SAVED_EVIDENCE_INVALID_OR_UNAVAILABLE"},
                         sort_keys=True))
        return 2
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
