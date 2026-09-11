# FJSP Pipeline Audit — Inter-IIT / Prepathon Judge Review

## Executive verdict

The authoritative implementation is the package under `fjsp/`, not the
legacy root-level monolith/backup files. The package now has the requested
separable stages:

```text
fjsp/generator          Generate
fjsp/environment        Validate + Metrics
fjsp/algorithms         Solve + Improve
fjsp/experiments        Stress Test + Reproduce
fjsp/analysis           Failure Analysis
```

The implementation is functionally credible and substantially aligned with
the statement. I ran the test suite and targeted adversarial checks:

- **11/11 unit tests passed**
- all required named classes generated valid schedules
- deterministic regeneration held for repeated seeds
- overlap, precedence, ineligible-machine, duration, negative-time,
  duplicate, missing, and malformed-schedule cases were rejected
- variable-length jobs, one-machine, one-job, many-machine, high-variance,
  bottleneck, and extreme instances solved validly
- the package solver returned valid schedules on the tested stress cases

### Judge score estimate: **87/100**

This is a strong shortlist-level baseline. It is not yet a 95+ award-winning
submission because the evidence is mostly generated-instance evidence, the
experiment layer lacks statistical/benchmark depth, and a few engineering
details create avoidable judge risk.

## Score breakdown

| Category | Max | Score | Judge assessment |
|---|---:|---:|---|
| Generator Design & Instance Classes | 20 | 18 | Custom, seeded, feasible, variable-length generator with the required stress classes; metadata and parameter semantics need tightening. |
| Independent Validator Rigor & Diagnostics | 25 | 23 | Independent and comprehensive for the schedule model; JSON/API normalization and malformed-instance boundary behavior need more tests. |
| Algorithm & Search Space Engineering | 20 | 17 | Real critical-path-guided tabu search with swap, insertion, reassignment, and validated rebuilds; move quality and benchmark proof remain limited. |
| Experiments, Edge Cases & Causal Failure Analysis | 25 | 21 | Strong causal write-up and artifacts; lacks standard benchmark instances, confidence intervals, plots, and automated trace linkage. |
| Reproducibility & Pipeline Integration | 10 | 8 | Package pipeline and seeded runner are present; legacy duplicate implementations and missing clean packaging create ambiguity. |
| **Total** | **100** | **87** | **Strong functional submission; not yet award-winning evidence quality.** |

## 1. Pipeline and workspace inspection

### Stage mapping

| Required stage | Implementation | Status |
|---|---|---|
| Generate | `fjsp/generator/instance_generator.py` | Implemented |
| Validate | `fjsp/environment/validator.py` and `fjsp/model.py` | Implemented independently |
| Solve | `fjsp/algorithms/solver.py` | Implemented |
| Stress Test | `fjsp/experiments/runner.py`, `run_submission.py`, edge fixtures | Implemented, mostly script-driven |
| Analyze | `fjsp/environment/metrics.py`, `fjsp/analysis/failure_analysis.md` | Implemented |
| Improve | critical-path local search, N5-style swaps, insertion, reassignment, tabu list | Implemented |

The package layout is appropriate for judging. However, the workspace also
contains legacy root files such as `fjsp_monolith_backup.py`, root result
artifacts, caches, and the older `feedback.md`. A judge should not have to
guess which implementation is authoritative.

### Pipeline integrity risks

1. **Two implementations exist.** The package and legacy monolith can drift.
   The package is the one imported by `from fjsp import ...`, but this is not
   obvious from the top-level README.
2. **No explicit clean-entrypoint contract.** The package runner is usable, but
   there is no `pyproject.toml`, console script, or one documented clean
   command that creates a fresh output directory and verifies every artifact.
3. **Generated artifacts are not fully self-describing.** Results record seeds
   and solver settings, but do not store every generated instance inline or
   provide a manifest hash for every artifact.
4. **Stress execution is not fail-fast on all artifact classes.** The runner
   validates produced schedules, but it does not systematically run every
   checked-in edge fixture through a separate validator command and record a
   pass/fail matrix.

