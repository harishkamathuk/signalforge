"""Read-only SF-278 checks for the four approved Stage 6 released results.

Never runs a strategy, opens source data, copies results or mutates custody.
All output is allowlisted; exception text can contain private data and is omitted.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from decimal import Context, InvalidOperation, localcontext
from pathlib import Path

import stage6_result_custody as custody

from signalforge.research import stage6_validation

REPO = Path(__file__).resolve().parents[1]
OOS_URL = "https://github.com/harishkamathuk/signalforge/issues/253#issuecomment-6828627582"
# Genuine #253 release decision and #260 released-byte/operator receipt record.
# These are public metadata, never private evidence or a new preregistration.
APPROVED = {
    "REFERENCE_RAW": (
        "29ec9839b67b9e9383c732d3711805195584506c0cc6450e2ce83b46345080cf",
        (
            "9c640b784a47263633405d86ca29cec56bccf720d5eb3326f4de5573282b5fa9",
            "34865b3d5302a6fad73fb04a6dfc6ac8dc3c8c09835c4ecf6510e67c9bc63efe",
        ),
        (
            "0672039bf74ca59080fd84e21e2334c4bc8bb4282e1fadc9850ba31936b53820",
            "66e4173c31e1520dd2847125de8df854b4cc10930451cde13af854f26e81a047",
        ),
    ),
    "ADVERSE_RAW": (
        "921f3521fcff0bed5e248e1a13de7520ce37d145a9992bd6b2132080ced7e5a5",
        (
            "7ada904ca5c7c6c2cef4ffec5ea1055c96c86216c6d0e7f9f387c1b937aeaaf1",
            "396fd5bf6fdfd955ed24f48c61b2b1a25a7403ce1fdd447ea409f080fb960aed",
        ),
        (
            "0e5d1c84aa6a0292a1bd4629a61817d12825534fe29e1da71a7d057895e93cf3",
            "331d3035996699d7fb7b735b820136ccfc5445b9b6aa0002247e3e49f5be22fc",
        ),
    ),
}


def _revision() -> dict[str, object]:
    def git(*args: str) -> str:
        return subprocess.check_output(
            ["git", "-C", str(REPO), *args],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()

    return {
        "git_revision": git("rev-parse", "HEAD"),
        "working_tree_dirty": bool(git("status", "--porcelain", "--untracked-files=normal")),
        "code_sha256": {
            "cli": custody._digest(Path(__file__).read_bytes()),
            "rules": custody._digest(Path(stage6_validation.__file__).read_bytes()),
            "canonical_custody": custody._digest(Path(custody.__file__).read_bytes()),
        },
    }


def _validate_released(
    *, root: Path, oos_records: list[Path], synthetic: bool = False
) -> dict[str, object]:
    """Authenticate all four released copies and return sanitized rule verdicts.

    Args:
        root: Existing 0700 custody root; reads released, receipts and IS-QA only.
        oos_records: Exactly four existing 0600 operator approval records, in
            REFERENCE attempts 1,2 then ADVERSE attempts 1,2 order.
        synthetic: Explicit test-only mode rejecting protected source identities.

    Returns:
        Deterministic, non-economic report with every attempt represented.
        Local approval records attest authority; they cannot authenticate the
        GitHub author, past procedure or protected source bytes.

    Raises:
        CustodyBlocked: Unsafe root or malformed selection, before result access.
    """
    root = custody._private_directory(root)
    custody._check(len(oos_records) == 4, "four OOS records required")
    expected = {
        f"{profile.lower()}-attempt-{attempt}.json"
        for profile in custody.RUNS
        for attempt in (1, 2)
    }
    released = custody._ancestors_safe(root / "released")
    custody._check(
        {p.name for p in released.iterdir()} == expected,
        "released selection differs from approved four attempts",
    )
    reports: list[dict[str, object]] = []
    hashes: dict[str, list[str]] = {profile: [] for profile in custody.RUNS}
    index = 0
    for profile in custody.RUNS:
        for attempt in (1, 2):
            row: dict[str, object] = {"profile": profile, "attempt": attempt}
            approval = oos_records[index]
            index += 1
            try:
                stem = f"{profile.lower()}-attempt-{attempt}.json"
                receipt_raw = custody._private_file(root / "receipts" / stem)
                receipt = custody._mapping(json.loads(receipt_raw), "seal receipt")
                qa_raw = custody._private_file(root / "is-qa" / stem)
                qa = custody._mapping(json.loads(qa_raw), "IS QA")
                # Verify release authority before parsing full-window contents.
                approved_sha, qa_shas, record_shas = APPROVED[profile]
                decision = "SYNTHETIC_OOS_RELEASE_TEST" if synthetic else "OOS_RELEASE_ACCEPT"
                extras = {
                    "seal_sha256": receipt.get("result_sha256"),
                    "is_qa_sha256": custody._digest(qa_raw),
                }
                if not synthetic:
                    extras["preregistration_id"] = custody.PREREG
                authority = custody._check_approval(approval, decision=decision, extra=extras)
                approval_sha = custody._digest(custody._private_file(approval))
                if not synthetic:
                    custody._check(
                        authority["record_url"] == OOS_URL
                        and receipt.get("result_sha256") == approved_sha
                        and custody._digest(qa_raw) == qa_shas[attempt - 1]
                        and approval_sha == record_shas[attempt - 1],
                        "unapproved release binding",
                    )
                raw, manifest, result = custody._parse_result(released / stem)
                diagnostic = custody._validate_source(manifest, synthetic=synthetic)
                sha = custody._digest(raw)
                result_id = custody._hash_config({"domain": "scenario-result-v1", "result": result})
                run_id = result["scenario_run_id"]
                manifest_sha = custody._digest(
                    custody._canonical(
                        {
                            "input_mapping": manifest,
                            "scenario_run_id": run_id,
                        }
                    )
                )
                custody._check(
                    receipt.get("schema") == "stage6-seal-receipt-v1"
                    and receipt.get("profile") == profile
                    and type(receipt.get("attempt")) is int
                    and receipt.get("attempt") == attempt
                    and receipt.get("source_kind")
                    == ("SYNTHETIC_TEST_ONLY" if synthetic else "PROTECTED_GATE_D_APPROVED")
                    and receipt.get("byte_length") == len(raw)
                    and receipt.get("result_sha256") == sha
                    and receipt.get("scenario_run_id") == run_id
                    and receipt.get("scenario_result_id") == result_id
                    and custody._mapping(manifest.get("fills"), "fills").get("profile_id")
                    == profile,
                    "released receipt identity mismatch",
                )
                custody._check(
                    qa.get("schema") == "stage6-is-qa-v1"
                    and qa.get("profile") == profile
                    and qa.get("attempt") == attempt
                    and qa.get("scenario_run_id") == run_id
                    and qa.get("source_kind") == receipt["source_kind"]
                    and qa.get("sealed_result_sha256") == sha
                    and qa.get("is_expected_5m") == 69984
                    and qa.get("is_observed_5m") == result["is_observed"]
                    and qa.get("is_grid_complete") is (result["is_observed"] == 69984),
                    "IS checkpoint mismatch",
                )
                if not synthetic:
                    custody._check(
                        sha == approved_sha
                        and run_id == custody.RUNS[profile][0]
                        and manifest_sha == custody.RUNS[profile][1]
                        and receipt.get("preregistration_id") == custody.PREREG
                        and type(receipt.get("gate_d_record_sha256")) is str
                        and len(receipt["gate_d_record_sha256"]) == 64,
                        "frozen identities mismatch",
                    )
                hashes[profile].append(sha)
                row.update(
                    {
                        "identity_check": "PASS",
                        "source_diagnostic_id": diagnostic,
                        "scenario_run_id": run_id,
                        "scenario_result_id": result_id,
                        "manifest_sha256": manifest_sha,
                        "result_sha256": sha,
                        "receipt_sha256": custody._digest(receipt_raw),
                        "is_qa_sha256": custody._digest(qa_raw),
                        "oos_record_sha256": approval_sha,
                        **stage6_validation.validate_result(result),
                    }
                )
                # Do not retain four large parsed canonical histories concurrently.
                del raw, manifest, result
            except (
                ValueError,
                TypeError,
                KeyError,
                OSError,
                InvalidOperation,
                OverflowError,
                RecursionError,
                subprocess.SubprocessError,
            ):
                row.update(
                    {
                        "identity_check": "INVALID",
                        "status": "INVALID",
                        "point_metrics_allowed": False,
                    }
                )
            reports.append(row)
    repeat = {
        profile: "PASS" if len(values) == 2 and values[0] == values[1] else "INVALID"
        for profile, values in hashes.items()
    }
    distinct = (
        all(len(v) == 2 for v in hashes.values())
        and hashes["REFERENCE_RAW"][0] != hashes["ADVERSE_RAW"][0]
    )
    invalid = (
        any(row["status"] == "INVALID" for row in reports)
        or "INVALID" in repeat.values()
        or not distinct
    )
    return {
        "schema": "stage6-released-validation-v1",
        "validator": _revision(),
        "status": "INVALID" if invalid else "INCONCLUSIVE",
        "source_kind": "SYNTHETIC_TEST_ONLY" if synthetic else "RELEASED_STAGE6",
        "preregistration_id": None if synthetic else custody.PREREG,
        "certainty": "SCENARIO_CONDITIONED",
        "execution_valid": False,
        "source_qualification": "UNQUALIFIED_HISTORICAL_METADATA",
        "gate_e_approved": False,
        "point_metrics_allowed": False,
        "attempts": reports,
        "within_profile_byte_repeatability": repeat,
        "distinct_profile_results": distinct,
        "authority_verification": "OPERATOR_ATTESTED_NOT_GITHUB_AUTHENTICATED",
    }


def validate_released(
    *, root: Path, oos_records: list[Path], synthetic: bool = False
) -> dict[str, object]:
    """Validate released evidence under the frozen serializer's decimal context.

    Args:
        root: Existing private custody root outside Git and source archives.
        oos_records: REFERENCE 1,2 then ADVERSE 1,2 private approval paths.
        synthetic: Explicit synthetic-only test mode; refuses protected identities.

    Returns:
        Deterministic allowlisted report, with no economics or private paths.

    Raises:
        CustodyBlocked: Unsafe directory or incomplete/extra released selection.
    """
    # Canonical decimal normalization in the existing custody parser uses the
    # context precision. Freeze its established default rather than inheriting a
    # caller's ambient decimal context and changing identities across invocations.
    with localcontext(Context(prec=28)):
        return _validate_released(root=root, oos_records=oos_records, synthetic=synthetic)


def main(argv: list[str] | None = None) -> int:
    """Print deterministic sanitized JSON or exclusively create a private report.

    Exit codes: 0 independent pass (not attainable from v1 evidence alone),
    2 inconclusive, 1 invalid/blocked. Summary requests remain withheld when
    the full independent gate is not satisfied. No point statistics are leaked.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument(
        "--oos-records",
        type=Path,
        nargs=4,
        required=True,
        metavar="RECORD",
        help="REFERENCE 1,2 then ADVERSE 1,2",
    )
    parser.add_argument("--synthetic-test-only", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--research-summary",
        action="store_true",
        help="separate gated summary; v1 missing evidence withholds metrics",
    )
    args = parser.parse_args(argv)
    try:
        # Compare canonical directories on both sides. Lexical '..' in the
        # operator's root spelling must not let a report enter custody.
        root = custody._private_directory(args.root)
        report = validate_released(
            root=root, oos_records=args.oos_records, synthetic=args.synthetic_test_only
        )
        if args.research_summary:
            report = {
                "schema": "stage6-research-summary-v1",
                "status": "WITHHELD",
                "reason": "INDEPENDENT_VALIDATION_PASS_REQUIRED",
                "validation": report,
            }
        raw = (json.dumps(report, sort_keys=True, indent=2) + "\n").encode()
        if args.output is None:
            sys.stdout.buffer.write(raw)
        else:
            parent = custody._private_directory(args.output.parent)
            custody._check(
                not parent.is_relative_to(root),
                "report must be outside existing custody evidence",
            )
            custody._write_once(parent / args.output.name, raw)
        return (
            1
            if (
                report.get("status") == "INVALID"
                or report.get("status") == "WITHHELD"
                and report["validation"]["status"] == "INVALID"
            )
            else 2
        )
    except (
        ValueError,
        TypeError,
        KeyError,
        OSError,
        InvalidOperation,
        OverflowError,
        RecursionError,
        subprocess.SubprocessError,
    ):
        print(
            '{"schema":"stage6-released-validation-v1","status":"INVALID",'
            '"rule":"CUSTODY_OR_SELECTION_BLOCKED","point_metrics_allowed":false}'
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
