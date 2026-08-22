"""The accuracy table.

Deletion rate gets its own column rather than being folded into WER. Whisper's
characteristic failure under a music bed is not mistranscription, it is silence
— whole lines simply absent — and a WER of 30% made of deletions means something
quite different from a WER of 30% made of substitutions. The first says the
system did not hear the dialogue; the second says it heard it and got the words
wrong. They have different fixes, so they are shown separately.

Results are grouped by fixture kind for the same reason ``evals/report.py``
never pools descriptive and temporal: a quiet-dialogue clip and a music-heavy
one average into a number that describes neither.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict

__all__ = ["print_report"]


def _load(out_dir: str) -> list[dict]:
    scores = []
    for name in sorted(os.listdir(out_dir)):
        if name.endswith(".score.json"):
            with open(os.path.join(out_dir, name), encoding="utf-8") as handle:
                scores.append(json.load(handle))
    return scores


def _rate(got: int, total: int) -> float:
    return got / total if total else 0.0


def print_report(out_dir: str) -> None:
    if not os.path.isdir(out_dir):
        raise SystemExit(f"No results directory at {out_dir}")

    scores = _load(out_dir)
    if not scores:
        raise SystemExit(
            f"No scores in {out_dir} — run `python -m evals.asr.run score` first."
        )

    # Errors are pooled across fixtures rather than averaging per-fixture rates:
    # a corpus-level WER weights each clip by how much was said in it, which is
    # what you want when clips differ in length.
    totals: dict[str, dict] = defaultdict(
        lambda: {"ref": 0, "sub": 0, "del": 0, "ins": 0, "cer": 0.0, "sec": 0.0, "n": 0}
    )
    by_kind: dict[str, dict[str, dict]] = defaultdict(
        lambda: defaultdict(lambda: {"ref": 0, "sub": 0, "del": 0, "ins": 0})
    )

    for score in scores:
        config = score["config"]
        entry = totals[config]
        entry["ref"] += score["reference_words"]
        entry["sub"] += score["substitutions"]
        entry["del"] += score["deletions"]
        entry["ins"] += score["insertions"]
        entry["cer"] += score["cer"]
        entry["sec"] += score["seconds"]
        entry["n"] += 1

        kind = score.get("extra", {}).get("kind", "dialogue")
        bucket = by_kind[kind][config]
        bucket["ref"] += score["reference_words"]
        bucket["sub"] += score["substitutions"]
        bucket["del"] += score["deletions"]
        bucket["ins"] += score["insertions"]

    configs = sorted(totals)

    print("\nAccuracy   (pooled over every fixture, lower is better)\n")
    header = (
        f"{'config':<30}{'clips':>6}{'WER':>9}{'CER':>9}"
        f"{'deleted':>10}{'inserted':>10}{'wall':>9}"
    )
    print(header)
    print("-" * len(header))
    for config in configs:
        e = totals[config]
        wer = _rate(e["sub"] + e["del"] + e["ins"], e["ref"])
        # WER pools errors over words so long clips count for more; CER is a
        # plain per-clip mean, since character counts are not tracked.
        cer = e["cer"] / e["n"] if e["n"] else 0.0
        print(
            f"{config:<30}{e['n']:>6}{wer * 100:>8.1f}%{cer * 100:>8.1f}%"
            f"{_rate(e['del'], e['ref']) * 100:>9.1f}%"
            f"{_rate(e['ins'], e['ref']) * 100:>9.1f}%"
            f"{e['sec']:>8.0f}s"
        )

    print("\nWER by clip type\n")
    kinds = sorted(by_kind)
    header = f"{'config':<30}" + "".join(f"{kind:>18}" for kind in kinds)
    print(header)
    print("-" * len(header))
    for config in configs:
        row = f"{config:<30}"
        for kind in kinds:
            bucket = by_kind[kind].get(config)
            if not bucket or not bucket["ref"]:
                row += f"{'-':>18}"
                continue
            wer = _rate(bucket["sub"] + bucket["del"] + bucket["ins"], bucket["ref"])
            row += f"{wer * 100:>17.1f}%"
        print(row)

    print(
        "\nRead the deleted column first. Dialogue Whisper never returned is the\n"
        "failure this pipeline keeps hitting under a music bed, and it is not\n"
        "distinguishable from ordinary error inside a single WER number."
    )
