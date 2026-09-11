"""Flexible Job-Shop Scheduling Problem toolkit.

The module deliberately keeps the solver and validator independent: a schedule
is produced as plain records, then checked from the instance definition.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from functools import lru_cache
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Operation:
    job: int
    index: int
    options: dict[int, int]


@dataclass(frozen=True)
class Instance:
    jobs: int
    machines: int
    operations: list[Operation]
    seed: int | None = None
    parameters: dict[str, Any] | None = None

    @property
    def operations_by_job(self) -> dict[int, list[Operation]]:
        result: dict[int, list[Operation]] = {job: [] for job in range(self.jobs)}
        for operation in self.operations:
            result[operation.job].append(operation)
        for operations in result.values():
            operations.sort(key=lambda item: item.index)
        return result


@dataclass(frozen=True)
class ScheduledOperation:
    job: int
    index: int
    machine: int
    start: int
    end: int


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    makespan: int | None
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def metrics(instance: Instance, schedule: list[ScheduledOperation]) -> dict[str, Any]:
    """Return reproducible diagnostics used in experiment tables."""
    result = validate(instance, schedule)
    if not result.valid:
        raise ValueError("metrics require a valid schedule")
    by_machine: dict[int, list[ScheduledOperation]] = {m: [] for m in range(instance.machines)}
    by_job = instance.operations_by_job
    for item in schedule:
        by_machine[item.machine].append(item)
    horizon = result.makespan or 0
    utilization = {
        machine: sum(item.end - item.start for item in items) / horizon if horizon else 0.0
        for machine, items in by_machine.items()
    }
    job_chain = max(
        sum(op.options[item.machine] for op, item in zip(by_job[job], sorted(
            [entry for entry in schedule if entry.job == job], key=lambda entry: entry.index)))
        for job in by_job
    )
    machine_sequences = {machine: sorted(items, key=lambda item: (item.start, item.end))
                         for machine, items in by_machine.items()}
    predecessors: dict[tuple[int, int], set[tuple[int, int]]] = {
        (item.job, item.index): set() for item in schedule
    }
    for items in by_job.values():
        ordered = sorted(items, key=lambda item: item.index)
        for previous, current in zip(ordered, ordered[1:]):
            predecessors[(current.job, current.index)].add((previous.job, previous.index))
    for items in machine_sequences.values():
        for previous, current in zip(items, items[1:]):
            predecessors[(current.job, current.index)].add((previous.job, previous.index))
    duration = {(item.job, item.index): item.end - item.start for item in schedule}
    longest: dict[tuple[int, int], int] = {}
    for item in sorted(schedule, key=lambda entry: (entry.start, entry.end)):
        key = (item.job, item.index)
        longest[key] = duration[key] + max(
            (longest[pred] for pred in predecessors[key]), default=0
        )
    critical_path = max(longest.values(), default=0)
    machine_work = max(
        sum(item.end - item.start for item in items) for items in by_machine.values()
    )
    assignment_lb = max(
        sum(min(op.options.values()) for op in operations) for operations in by_job.values()
    )
    lower_bound = max(job_chain, machine_work, assignment_lb)
    return {
        "makespan": result.makespan,
        "job_completion_times": {
            job: max(item.end for item in schedule if item.job == job)
            for job in by_job
        },
        "machine_utilization": utilization,
        "critical_path": critical_path,
        "job_chain_lower_bound": job_chain,
        "max_machine_workload": machine_work,
        "lower_bound": lower_bound,
        "lower_bound_gap": (result.makespan - lower_bound) / lower_bound if lower_bound else 0.0,
    }


def exact_optimum(instance: Instance, limit: int = 9) -> int:
    """Compute the optimum for tiny instances by exhaustive branch-and-bound."""
    if len(instance.operations) > limit:
        raise ValueError(f"exact benchmark supports at most {limit} operations")
    jobs = instance.operations_by_job
    operation_counts = tuple(len(jobs[job]) for job in range(instance.jobs))
    durations = {(op.job, op.index, machine): value
                 for op in instance.operations for machine, value in op.options.items()}

    @lru_cache(maxsize=None)
    def search(next_indices: tuple[int, ...], job_ends: tuple[int, ...],
               machine_ends: tuple[int, ...]) -> int:
        if next_indices == operation_counts:
            return max(job_ends, default=0)
        best = float("inf")
        for job, index in enumerate(next_indices):
            if index >= operation_counts[job]:
                continue
            operation = jobs[job][index]
            for machine in operation.options:
                start = max(job_ends[job], machine_ends[machine])
                end = start + durations[(job, index, machine)]
                next_state = list(next_indices)
                next_state[job] += 1
                new_jobs = list(job_ends)
                new_machines = list(machine_ends)
                new_jobs[job], new_machines[machine] = end, end
                if max(end, *new_jobs) >= best:
                    continue
                best = min(best, search(tuple(next_state), tuple(new_jobs), tuple(new_machines)))
        return best

    return int(search((0,) * instance.jobs, (0,) * instance.jobs, (0,) * instance.machines))


def _rebuild(instance: Instance, assignments: dict[tuple[int, int], int],
             priority: dict[tuple[int, int], int]) -> list[ScheduledOperation]:
    """List-schedule a candidate assignment in a deterministic priority order."""
    operations = {(op.job, op.index): op for op in instance.operations}
    next_index = {job: 0 for job in range(instance.jobs)}
    job_end = {job: 0 for job in range(instance.jobs)}
    machine_end = {machine: 0 for machine in range(instance.machines)}
    result: list[ScheduledOperation] = []
    unscheduled = set(operations)
    while len(result) < len(operations):
        ready = [
            op for key, op in operations.items()
            if key in unscheduled
            and next_index[op.job] == op.index
        ]
        if not ready:
            raise ValueError("candidate priority contains an invalid precedence order")
        operation = min(ready, key=lambda op: priority[(op.job, op.index)])
        key = (operation.job, operation.index)
        machine = assignments[key]
        start = max(job_end[operation.job], machine_end[machine])
        end = start + operation.options[machine]
        result.append(ScheduledOperation(operation.job, operation.index, machine, start, end))
        unscheduled.remove(key)
        next_index[operation.job] += 1
        job_end[operation.job] = end
        machine_end[machine] = end
    return result


def _critical_pairs(schedule: list[ScheduledOperation]) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    """Return adjacent same-machine pairs on the schedule's longest path."""
    by_machine: dict[int, list[ScheduledOperation]] = {}
    for item in schedule:
        by_machine.setdefault(item.machine, []).append(item)
    pairs: list[tuple[tuple[int, int], tuple[int, int]]] = []
    for items in by_machine.values():
        items.sort(key=lambda item: item.start)
        pairs.extend(
            ((left.job, left.index), (right.job, right.index))
            for left, right in zip(items, items[1:])
        )
    return pairs


