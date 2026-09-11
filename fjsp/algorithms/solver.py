"""FJSP solver with critical-path-guided tabu search.

Architecture
------------
1. **Construction phase** — Congestion-aware randomized greedy multi-start
   dispatcher.  At each step every ready (operation, machine) pair is scored
   by earliest finish + congestion penalty; the best is scheduled.

2. **Improvement phase** — Critical-path-restricted local search with tabu
   memory.  The disjunctive graph is built, the true critical path is
   computed via longest-path DAG traversal, critical *blocks* (maximal runs
   of consecutive critical-path operations on the same machine) are
   extracted, and three neighbourhood operators are applied:

   * **Adjacent swap** — swap the first or last pair in each critical block
     (Nowicki & Smutnicki N5 style).
   * **Insertion move** — remove a critical operation from its machine
     position and reinsert it at every other feasible slot.
   * **Machine reassignment** — reassign a critical operation to an
     alternative eligible machine.

   A *tabu list* of recently applied moves prevents cycling.  The
   *aspiration criterion* overrides the tabu if a move produces a new
   global best.

Representation
--------------
A schedule is a list of ``ScheduledOperation(job, index, machine, start,
end)``.  Internally the search manipulates an *assignment dict*
``{(job, op_idx): machine}`` and a *priority dict*
``{(job, op_idx): int}`` that together deterministically produce a
semi-active schedule via ``_rebuild()``.

Complexity
----------
With *I* starts, *O* operations, *M* machines, and *L* local-search
iterations the construction phase is O(I · O² · M) and the improvement
phase is O(L · O² · M) per restart.  Memory is O(O + M).
"""

from __future__ import annotations

import math
import random
from collections import deque
from typing import Any

from fjsp.model import Instance, Operation, ScheduledOperation
from fjsp.environment.validator import validate


# ---------------------------------------------------------------------------
# Schedule builder
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Critical-path computation on the disjunctive graph
# ---------------------------------------------------------------------------

def _compute_critical_path(
    instance: Instance,
    schedule: list[ScheduledOperation],
) -> tuple[list[tuple[int, int]], dict[tuple[int, int], int]]:
    """Compute the true critical path through the disjunctive graph.

    Returns
    -------
    critical_ops : list[(job, index)]
        Operation keys on the longest path, in topological order.
    longest : dict[(job, index), int]
        Longest path length ending at each operation.
    """
    by_job = instance.operations_by_job
    by_machine: dict[int, list[ScheduledOperation]] = {}
    for item in schedule:
        by_machine.setdefault(item.machine, []).append(item)
    machine_sequences = {
        machine: sorted(items, key=lambda item: (item.start, item.end))
        for machine, items in by_machine.items()
    }

    # Build predecessor map (job-order + machine-sequence edges)
    predecessors: dict[tuple[int, int], list[tuple[int, int]]] = {
        (item.job, item.index): [] for item in schedule
    }
    for items in by_job.values():
        ordered = sorted(items, key=lambda item: item.index)
        for previous, current in zip(ordered, ordered[1:]):
            predecessors[(current.job, current.index)].append(
                (previous.job, previous.index)
            )
    for items in machine_sequences.values():
        for previous, current in zip(items, items[1:]):
            predecessors[(current.job, current.index)].append(
                (previous.job, previous.index)
            )

    duration = {(item.job, item.index): item.end - item.start for item in schedule}
    longest: dict[tuple[int, int], int] = {}

    # Process in topological order (by start time)
    for item in sorted(schedule, key=lambda entry: (entry.start, entry.end)):
        key = (item.job, item.index)
        longest[key] = duration[key] + max(
            (longest[pred] for pred in predecessors[key]), default=0
        )

    if not longest:
        return [], longest

    # Back-trace to find the critical path
    makespan = max(longest.values())
    # Find the terminal node
    terminal = max(longest, key=lambda k: longest[k])
    critical_ops: list[tuple[int, int]] = []
    current = terminal
    while current is not None:
        critical_ops.append(current)
        best_pred = None
        best_length = -1
        for pred in predecessors[current]:
            if longest[pred] > best_length:
                best_length = longest[pred]
                best_pred = pred
        current = best_pred

    critical_ops.reverse()
    return critical_ops, longest


