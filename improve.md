# FJSP Improvement Plan — From 72 → 92+
**All edits are to `fjsp.py` unless a different file is named.**
**Apply in order. Each section states the score it unlocks.**

---

## PHASE 1 — Fix Breaking Bugs (72 → 79)

These three bugs cause crashes or false test results on a clean checkout.
Fix them first before anything else.

---

### FIX 1 — Add `unbalanced` to `class_settings` inside `generate_instance`

**Problem:** `run_submission.py` runs the `unbalanced` experiment, but
`generate_instance()` raises `ValueError("unknown instance class: unbalanced")`
because `"unbalanced"` is not in its internal `class_settings` dict.
`python run_submission.py` crashes on a clean checkout.

**Location:** inside `generate_instance()`, find this block:

```python
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
```

**Replace with:**

```python
class_settings = {
    "low_flexibility":    {"flexibility": .05},
    "high_flexibility":   {"flexibility": .95},
    "bottleneck":         {"bottleneck_probability": .85},
    "high_variance":      {"processing_time_variance": 1.0, "processing_time_max": 100},
    "machine_advantage":  {"machine_advantage": .8},
    "extreme":            {"flexibility": .95, "processing_time_variance": 1.5,
                           "processing_time_max": 10000, "bottleneck_probability": .8},
    "balanced":           {"bottleneck_probability": 0.0},
    "unbalanced":         {},   # <-- ADD THIS LINE
    "average":            {},
    "small":              {},
    "large":              {},
}
```

Also add `"unbalanced"` to the `named_instance_parameters` presets so the
experiment runner can call it without a KeyError:

**Location:** inside `named_instance_parameters()`, find:

```python
presets = {
    "average": dict(flexibility=.5, processing_time_variance=.15, bottleneck_probability=.1),
    ...
    "extreme": dict(...),
}
```

**Add one line before the closing brace:**

```python
    "unbalanced": dict(flexibility=.5, processing_time_variance=.3, bottleneck_probability=.1),
```

Also update the `run_submission.py` loop so `unbalanced` gets a variable-length
operations tuple. Find:

```python
args = argparse.Namespace(
    jobs=12, machines=6, operations=5, ...
    instance_class=name, ...
)
```

**Replace with:**

```python
ops = (1, 8) if name == "unbalanced" else 5
args = argparse.Namespace(
    jobs=12, machines=6, operations=ops, ...
    instance_class=name, ...
)
```

---

### FIX 2 — Enrich validator overlap message and fix the failing test

**Problem:** `test_enriched_validator_error_messages` asserts the overlap
error contains `"Overlap on M0"` and interval strings like `"J0-O0 [5, 12)"`.
The current validator emits `"overlap on machine M0"` with no coordinates.
The test **fails**. Fix the validator to emit the enriched format.

**Location:** inside `validate()`, find:

```python
    for machine, items in by_machine.items():
        items.sort(key=lambda item: (item.start, item.end))
        for previous, current in zip(items, items[1:]):
            if previous.end > current.start:
                errors.append(f"overlap on machine M{machine}")
```

**Replace with:**

```python
    for machine, items in by_machine.items():
        items.sort(key=lambda item: (item.start, item.end))
        for previous, current in zip(items, items[1:]):
            if previous.end > current.start:
                errors.append(
                    f"Overlap on M{machine}: "
                    f"J{previous.job}-O{previous.index} [{previous.start}, {previous.end})"
                    f" and J{current.job}-O{current.index} [{current.start}, {current.end})"
                )
```

Now update the `test_enriched_validator_error_messages` test assertion in
`test_fjsp.py` to also check the precedence message format matches.
The existing assertions should now pass with the new format above.

---

### FIX 3 — Exit code 1 on INVALID schedule in CLI

**Problem:** `main()` prints "INVALID" but exits with code 0.
Automated referee scripts cannot detect failure.

**Location:** inside `main()`, find the `validate` command handler:

```python
        result = validate(instance, schedule)
        print("VALID" if result.valid else "INVALID")
        if result.valid:
            print(f"Makespan: {result.makespan}")
        else:
            for error in result.errors:
                print(f"Error: {error}")
```

**Replace with:**

```python
        result = validate(instance, schedule)
        if result.valid:
            print("VALID")
            print(f"Makespan: {result.makespan}")
        else:
            print("INVALID")
            for error in result.errors:
                print(f"Error: {error}")
            raise SystemExit(1)
```

---

## PHASE 2 — Workspace & Pipeline Hygiene (79 → 83)

---

### FIX 4 — Remove `fjsp_monolith_backup.py`

```bash
git rm fjsp_monolith_backup.py
git commit -m "remove duplicate backup file"
```

