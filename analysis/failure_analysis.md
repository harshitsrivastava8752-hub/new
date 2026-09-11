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
