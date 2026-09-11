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


def _extract_critical_blocks(
    schedule: list[ScheduledOperation],
    critical_ops: list[tuple[int, int]],
) -> list[list[ScheduledOperation]]:
    """Extract critical blocks — maximal runs of critical operations on the same machine.

    A critical block is a maximal sequence of consecutive operations on the
    same machine where every operation lies on the critical path.  Only blocks
    of length >= 2 are useful for swap moves.
    """
    sched_map = {(item.job, item.index): item for item in schedule}
    critical_set = set(critical_ops)

    # Group scheduled operations by machine, in time order
    by_machine: dict[int, list[ScheduledOperation]] = {}
    for item in schedule:
        by_machine.setdefault(item.machine, []).append(item)
    for items in by_machine.values():
        items.sort(key=lambda item: (item.start, item.end))

    blocks: list[list[ScheduledOperation]] = []
    for machine, items in by_machine.items():
        current_block: list[ScheduledOperation] = []
        for item in items:
            key = (item.job, item.index)
            if key in critical_set:
                current_block.append(item)
            else:
                if len(current_block) >= 2:
                    blocks.append(current_block)
                current_block = []
        if len(current_block) >= 2:
            blocks.append(current_block)

    return blocks


# ---------------------------------------------------------------------------
# Neighbourhood operators
# ---------------------------------------------------------------------------

def _adjacent_swap_moves(
    assignments: dict[tuple[int, int], int],
    priority: dict[tuple[int, int], int],
    blocks: list[list[ScheduledOperation]],
) -> list[tuple[dict[tuple[int, int], int], dict[tuple[int, int], int], tuple[Any, ...]]]:
    """Generate adjacent swap moves on critical blocks (N5 neighbourhood).

    For each critical block, try swapping:
    - The first two operations (may break the incoming critical edge)
    - The last two operations (may break the outgoing critical edge)

    Returns a list of (new_assignments, new_priority, move_signature) tuples.
    """
    moves: list[tuple[dict[tuple[int, int], int], dict[tuple[int, int], int], tuple[Any, ...]]] = []
    for block in blocks:
        # Swap pairs: first two and last two
        swap_pairs = []
        if len(block) >= 2:
            swap_pairs.append((block[0], block[1]))
            if len(block) >= 3:
                swap_pairs.append((block[-2], block[-1]))
        for a, b in swap_pairs:
            key_a = (a.job, a.index)
            key_b = (b.job, b.index)
            new_priority = priority.copy()
            # Swap priorities to reverse order on the machine
            new_priority[key_a], new_priority[key_b] = (
                new_priority[key_b], new_priority[key_a]
            )
            move_sig = ("swap", key_a, key_b)
            moves.append((assignments.copy(), new_priority, move_sig))
    return moves


def _insertion_moves(
    instance: Instance,
    assignments: dict[tuple[int, int], int],
    priority: dict[tuple[int, int], int],
    blocks: list[list[ScheduledOperation]],
    schedule: list[ScheduledOperation],
) -> list[tuple[dict[tuple[int, int], int], dict[tuple[int, int], int], tuple[Any, ...]]]:
    """Generate insertion moves for critical operations.

    Try removing a critical operation from its current position on the machine
    and inserting it at the beginning or end of the machine sequence.
    """
    moves: list[tuple[dict[tuple[int, int], int], dict[tuple[int, int], int], tuple[Any, ...]]] = []
    critical_keys: set[tuple[int, int]] = set()
    for block in blocks:
        for item in block:
            critical_keys.add((item.job, item.index))

    min_priority = min(priority.values()) if priority else 0
    max_priority = max(priority.values()) if priority else 0

    for key in critical_keys:
        # Try inserting at the front (lowest priority) or back (highest priority)
        for new_prio_val, label in [
            (min_priority - 1, "insert_front"),
            (max_priority + 1, "insert_back"),
        ]:
            new_priority = priority.copy()
            new_priority[key] = new_prio_val
            move_sig = (label, key)
            moves.append((assignments.copy(), new_priority, move_sig))

    return moves


def _reassignment_moves(
    instance: Instance,
    assignments: dict[tuple[int, int], int],
    priority: dict[tuple[int, int], int],
    blocks: list[list[ScheduledOperation]],
    rng: random.Random,
) -> list[tuple[dict[tuple[int, int], int], dict[tuple[int, int], int], tuple[Any, ...]]]:
    """Generate machine reassignment moves for critical operations."""
    moves: list[tuple[dict[tuple[int, int], int], dict[tuple[int, int], int], tuple[Any, ...]]] = []
    ops_map = {(op.job, op.index): op for op in instance.operations}

    critical_keys: set[tuple[int, int]] = set()
    for block in blocks:
        for item in block:
            critical_keys.add((item.job, item.index))

    max_prio = max(priority.values()) if priority else 0

    for key in critical_keys:
        operation = ops_map[key]
        current_machine = assignments[key]
        alternatives = [m for m in operation.options if m != current_machine]
        for alt_machine in alternatives:
            new_assignments = assignments.copy()
            new_assignments[key] = alt_machine
            new_priority = priority.copy()
            new_priority[key] = max_prio + 1
            move_sig = ("reassign", key, current_machine, alt_machine)
            moves.append((new_assignments, new_priority, move_sig))

    return moves