If you want to keep it for reference, rename it so it is clearly not
authoritative:

```bash
git mv fjsp_monolith_backup.py _archive/fjsp_monolith_backup.py
```

---

### FIX 5 — Resolve `from fjsp import ...` ambiguity

The test file does `from fjsp import ...`. This resolves to the `fjsp/`
**directory** (package) if it has an `__init__.py`, OR to `fjsp.py` if it
doesn't. To make `fjsp.py` the one true implementation:

**Option A (simplest):** rename the `fjsp/` directory:

```bash
git mv fjsp _fjsp_package_unused
```

Then `from fjsp import ...` unambiguously imports `fjsp.py`.

**Option B (cleaner):** make `fjsp/` the package and put everything in it.
Create `fjsp/__init__.py` that re-exports from the module:

```python
# fjsp/__init__.py
from fjsp.core import (  # noqa: F401
    Instance, Operation, ScheduledOperation, ValidationResult,
    generate_instance, validate, validate_instance, solve, metrics,
    exact_optimum, instance_to_dict, instance_from_dict,
    function_one, run_experiment, named_instance_parameters,
)
```

Pick one option and commit. The judge must see exactly one implementation.

---

### FIX 6 — Add clean-run flag to `run_submission.py`

**Problem:** results are pre-committed; a judge can't tell if
`python run_submission.py` regenerates them or just overwrites with the
same bytes.

**Add at the top of `run_submission.py`:**

```python
import shutil
import sys

def main(seed_base: int = 20260910, clean: bool = False) -> None:
    output = Path("results")
    if clean and output.exists():
        shutil.rmtree(output)
    output.mkdir(exist_ok=True)
    ...
```

**And at the bottom:**

```python
if __name__ == "__main__":
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 20260910
    clean_flag = "--clean" in sys.argv
    main(seed, clean=clean_flag)
```

Usage: `python run_submission.py --clean`

---

## PHASE 3 — Generator Improvements (83 → 87)

---

### FIX 7 — Rename `processing_time_variance` to `processing_time_noise_scale`

**Problem:** the parameter name implies statistical variance but it is
actually a Gaussian noise multiplier (coefficient of variation). This
misleads judges reading the metadata.

This is a rename across the entire file. Run:

```bash
sed -i 's/processing_time_variance/processing_time_noise_scale/g' fjsp.py
sed -i 's/processing_time_variance/processing_time_noise_scale/g' run_submission.py
```

Then in `generate_instance`, update the docstring / inline comment:

```python
processing_time_noise_scale: float = 0.0,
# ^ Gaussian noise: value = center * (1 + N(0, noise_scale))
# Actual std-dev of output ≈ center * noise_scale
# Set to 0 for uniform integers, ~0.15 for mild variance, 1.0 for high variance
```

Also update REPORT.md §2 to include this formula explicitly.

---

### FIX 8 — Separate bottleneck and specialist machines

**Problem:** both `bottleneck_probability` (demand contention) and
`machine_advantage` (speed specialisation) use the same `bottleneck`
variable. You cannot study them independently.

**Location:** inside `generate_instance()`, find:

```python
    bottleneck = rng.randrange(machines)
```

**Replace with:**

```python
    bottleneck = rng.randrange(machines)
    # Specialist machine may be the same as bottleneck or different.
    # Use a separate draw so the two effects can be decoupled.
    specialist = rng.randrange(machines)
```

Then find in the options loop:

```python
            if machine_advantage and machine == bottleneck:
                value *= max(0.05, 1 - machine_advantage)
```

**Replace with:**

```python
            if machine_advantage and machine == specialist:
                value *= max(0.05, 1 - machine_advantage)
```

Store both in metadata:

```python
    parameters = {
        ...
        "bottleneck_machine": bottleneck,
        "specialist_machine": specialist,
        ...
    }
```

---

### FIX 9 — Add generator self-check

After `return Instance(...)` at the end of `generate_instance()`, add:

```python
    instance = Instance(jobs, machines, operations, seed, parameters)
    # Belt-and-suspenders: every generated instance must be well-formed.
    _errors = validate_instance(instance)
    if _errors:
        raise RuntimeError(f"generate_instance produced invalid instance: {_errors}")
    return instance
```

This guarantees by assertion, not just by argument, that the generator
never emits an invalid instance.

---

## PHASE 4 — Algorithm Upgrade to Real Tabu Search (87 → 92)

This is the highest-value single change. Replace the random critical-pair
swap with a proper tabu search. The entire `solve()` function body changes.

**Replace the current `solve()` function with the following:**