def generate_instance(
    jobs: int,
    machines: int,
    operations_per_job: int | tuple[int, int],
    flexibility: float = 0.5,
    processing_time_min: int = 1,
    processing_time_max: int = 20,
    processing_time_variance: float = 0.0,
    bottleneck_probability: float = 0.0,
    machine_advantage: float = 0.0,
    seed: int | None = None,
    instance_class: str = "average",
) -> Instance:
    """Generate a reproducible, always-solvable FJSP instance."""
    if jobs < 1 or machines < 1:
        raise ValueError("jobs, machines, and operations_per_job must be positive")
    if isinstance(operations_per_job, tuple):
        min_operations, max_operations = operations_per_job
    else:
        min_operations = max_operations = operations_per_job
    if min_operations < 1 or min_operations > max_operations:
        raise ValueError("operations_per_job must be a positive integer or (min, max)")
    if not 0 <= flexibility <= 1 or not 0 <= bottleneck_probability <= 1:
        raise ValueError("flexibility and bottleneck_probability must be in [0, 1]")
    if processing_time_variance < 0 or machine_advantage < 0:
        raise ValueError("processing_time_variance and machine_advantage must be non-negative")
    if processing_time_min < 1 or processing_time_min > processing_time_max:
        raise ValueError("processing time bounds are invalid")

    rng = random.Random(seed)
    operations: list[Operation] = []
    bottleneck = rng.randrange(machines)
    class_settings = {
        "low_flexibility": {"flexibility": .05},
        "high_flexibility": {"flexibility": .95},
        "bottleneck": {"bottleneck_probability": .85},
        "high_variance": {"processing_time_variance": 1.0, "processing_time_max": 100},
        "machine_advantage": {"machine_advantage": .8},
        "extreme": {"flexibility": .95, "processing_time_variance": 1.5,
                    "processing_time_max": 10000, "bottleneck_probability": .8},
        "balanced": {"bottleneck_probability": 0.0},
        "average": {},
        "small": {},
        "large": {},
    }
    if instance_class not in class_settings:
        raise ValueError(f"unknown instance class: {instance_class}")
    settings = class_settings[instance_class]
    flexibility = settings.get("flexibility", flexibility)
    processing_time_variance = settings.get("processing_time_variance", processing_time_variance)
    processing_time_max = max(processing_time_max, settings.get("processing_time_max", processing_time_max))
    bottleneck_probability = max(bottleneck_probability, settings.get("bottleneck_probability", 0.0))
    machine_advantage = max(machine_advantage, settings.get("machine_advantage", 0.0))
    option_count = max(1, min(machines, round(1 + flexibility * (machines - 1))))
    for job in range(jobs):
        count = rng.randint(min_operations, max_operations)
        for index in range(count):
            eligible = set(rng.sample(range(machines), option_count))
            if rng.random() < bottleneck_probability:
                eligible.add(bottleneck)
            options = {}
            for machine in sorted(eligible):
                if processing_time_variance:
                    center = rng.uniform(processing_time_min, processing_time_max)
                    value = center * (1 + rng.gauss(0, processing_time_variance))
                else:
                    value = rng.randint(processing_time_min, processing_time_max)
                if machine_advantage and machine == bottleneck:
                    value *= max(0.05, 1 - machine_advantage)
                options[machine] = max(1, int(round(min(processing_time_max, value))))
            operations.append(Operation(job, index, options))
    parameters = {
        "jobs": jobs,
        "machines": machines,
        "operations_per_job": operations_per_job,
        "flexibility": flexibility,
        "processing_time_min": processing_time_min,
        "processing_time_max": processing_time_max,
        "processing_time_variance": processing_time_variance,
        "bottleneck_probability": bottleneck_probability,
        "machine_advantage": machine_advantage,
        "instance_class": instance_class,
    }
    return Instance(jobs, machines, operations, seed, parameters)


