# SF-260 — 90-measured-day audited historical variant v1 (preparation only)

**Owner authority:** [90-day approved window](https://github.com/harishkamathuk/signalforge/issues/253#issuecomment-6864968129); [separate audited source-slice contract](https://github.com/harishkamathuk/signalforge/issues/253#issuecomment-6865128606).

**Current status: PROTECTED EXECUTION NO-GO.** This implementation must not be used to read historical scenario economics or release OOS until a later, separate 00.01 Gate D decision, independently accepted 04 method review and custody packet. The source-only code calculates inputs, not signals or outcomes. This is not a replacement for the original full-year SF-094/SF-260 study, IDs, manifests or source proof.

## Fixed boundaries and repeated sample

| Boundary | Half-open UTC | Count |
|---|---|---|
| Protected source | 2025-10-30 00:00 to 2026-01-29 00:00 | 131,040 one-minute / 26,208 five-minute bars; **91 days** |
| Warm-up | 2025-10-30 to 2025-10-31 | 1,440 minutes / 288 five-minute bars |
| IS | 2025-10-31 to 2025-12-30 | 86,400 minutes / 17,280 decisions |
| OOS | 2025-12-30 to 2026-01-29 | 43,200 minutes / 8,640 decisions |
| Measured | 2025-10-31 to 2026-01-29 | 129,600 minutes / 25,920 decisions |

The three-month fictional capacity probe was **90 source days** with 29 OOS days, not the **91-source-day** audited study. Its operator PASS does not establish this 91-day source-audit-to-worker memory ceiling. The proposed OOS was within previously inspected original full-year IS: label `REPEATED_SAMPLE`, not pristine OOS.

## Source proof and threat model

`AuditedSourceSliceV1` is **not** a `RawDiagnosticSource` subclass. The existing full-year constructor proof and original manifests are unchanged. Its factory accepts only the authenticated full-year `RawDiagnosticSource`, checks frozen original report and full-year dataset content identity, selects the exact first 131,040 chronological UTC one-minute records and constructs a distinct 91-day dataset. Its versioned SHA identity binds parent report, original dataset hash, canonical child manifest/hash, full ordered 1m semantic digest and independently aggregated 5m-close digest, UTC boundaries, method status and evidence tier. Parent bar references are released before any subsequent runner call.

A module-private factory seal prevents accidental or ordinary constructor-side source identity relabelling; it is **not** a security boundary against a hostile interpreter modifying private module attributes or introspecting object internals. Real integrity authority is the frozen parent evidence audit, independent source-only recomputation, canonical preregistration hashes and externally enforced custody/access controls. Do not pass untrusted Python code into the operator process.

### Memory and custody preconditions

The audited full-year parent is necessarily materialised by the existing frozen SF-095 source loader, which independently checks original raw/semantic chunks and report. The operator's memory consumption during that source audit can differ from the later 91-day scenario process. Both source-only steps must use independently enforced **3 GiB RSS cgroup / 4 GiB address space / swap zero / pids max 64 / 512 MiB output / 1,200 s wall**, with 0.75 GiB available-memory reserve and separate private output disk reserve. The source-only code itself checks effective limits **before reading the archive** and records high-water RSS; an external cgroup, not Python polling alone, is required. If full-year materialisation cannot fit, **STOP and escalate**; never increase ceilings or weaken audit fidelity.

The preparer and verifier have no runner calls, no performance metric output and no historical alternative-date selection. They demand a clean repository checkout and use real source bytes. Provide privately owned, unlinked `0700` destination directory:
`~/signalforge-private/stage6/90d-v1/source-prereg`. First preparation is exclusive/write-once. Keep generated canonical JSON `0600`; securely quarantine any partial outputs after an interrupted attempt rather than overwriting or treating them as success.

The source-only preparer is `scripts/stage6_90d_source_preflight.py`, invoked with `--source-only-attestation`; the **separate** checker is `scripts/stage6_90d_independent_verifier.py`, invoked with `--independent-source-only-verify --write-private-receipt`. Run *each* under the externally confirmed guarded process envelope above, on the reviewed/merged `develop` checkout, not from this IMP feature branch or before 04 review. Use the 04-approved WSL operator wrapper and retain the raw terminal resource status without publishing protected bytes. They are not Gate D authorisation or historical scenario execution. Independent verification recomputes the parent evidence audit, UTC continuity and ordered child SHA and 5m closes without invoking the child factory or strategy runner, then verifies profile manifests/run IDs and private hashes. Independent-algorithmic verification is not a claim of independent-human source-byte review.

## Distinct guarded research launcher — not authorised to run yet

`scripts/stage6_90d_guarded_launcher.py` is separate from the legacy launcher. Its **default** `--probe` checks the bounded systemd-run scope without source access; `--run --profile REFERENCE_RAW|ADVERSE_RAW --attempt 1|2` is **strictly prohibited until a later distinct owner Gate D_90D_ACCEPT**.

Before the protected worker can start, it demands:
- Exact clean `develop` checkout matching canonical prereg execution revision and unchanged approved BTC strategy/RAW contracts
- Real-source-derived canonical two-profile manifests, their read-back SHA, domain-separated run IDs and independently verified private source-only receipt
- A **new** `gate-d-90d-record.json` binding the later owner decision URL, exact variant, revision, input prereg ID and audited slice derivation ID; original full-year Gate D/prereg IDs never apply
- A separately verified encrypted source-backup receipt bound by SHA to the Gate D record (not a fabricated hash), existing restricted private output root, adequate available RAM/disk and no reuse/collision
- Effective memory/swap/pid and rlimit guards; one profile/attempt at a time under a named systemd scope, persistent crash marker and explicit verification that the scope has stopped

The worker independently rechecks the audited parent, derives the exact source slice, measures the source-audit-to-child peak RSS, recomputes the input manifest and its exact prereg hash **before** calling `run_verified`. Complete results are written only to exclusive private `0600` files, with hashes, sealed OOS and no performance output to stdout. A failure remains quarantined; a successful private file remains **unreleased**. Any later OOS release requires a *separate* explicitly verified encrypted result backup, research-interpretation custody checkpoint and owner authorisation; the launcher never unseals OOS.

## Evidence and governance gates

- `SF260_90D_AUDITED_V1` is additive. The legacy `SF094_FULL_YEAR_V1` is the unchanged default, with unchanged manifest/run ID preimages and 69,984/34,848 completion grid.
- Variant-specific runner method validity requires exact 17,280/8,640 full-grid decisions, zero unsupported, no failure, measured-end alignment and deterministic independent replay; synthetic/unverified source cannot be promoted.
- ADR-011 strict eligible/assessed/ambiguous/unassessed/indeterminate source coverage and withheld-economics requirements remain unchanged. Source metadata stays `UNQUALIFIED_HISTORICAL_METADATA`; result `execution_valid=false`, `SCENARIO_CONDITIONED`. This is not execution-quality P&L.
- **Before FIN:** adversarial review, exact PR-head CI, **04 independently records ACCEPT/MODIFY/REJECT** of research methodology and source-only verifier, and any required COR is resolved.
- **After eligible FIN:** 04 can arrange tightly guarded source-only attestation, then return fresh B1–B5 and custody/release evidence to 00.01. A distinct later 00.01 protected-run GO is mandatory. No historical scenario runner, output inspection or OOS release under IMP.
