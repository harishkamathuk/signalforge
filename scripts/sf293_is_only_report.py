"""SF-293 Slice 3: synthetic TEST_ONLY IS-only economic reporting demo.

No historical/protected input, real BTC costs, durable reports, OOS or Gate D.
Only existing private 0700/0600 fixture sets are accepted.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from signalforge.research._is_only_release import _safe_run  # noqa: E402

CONTRACT = "sf293-slice3-synthetic-is-only-v1"


class _Parser(argparse.ArgumentParser):
    """All parser failures are fixed-class, never option/error echo."""

    def error(self, message: str) -> None:
        raise ValueError("INVALID_REQUEST")


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(description=__doc__, add_help=False)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--set", dest="set_name", required=True)
    parser.add_argument("--recipient", required=True)
    try:
        args = parser.parse_args(argv)
        result = _safe_run(args.root, args.set_name, args.recipient)
    except Exception:
        result = {
            "contract": CONTRACT, "status": "RELEASE_BLOCKED", "oos": "SEALED",
        }
    # Output is already a closed success allowlist or one generic failure.
    # Never stream from internal validators, flush partial metrics or log.
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return {"IS_ONLY_QUALIFIED": 0, "WITHHELD": 2}.get(result["status"], 1)


if __name__ == "__main__":
    sys.exit(main())