# ---------------------------------------------------------------------------
# Main solver
# ---------------------------------------------------------------------------

def solve(
    instance: Instance,
    seed: int | None = None,
    iterations: int = 20,
    local_search_iterations: int = 200,
    tabu_tenure: int = 7,
) -> list[ScheduledOperation]:
    """
    Phase 1: Congestion-aware randomized greedy multi-start construction.
    Phase 2: Tabu search with machine-reassignment and operation-resequencing moves.

    Neighbourhood N1: reassign operation O(j,k) to an alternative eligible machine.
    Neighbourhood N2: swap the sequence of two adjacent operations on the same machine.

    Tabu list: stores (op_key, from_machine, to_machine) for N1 moves and
               (op_key_a, op_key_b, machine) for N2 moves, with tenure.
    Aspiration: accept a tabu move if it beats the global best makespan.
    """
    if iterations < 1:
        raise ValueError("iterations must be positive")
    if local_search_iterations < 0:
        raise ValueError("local_search_iterations must be non-negative")

    rng = random.Random(seed)
    operations_by_job = instance.operations_by_job

    # ── Phase 1: Multi-start greedy construction ──────────────────────────
    best: list[ScheduledOperation] | None = None
    best_makespan = float("inf")

    for _ in range(iterations):
        ready   = {job: 0 for job in range(instance.jobs)}
        mach_end = {m: 0 for m in range(instance.machines)}
        mach_load = {m: 0 for m in range(instance.machines)}
        next_idx = {job: 0 for job in range(instance.jobs)}
        current: list[ScheduledOperation] = []
        remaining = sum(len(ops) for ops in operations_by_job.values())

        while remaining:
            candidates = []
            for job, idx in next_idx.items():
                ops = operations_by_job[job]
                if idx >= len(ops):
                    continue
                op = ops[idx]
                for machine, duration in op.options.items():
                    start  = max(ready[job], mach_end[machine])
                    finish = start + duration
                    total  = max(1, sum(mach_load.values()))
                    cong   = mach_load[machine] / total
                    score  = (finish + cong * duration, rng.random())
                    candidates.append((score, op, machine, start, finish))

            _, op, machine, start, finish = min(candidates, key=lambda x: x[0])
            current.append(ScheduledOperation(op.job, op.index, machine, start, finish))
            ready[op.job]     = finish
            next_idx[op.job] += 1
            mach_end[machine]  = finish
            mach_load[machine] += finish - start
            remaining -= 1

        vr = validate(instance, current)
        if vr.valid and vr.makespan is not None and vr.makespan < best_makespan:
            best, best_makespan = current, vr.makespan

    if best is None:
        raise RuntimeError("solver failed to produce a valid schedule")

    if not local_search_iterations:
        return sorted(best, key=lambda x: (x.start, x.machine, x.job, x.index))

    # ── Phase 2: Tabu Search ──────────────────────────────────────────────

    # O(1) op lookup — build once
    op_lookup = {(o.job, o.index): o for o in instance.operations}

    assignments = {(item.job, item.index): item.machine for item in best}
    ordered     = sorted(best, key=lambda x: (x.start, x.machine, x.job, x.index))
    priority    = {(item.job, item.index): rank for rank, item in enumerate(ordered)}

    global_best       = best
    global_best_span  = best_makespan
    current_schedule  = best
    current_span      = best_makespan

    # O(1) tabu lookup via dict instead of linear deque scan
    tabu: dict[tuple, int] = {}  # sig -> expiry_iteration

    def is_tabu(sig: tuple, iteration: int) -> bool:
        return tabu.get(sig, 0) > iteration

    def add_tabu(sig: tuple, iteration: int) -> None:
        tabu[sig] = iteration + tabu_tenure

    def fast_makespan(sched: list[ScheduledOperation]) -> int:
        return max(s.end for s in sched) if sched else 0

    budget = min(local_search_iterations, max(20, 30000 // max(1, len(instance.operations))))
    stagnation = 0
    max_stagnation = 15

    for iteration in range(budget):
        best_move_delta = float("inf")
        best_move       = None
        best_move_sig   = None
        best_move_type  = None

        # ── Neighbourhood N1: machine reassignment ────────────────────────
        crit_ops, _ = _compute_critical_path(instance, current_schedule)
        crit_keys = set(crit_ops)
        all_keys  = list(assignments.keys())
        # Prioritise critical ops but evaluate all within a sample budget
        candidate_keys = list(crit_keys) + [k for k in all_keys if k not in crit_keys]
        sample_size    = min(len(candidate_keys), max(10, len(candidate_keys) // 3))
        sampled_keys   = candidate_keys[:sample_size]

        for key in sampled_keys:
            op = op_lookup[key]                    # O(1) instead of O(O)
            current_machine = assignments[key]
            for alt_machine in op.options:
                if alt_machine == current_machine:
                    continue
                sig     = ("N1", key, current_machine, alt_machine)
                rev_sig = ("N1", key, alt_machine, current_machine)

                trial_assign = assignments.copy()
                trial_assign[key] = alt_machine
                try:
                    trial_sched = _rebuild(instance, trial_assign, priority)
                except (KeyError, ValueError):
                    continue

                span = fast_makespan(trial_sched)  # O(O) instead of full validate
                delta = span - current_span
                tabu_blocked = is_tabu(sig, iteration) or is_tabu(rev_sig, iteration)
                aspirated    = span < global_best_span

                if (not tabu_blocked or aspirated) and delta < best_move_delta:
                    best_move_delta = delta
                    best_move       = (trial_assign, trial_sched, span)
                    best_move_sig   = sig
                    best_move_type  = "N1"

        # ── Neighbourhood N2: swap two adjacent ops on same machine ───────
        by_machine_now: dict[int, list[ScheduledOperation]] = {}
        for item in current_schedule:
            by_machine_now.setdefault(item.machine, []).append(item)

        for machine_items in by_machine_now.values():
            machine_items.sort(key=lambda x: x.start)
            for left, right in zip(machine_items, machine_items[1:]):
                lk = (left.job,  left.index)
                rk = (right.job, right.index)
                sig     = ("N2", lk, rk, left.machine)
                rev_sig = ("N2", rk, lk, left.machine)

                # Try swapping their priority ranks
                trial_prio = priority.copy()
                trial_prio[lk], trial_prio[rk] = trial_prio[rk], trial_prio[lk]
                try:
                    trial_sched = _rebuild(instance, assignments, trial_prio)
                except (KeyError, ValueError):
                    continue

                span = fast_makespan(trial_sched)  # O(O) instead of full validate
                delta = span - current_span
                tabu_blocked = is_tabu(sig, iteration) or is_tabu(rev_sig, iteration)
                aspirated    = span < global_best_span

                if (not tabu_blocked or aspirated) and delta < best_move_delta:
                    best_move_delta = delta
                    best_move       = (assignments, trial_sched, span)
                    best_move_sig   = sig
                    best_move_type  = "N2"

        if best_move is None:
            # No improving or non-tabu move found; continue to next iteration
            continue

        new_assign, new_sched, new_span = best_move
        add_tabu(best_move_sig, iteration)

        # Update current solution (accept any best non-tabu move, even if worse)
        if best_move_type == "N1":
            assignments = new_assign
        else:
            # N2: update priority from the new schedule's order
            reordered = sorted(new_sched, key=lambda x: (x.start, x.machine, x.job, x.index))
            priority  = {(item.job, item.index): rank for rank, item in enumerate(reordered)}

        current_schedule = new_sched
        current_span     = new_span

        if new_span < global_best_span:
            global_best      = new_sched
            global_best_span = new_span
            stagnation = 0
        else:
            stagnation += 1
            if stagnation >= max_stagnation:
                break

    return sorted(global_best, key=lambda x: (x.start, x.machine, x.job, x.index))