## 2. Part A — Generator audit

### What is correct

`generate_instance()` implements custom logic rather than dumping random
numbers:

- jobs and machines are configurable;
- operation counts may be fixed or sampled from a range;
- flexibility controls the number of eligible machines;
- bottleneck inclusion is probabilistic;
- processing times support range and Gaussian-noise controls;
- machine advantage changes processing time on the selected specialist;
- a local `random.Random(seed)` gives deterministic regeneration;
- operation/job/machine IDs are generated contiguously;
- every operation has at least one eligible machine;
- every selected-machine duration is a positive integer;
- each job is a strict linear chain with no branches.

The package defines the requested named classes:

```text
average
low_flexibility
high_flexibility
bottleneck
balanced
high_variance
machine_advantage
extreme
unbalanced
```

The adversarial class smoke test generated valid schedules for all nine classes.

### Generator deficiencies

#### A. `processing_time_range` is represented as two parameters

The statement names a processing-time range. The implementation exposes
`processing_time_min` and `processing_time_max`, which is functionally fine but
less directly aligned with the requested API.

**Fix:** accept both forms:

```python
processing_time_range=(1, 20)
processing_time_min=1
processing_time_max=20
```

Reject conflicting values explicitly.

#### B. Machine advantage and bottleneck are coupled

The same randomly selected machine is used as the bottleneck and specialist.
This makes it impossible to isolate:

- congestion caused by high demand,
- speed advantage caused by specialization.

**Fix:** generate separate `bottleneck_machine` and `specialist_machine`
parameters, with an optional mode where they intentionally coincide.

#### C. Metadata can be inaccurate for `unbalanced`

The `unbalanced` class overrides the effective operation-count range to
`(1, 8)`, but the stored `parameters["operations_per_job"]` can still contain
the caller’s original value. That weakens reproducibility/auditability.

**Fix:** store both:

```json
{
  "requested_operations_per_job": 5,
  "effective_operations_per_job": [1, 8]
}
```

#### D. Parameter semantics are not statistically calibrated

`processing_time_variance` is actually a Gaussian relative-noise scale:

```text
value = center * (1 + Gaussian(0, scale))
```

It is not the measured variance of the generated duration distribution.

**Fix:** rename it to `processing_time_noise_scale`, or define the
distribution mathematically and report observed mean/variance/CV in metadata.

#### E. Feasibility is guaranteed, but imported-instance validation is separate

Generation is safe by construction, and `validate_instance()` protects JSON
imports. This is good. The report should explicitly distinguish:

```text
generator guarantee != imported-file validation
```

That distinction matters in a referee environment.

## 3. Part B — Independent validator audit

### Independence

The validator reads only:

- the `Instance` definition;
- the submitted `ScheduledOperation` records.

It does not inspect solver assignments, priorities, tabu state, or search
metadata. This satisfies the independence requirement.

### Corruption tests

The following classes of corruption were exercised and rejected:

| Corruption | Result |
|---|---|
| Same-machine overlap | Rejected with machine and interval details |
| Job precedence violation | Rejected with predecessor/current operation details |
| Ineligible machine | Rejected with eligible-machine list |
| Wrong completion duration | Rejected with expected and observed durations |
| Negative start | Rejected with interval |
| Duplicate operation | Rejected |
| Missing operation | Rejected |
| Unknown operation | Rejected |
| `None`, string, dict schedule entries | Rejected without crashing |

The validator also checks completeness and returns a `ValidationResult` with
`valid`, `makespan`, and diagnostic errors.

### Remaining validator risks

1. **The Python API accepts only `ScheduledOperation` objects.** The CLI
   normalizes JSON dictionaries, but direct callers passing dictionaries to
   `validate()` receive “malformed entry” rather than field-level diagnostics.
   This is safe, but a reusable validator API would be stronger with one
   normalization layer shared by API and CLI.
2. **No explicit total-error summary.** The individual diagnostics are useful,
   but `error_count` and a stable machine-readable error code would improve
   automated judging.
