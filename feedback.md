# FJSP Pipeline — Independent Judge Audit
**Repo:** https://github.com/harshitsrivastava8752-hub/new  
**Auditor:** Senior OR / Algorithms Engineer (independent, from-scratch read)  
**PS Reference:** Inter-IIT Tech Meet 15.0 Prepathon — Algorithms (FJSP)  
**Audit Date:** 11 September 2026  

---

## EXECUTIVE VERDICT

The submission is a single-file monolith (`fjsp.py` / `fjsp_monolith_backup.py`) rather
than the modular package the PS pipeline implies. Despite that structural mismatch, the
core logic is **functionally sound, honestly documented, and genuinely self-consistent**.
The generator, validator, solver, and experiment runner are all present and correctly
cross-reference one another. The failure analysis in REPORT.md is causal and honest rather
than just a leaderboard table.

**Judge Score Estimate: 72 / 100**

The ceiling is not higher because: the PS asked for a modular pipeline with explicit
`generator/`, `environment/`, `algorithms/`, `experiments/`, `analysis/` folders —
this is one `.py` file. The algorithm is a greedy heuristic with limited neighbourhood
search, not a search-space algorithm (tabu, SA, GA). The failure analysis is brief and
lives in the report rather than a dedicated `analysis/` artefact. The test suite has
one critical false-positive bug. No standard benchmark instances are used.

---

## SCORE BREAKDOWN

| Category | Max | Score | Rationale |
|---|---:|---:|---|
| Generator Design & Instance Classes | 20 | 16 | Custom, seeded, 9 named classes, feasible by construction, variable-length jobs. Loses 4 pts: `processing_time_variance` is a noise scale not a variance; `unbalanced` class missing from the `class_settings` dict inside `generate_instance`; bottleneck and specialist machine are the same object. |
| Independent Validator Rigor & Diagnostics | 25 | 21 | Completely independent of solver state. Catches all 7 PS constraint classes. Loses 4 pts: one test (`test_enriched_validator_error_messages`) asserts `"Overlap on M0"` and `"J0-O0 [5, 12)"` format strings that do NOT appear in the actual validator output — this test will **fail**, contradicting the checklist. No malformed-JSON or NaN/infinity boundary tests. |
| Algorithm & Search Space Engineering | 20 | 13 | Multi-start randomized greedy with congestion penalty + bounded local search (critical-machine neighbour swap). Correct and reproducible. Loses 7 pts: not a search-space algorithm by PS standards (no tabu list, no SA, no population); the local search only tries machine-reassignment, never operation-resequencing; no baseline comparison; `exact_optimum` branch-and-bound is correct but limited to 9 operations and used only for reporting; no documented neighbourhood structure. |
| Experiments, Edge Cases & Causal Failure Analysis | 25 | 16 | 10 seeds × 9 classes, ablation (greedy vs greedy+LS), controlled sweeps over flexibility and bottleneck probability, exact-small comparison, 5 hand-built edge fixtures. REPORT.md has two causal failure modes with structural explanation and proposed improvement. Loses 9 pts: failure analysis is ~10 lines in a 142-line report, not a dedicated `analysis/` artefact; no per-class machine utilisation plots or convergence curves; no confidence intervals; the "unbalanced" class experiment runs but the class is not handled in `generate_instance`'s `class_settings` (see generator bug below); no extreme single-machine / extreme time-gap fixtures actually exercised by a printed result table. |
| Reproducibility & Pipeline Integration | 10 | 6 | Seed-based reproduction works. `run_submission.py` regenerates all result files. Single command. Loses 4 pts: the PS pipeline is Generate → Validate → Solve → Stress Test → Analyze → Improve — there is no `analysis/` folder, no `environment/` folder, no `algorithms/` folder; `fjsp_monolith_backup.py` is a duplicate that creates judge ambiguity; no `pyproject.toml` or clean entrypoint contract; results directory is pre-committed, making it unclear whether `run_submission.py` overwrites them or appends. |
| **Total** | **100** | **72** | Solid functional baseline; structural gaps and one failing test prevent a shortlist score. |

---

## STEP 1 — PIPELINE & WORKSPACE INSPECTION

### Required pipeline stages vs actual implementation

| PS Stage | Expected location | Actual location | Status |
|---|---|---|---|
| Generate | `generator/` | `fjsp.py::generate_instance()` | ✅ Present, wrong folder |
| Validate | `environment/validator.py` | `fjsp.py::validate()` + `validate_instance()` | ✅ Present, wrong folder |
| Solve | `algorithms/solver.py` | `fjsp.py::solve()` | ✅ Present, wrong folder |
| Stress Test | `experiments/runner.py` | `run_submission.py` + `fjsp.py::run_experiment()` | ✅ Present, partially |
| Analyze | `analysis/` | REPORT.md §5 only | ⚠️ No dedicated artefact |
| Improve | improvement operators | critical-machine swap inside `solve()` | ⚠️ Embedded in solver, undocumented as separate stage |

