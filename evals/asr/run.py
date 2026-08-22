"""CLI driver for transcription accuracy.

    python -m evals.asr.run run    --manifest evals/asr/fixtures/manifest.json \
        --configs groq:whisper-large-v3,local:small,local:medium --out evals/asr/results
    python -m evals.asr.run score  --manifest evals/asr/fixtures/manifest.json \
        --out evals/asr/results
    python -m evals.asr.run report --out evals/asr/results

``run`` and ``score`` are separate for the same reason they are in
``evals/run.py``: transcription is the expensive half. Hypotheses are cached to
disk, so revising the normalisation in ``score.py`` and re-scoring costs nothing
and re-runs no ASR.

Every knob the accuracy streams added is exposed as a flag and recorded in the
config label, so ``--glossary`` and ``--no-glossary`` runs of the same backend
cache side by side and can be compared directly rather than overwriting.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

from evals.asr.fixtures import Fixture, load_manifest, read_reference
from evals.asr.report import print_report
from evals.asr.score import score_transcript
from vida import Vida
from vida.config import ASRConfig, VidaConfig
from vida.errors import VidaError


def _parse_configs(spec: str, args) -> list[tuple[str, ASRConfig]]:
    """Turn ``backend[:model],...`` into labelled :class:`ASRConfig` objects.

    The label carries every flag that could move the number, so two runs that
    differ only by ``--glossary`` land in different cache files instead of one
    silently overwriting the other.
    """
    configs = []
    for raw in (part.strip() for part in spec.split(",")):
        if not raw:
            continue
        backend, _, model = raw.partition(":")
        config = ASRConfig(backend=backend.strip(), model=model.strip() or None)

        label = raw
        if args.glossary:
            label += "+glossary"
        if args.dialogue_filter:
            config.dialogue_filter = args.dialogue_filter
            label += "+dialogue"
        if args.silence_aware:
            config.silence_aware_chunking = True
            label += "+silenceaware"
        if args.no_audio_filter:
            config.audio_filter = ""
            label += "+rawaudio"
        if args.chunk_seconds:
            config.chunk_seconds = args.chunk_seconds
            label += f"+chunk{args.chunk_seconds:g}"

        configs.append((label, config))

    if not configs:
        raise SystemExit("No configs given — pass e.g. --configs groq:whisper-large-v3")
    return configs


def _usable(fixtures: list[Fixture]) -> list[Fixture]:
    """Drop fixtures whose media is not on disk, saying so.

    Missing media is the normal case for a fresh clone: the references are
    committed and the clips are not.
    """
    usable = []
    for fixture in fixtures:
        if fixture.available:
            usable.append(fixture)
        else:
            missing = "media" if not os.path.isfile(fixture.media) else "reference"
            print(f"  {fixture.id:<20} skipped — {missing} not found", file=sys.stderr)
    if not usable:
        raise SystemExit(
            "No fixtures are available.\n"
            "The clips are gitignored on purpose; put them where the manifest points."
        )
    return usable


async def _write_json(path: str, payload) -> None:
    """Offloaded so the driver never blocks the loop on disk, as evals/run.py does."""

    def _write() -> None:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)

    await asyncio.to_thread(_write)


def _result_path(out_dir: str, fixture_id: str, label: str) -> str:
    safe = label.replace(":", "-").replace("/", "-")
    return os.path.join(out_dir, f"{fixture_id}.{safe}.json")


async def _run(args) -> None:
    fixtures = _usable(load_manifest(args.manifest))
    configs = _parse_configs(args.configs, args)
    os.makedirs(args.out, exist_ok=True)

    for label, asr_config in configs:
        print(f"\n{label}")
        async with Vida(VidaConfig(asr=asr_config)) as vida:
            for fixture in fixtures:
                dest = _result_path(args.out, fixture.id, label)
                if os.path.exists(dest) and not args.force:
                    print(f"  {fixture.id:<20} cached")
                    continue

                started = time.perf_counter()
                error = None
                text = ""
                segments = 0
                try:
                    transcript = await vida.transcribe(
                        fixture.media,
                        language=fixture.language,
                        prompt=args.prompt,
                        glossary=fixture.glossary if args.glossary else None,
                    )
                    text = transcript.text
                    segments = len(transcript.segments)
                except VidaError as exc:
                    error = str(exc)
                elapsed = time.perf_counter() - started

                payload = {
                    "fixture_id": fixture.id,
                    "config": label,
                    "kind": fixture.kind,
                    "media": fixture.media,
                    "hypothesis": text,
                    "segments": segments,
                    "seconds": elapsed,
                    "error": error,
                }
                await _write_json(dest, payload)

                note = f"  FAILED: {error}" if error else ""
                print(
                    f"  {fixture.id:<20} {segments:>4} segments  "
                    f"{len(text.split()):>5} words  {elapsed:>6.1f}s{note}"
                )


def _score(args) -> None:
    references = {
        fixture.id: read_reference(fixture.reference)
        for fixture in load_manifest(args.manifest)
        if os.path.isfile(fixture.reference)
    }

    if not os.path.isdir(args.out):
        raise SystemExit(f"No results directory at {args.out} — run `run` first")

    scored = 0
    for name in sorted(os.listdir(args.out)):
        if not name.endswith(".json") or name.endswith(".score.json"):
            continue
        path = os.path.join(args.out, name)
        with open(path, encoding="utf-8") as handle:
            result = json.load(handle)

        reference = references.get(result["fixture_id"])
        if reference is None:
            print(f"  no reference for {result['fixture_id']} — skipping", file=sys.stderr)
            continue
        if result.get("error"):
            print(f"  {result['fixture_id']:<20} {result['config']:<28} run failed — skipping")
            continue

        score = score_transcript(
            result["fixture_id"],
            result["config"],
            reference,
            result["hypothesis"],
            seconds=result.get("seconds", 0.0),
            extra={"kind": result.get("kind", "dialogue"), "segments": result.get("segments", 0)},
        )
        dest = path[: -len(".json")] + ".score.json"
        with open(dest, "w", encoding="utf-8") as handle:
            json.dump(score.to_dict(), handle, indent=2)
        scored += 1

        print(
            f"  {score.fixture_id:<20} {score.config:<28} "
            f"WER {score.wer * 100:>5.1f}%   CER {score.cer * 100:>5.1f}%   "
            f"del {score.deletion_rate * 100:>5.1f}%"
        )

    if not scored:
        raise SystemExit("Nothing was scored — check the manifest ids match the cached results.")


def main() -> int:
    parser = argparse.ArgumentParser(prog="evals.asr.run", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    default_manifest = "evals/asr/fixtures/manifest.json"

    run = sub.add_parser("run", help="Transcribe the fixtures and cache the hypotheses.")
    run.add_argument("--manifest", default=default_manifest)
    run.add_argument("--out", default="evals/asr/results")
    run.add_argument(
        "--configs", default="auto",
        help="Comma-separated backend[:model] specs, e.g. groq:whisper-large-v3,local:medium.",
    )
    run.add_argument("--prompt", default=None, help="Free-text vocabulary hint for every fixture.")
    run.add_argument(
        "--glossary", action="store_true",
        help="Pass each fixture's glossary terms to the ASR backend.",
    )
    run.add_argument(
        "--dialogue-filter", default=None,
        help="ffmpeg filter applied in the source channel layout, e.g. 'pan=mono|c0=FC'.",
    )
    run.add_argument(
        "--silence-aware", action="store_true", help="Snap chunk boundaries to silence."
    )
    run.add_argument(
        "--no-audio-filter", action="store_true", help="Disable the denoise chain entirely."
    )
    run.add_argument("--chunk-seconds", type=float, default=None)
    run.add_argument("--force", action="store_true", help="Re-transcribe cached fixtures.")

    score = sub.add_parser("score", help="Score cached hypotheses against the references.")
    score.add_argument("--manifest", default=default_manifest)
    score.add_argument("--out", default="evals/asr/results")

    report = sub.add_parser("report", help="Print the accuracy table.")
    report.add_argument("--out", default="evals/asr/results")

    args = parser.parse_args()

    try:
        if args.command == "report":
            print_report(args.out)
        elif args.command == "score":
            _score(args)
        else:
            asyncio.run(_run(args))
    except VidaError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
