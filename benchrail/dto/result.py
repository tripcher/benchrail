from collections.abc import Callable

from pydantic import BaseModel, ConfigDict


class AgentStats(BaseModel):
    duration_ms: int | None = None
    turns: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_creation_tokens: int | None = None
    reasoning_tokens: int | None = None
    cost_usd: float | None = None
    cost_credits: float | None = None


class CheckResult(BaseModel):
    name: str
    status: str  # pass | fail | error
    exit_code: int
    duration_seconds: float


class InstanceResult(BaseModel):
    schema_version: str = "1.0"
    instance_id: str
    agent: str
    agent_session_id: str = ""
    repo: str
    base_commit: str
    status: str  # pass | fail
    duration_seconds: float
    agent_stats: AgentStats
    checks: list[CheckResult]


class RunResult(BaseModel):
    schema_version: str = "1.0"
    run_id: str
    mode: str
    dataset_path: str
    status: str  # completed | failed | aborted
    passed: int
    failed: int
    total: int
    duration_seconds: float
    total_input_tokens: int | None = None
    total_output_tokens: int | None = None
    total_cache_read_tokens: int | None = None
    total_cache_creation_tokens: int | None = None
    total_reasoning_tokens: int | None = None
    total_cost_usd: float | None = None
    total_cost_credits: float | None = None
    total_agent_duration_ms: int | None = None
    total_turns: int | None = None

    model_config = ConfigDict(extra="allow")

    @classmethod
    def aggregate(
        cls,
        run_id: str,
        mode: str,
        dataset_path: str,
        status: str,
        duration_seconds: float,
        instance_results: list[InstanceResult],
    ) -> "RunResult":
        passed = sum(1 for r in instance_results if r.status == "pass")
        failed = len(instance_results) - passed
        total = len(instance_results)

        def _sum(
            getter: Callable[[InstanceResult], int | None],
            results: list[InstanceResult],
        ) -> int | None:
            vals = [getter(r) for r in results]
            if all(v is None for v in vals):
                return None
            return sum(v or 0 for v in vals)

        def _sum_float(
            getter: Callable[[InstanceResult], float | None],
            results: list[InstanceResult],
        ) -> float | None:
            vals = [getter(r) for r in results]
            if any(v is None for v in vals):
                return None
            return float(sum(v for v in vals if v is not None))

        total_input = _sum(lambda r: r.agent_stats.input_tokens, instance_results)
        total_output = _sum(lambda r: r.agent_stats.output_tokens, instance_results)
        total_cache_read = _sum(lambda r: r.agent_stats.cache_read_tokens, instance_results)
        total_cache_creation = _sum(lambda r: r.agent_stats.cache_creation_tokens, instance_results)
        total_reasoning = _sum(lambda r: r.agent_stats.reasoning_tokens, instance_results)
        total_cost = _sum_float(lambda r: r.agent_stats.cost_usd, instance_results)
        total_cost_credits = _sum_float(lambda r: r.agent_stats.cost_credits, instance_results)
        total_agent_dur = _sum(lambda r: r.agent_stats.duration_ms, instance_results)
        total_turns = _sum(lambda r: r.agent_stats.turns, instance_results)

        # Collect per-check aggregates
        check_counts: dict[str, dict[str, int]] = {}
        for r in instance_results:
            for c in r.checks:
                if c.name not in check_counts:
                    check_counts[c.name] = {"passed": 0, "failed": 0}
                if c.status == "pass":
                    check_counts[c.name]["passed"] += 1
                else:
                    check_counts[c.name]["failed"] += 1

        extra: dict[str, int] = {}
        for name, counts in check_counts.items():
            safe = name.replace("-", "_").replace(" ", "_")
            extra[f"checks_{safe}_passed"] = counts["passed"]
            extra[f"checks_{safe}_failed"] = counts["failed"]
            extra[f"checks_{safe}_total"] = counts["passed"] + counts["failed"]

        run = cls(
            run_id=run_id,
            mode=mode,
            dataset_path=dataset_path,
            status=status,
            passed=passed,
            failed=failed,
            total=total,
            duration_seconds=round(duration_seconds, 1),
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            total_cache_read_tokens=total_cache_read,
            total_cache_creation_tokens=total_cache_creation,
            total_reasoning_tokens=total_reasoning,
            total_cost_usd=total_cost,
            total_cost_credits=total_cost_credits,
            total_agent_duration_ms=total_agent_dur,
            total_turns=total_turns,
            **extra,
        )
        return run