### Workspace problems

1. **`fjsp_monolith_backup.py` is identical to `fjsp.py`** (same 679 lines, same content).
   A judge seeing two authoritative-looking files must guess which one is correct.
2. **`fjsp/` directory exists but is unexplored**. The README says `from fjsp import ...`
   but the repo root also has `fjsp.py`. The test file imports `from fjsp import ...`
   which resolves to the `fjsp/` package if it has an `__init__.py`, or falls back to
   `fjsp.py` on some Python versions. This is a silent ambiguity risk.
3. **`__pycache__/` is committed**. Minor but avoidable noise.
4. **No `.github/actions` or CI**. Test-pass claim in checklist is unverified by
   automation.

---

## STEP 2A — GENERATOR AUDIT

### What is correctly implemented

- `random.Random(seed)` local instance — never touches global RNG state. ✅
- Contiguous job/operation IDs. ✅
- `E(j,k)` always non-empty (`option_count = max(1, ...)`). ✅
- Durations are `max(1, int(round(...)))` — always strictly positive integers. ✅
- Linear job precedence is enforced by construction (loop `for index in range(count)`). ✅
- `processing_time_variance` triggers Gaussian noise; zero gives uniform integers. ✅
- All 9 named classes have `named_instance_parameters()` presets. ✅
- Metadata stored in `instance.parameters`. ✅

### Generator deficiency 1 — CRITICAL BUG: `unbalanced` class missing from `class_settings`

Inside `generate_instance()`, the `class_settings` dict is:

```python
class_settings = {
    "low_flexibility": ...,
    "high_flexibility": ...,
    "bottleneck": ...,
    "high_variance": ...,
    "machine_advantage": ...,
    "extreme": ...,
    "balanced": ...,
    "average": {},
    "small": {},
    "large": {},
}
```

**`unbalanced` is not in this dict.** The guard `if instance_class not in class_settings`
will raise `ValueError("unknown instance class: unbalanced")` for any call that passes
`instance_class="unbalanced"`.

However, `run_submission.py` calls `run_experiment(args)` with `instance_class="unbalanced"`,
and `run_experiment` calls `named_instance_parameters(instance_class)` — which DOES have
`unbalanced` in its preset dict — but then passes `instance_class=name` to
`generate_instance()`, which will raise. This means **`python run_submission.py` will
crash** unless the submitted results pre-exist (which they do, as committed files).
The checklist claims the reproduction command works on a clean checkout — it does not.

**Fix:**
```python
"unbalanced": {},   # add to class_settings dict inside generate_instance()
```
and then handle variable `operations_per_job` for unbalanced (currently the preset in
`named_instance_parameters` doesn't override `operations_per_job`, so the caller must
pass a tuple).

### Generator deficiency 2 — `processing_time_variance` is a noise scale, not a variance

The code applies:
```python
value = center * (1 + rng.gauss(0, processing_time_variance))
```
This is a relative Gaussian noise scale (coefficient of variation). The PS parameter is
named `processing_time_variance`. The statistical variance of the output distribution is
`(center * processing_time_variance)^2`, not `processing_time_variance` itself.
A judge reading `"processing_time_variance": 0.15` in the metadata expects the variance
to be 0.15, not the noise multiplier.

**Fix:** Rename the parameter to `processing_time_noise_scale` or document the
distribution explicitly in REPORT.md with its mean and actual variance formula.

### Generator deficiency 3 — Bottleneck and specialist machines are the same

`bottleneck` (used for forced inclusion via `bottleneck_probability`) and `machine_advantage`
(used for faster processing) both reference `bottleneck = rng.randrange(machines)` — the
same variable. It's impossible to test "high demand on machine X but speed advantage on
machine Y" independently.

### Generator deficiency 4 — `class_settings` overrides ignore caller's value for `processing_time_max`

The code does:
```python
processing_time_max = max(processing_time_max, settings.get("processing_time_max", processing_time_max))
```
This means a caller passing `processing_time_max=5000` with `instance_class="extreme"` will get
`max(5000, 10000) = 10000`, silently ignoring the caller's value. The stored metadata
records the caller's original `processing_time_max` before this override, so the stored
parameters do not reflect the actual generation parameters.

---

## STEP 2B — INDEPENDENT VALIDATOR AUDIT

### Independence confirmation

