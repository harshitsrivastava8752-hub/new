"""Generate the reproducible result bundle included with the submission."""

import argparse
import json
import csv
import statistics
from pathlib import Path

from fjsp import (exact_optimum, generate_instance, instance_to_dict,
                  function_one, run_experiment, solve, validate)


def main(seed_base: int = 20260910) -> None:
    output = Path("results")
    output.mkdir(exist_ok=True)
    (output / "function_one.json").write_text(
        json.dumps(function_one(instance_class="average", seed=seed_base), indent=2) + "\n",
        encoding="utf-8",
    )
    classes = ["average", "low_flexibility", "high_flexibility", "bottleneck",
               "balanced", "high_variance", "machine_advantage", "extreme",
               "unbalanced"]
    for name in classes:
        args = argparse.Namespace(
            jobs=12, machines=6, operations=5, flexibility=.5,
            time_min=1, time_max=30, variance=.15, bottleneck=.1,
            instance_class=name, seed=seed_base, iterations=30, repetitions=10,
            local_search=100,
        )
        result = run_experiment(args)
        (output / f"{name}.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    sweep_rows = []
    for parameter, values in (("flexibility", [0.0, .2, .4, .6, .8, 1.0]),
                              ("bottleneck_probability", [0.0, .2, .4, .6, .8, 1.0])):
        for value in values:
            makespans = []
            for seed in range(seed_base, seed_base + 20):
                kwargs = {parameter: value}
                instance = generate_instance(10, 5, 4, seed=seed, **kwargs)
                schedule = solve(instance, seed, 20, 50)
                result = validate(instance, schedule)
                if not result.valid or result.makespan is None:
                    raise RuntimeError("sweep generated an invalid schedule")
                makespans.append(result.makespan)
            sweep_rows.append({
                "parameter": parameter, "value": value,
                "mean_makespan": sum(makespans) / len(makespans),
                "stddev": (statistics.stdev(makespans) if len(makespans) > 1 else 0.0),
                "seeds": len(makespans),
            })
    with (output / "controlled_sweeps.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=sweep_rows[0])
        writer.writeheader()
        writer.writerows(sweep_rows)

    exact_rows = []
    for seed in range(10):
        instance = generate_instance(3, 2, 2, flexibility=.7, seed=seed)
        heuristic = validate(instance, solve(instance, seed, 30, 50)).makespan
        optimum = exact_optimum(instance)
        exact_rows.append({"seed": seed, "heuristic": heuristic, "optimum": optimum,
                           "gap": (heuristic - optimum) / optimum})
    (output / "exact_small_instances.json").write_text(
        json.dumps(exact_rows, indent=2) + "\n", encoding="utf-8"
    )

    ablation_rows = []
    for name, local_search in (("greedy_multistart", 0), ("greedy_plus_local_search", 100)):
        values = []
        for seed in range(seed_base, seed_base + 20):
            instance = generate_instance(10, 5, 4, instance_class="average", seed=seed)
            schedule = solve(instance, seed, 30, local_search)
            result = validate(instance, schedule)
            if not result.valid or result.makespan is None:
                raise RuntimeError("ablation generated an invalid schedule")
            values.append(result.makespan)
        ablation_rows.append({
            "algorithm": name, "mean_makespan": sum(values) / len(values),
            "stddev": statistics.stdev(values), "seeds": len(values),
        })
    (output / "ablation.csv").write_text(
        "algorithm,mean_makespan,stddev,seeds\n" +
        "\n".join(f"{row['algorithm']},{row['mean_makespan']},{row['stddev']},{row['seeds']}"
                  for row in ablation_rows) + "\n", encoding="utf-8"
    )

    fixtures = Path("instances") / "edge_cases"
    fixtures.mkdir(parents=True, exist_ok=True)
    edge_specs = {
        "single_machine": (5, 1, 3, {"flexibility": 0.0}),
        "single_job": (1, 4, 4, {"flexibility": 1.0}),
        "many_machines": (3, 8, 2, {"flexibility": 1.0}),
        "extreme_gap": (2, 2, 2, {"processing_time_min": 1, "processing_time_max": 10000}),
        "long_chain": (2, 1, 12, {"flexibility": 0.0}),
    }
    for name, (jobs, machines, operations, kwargs) in edge_specs.items():
        instance = generate_instance(jobs, machines, operations, seed=seed_base, **kwargs)
        (fixtures / f"{name}.json").write_text(
            json.dumps(instance_to_dict(instance), indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    import sys
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 20260910
    main(seed)
