# Historical Source Qualification

SF-079 Phase A introduces a typed, deterministic qualification contract for external historical
data sources.

::: signalforge.research.source_qualification


## Auditability rules

Gate A evidence is semantic identity material. A qualification record includes:

- immutable implementation source/revision identity;
- evidence reference plus immutable/versioned snapshot identity;
- observation timestamp for time-sensitive evidence;
- one status per mandatory criterion.

Partial evidence remains `PENDING`; there is no selectable partial state.

The current repository state is executable through
`signalforge.research.sf079_phase_a_report.CURRENT_SF079_PHASE_A_REPORT`.