`validate(instance, schedule)` reads only `instance.operations` and the submitted
`schedule` list of `ScheduledOperation` records. It never calls `solve()`, never reads
solver state, priority maps, or assignment dicts. **Independence requirement: satisfied.**

### Constraint coverage

| PS Constraint | Validator check | Status |
|---|---|---|
| Machine assignment (exactly one, must be in E(j,k)) | `operation.options.get(item.machine)` | ✅ |
| Duration correctness C(j,k) = S + p(j,k,m) | `item.end - item.start != duration` | ✅ |
| Job precedence S(j,k+1) ≥ C(j,k) | `previous.end > current.start` | ✅ |
| Machine non-overlap | `previous.end > current.start` on sorted machine list | ✅ |
| Non-preemption | Implied by duration correctness + no split records | ✅ (implicit) |
| Non-negative time | `item.start < 0 or item.end < item.start` | ✅ |
| Completeness (all ops exactly once) | `seen` set + missing ops check | ✅ |
| Duplicate operations | `key in seen` | ✅ |
| Malformed records | type checks on all fields | ✅ |

### Validator deficiency 1 — CRITICAL: Test `test_enriched_validator_error_messages` will FAIL

The test asserts:
```python
self.assertIn("Overlap on M0", overlap_errors[0])
self.assertIn("J0-O0 [5, 12)", overlap_errors[0])
self.assertIn("J1-O0 [8, 15)", overlap_errors[0])
```

The actual validator error message is:
```python
errors.append(f"overlap on machine M{machine}")
```
(lowercase `"overlap on machine M{machine}"`, no interval coordinates)

The asserted strings `"Overlap on M0"` (capital O), `"J0-O0 [5, 12)"`, and
`"J1-O0 [8, 15)"` are **not produced** by the current `validate()` function.
This test will fail with `AssertionError`. The checklist says all tests pass — that is false.

**Fix:** Either update the validator to emit the enriched format:
```python
errors.append(
    f"Overlap on M{machine}: "
    f"J{previous.job}-O{previous.index} [{previous.start}, {previous.end})"
    f" and J{current.job}-O{current.index} [{current.start}, {current.end})"
)
```
or downgrade the test assertion to match the current format.

### Validator deficiency 2 — No malformed-JSON boundary tests

The test suite does not cover: NaN floats, booleans-as-integers (e.g. `True` for job=1),
string keys for machine IDs in imported JSON, or empty operation list with non-zero
`jobs`. The `validate_instance()` function partially handles these but is not exercised.

### Validator deficiency 3 — CLI validate command does not exit with code 1 on INVALID

`main()` prints "INVALID" and errors to stdout on failure, but exits normally (code 0).
A judge running automated verification would see exit code 0 even on invalid schedules.

---

## STEP 2C — ALGORITHM AUDIT

### What is implemented

**Phase 1: Congestion-aware randomized greedy multi-start**
- `iterations` independent construction passes (default 20)
- At each step: for every ready operation × eligible machine, compute
  `score = finish_time + congestion_ratio * duration`
- `congestion_ratio = machine_load[m] / total_load`
- Random tie-breaker ensures independent starts
- Best validated schedule kept

**Phase 2: Bounded critical-machine neighbourhood search**
- Identifies adjacent pairs on the same machine (`_critical_pairs`)
- Picks one pair at random; picks one of the two ops
- Tries a random alternative machine assignment
- Rebuilds with `_rebuild()` using the existing priority order
- Accepts only if validated makespan strictly improves
- Budget: `min(local_search_iterations, max(10, 20000 // len(operations)))`

### Algorithm deficiencies

**A. Not a search-space algorithm by PS standards**

The PS explicitly lists: "local search, simulated annealing, tabu search, GA, PSO, ACO,
MILP, CP-SAT, LNS, RL, GNNs, or hybrids." The implemented approach is a greedy
dispatching heuristic with a limited improvement move. It has no tabu list, no acceptance
criterion that allows uphill moves, no population, no systematic neighbourhood enumeration.
The PS says "at least one algorithm" — this barely qualifies. The improvement phase is
thin: it only retries machine assignments, never resequences operations.

**B. `_rebuild` uses a fixed priority order that ignores precedence feasibility**

