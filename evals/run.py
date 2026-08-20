"""CLI driver for the arm comparison.

    python -m evals.run run    --videos vids/ --out evals/results
    python -m evals.run score  --out evals/results --questions evals/questions.json
    python -m evals.run report --out evals/results

``run`` and ``score`` are separate on purpose: arm output is cached to disk, so
re-grading with a different judge or a revised question set costs nothing and
re-runs no video work.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import shutil
import sys
import tempfile
import time

from evals.arms import ARMS, run_arm
from evals.judge import Question, score_arm
from evals.report import print_report
from vida import Vida
from vida.config import VidaConfig
from vida.errors import VidaError
from vida.media.video import probe

_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mpg", ".mpeg"}


def _discover(path: str) -> list[str]:
    if os.path.isfile(path):
        return [path]
    found = [
        os.path.join(path, name)
        for name in sorted(os.listdir(path))
        if os.path.splitext(name)[1].lower() in _VIDEO_EXTENSIONS
    ]
    if not found:
        raise SystemExit(f"No video files found in {path}")
    return found


def _slug(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


async def _read_json(path: str):
    """Offloaded so the async driver never blocks the loop on disk."""
    return await asyncio.to_thread(lambda: json.load(open(path)))


async def _write_json(path: str, payload) -> None:
    def _write() -> None:
        with open(path, "w") as handle:
            json.dump(payload, handle, indent=2)

    await asyncio.to_thread(_write)


def _result_path(out_dir: str, video: str, arm: str, frames: int | None) -> str:
    suffix = "" if frames is None else f".f{frames}"
    return os.path.join(out_dir, f"{_slug(video)}.{arm}{suffix}.json")


@contextlib.contextmanager
def _work_dir(keep: bool):
    path = tempfile.mkdtemp(prefix="vida_eval_")
    try:
        yield path
    finally:
        if keep:
            print(f"  scratch kept at {path}", file=sys.stderr)
        else:
            shutil.rmtree(path, ignore_errors=True)


async def _run(args) -> None:
    videos = _discover(args.videos)
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    for arm in arms:
        if arm not in ARMS:
            raise SystemExit(f"Unknown arm {arm!r}. Choose from: {', '.join(ARMS)}")
    frame_counts = [int(n) for n in args.frames.split(",") if n.strip()]

    os.makedirs(args.out, exist_ok=True)
    config = VidaConfig()

    async with Vida(config) as vida:
        for video in videos:
            media = probe(video)
            print(f"\n{video}  ({media.duration:.0f}s, {media.size_mb:.0f} MB)")

            # One transcript per video, shared by every arm that needs it, so
            # ASR cost does not multiply across arms or frame counts.
            transcript = None
            if "frames_text" in arms:
                started = time.perf_counter()
                try:
                    transcript = await vida.transcribe(video)
                    print(
                        f"  transcript: {len(transcript.segments)} segments "
                        f"in {time.perf_counter() - started:.1f}s"
                    )
                except VidaError as exc:
                    print(f"  transcript FAILED: {exc} — skipping frames_text")
                    arms = [a for a in arms if a != "frames_text"]

            for arm in arms:
                counts = frame_counts if arm != "video" else [None]
                for frames in counts:
                    dest = _result_path(args.out, video, arm, frames)
                    if os.path.exists(dest) and not args.force:
                        print(f"  {arm:<13} {str(frames or '-'):>3} frames  cached")
                        continue

                    label = f"  {arm:<13} {str(frames or '-'):>3} frames"
                    with _work_dir(args.keep_scratch) as work_dir:
                        result = await run_arm(
                            arm,
                            media,
                            client=vida.llm,
                            model=args.model or config.analysis.model,
                            synthesis_model=(
                                args.synthesis_model or config.analysis.synthesis_model
                            ),
                            work_dir=work_dir,
                            window_seconds=args.window,
                            overlap=args.overlap,
                            frames_per_window=frames or 6,
                            audio_format=args.audio_format,
                            concurrency=args.concurrency,
                            transcript=transcript,
                        )

                    await _write_json(dest, result.to_dict())

                    note = f" [{result.error}]" if result.error else ""
                    print(
                        f"{label}  {result.requests:>3} req  "
                        f"{result.uploaded_bytes / 1024 / 1024:>7.1f} MB  "
                        f"{result.seconds:>6.1f}s  "
                        f"{result.failed_windows} failed{note}"
                    )


def _load_results(out_dir: str) -> list[dict]:
    if not os.path.isdir(out_dir):
        raise SystemExit(f"No results directory at {out_dir}")
    results = []
    for name in sorted(os.listdir(out_dir)):
        if name.endswith(".json") and not name.endswith(".scores.json"):
            with open(os.path.join(out_dir, name)) as handle:
                results.append(json.load(handle))
    if not results:
        raise SystemExit(f"No arm results in {out_dir} — run `run` first")
    return results


async def _score(args) -> None:
    raw = await _read_json(args.questions)

    by_video = {
        entry["video"]: [Question.from_dict(q) for q in entry["questions"]] for entry in raw
    }
    results = _load_results(args.out)
    config = VidaConfig()

    async with Vida(config) as vida:
        for result in results:
            key = os.path.basename(result["video"])
            questions = by_video.get(key) or by_video.get(result["video"])
            if not questions:
                print(f"  no questions for {key} — skipping")
                continue

            verdicts = await score_arm(
                result["summary"],
                questions,
                client=vida.llm,
                model=args.judge_model or config.analysis.synthesis_model,
                concurrency=args.concurrency,
            )
            suffix = (
                "" if result["frames_per_window"] is None else f".f{result['frames_per_window']}"
            )
            dest = os.path.join(
                args.out, f"{_slug(result['video'])}.{result['arm']}{suffix}.scores.json"
            )
            await _write_json(dest, [v.to_dict() for v in verdicts])

            graded = [v for v in verdicts if v.score >= 0]
            total = sum(v.score for v in graded)
            possible = 2 * len(graded)
            print(
                f"  {key:<24} {result['arm']:<13}{suffix:<5} "
                f"{total}/{possible}"
                + (
                    f"  ({len(verdicts) - len(graded)} ungraded)"
                    if len(graded) < len(verdicts)
                    else ""
                )
            )


def main() -> int:
    parser = argparse.ArgumentParser(prog="evals.run", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run the arms and cache their output.")
    run.add_argument("--videos", default="vids", help="Video file or directory.")
    run.add_argument("--out", default="evals/results", help="Where to cache arm output.")
    run.add_argument("--arms", default=",".join(ARMS), help="Comma-separated arm names.")
    run.add_argument("--frames", default="6,12", help="Frames per window to sweep.")
    run.add_argument("--window", type=float, default=60.0, help="Window length in seconds.")
    run.add_argument("--overlap", type=float, default=2.0)
    run.add_argument("--concurrency", type=int, default=4)
    run.add_argument("--audio-format", default="mp3", choices=["mp3", "wav", "flac", "ogg"])
    run.add_argument("--model", default=None, help="Per-window model. Defaults to config.")
    run.add_argument("--synthesis-model", default=None)
    run.add_argument("--force", action="store_true", help="Re-run arms that are already cached.")
    run.add_argument("--keep-scratch", action="store_true", help="Keep clips and frames on disk.")
    run.set_defaults(_fn=_run)

    score = sub.add_parser("score", help="Grade cached arm output against the question set.")
    score.add_argument("--out", default="evals/results")
    score.add_argument("--questions", default="evals/questions.json")
    score.add_argument("--judge-model", default=None)
    score.add_argument("--concurrency", type=int, default=4)
    score.set_defaults(_fn=_score)

    report = sub.add_parser("report", help="Print the comparison table.")
    report.add_argument("--out", default="evals/results")
    report.set_defaults(_fn=None)

    args = parser.parse_args()

    if args.command == "report":
        print_report(args.out)
        return 0

    try:
        asyncio.run(args._fn(args))
    except VidaError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