def named_instance_parameters(instance_class: str) -> dict[str, Any]:
    """Concrete presets used by the report and repeatable experiment runner."""
    presets = {
        "average": dict(flexibility=.5, processing_time_variance=.15, bottleneck_probability=.1),
        "low_flexibility": dict(flexibility=.05),
        "high_flexibility": dict(flexibility=.95),
        "bottleneck": dict(flexibility=.7, bottleneck_probability=.9),
        "balanced": dict(flexibility=.5, bottleneck_probability=0),
        "high_variance": dict(flexibility=.5, processing_time_variance=1.0, processing_time_max=100),
        "machine_advantage": dict(flexibility=.8, machine_advantage=.8),
        "extreme": dict(flexibility=.95, processing_time_variance=1.5, processing_time_max=10000,
                        bottleneck_probability=.8),
    }
    if instance_class not in presets:
        raise ValueError(f"unknown instance class: {instance_class}")
    return presets[instance_class]


def validate(instance: Instance, schedule: list[ScheduledOperation]) -> ValidationResult:
    """Independently verify completeness, timing, eligibility, precedence, and overlap."""
    errors: list[str] = []
    expected = {(op.job, op.index): op for op in instance.operations}
    seen: set[tuple[int, int]] = set()
    by_job: dict[int, list[ScheduledOperation]] = {}
    by_machine: dict[int, list[ScheduledOperation]] = {}

    if not isinstance(schedule, list):
        return ValidationResult(False, None, ["malformed schedule: expected a list"])
    for position, item in enumerate(schedule):
        if not isinstance(item, ScheduledOperation):
            errors.append(f"malformed schedule entry at position {position}")
            continue
        values = (item.job, item.index, item.machine, item.start, item.end)
        if not all(isinstance(value, int) and not isinstance(value, bool) for value in values):
            errors.append(f"malformed values in schedule entry at position {position}")
            continue
        key = (item.job, item.index)
        if key in seen:
            errors.append(f"duplicate operation J{item.job}-O{item.index}")
            continue
        seen.add(key)
        operation = expected.get(key)
        if operation is None:
            errors.append(f"unknown operation J{item.job}-O{item.index}")
            continue
        duration = operation.options.get(item.machine)
        if duration is None:
            errors.append(f"machine M{item.machine} is not eligible for J{item.job}-O{item.index}")
        if item.start < 0 or item.end < item.start:
            errors.append(f"invalid interval for J{item.job}-O{item.index}")
        elif duration is not None and item.end - item.start != duration:
            errors.append(f"wrong duration for J{item.job}-O{item.index}")
        by_job.setdefault(item.job, []).append(item)
        by_machine.setdefault(item.machine, []).append(item)

    missing = set(expected) - seen
    errors.extend(f"missing operation J{job}-O{index}" for job, index in sorted(missing))
    for job, items in by_job.items():
        items.sort(key=lambda item: item.index)
        for previous, current in zip(items, items[1:]):
            if previous.end > current.start:
                errors.append(f"precedence violation in job {job}: O{previous.index} -> O{current.index}")
    for machine, items in by_machine.items():
        items.sort(key=lambda item: (item.start, item.end))
        for previous, current in zip(items, items[1:]):
            if previous.end > current.start:
                errors.append(f"overlap on machine M{machine}")
    makespan = max((item.end for item in schedule), default=0) if not errors else None
    return ValidationResult(not errors, makespan, errors)


