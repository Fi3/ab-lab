"""Benchmark-owned adapters, selected by their JSON configuration section.

Register a new benchmark here; the runner only uses the shared lifecycle.
Definitions without one of these sections keep their ordinary final checks.
"""

ADAPTERS = {
    "slopcodebench": "benchmarks.slopcodebench",
    "swe_milestone": "benchmarks.swe_milestone_evaluator",
}