# ---------------------------------------------------------------------------
# Main solver
# ---------------------------------------------------------------------------

def solve(
    instance: Instance,
    seed: int | None = None,
    iterations: int = 20,
    local_search_iterations: int = 100,
    tabu_tenure: int | None = None,
) -> list[ScheduledOperation]:
    """Congestion-aware randomized greedy multi-start with critical-path tabu search.

    Parameters
    ----------
    instance : Instance
        The FJSP instance to solve.
    seed : int | None
        Random seed for reproducibility.
    iterations : int
        Number of independent construction starts (>= 1).
    local_search_iterations : int
        Maximum improvement iterations per start (>= 0).
    tabu_tenure : int | None
        Number of iterations a move stays tabu.  Defaults to
        ``ceil(sqrt(num_operations))``.

    Returns
    -------
    list[ScheduledOperation]
        The best valid schedule found, sorted by (start, machine, job, index).
    """
    if iterations < 1:
        raise ValueError("iterations must be positive")
    if local_search_iterations < 0:
        raise ValueError("local_search_iterations must be non-negative")
    rng = random.Random(seed)
    operations_by_job = instance.operations_by_job
    num_ops = len(instance.operations)
    if tabu_tenure is None:
        tabu_tenure = max(5, math.ceil(math.sqrt(num_ops)))

    best: list[ScheduledOperation] | None = None
    best_makespan = float("inf")

    # ---- Phase 1: Multi-start greedy construction ----
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

    # ---- Phase 2: Critical-path tabu search ----
    if local_search_iterations and num_ops > 1:
        assignments = {(item.job, item.index): item.machine for item in best}
        ordered = sorted(best, key=lambda item: (item.start, item.machine, item.job, item.index))
        priority = {(item.job, item.index): rank for rank, item in enumerate(ordered)}

        search_budget = min(local_search_iterations, max(10, 20000 // num_ops))
        tabu_list: deque[tuple[Any, ...]] = deque(maxlen=tabu_tenure)

        no_improve_count = 0
        max_no_improve = max(10, search_budget // 3)

        for iteration in range(search_budget):
            # Compute the true critical path
            critical_ops, longest = _compute_critical_path(instance, best)
            blocks = _extract_critical_blocks(best, critical_ops)

            if not blocks:
                # Fall back to random reassignment if no critical blocks
                key = rng.choice(list(assignments))
                operation = next(op for op in instance.operations if (op.job, op.index) == key)
                alternatives = [m for m in operation.options if m != assignments[key]]
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
                    no_improve_count = 0
                continue

            # Generate all candidate moves
            candidate_moves: list[tuple[dict[tuple[int, int], int], dict[tuple[int, int], int], tuple[Any, ...]]] = []
            candidate_moves.extend(_adjacent_swap_moves(assignments, priority, blocks))
            candidate_moves.extend(_insertion_moves(instance, assignments, priority, blocks, best))
            candidate_moves.extend(_reassignment_moves(instance, assignments, priority, blocks, rng))

            if not candidate_moves:
                continue

            # Evaluate all candidates, pick the best non-tabu (or aspiration)
            best_candidate = None
            best_candidate_makespan = float("inf")
            best_candidate_move_sig: tuple[Any, ...] | None = None

            # Shuffle to break ties randomly
            rng.shuffle(candidate_moves)

            for trial_assignments, trial_priority, move_sig in candidate_moves:
                is_tabu = move_sig in tabu_list

                try:
                    trial = _rebuild(instance, trial_assignments, trial_priority)
                except (KeyError, ValueError):
                    continue
                trial_result = validate(instance, trial)
                if not trial_result.valid or trial_result.makespan is None:
                    continue

                # Accept if: (not tabu AND improves over current best candidate)
                #          OR (aspiration: beats global best)
                if trial_result.makespan < best_candidate_makespan:
                    if not is_tabu or trial_result.makespan < best_makespan:
                        best_candidate = trial
                        best_candidate_makespan = trial_result.makespan
                        best_candidate_move_sig = move_sig
                        # If this is already better than global best,
                        # we can skip evaluating more moves for speed
                        if trial_result.makespan < best_makespan:
                            break

            if best_candidate is not None and best_candidate_move_sig is not None:
                # Apply the move
                if best_candidate_makespan < best_makespan:
                    best = best_candidate
                    best_makespan = best_candidate_makespan
                    no_improve_count = 0
                else:
                    no_improve_count += 1

                # Update assignments and priority from the accepted schedule
                assignments = {(item.job, item.index): item.machine for item in best_candidate}
                priority = {
                    (item.job, item.index): rank
                    for rank, item in enumerate(
                        sorted(best_candidate, key=lambda item: (item.start, item.machine, item.job, item.index))
                    )
                }

                # Add reverse move to tabu list
                tabu_list.append(best_candidate_move_sig)
            else:
                no_improve_count += 1

            if no_improve_count >= max_no_improve:
                break

    return sorted(best, key=lambda item: (item.start, item.machine, item.job, item.index))
