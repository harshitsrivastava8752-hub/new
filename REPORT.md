# Flexible Job-Shop Scheduling — Final Report

## 1. Scope and reproducibility

This submission implements the required pipeline:

`Generate -> Validate -> Solve -> Stress Test -> Analyze -> Improve`

It has no third-party runtime dependencies and targets Python 3.10+. The
command `python run_submission.py` regenerates all files in `results/`.
Experiments use ten independent seeds (`20260910` through `20260919`) and
record generator settings, algorithm settings, runtime, feasibility, makespan,
utilization, critical-path lower bound, and lower-bound gap.

## 2. Instance generator

An instance stores contiguous job and machine IDs, an ordered operation list,
eligible machine sets, processing times, seed, generator parameters, and named
instance class. A job may have a fixed operation count or a `(minimum,
maximum)` range. For each operation, the generator samples a set of
`round(1 + flexibility * (machines - 1))` distinct machines, always at least
one. A bottleneck machine can be forcibly included with the configured
probability.

Processing times are positive integers. With zero variance, they are sampled
uniformly in the requested range. With non-zero variance, a uniformly sampled
centre is multiplied by a Gaussian factor and clamped to the positive range.
Machine advantage shortens times on the selected specialist machine. These
choices are made by a local `random.Random(seed)`, so generation is exactly
reproducible and never changes global random state.

Named classes map to concrete stress conditions: `low_flexibility`,
`high_flexibility`, `bottleneck`, `balanced`, `high_variance`,
`machine_advantage`, and `extreme`. Every operation samples at least one
machine and every chosen machine receives exactly one positive finite duration;
therefore every generated instance is feasible by construction.

## 3. Independent validation environment

`validate(instance, schedule)` does not use solver state. It rejects missing,
duplicate, unknown, ineligible, malformed, negative, incorrectly timed, or
overlapping operations. It also checks the precedence chain independently.
Malformed records are rejected without exceptions, and the CLI provides a
standalone referee command: `python fjsp.py validate instance.json
schedule.json`.
For valid schedules, `metrics` reconstructs job completion times, machine
utilization, the actual schedule critical path (including job and machine
sequence edges), a safe lower bound, and the lower-bound gap.

## 4. Algorithm

The solver is a randomized greedy multi-start dispatching heuristic followed by
a bounded critical-machine neighborhood search. At each construction step it
considers every currently ready operation and eligible machine. The primary
score is earliest resulting finish time plus a congestion penalty based on
accumulated machine load; a random tie-breaker creates independent starts. The
improvement phase prioritizes adjacent operations on currently used machines,
tries alternative eligible machines, rebuilds the schedule, and accepts only
validated makespan improvements. The best validated schedule across starts is
returned. The `function-one` command exposes the complete first milestone as a
single JSON artifact containing instance, schedule, validation, metrics, and
algorithm configuration.

The representation is a list of `(job, operation, machine, start, end)`.
The search space consists of machine assignments and the induced order of
ready operations. The objective is makespan. With `I` starts, `O` operations,
and `M` machines, construction is approximately `O(I * O^2 * M)` in this
straightforward implementation; memory is `O(O + M)`.

This approach intentionally prioritizes explainability and valid schedules over
claiming optimality. `results/ablation.csv` measures the benefit of the local
search against the multi-start constructor alone.

## 5. Experiments and failure analysis

The JSON files in `results/` contain the complete per-seed evidence. The
experiment matrix covers normal, routing-constrained, highly flexible,
bottleneck-heavy, balanced, high-variance, specialized-machine, and extreme
instances. It also records small/large dimensions through the CLI options.
`controlled_sweeps.csv` isolates flexibility and bottleneck probability over
20 seeds per setting. `exact_small_instances.json` compares the heuristic with
an exhaustive optimum on ten instances of six operations.
`ablation.csv` compares the solver with and without local search, and
`instances/edge_cases/` contains reproducible hand-built stress fixtures.
`function_one.json` is the one-command first-milestone artifact: a generated
instance, candidate schedule, independent validation result, metrics, and
algorithm configuration in one file.

The controlled sweep found mean makespan decreasing from 150.45 at zero
flexibility to 44.80 at total flexibility in this fixed-size setting. This is
an observed result, not a universal claim: extra routing choices help here
because processing times are heterogeneous and the solver can spread work.
Bottleneck probability remained comparatively stable (61.2--65.2 mean
makespan), showing that the current instance size and congestion penalty absorb
much of that stress. The tiny exact benchmark had a 12.0% mean optimality gap
and reached the optimum on 2 of 10 seeds; this is the honest quality baseline
for the heuristic.
The ablation also provides a direct improvement check: on the 20-seed average
set, multi-start construction averaged 67.15 makespan units, while adding
local search averaged 64.40, a 4.1% improvement. This supports retaining the
additional search budget rather than presenting it as an unmeasured
complexity.

The checked-in run produced this aggregate snapshot (10 seeds per class):

| Class | Average makespan | Average lower-bound gap |
|---|---:|---:|
| average | 102.3 | 0.162 |
| balanced | 94.6 | 0.168 |
| bottleneck | 100.4 | 0.202 |
| extreme | 6835.8 | 0.146 |
| high_flexibility | 74.2 | 0.175 |
| high_variance | 182.3 | 0.241 |
| low_flexibility | 246.3 | 0.229 |
| machine_advantage | 55.7 | 0.124 |

Expected structural failure mode: high-flexibility bottleneck instances can
produce a larger lower-bound gap than low-flexibility instances. More eligible
machines enlarge the assignment search space; the greedy method commits early
using current finish time, while a later operation may require the same
machine. That creates queueing on a bottleneck and increases waiting on the
critical path. The evidence to inspect is the per-class `average_lower_bound_gap`
and `machine_utilization` in the result files.

Other failure modes are high-variance operations dominating the critical path
and machine advantage causing an attractive specialist machine to become
overloaded. The proposed improvements are congestion-aware lookahead,
critical-block swaps, and a bounded tabu or simulated-annealing phase. They
are deliberately proposals rather than hidden claims of optimality.

Hand-built correctness cases are covered in `test_fjsp.py`: one machine,
multiple jobs, overlap rejection, reproducibility, and solver validity. The
CLI can generate further edge cases with `--machines 1`, `--jobs 1`,
`--instance-class extreme`, or a large `--time-max`.

## 6. Submission contents

- `fjsp.py` — generator, validator, metrics, solver, and CLI.
- `test_fjsp.py` — correctness and invalid-schedule tests.
- `run_submission.py` — reproducible experiment runner.
- `results/*.json` — generated aggregate and per-seed evidence.
- `README.md` — usage and project overview.