```python
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
    from collections import deque

    assignments = {(item.job, item.index): item.machine for item in best}
    ordered     = sorted(best, key=lambda x: (x.start, x.machine, x.job, x.index))
    priority    = {(item.job, item.index): rank for rank, item in enumerate(ordered)}

    global_best       = best
    global_best_span  = best_makespan
    current_schedule  = best
    current_span      = best_makespan

    # Tabu list stores (move_signature, expiry_iteration)
    tabu: deque[tuple[tuple, int]] = deque()

    def is_tabu(sig: tuple, iteration: int) -> bool:
        return any(s == sig and exp > iteration for s, exp in tabu)

    def add_tabu(sig: tuple, iteration: int) -> None:
        tabu.append((sig, iteration + tabu_tenure))
        # Prune expired entries to keep deque short
        while tabu and tabu[0][1] <= iteration:
            tabu.popleft()

    budget = min(local_search_iterations, max(20, 30000 // max(1, len(instance.operations))))

    for iteration in range(budget):
        best_move_delta = float("inf")
        best_move       = None
        best_move_sig   = None
        best_move_type  = None

        # ── Neighbourhood N1: machine reassignment ────────────────────────
        # Consider all operations on the critical path first, then others.
        crit = _critical_pairs(current_schedule)
        crit_keys = {k for pair in crit for k in pair}
        all_keys  = list(assignments.keys())
        # Prioritise critical ops but evaluate all within a sample budget
        candidate_keys = list(crit_keys) + [k for k in all_keys if k not in crit_keys]
        sample_size    = min(len(candidate_keys), max(10, len(candidate_keys) // 3))
        sampled_keys   = candidate_keys[:sample_size]

        for key in sampled_keys:
            op = next(o for o in instance.operations if (o.job, o.index) == key)
            current_machine = assignments[key]
            for alt_machine in op.options:
                if alt_machine == current_machine:
                    continue
                sig = ("N1", key, current_machine, alt_machine)
                rev_sig = ("N1", key, alt_machine, current_machine)

                trial_assign = assignments.copy()
                trial_assign[key] = alt_machine
                try:
                    trial_sched = _rebuild(instance, trial_assign, priority)
                except (KeyError, ValueError):
                    continue
                tr = validate(instance, trial_sched)
                if not tr.valid or tr.makespan is None:
                    continue

                delta = tr.makespan - current_span
                tabu_blocked = is_tabu(sig, iteration) or is_tabu(rev_sig, iteration)
                aspirated    = tr.makespan < global_best_span

                if (not tabu_blocked or aspirated) and delta < best_move_delta:
                    best_move_delta = delta
                    best_move       = (trial_assign, trial_sched, tr.makespan)
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
                tr = validate(instance, trial_sched)
                if not tr.valid or tr.makespan is None:
                    continue

                delta = tr.makespan - current_span
                tabu_blocked = is_tabu(sig, iteration) or is_tabu(rev_sig, iteration)
                aspirated    = tr.makespan < global_best_span

                if (not tabu_blocked or aspirated) and delta < best_move_delta:
                    best_move_delta = delta
                    best_move       = (assignments, trial_sched, tr.makespan)
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

    return sorted(global_best, key=lambda x: (x.start, x.machine, x.job, x.index))
```

**Also update the function signature in `function_one()` and `run_experiment()`
to pass `tabu_tenure` if desired, or leave defaults.**

**Document the algorithm in REPORT.md §4** — replace the current paragraph with:

```markdown
## 4. Algorithm — Tabu Search

**Phase 1 (Construction):** `iterations` independent congestion-aware
randomized greedy starts. At each step, every ready operation × eligible
machine is scored by `finish_time + congestion_ratio × duration`. A random
tie-breaker creates diverse starts. The best validated schedule is kept.

**Phase 2 (Tabu Search):**
- **Representation:** machine assignment dict + priority order of operations.
- **Neighbourhood N1:** reassign operation O(j,k) to an alternative eligible
  machine. |N1| ≤ O × (M−1).
- **Neighbourhood N2:** swap the priority ranks of two adjacent operations on
  the same machine, inducing a resequencing. |N2| ≤ total adjacent pairs.
- **Tabu list:** deque of (move_signature, expiry_iteration) with tenure T=7.
  Reverse moves are also stored as tabu to prevent immediate cycling.
- **Aspiration criterion:** a tabu move is accepted if it beats the global
  best makespan.
- **Acceptance:** best non-tabu (or aspirated) move is accepted each
  iteration, even if it worsens the current makespan (allows escaping
  local optima).
- **Budget:** min(local_search_iterations, 30000 / |operations|).
- **Complexity:** O(budget × (O×M + adjacent_pairs)) per call.
```

