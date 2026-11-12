# Scenario Research Execution API

Research-only hypothetical execution semantics. This module is not accessible from broker, PAPER/live or strict backtest dispatch.

::: signalforge.research.scenario_execution

## Released Stage 6 evidence checks

The [operator workflow](../engineering/stage6-released-validation.md) validates
already released artifacts without running research. The accepted bounded persisted-v1 scope
permits artifact-consistency PASS while reporting supported event-time counts
separately from unavailable mandatory cohort metrics. Artifact PASS does not
establish report completeness or permission to publish unsupported point metrics.

::: signalforge.research.stage6_validation