3. **No explicit validator test for non-finite numeric input.** The dataclass
   validator rejects floats entirely, which is safe, but the test suite should
   explicitly cover `NaN`, infinity, booleans, and numeric strings.
4. **Validator assumes the `Instance` is valid.** This is reasonable when
   `instance_from_dict()` is used, but direct API callers can construct an
   invalid `Instance` manually. Add an optional instance preflight or document
   this contract clearly.

No core scheduling constraint was found to be silently accepted for a valid
instance and a typed schedule.

## 4. Part C — Algorithm and search-space audit

### Implemented design

The package solver has two phases:

1. **Congestion-aware randomized multi-start construction**
   - enumerate ready operation/machine pairs;
   - score earliest completion plus congestion;
   - choose with deterministic seeded tie-breaking.
2. **Critical-path-guided tabu improvement**
   - build the disjunctive graph;
   - compute a longest path;
   - extract critical blocks;
   - generate N5-style adjacent swaps;
   - generate front/back insertion moves;
   - generate alternative-machine reassignment moves;
   - rebuild semi-active schedules;
   - independently validate each candidate;
   - use tabu tenure and aspiration.

This explicitly handles the joint FJSP decision:

```text
machine assignment + operation sequencing
```

The `solver.py` module documents representation, neighborhood operators,
acceptance, and complexity. This is substantially stronger than a basic greedy
implementation.

### Algorithm weaknesses

#### A. Move operators are valid but incomplete

Insertion currently tries mainly front/back priority positions rather than every
feasible insertion slot on the relevant machine. That limits the neighborhood.

**Fix:** enumerate all insertion positions in the affected machine sequence,
then filter by precedence feasibility before rebuilding.

#### B. Tabu reverse-move handling should be explicit

The solver stores a move signature, but the implementation should clearly store
the reverse signature or a normalized move key with expiry. Otherwise the tabu
mechanism can prevent repeating the same move without fully preventing an
immediate reversal.

**Fix:** store:

```text
(operation, old_machine, new_machine, old_position, new_position)
```

and mark the exact inverse as tabu.

#### C. No public benchmark comparison

The exact solver is useful for tiny generated cases, but the project does not
compare against standard FJSP benchmark families or a recognized baseline such
as:

- earliest-finish greedy;
- shortest-processing-time dispatch;
- longest-remaining-chain dispatch;
- random feasible construction.

A judge cannot tell whether the local-search complexity materially improves
general solution quality beyond the own-generator distribution.

#### D. Critical-path metrics need a consistency assertion

The metrics module computes a graph critical path, while the solver computes a
critical path independently. Add a test that both implementations agree on a
set of hand-built schedules. This prevents silent divergence between analysis
and optimization.

#### E. Complexity is likely pessimistic in practice

The documented asymptotic complexity is reasonable, but repeated full rebuilds
and candidate validation can become expensive. Add scaling results at 100,
500, 1,000, and 5,000 operations and expose a bounded runtime mode.

## 5. Part D — Edge cases and failure analysis

### Edge cases present

The workspace includes fixtures for:

- one machine;
- one job;
- many machines;
- extreme processing-time gap;
- long precedence chains.

The generator and runner also cover:

- near-zero flexibility;
- near-total flexibility;
- bottleneck-heavy instances;
- high variance;
- machine advantage;
- unbalanced job lengths.

### Failure-analysis quality

`fjsp/analysis/failure_analysis.md` is the strongest part of the submission.
It follows the required causal structure:

1. Observation
2. Evidence
3. Hypothesis
4. Structural Explanation
5. Proposed Improvement

It connects:

- precedence-chain depth;
- disjunctive machine cliques;
- queue cascades;
- critical-path elongation;
- high-flexibility search-space growth;
- unbalanced job-chain delay.

It also names concrete operation coordinates, machines, intervals, and
candidate improvements. This is true structural reasoning rather than static
makespan logging.

### Failure-analysis risks

1. Several detailed schedule traces appear hand-authored. They should be
   generated directly from checked-in seeds and validated automatically.
2. The report claims quantitative improvement from tabu/critical-block search;
   every claimed number should point to a result artifact and command.