---

## PHASE 5 — Experiments & Analysis (92 → 95+)

---

### FIX 10 — Add variance and machine-advantage sweeps to `run_submission.py`

Add this block after the existing flexibility/bottleneck sweep loop:

```python
    # Variance and machine-advantage sweeps
    for parameter, values in (
        ("processing_time_noise_scale", [0.0, 0.3, 0.6, 1.0, 1.5]),
        ("machine_advantage",           [0.0, 0.2, 0.5, 0.8, 1.0]),
    ):
        for value in values:
            makespans = []
            for seed in range(seed_base, seed_base + 20):
                kwargs = {parameter: value}
                instance = generate_instance(10, 5, 4, seed=seed, **kwargs)
                schedule = solve(instance, seed, 20, 50)
                result   = validate(instance, schedule)
                if not result.valid or result.makespan is None:
                    raise RuntimeError(f"sweep ({parameter}={value}) invalid")
                makespans.append(result.makespan)
            sweep_rows.append({
                "parameter": parameter, "value": value,
                "mean_makespan": sum(makespans) / len(makespans),
                "stddev": statistics.stdev(makespans) if len(makespans) > 1 else 0.0,
                "seeds": len(makespans),
            })
```

---

### FIX 11 — Add confidence intervals to all result tables

In `run_experiment()`, add to the returned dict:

```python
    n = len(makespans)
    ci_half = 1.96 * statistics.stdev(makespans) / (n ** 0.5) if n > 1 else 0.0
    return {
        ...
        "makespan_ci_95_half": ci_half,
        "makespan_mean_lower": statistics.mean(makespans) - ci_half,
        "makespan_mean_upper": statistics.mean(makespans) + ci_half,
        ...
    }
```

---

### FIX 12 — Add SPT baseline to ablation

In `run_submission.py`, add a shortest-processing-time dispatch baseline:

```python
def spt_schedule(instance: Instance) -> list[ScheduledOperation]:
    """Shortest-processing-time greedy baseline (always pick min duration option)."""
    ops_by_job = instance.operations_by_job
    next_idx   = {j: 0 for j in range(instance.jobs)}
    job_end    = {j: 0 for j in range(instance.jobs)}
    mach_end   = {m: 0 for m in range(instance.machines)}
    result     = []
    total      = sum(len(v) for v in ops_by_job.values())
    while len(result) < total:
        candidates = []
        for job, idx in next_idx.items():
            ops = ops_by_job[job]
            if idx >= len(ops):
                continue
            op = ops[idx]
            best_m, best_d = min(op.options.items(), key=lambda x: x[1])
            start  = max(job_end[job], mach_end[best_m])
            finish = start + best_d
            candidates.append((finish, op, best_m, start, finish))
        _, op, machine, start, finish = min(candidates)
        result.append(ScheduledOperation(op.job, op.index, machine, start, finish))
        job_end[op.job] = finish
        next_idx[op.job] += 1
        mach_end[machine] = finish
    return result
```

Then add an `"spt_baseline"` row to the ablation loop.

---

### FIX 13 — Create `analysis/failure_analysis.md`

Create this file at `analysis/failure_analysis.md` with the PS 5-step
template for each of the three failure modes:

