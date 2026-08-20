"""The comparison table.

Descriptive and temporal scores are always reported separately. Pooling them
hides the effect the comparison exists to find: frames are expected to hold
their own on description and to lose on motion, and a single combined number
would average that distinction away.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict

__all__ = ["print_report"]


def _arm_key(result: dict) -> str:
    frames = result.get("frames_per_window")
    return result["arm"] if frames is None else f"{result['arm']}/f{frames}"


def _load(out_dir: str) -> tuple[list[dict], dict[str, list[dict]]]:
    results, scores = [], {}
    for name in sorted(os.listdir(out_dir)):
        path = os.path.join(out_dir, name)
        if name.endswith(".scores.json"):
            with open(path) as handle:
                scores[name[: -len(".scores.json")]] = json.load(handle)
        elif name.endswith(".json"):
            with open(path) as handle:
                results.append(json.load(handle))
    return results, scores


def _stem(result: dict) -> str:
    base = os.path.splitext(os.path.basename(result["video"]))[0]
    frames = result.get("frames_per_window")
    suffix = "" if frames is None else f".f{frames}"
    return f"{base}.{result['arm']}{suffix}"


def print_report(out_dir: str) -> None:
    if not os.path.isdir(out_dir):
        raise SystemExit(f"No results directory at {out_dir}")

    results, scores = _load(out_dir)
    if not results:
        raise SystemExit(f"No arm results in {out_dir}")

    cost = defaultdict(lambda: {"req": 0, "mb": 0.0, "sec": 0.0, "failed": 0, "n": 0})
    quality = defaultdict(lambda: defaultdict(lambda: [0, 0]))  # arm -> kind -> [got, possible]
    ungraded = 0

    for result in results:
        arm = _arm_key(result)
        entry = cost[arm]
        entry["req"] += result["requests"]
        entry["mb"] += result["uploaded_bytes"] / 1024 / 1024
        entry["sec"] += result["seconds"]
        entry["failed"] += result["failed_windows"]
        entry["n"] += 1

        for verdict in scores.get(_stem(result), []):
            if verdict["score"] < 0:
                ungraded += 1
                continue
            bucket = quality[arm][verdict["kind"]]
            bucket[0] += verdict["score"]
            bucket[1] += 2

    arms = sorted(cost)
    kinds = sorted({k for arm in quality.values() for k in arm}) or ["descriptive", "temporal"]

    print("\nCost and reliability   (totals across all videos)\n")
    header = f"{'arm':<18}{'videos':>7}{'requests':>10}{'uploaded':>12}{'wall':>9}{'failed':>8}"
    print(header)
    print("-" * len(header))
    for arm in arms:
        e = cost[arm]
        print(
            f"{arm:<18}{e['n']:>7}{e['req']:>10}{e['mb']:>10.1f} MB"
            f"{e['sec']:>8.0f}s{e['failed']:>8}"
        )

    if not quality:
        print("\nNo scores yet — run `python -m evals.run score` to grade the output.")
        return

    print("\nInformation captured   (judge score / possible, higher is better)\n")
    header = f"{'arm':<18}" + "".join(f"{k:>16}" for k in kinds) + f"{'overall':>12}"
    print(header)
    print("-" * len(header))
    for arm in arms:
        row = f"{arm:<18}"
        got_all = pos_all = 0
        for kind in kinds:
            got, possible = quality[arm].get(kind, [0, 0])
            got_all += got
            pos_all += possible
            cell = f"{got}/{possible}" if possible else "-"
            pct = f" ({got / possible * 100:.0f}%)" if possible else ""
            row += f"{cell + pct:>16}"
        overall = f"{got_all / pos_all * 100:.0f}%" if pos_all else "-"
        print(row + f"{overall:>12}")

    if ungraded:
        print(f"\n{ungraded} verdict(s) could not be graded — judge failed or replied unparseably.")

    print(
        "\nRead descriptive and temporal separately. Frames are expected to hold up on\n"
        "description and to fall behind on motion; a combined number hides exactly that."
    )
