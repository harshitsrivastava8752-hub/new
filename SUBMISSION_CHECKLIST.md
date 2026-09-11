# Submission checklist

- [x] Reproducible generator with seeds and named stress classes.
- [x] Independent validator with malformed-input diagnostics.
- [x] Validity, duration, precedence, overlap, and completeness tests.
- [x] Congestion-aware multi-start solver with bounded local search.
- [x] Utilization, workload, critical-path, and lower-bound metrics.
- [x] Multi-seed result artifacts in `results/`.
- [x] Reproduction command: `python run_submission.py`.
- [x] Standard-library-only runtime.

Before uploading, run `python -m unittest -v` and
`python run_submission.py` from a clean checkout, then verify that the public
repository contains `README.md`, `REPORT.md`, `fjsp.py`, tests, instances, and
results.