def solve(instance: Instance, seed: int | None = None, iterations: int = 20,
          local_search_iterations: int = 100) -> list[ScheduledOperation]:
    """Congestion-aware randomized greedy multi-start scheduler with improvement."""
    if iterations < 1:
        raise ValueError("iterations must be positive")
    if local_search_iterations < 0:
        raise ValueError("local_search_iterations must be non-negative")
    rng = random.Random(seed)
    operations_by_job = instance.operations_by_job
    best: list[ScheduledOperation] | None = None
    best_makespan = float("inf")
    for _ in range(iterations):
        ready = {job: 0 for job in range(instance.jobs)}
        machine_end = {machine: 0 for machine in range(instance.machines)}
        machine_load = {machine: 0 for machine in range(instance.machines)}
        next_index = {job: 0 for job in range(instance.jobs)}
        current: list[ScheduledOperation] = []
        remaining = sum(len(operations) for operations in operations_by_job.values())
        while remaining:
            candidates = []
            for job, index in next_index.items():
                operations = operations_by_job[job]
                if index >= len(operations):
                    continue
                operation = operations[index]
                for machine, duration in operation.options.items():
                    start = max(ready[job], machine_end[machine])
                    finish = start + duration
                    congestion = machine_load[machine] / max(1, sum(machine_load.values()))
                    score = (finish + congestion * duration, rng.random())
                    candidates.append((score, operation, machine, start, finish))
            _, operation, machine, start, finish = min(candidates, key=lambda item: item[0])
            current.append(ScheduledOperation(operation.job, operation.index, machine, start, finish))
            ready[operation.job] = finish
            next_index[operation.job] += 1
            machine_end[machine] = finish
            machine_load[machine] += finish - start
            remaining -= 1
        result = validate(instance, current)
        if result.valid and result.makespan is not None and result.makespan < best_makespan:
            best, best_makespan = current, result.makespan
    if best is None:
        raise RuntimeError("solver failed to produce a valid schedule")
    if local_search_iterations:
        assignments = {(item.job, item.index): item.machine for item in best}
        ordered = sorted(best, key=lambda item: (item.start, item.machine, item.job, item.index))
        priority = {(item.job, item.index): rank for rank, item in enumerate(ordered)}
        search_budget = min(local_search_iterations, max(10, 20000 // len(instance.operations)))
        for _ in range(search_budget):
            pairs = _critical_pairs(best)
            pair = rng.choice(pairs) if pairs else None
            key = rng.choice(pair) if pair else rng.choice(list(assignments))
            operation = next(op for op in instance.operations if (op.job, op.index) == key)
            alternatives = [machine for machine in operation.options if machine != assignments[key]]
            if not alternatives:
                continue
            trial_assignments = assignments.copy()
            trial_assignments[key] = rng.choice(alternatives)
            trial_priority = priority.copy()
            trial_priority[key] = max(trial_priority.values()) + 1
            try:
                trial = _rebuild(instance, trial_assignments, trial_priority)
            except (KeyError, ValueError):
                continue
            trial_result = validate(instance, trial)
            if trial_result.valid and trial_result.makespan is not None and trial_result.makespan < best_makespan:
                best, best_makespan = trial, trial_result.makespan
                assignments, priority = trial_assignments, trial_priority
    return sorted(best, key=lambda item: (item.start, item.machine, item.job, item.index))


def instance_to_dict(instance: Instance) -> dict[str, Any]:
    return {
        "jobs": instance.jobs,
        "machines": instance.machines,
        "seed": instance.seed,
        "parameters": instance.parameters,
        "operations": [asdict(operation) for operation in instance.operations],
    }


def validate_instance(instance: Instance) -> list[str]:
    """Independently check the well-formedness contract for imported instances."""
    errors: list[str] = []
    if not isinstance(instance.jobs, int) or instance.jobs < 1:
        errors.append("jobs must be a positive integer")
    if not isinstance(instance.machines, int) or instance.machines < 1:
        errors.append("machines must be a positive integer")
    expected: dict[tuple[int, int], Operation] = {}
    for operation in instance.operations:
        if not all(isinstance(value, int) and not isinstance(value, bool)
                   for value in (operation.job, operation.index)):
            errors.append("job and operation IDs must be integers")
            continue
        key = (operation.job, operation.index)
        if not 0 <= operation.job < instance.jobs:
            errors.append(f"invalid job ID {operation.job}")
        if operation.index < 0:
            errors.append(f"invalid operation ID {operation.index}")
        if key in expected:
            errors.append(f"duplicate operation J{operation.job}-O{operation.index}")
        expected[key] = operation
        if not operation.options:
            errors.append(f"operation J{operation.job}-O{operation.index} has no machines")
        if not isinstance(operation.options, dict):
            errors.append(f"options for J{operation.job}-O{operation.index} must be an object")
            continue
        for machine, duration in operation.options.items():
            if not isinstance(machine, int) or not 0 <= machine < instance.machines:
                errors.append(f"invalid machine ID M{machine}")
            if not isinstance(duration, int) or isinstance(duration, bool) or duration <= 0:
                errors.append(f"invalid duration for J{operation.job}-O{operation.index}")
    by_job = {job: [] for job in range(max(0, instance.jobs))}
    for operation in instance.operations:
        if 0 <= operation.job < instance.jobs:
            by_job[operation.job].append(operation.index)
    for job, indices in by_job.items():
        if not indices:
            errors.append(f"job {job} has no operations")
        if sorted(indices) != list(range(len(indices))):
            errors.append(f"job {job} operation IDs are not contiguous")
    return errors


def instance_from_dict(data: dict[str, Any]) -> Instance:
    if not isinstance(data, dict):
        raise ValueError("instance JSON must be an object")
    operations = [
        Operation(item["job"], item["index"], {int(k): v for k, v in item["options"].items()})
        for item in data["operations"]
    ]
    instance = Instance(data["jobs"], data["machines"], operations, data.get("seed"), data.get("parameters"))
    errors = validate_instance(instance)
    if errors:
        raise ValueError("; ".join(errors))
    return instance


def function_one(jobs: int = 5, machines: int = 3, operations: int = 4,
                 instance_class: str = "average", seed: int = 42,
                 starts: int = 30, local_search: int = 100) -> dict[str, Any]:
    """Run the complete first milestone and return submission-ready JSON data."""
    instance = generate_instance(jobs, machines, operations,
                                 instance_class=instance_class, seed=seed)
    schedule = solve(instance, seed, starts, local_search)
    validation = validate(instance, schedule)
    if not validation.valid:
        raise RuntimeError("Function 1 produced an invalid schedule")
    return {
        "instance": instance_to_dict(instance),
        "schedule": [asdict(item) for item in schedule],
        "validation": validation.to_dict(),
        "metrics": metrics(instance, schedule),
        "algorithm": {
            "name": "congestion_greedy_critical_block_multistart",
            "seed": seed,
            "starts": starts,
            "local_search_iterations": local_search,
        },
    }


def run_experiment(args: argparse.Namespace) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    runtimes: list[float] = []
    for offset in range(args.repetitions):
        parameters = named_instance_parameters(args.instance_class)
        parameters.setdefault("flexibility", args.flexibility)
        parameters.setdefault("processing_time_variance", args.variance)
        parameters.setdefault("bottleneck_probability", args.bottleneck)
        parameters.setdefault("processing_time_max", args.time_max)
        instance = generate_instance(
            args.jobs, args.machines, args.operations, seed=args.seed + offset,
            processing_time_min=args.time_min,
            instance_class=args.instance_class, **parameters,
        )
        started = time.perf_counter()
        schedule = solve(instance, args.seed + offset, args.iterations, args.local_search)
        runtimes.append(time.perf_counter() - started)
        result = validate(instance, schedule)
        if not result.valid or result.makespan is None:
            raise RuntimeError("experiment produced an invalid schedule")
        record = metrics(instance, schedule)
        record.update({
            "seed": args.seed + offset,
            "instance_class": args.instance_class,
            "jobs": instance.jobs,
            "machines": instance.machines,
            "operations": len(instance.operations),
            "runtime_ms": runtimes[-1] * 1000,
        })
        records.append(record)
    makespans = [record["makespan"] for record in records]
    return {
        "repetitions": args.repetitions,
        "instance_class": args.instance_class,
        "average_makespan": statistics.mean(makespans),
        "best_makespan": min(makespans),
        "worst_makespan": max(makespans),
        "average_runtime_ms": statistics.mean(runtimes) * 1000,
        "average_lower_bound_gap": statistics.mean(record["lower_bound_gap"] for record in records),
        "makespan_stddev": statistics.stdev(makespans) if len(makespans) > 1 else 0.0,
        "makespans": makespans,
        "records": records,
        "algorithm": {
            "name": "congestion_greedy_multistart",
            "seed_base": args.seed,
            "iterations": args.iterations,
            "local_search_iterations": args.local_search,
            "python_version": sys.version.split()[0],
        },
        "generator": {
            "jobs": args.jobs,
            "machines": args.machines,
            "operations_per_job": args.operations,
            "seed_base": args.seed,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate and solve flexible job-shop scheduling instances.")
    sub = parser.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--jobs", type=int, default=5)
    common.add_argument("--machines", type=int, default=3)
    common.add_argument("--operations", type=int, default=4)
    common.add_argument("--flexibility", type=float, default=0.5)
    common.add_argument("--time-min", type=int, default=1)
    common.add_argument("--time-max", type=int, default=20)
    common.add_argument("--variance", type=float, default=0.0)
    common.add_argument("--bottleneck", type=float, default=0.0)
    common.add_argument("--instance-class", default="average",
                        choices=["average", "low_flexibility", "high_flexibility", "bottleneck",
                                 "balanced", "high_variance", "machine_advantage", "extreme"])
    common.add_argument("--seed", type=int, default=42)
    common.add_argument("--iterations", type=int, default=20)
    common.add_argument("--local-search", type=int, default=100)
    generate = sub.add_parser("generate", parents=[common])
    generate.add_argument("--output", default="-")
    solve_parser = sub.add_parser("solve")
    solve_parser.add_argument("instance")
    solve_parser.add_argument("--iterations", type=int, default=20)
    solve_parser.add_argument("--local-search", type=int, default=100)
    validate_parser = sub.add_parser("validate", help="independently referee a schedule JSON file")
    validate_parser.add_argument("instance")
    validate_parser.add_argument("schedule")
    function_parser = sub.add_parser("function-one", help="run the complete first milestone")
    function_parser.add_argument("--jobs", type=int, default=5)
    function_parser.add_argument("--machines", type=int, default=3)
    function_parser.add_argument("--operations", type=int, default=4)
    function_parser.add_argument("--instance-class", default="average",
                                 choices=["average", "low_flexibility", "high_flexibility",
                                          "bottleneck", "balanced", "high_variance",
                                          "machine_advantage", "extreme"])
    function_parser.add_argument("--seed", type=int, default=42)
    function_parser.add_argument("--output", default="-")
    experiment = sub.add_parser("experiment", parents=[common])
    experiment.add_argument("--repetitions", type=int, default=10)
    args = parser.parse_args()

    try:
        if args.command == "generate":
            data = json.dumps(instance_to_dict(generate_instance(
                args.jobs, args.machines, args.operations, args.flexibility,
                args.time_min, args.time_max, args.variance, args.bottleneck,
                seed=args.seed, instance_class=args.instance_class,
            )), indent=2)
            if args.output == "-":
                print(data)
            else:
                with open(args.output, "w", encoding="utf-8") as file:
                    file.write(data + "\n")
        elif args.command == "solve":
            with open(args.instance, encoding="utf-8-sig") as file:
                instance = instance_from_dict(json.load(file))
            schedule = solve(instance, instance.seed, args.iterations, args.local_search)
            result = validate(instance, schedule)
            print(json.dumps({"schedule": [asdict(item) for item in schedule],
                              "validation": result.to_dict(),
                              "metrics": metrics(instance, schedule)}, indent=2))
        elif args.command == "validate":
            with open(args.instance, encoding="utf-8-sig") as file:
                instance = instance_from_dict(json.load(file))
            with open(args.schedule, encoding="utf-8-sig") as file:
                raw_schedule = json.load(file)
            if isinstance(raw_schedule, dict):
                raw_schedule = raw_schedule.get("schedule")
            if not isinstance(raw_schedule, list):
                raise ValueError("malformed schedule JSON: expected a list")
            schedule = [ScheduledOperation(
                item["job"], item["index"], item["machine"], item["start"], item["end"]
            ) for item in raw_schedule]
            result = validate(instance, schedule)
            print("VALID" if result.valid else "INVALID")
            if result.valid:
                print(f"Makespan: {result.makespan}")
            else:
                for error in result.errors:
                    print(f"Error: {error}")
        else:
            if args.command == "function-one":
                data = json.dumps(function_one(args.jobs, args.machines, args.operations,
                                               args.instance_class, args.seed), indent=2)
                if args.output == "-":
                    print(data)
                else:
                    with open(args.output, "w", encoding="utf-8") as file:
                        file.write(data + "\n")
            else:
                print(json.dumps(run_experiment(args), indent=2))
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