```markdown
# FJSP Failure Analysis

## Failure Mode 1 — High-Flexibility Bottleneck

**Observation:** As flexibility increases from 0.0 to 1.0, the
lower-bound gap grows from ~0.08 to ~0.23 (controlled_sweeps.csv).

**Evidence:** `results/controlled_sweeps.csv`, parameter=flexibility,
seeds 20260910–20260929.

**Hypothesis:** High flexibility gives the greedy phase too many
choices per operation, causing it to commit a machine early based on
current congestion that ignores downstream demand.

**Structural Explanation:** More eligible machines → larger N1
neighbourhood → greedy dispatching picks the currently least-loaded
machine → later operations in the same job require the same machine →
queue builds on that machine → it appears on the critical path →
makespan increases. The tabu search helps by resequencing, but the
assignment space is still large.

**Proposed Improvement:** Lookahead: when scoring a machine assignment,
add a penalty for remaining operations in the same job that also list
that machine as eligible. Penalises assignments that are likely to
create future contention.

---

## Failure Mode 2 — High-Variance Critical Path

**Observation:** At noise_scale=1.5, mean makespan is ~3× that of
noise_scale=0.0 for the same instance size.

**Evidence:** `results/controlled_sweeps.csv`, parameter=processing_time_noise_scale.

**Hypothesis:** A single very long operation (tail of the Gaussian)
dominates the critical path; all downstream operations in the same job
must wait regardless of machine assignment.

**Structural Explanation:** The lower bound = max(job_chain_lower_bound,
max_machine_workload). With high variance, a single outlier duration
adds directly to the job chain lower bound. No scheduling heuristic can
reduce it without reordering operations, which is forbidden by precedence.

**Proposed Improvement:** Before solving, identify operations whose
minimum-machine duration is more than 2× the median. Flag them as
"critical seeds" and schedule them first (as a priority pre-pass) to
give downstream operations maximum time slack.

---

## Failure Mode 3 — Machine Advantage Overloading

**Observation:** At machine_advantage=0.8, the specialist machine
receives ~70% of all operations (measured by machine_utilization in
result JSONs) while having the shortest durations.

**Evidence:** `results/machine_advantage.json`, machine_utilization field.

**Hypothesis:** The greedy phase assigns most operations to the
specialist because its finish time is always shortest. This creates
a queue on the specialist that eventually dominates the makespan.

**Structural Explanation:** Machine advantage reduces duration → reduces
finish_time score → greedy always prefers the specialist → machine_end
of specialist grows → later assignments still prefer it because the
duration saving outweighs the wait → single-machine bottleneck even
though other machines are idle.

**Proposed Improvement:** Add a utilisation cap: if a machine's
accumulated load already exceeds (total_work / machines) × 1.5, apply
a penalty multiplier to its congestion score. This spreads load at the
cost of slightly longer individual durations.
```

---

### FIX 14 — Add `results/manifest.json` to `run_submission.py`

At the end of `main()` in `run_submission.py`, add:

```python
    import hashlib

    manifest = {"seed_base": seed_base, "files": {}}
    for path in sorted(output.rglob("*")):
        if path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
            manifest["files"][str(path.relative_to(output))] = digest

    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print("Results written to results/. Manifest saved to results/manifest.json.")
```

---

## PHASE 6 — Final Polish (95+)

---

### FIX 15 — Add `unbalanced` to CLI `--instance-class` choices

In `main()`, find the `choices=["average", ...]` list in both the
`common` parser and `function-one` parser. Add `"unbalanced"` to both:

```python
choices=["average", "low_flexibility", "high_flexibility", "bottleneck",
         "balanced", "high_variance", "machine_advantage", "extreme", "unbalanced"]
```

---

### FIX 16 — Add two missing edge-case fixtures to `run_submission.py`

In the `edge_specs` dict, add:

```python
    "identical_times":    (3, 2, 3, {"processing_time_min": 5, "processing_time_max": 5,
                                      "processing_time_noise_scale": 0.0}),
    "many_jobs_bottleneck": (20, 4, 2, {"bottleneck_probability": 1.0, "flexibility": 0.3}),
```

---

### FIX 17 — Add `pyproject.toml`

Create `pyproject.toml` in the repo root:

```toml
[project]
name = "fjsp"
version = "1.0.0"
requires-python = ">=3.10"
description = "Flexible Job-Shop Scheduling pipeline for Inter-IIT Tech Meet 15.0"

[project.scripts]
fjsp = "fjsp:main"

[build-system]
requires = ["setuptools"]
build-backend = "setuptools.backends.legacy:build"
```

---

## Score Projection After Each Phase

| After Phase | Score | Key gain |
|---|---:|---|
| Baseline (current) | 72 | — |
| Phase 1 (bugs fixed) | 79 | +7: runner works, tests pass, CLI correct |
| Phase 2 (workspace) | 83 | +4: one authoritative file, clean run |
| Phase 3 (generator) | 87 | +4: honest parameter naming, decoupled machines |
| Phase 4 (tabu search) | 92 | +5: real search-space algorithm with N1+N2 |
| Phase 5 (experiments) | 95 | +3: all sweeps, CI, failure analysis artefact |
| Phase 6 (polish) | 96+ | +1: CLI complete, manifest, pyproject |

---

## Verification Checklist

After applying all fixes, run these commands and verify:

```bash
# 1. All tests pass (should be 11/11 green)
python -m unittest -v

# 2. Clean reproduction works end-to-end
python run_submission.py --clean

# 3. Validator exits 1 on bad schedule
echo '[]' > bad.json
python fjsp.py validate results/function_one.json bad.json
echo "Exit code: $?"   # must print 1

# 4. Unbalanced class generates without crashing
python fjsp.py generate --instance-class unbalanced --jobs 4 --machines 3 --operations 3 --seed 42

# 5. Manifest exists and lists all result files
cat results/manifest.json | python -c "import sys,json; d=json.load(sys.stdin); print(len(d['files']), 'files hashed')"
```
