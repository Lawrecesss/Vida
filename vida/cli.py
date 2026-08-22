"""Command line interface: ``vida <command> ...``."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

from vida import __version__
from vida.asr import available_backends
from vida.client import Vida
from vida.config import VidaConfig
from vida.errors import VidaError


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vida", description="Analyze, transcribe, and translate video."
    )
    parser.add_argument("--version", action="version", version=f"vida {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("source", help="Path to the video or audio file.")
    common.add_argument(
        "--asr", default=None, choices=["auto", "groq", "openai", "local"],
        help="ASR backend (default: auto).",
    )
    common.add_argument("--asr-model", default=None, help="Override the ASR model id.")
    common.add_argument("--language", default=None, help="Source language hint, e.g. 'en'.")
    common.add_argument(
        "--prompt", default=None,
        help="Context to bias decoding: names, acronyms, jargon the model would mangle.",
    )
    common.add_argument(
        "--glossary", default=None, action="append", metavar="TERM",
        help="Term to bias decoding toward. Repeat, or pass a comma-separated list.",
    )

    transcribe = sub.add_parser("transcribe", parents=[common], help="Transcribe a file.")
    transcribe.add_argument(
        "-o", "--output", default=None, help="Write to this file (.srt/.vtt/.txt/.json)."
    )

    translate = sub.add_parser(
        "translate", parents=[common], help="Transcribe, then translate."
    )
    translate.add_argument(
        "-t", "--to", required=True, action="append",
        help="Target language. Repeat for several.",
    )
    translate.add_argument("-o", "--out-dir", default=None, help="Directory for subtitle files.")
    translate.add_argument(
        "-f", "--format", default="srt", choices=["srt", "vtt"], help="Subtitle format."
    )

    analyze = sub.add_parser("analyze", parents=[common], help="Analyze video content.")
    analyze.add_argument("-q", "--query", default=None, help="Question to focus the analysis on.")

    info = sub.add_parser("info", parents=[common], help="Probe a media file.")
    info.set_defaults(_info=True)

    sub.add_parser("backends", help="Show which ASR backends are usable right now.")

    return parser


def _glossary(args) -> list[str] | None:
    """Flatten repeated --glossary flags, each of which may itself be a list.

    Both spellings exist because both get typed: one flag per name when there
    are three, and a pasted comma-separated line when there are thirty.
    """
    raw = getattr(args, "glossary", None)
    if not raw:
        return None
    terms = [term.strip() for entry in raw for term in entry.split(",") if term.strip()]
    return terms or None


def _make_client(args) -> Vida:
    config = VidaConfig()
    if getattr(args, "asr", None):
        config.asr.backend = args.asr
    if getattr(args, "asr_model", None):
        config.asr.model = args.asr_model
    return Vida(config)


async def _cmd_transcribe(args) -> int:
    async with _make_client(args) as vida:
        started = time.perf_counter()
        transcript = await vida.transcribe(
            args.source,
            language=args.language,
            prompt=args.prompt,
            glossary=_glossary(args),
        )
        elapsed = time.perf_counter() - started

    if args.output:
        transcript.save(args.output)
        print(f"Wrote {args.output}", file=sys.stderr)
    else:
        print(transcript.to_srt())

    print(
        f"[{len(transcript.segments)} segments, {transcript.duration:.0f}s of audio, "
        f"{elapsed:.1f}s elapsed, backend={transcript.backend}]",
        file=sys.stderr,
    )
    return 0


async def _cmd_translate(args) -> int:
    async with _make_client(args) as vida:
        started = time.perf_counter()
        written = await vida.subtitles(
            args.source,
            languages=args.to,
            out_dir=args.out_dir,
            fmt=args.format,
            language=args.language,
            prompt=args.prompt,
            glossary=_glossary(args),
        )
        elapsed = time.perf_counter() - started

    for language, path in written.items():
        print(f"{language}: {path}")
    print(f"[{elapsed:.1f}s elapsed]", file=sys.stderr)
    return 0


async def _cmd_analyze(args) -> int:
    async with _make_client(args) as vida:
        started = time.perf_counter()
        analysis = await vida.analyze(args.source, query=args.query)
        elapsed = time.perf_counter() - started

    print(analysis.summary)
    failed = sum(1 for segment in analysis.segments if segment.status == "error")
    note = f", {failed} clip(s) failed" if failed else ""
    print(f"[{len(analysis.segments)} clips{note}, {elapsed:.1f}s elapsed]", file=sys.stderr)
    return 0


def _cmd_info(args) -> int:
    media = Vida().probe(args.source)
    print(json.dumps(media.model_dump(mode="json"), indent=2))
    return 0


def _cmd_backends(_args) -> int:
    for name, problem in available_backends().items():
        status = "ready" if not problem else f"unavailable — {problem}"
        print(f"{name:8} {status}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    handlers = {
        "transcribe": _cmd_transcribe,
        "translate": _cmd_translate,
        "analyze": _cmd_analyze,
    }

    try:
        if args.command == "info":
            return _cmd_info(args)
        if args.command == "backends":
            return _cmd_backends(args)

        if getattr(args, "source", None) and not os.path.exists(args.source):
            print(f"error: no such file: {args.source}", file=sys.stderr)
            return 2

        return asyncio.run(handlers[args.command](args))

    except VidaError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