3. The analysis does not yet include confidence intervals or significance
   tests for the observed improvements.
4. There is no comparison to public benchmark instances, so structural claims
   may be specific to the custom generator.

**Failure-analysis depth rating: 4.5/5.**

The causal reasoning is excellent conceptually. The missing 0.5 is empirical
trace provenance and statistical support.

## 6. Pipeline integrity gaps

### Hardcoded or weakly exposed inputs

- `run_submission.py` hardcodes the main experiment dimensions and seed range.
- `function_one()` is configurable, but the full reproduction matrix is not
  exposed as a declarative configuration file.
- The runner does not hash or store every generated instance used by result
  rows.
- The CLI does not provide a single `reproduce` command that clears and
  rebuilds all outputs in a clean directory.

### Missing hooks

- no processing-time-range tuple API;
- no separate specialist/bottleneck machine hook;
- no runtime budget hook;
- no standard benchmark import hook;
- no confidence-interval/statistical-analysis hook.

### Solver-dependent validation

The validator itself is independent. The main risk is process integration:
experiment code calls the same package model and validator, but the
submission does not run an external referee process against every generated
schedule. Add a subprocess-level validator check for representative artifacts.

## 7. Refactoring action plan for a 95+ score

### Priority 1 — remove judge ambiguity

1. Delete or move the legacy monolith, backup files, caches, and stale root
   artifacts out of the submission path.
2. Make `fjsp/` the only implementation and add a top-level `reproduce.py`.
3. Add `pyproject.toml` or a minimal documented package entrypoint.
4. Make reproduction write to a clean timestamped/output directory and emit a
   manifest with seeds, parameters, solver configuration, Python version, and
   hashes.

### Priority 2 — strengthen generator science

5. Add `processing_time_range=(lo, hi)` while preserving min/max compatibility.
6. Separate bottleneck and specialist machines.
7. Store requested and effective parameters.
8. Add generator sanity checks for every emitted instance.
9. Add measured flexibility, eligibility imbalance, and processing-time
   distribution summaries to every result row.

### Priority 3 — strengthen the algorithm

10. Enumerate all feasible insertion positions, not only front/back.
11. Normalize tabu move signatures and explicitly tabu inverse moves.
12. Add a longest-remaining-chain dispatch baseline.
13. Add a random-feasible and earliest-finish baseline.
14. Compare all baselines and the final solver on the same instance seeds.
15. Add public FJSP benchmark import/evaluation if licensing permits.
16. Add a runtime budget and operation-count scaling table.

### Priority 4 — strengthen the referee boundary

17. Add a shared schedule JSON normalization function for both API and CLI.
18. Add structured error codes and `error_count`.
19. Add tests for NaN, infinity, booleans, strings, malformed JSON, invalid
    instance IDs, empty option sets, and duplicate machine keys.
20. Run the external CLI validator against every generated schedule artifact.

### Priority 5 — make analysis award-grade

21. Generate all failure-analysis traces from code, not hand-maintained text.
22. Add 30–50 seeds for primary sweeps.
23. Report mean, median, standard deviation, 95% confidence interval, best,
    worst, utilization, and lower-bound gap.
24. Add ablation tables for:
    - greedy;
    - multi-start;
    - critical-block swaps;
    - insertion;
    - reassignment;
    - tabu search.
25. Add convergence curves and parameter sensitivity.
26. Tie every report number to a JSON/CSV row and command.

## Final judge recommendation

**Current recommendation: shortlist / technical finalist, not yet winner.**

The project has the right problem model, a genuinely independent validator,
custom reproducible instance generation, a real critical-path tabu solver, and
unusually good causal failure-analysis writing. The main reasons it is below
95 are not basic correctness failures; they are evidence quality, package
ambiguity, custom-generator bias, and incomplete benchmark/statistical
validation.

Completing Priority 1–5 would plausibly move the submission to **94–96/100**.
The single highest-return improvement is a clean baseline/ablation/benchmark
matrix generated from one reproducible manifest, followed by deleting the
legacy duplicate implementation so the judge sees one authoritative system.