`_rebuild` schedules operations in a fixed `priority` order (derived from the original
schedule's start-time ordering). When a machine reassignment changes start times, the
priority order may no longer reflect the earliest-available-first heuristic, leading to
suboptimal (though always feasible) schedules. The search is therefore not exploring the
full neighbourhood: it only finds improvements that happen to be reachable under the
original operation order.

**C. No baseline comparison in code**

The PS asks for evidence that the algorithm improves over a baseline. The ablation CSV
compares "greedy_multistart" (local_search=0) vs "greedy_plus_local_search" and finds
4.1% improvement. This is the right direction but the margin is very small and only one
dimension is varied. No "shortest processing time" or "longest remaining chain" dispatch
baseline exists.

**D. `exact_optimum` is correct but the bound is 9 operations**

The B&B `exact_optimum` is a clean implementation. However it is only tested on 3 jobs ×
2 machines × 2 ops/job = 6 operations. The PS asks for stress tests — a 9-op limit means
it can't verify anything beyond toy cases.

**E. `search_budget` computation can collapse to 10 for large instances**

For an instance with 200 operations: `min(100, max(10, 20000 // 200)) = min(100, 100) = 100`.
For 1000 operations: `min(100, max(10, 20)) = 20`. For 5000 operations: `min(100, 10) = 10`.
The local search essentially does nothing at scale. There is no documented runtime-budget
parameter exposed to the user.

---

## STEP 2D — FAILURE ANALYSIS & EDGE CASES AUDIT

### Edge fixtures present (`instances/edge_cases/`)

| Fixture | Config | Status |
|---|---|---|
| `single_machine` | 5 jobs, 1 machine, 3 ops, flexibility=0 | ✅ |
| `single_job` | 1 job, 4 machines, 4 ops, flexibility=1 | ✅ |
| `many_machines` | 3 jobs, 8 machines, 2 ops, flexibility=1 | ✅ |
| `extreme_gap` | 2 jobs, 2 machines, time range [1, 10000] | ✅ |
| `long_chain` | 2 jobs, 1 machine, 12 ops | ✅ |

**PS-required hand-built cases that are MISSING:**
- "many jobs with one bottleneck machine" (not a fixture, only generated randomly)
- "machine advantage" (not a fixture)
- "near-total / near-zero flexibility" (covered by high/low_flexibility classes but
  not as static hand-built fixtures with a known optimal)
- "identical processing times" (not present)

None of the edge fixtures are validated against a known optimum in a result table. They
are generated but not analysed.

### Failure analysis quality

REPORT.md §5 documents two structural failure modes:

**Mode 1 — High-flexibility bottleneck:**
> More eligible machines enlarge the assignment search space; the greedy method commits
> early using current finish time, while a later operation may require the same machine.

This correctly chains: high flexibility → large search space → early commitment →
downstream bottleneck → higher makespan. This is the required 5-step causal reasoning.
Evidence: `controlled_sweeps.csv` flexibility sweep. Proposed improvement: congestion-aware
lookahead. **Quality: good.**

**Mode 2 — High-variance critical path:**
> High-variance operations dominate the critical path.

This is stated but not evidenced with data — no sweep over `processing_time_variance`
is in `run_submission.py`. Evidence is absent. **Quality: asserted without data.**

**Mode 3 — Machine advantage overloading:**
> Machine advantage can cause an attractive specialist machine to become overloaded.

Again stated without a sweep over `machine_advantage`. **Quality: asserted without data.**

**Overall failure analysis rating: 2.5 / 5.** The causal writing for Mode 1 is correct.
Modes 2 and 3 lack supporting experiments. The write-up is ~10 lines in a combined report,
not a dedicated `analysis/` artefact. No observation → evidence → hypothesis → structural
explanation → proposed improvement table is actually filled out; it's summarised in prose.

---

## PIPELINE INTEGRITY GAPS

1. **`python run_submission.py` crashes on a clean checkout** due to the `unbalanced`
   class bug. Pre-committed results mask this.
2. **`from fjsp import ...`** in test_fjsp.py is ambiguous — resolves to either the `fjsp/`
   package or `fjsp.py` depending on Python path. If it resolves to the package, and the
   package's `__init__.py` re-exports everything from `fjsp.py`, this is fine; if not,
   tests will fail with `ImportError`.
3. **No `pyproject.toml` or `setup.py`**: the project cannot be installed as a package.
   `python -m fjsp` will not work unless `fjsp/` has a `__main__.py`.
4. **Results are pre-committed**: a judge running `python run_submission.py` cannot tell
   whether the output files are freshly generated or stale cached results.
5. **`fjsp_monolith_backup.py`** has no `__init__` exports and is never imported. It is
   dead code that creates confusion about which file is authoritative.
6. **No seed in `exact_optimum` results**: `exact_rows` reports `{"seed": seed}` but
   the instance is regenerated with `generate_instance(3, 2, 2, flexibility=.7, seed=seed)`
   — this is consistent. However no instance JSON is saved alongside the optimum table.

---

## REFACTORING ACTION PLAN FOR 90+ SCORE

### Priority 1 — Fix the breaking bugs (required for any honest score)

1. Add `"unbalanced": {}` to `class_settings` inside `generate_instance()`.
2. Fix `test_enriched_validator_error_messages`: update the validator to emit the
   enriched overlap message format (with coordinates), or update the test assertion
   to match the current format.
3. Make `main()` exit with code 1 when the schedule is INVALID.

### Priority 2 — Resolve structural / pipeline ambiguity

4. Delete `fjsp_monolith_backup.py` or clearly comment it as "deprecated".
5. Resolve the `from fjsp import ...` ambiguity: either make `fjsp/` the sole
   package with a proper `__init__.py`, or rename the package directory to avoid
   collision with `fjsp.py`.
6. Add a clean-output entrypoint: `python run_submission.py --clean` that deletes
   `results/` before regenerating.
7. Add `pyproject.toml` with `[project]` and `[project.scripts]`.

### Priority 3 — Strengthen the generator

8. Rename `processing_time_variance` → `processing_time_noise_scale` and document
   the actual output distribution.
9. Separate `bottleneck_machine` and `specialist_machine` into independent parameters.
10. Store effective parameters (post-override) in metadata, not just requested values.
11. Add generator self-check: call `validate_instance()` on every generated instance
    and raise if it fails (belt-and-suspenders guarantee).

### Priority 4 — Elevate the algorithm to PS standards

12. Implement a real tabu search: add a tabu list (deque of `(op, old_machine,
    new_machine)` tuples with tenure), aspiration criterion, and systematic
    neighbourhood enumeration (all swap/reassignment moves, not just random
    critical-pair picks).
13. Add operation resequencing moves: swap adjacent operations on the same machine.
14. Add a "shortest processing time" greedy dispatch baseline and compare.
15. Document neighbourhood size: with O operations and M machines, the full
    reassignment neighbourhood has O(O × M) candidates; enumerate them all with
    a budget cap.

### Priority 5 — Make the failure analysis award-grade

16. Add `results/variance_sweep.csv` and `results/machine_advantage_sweep.csv`
    mirroring the flexibility sweep, with 20 seeds each.
17. Add a dedicated `analysis/failure_analysis.md` with one section per failure mode,
    each following the PS 5-step template (Observation / Evidence / Hypothesis /
    Structural Explanation / Proposed Improvement).
18. Add confidence intervals (`mean ± 1.96 * stddev / sqrt(n)`) to all tables.
19. Generate at least one Gantt chart or utilisation bar from a checked-in seed's
    result JSON (can be ASCII art or a simple HTML table).
20. Add hand-built edge case with known optimum: 2 jobs × 1 machine × 3 ops with
    identical times → optimum = sum of all durations. Assert `exact_optimum` matches.

### Priority 6 — Reproducibility hardening

21. Hash every generated instance JSON and store in a `results/manifest.json`.
22. Record Python version in every result artefact.
23. Validate every edge fixture through the CLI validator in `run_submission.py`
    and record VALID/INVALID in the manifest.

---

## SUMMARY TABLE

| Finding | Severity | Component |
|---|---|---|
| `unbalanced` class raises ValueError in `generate_instance` | 🔴 Breaking | Generator |
| `test_enriched_validator_error_messages` will fail | 🔴 Breaking | Test Suite |
| `python run_submission.py` crashes on clean checkout | 🔴 Breaking | Runner |
| Ambiguous `from fjsp import` resolution | 🟠 High | Package Structure |
| `processing_time_variance` is mis-named (noise scale, not variance) | 🟠 High | Generator |
| Algorithm is greedy heuristic, not a search-space algorithm | 🟠 High | Algorithm |
| Failure modes 2 & 3 lack supporting experiments | 🟠 High | Analysis |
| Bottleneck/specialist machine coupling | 🟡 Medium | Generator |
| No dedicated `analysis/` folder | 🟡 Medium | Pipeline Structure |
| No CI / automated test run evidence | 🟡 Medium | Reproducibility |
| `main()` exits 0 on INVALID schedule | 🟡 Medium | Validator CLI |
| `search_budget` collapses to 10 at scale | 🟡 Medium | Algorithm |
| Results pre-committed (clean-run unclear) | 🟡 Medium | Reproducibility |
| No standard benchmark instances | 🟡 Medium | Experiments |
| Missing hand-built fixtures (identical times, many-jobs bottleneck) | 🟢 Low | Edge Cases |
| `fjsp_monolith_backup.py` dead code | 🟢 Low | Workspace Hygiene |
| No confidence intervals in result tables | 🟢 Low | Analysis |
