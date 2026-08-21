"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ChevronLeftIcon,
  ChevronRightIcon,
  DownloadIcon,
  PauseIcon,
  PlayIcon,
  RotateCcwIcon,
  TriangleAlertIcon,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Field,
  FieldDescription,
  FieldLabel,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import {
  CPS_LIMIT,
  charsPerSecond,
  secondsToTimecode,
  shortTimecode,
  timecodeToSeconds,
  type Cue,
} from "../lib/subtitles";
import type { Track } from "./tracks";

type Props = {
  track: Track;
  cues: Cue[];
  /** Same-index cues from the source transcript, when editing a translation. */
  sourceCues?: Cue[];
  /** Object URL for the chosen file, so the preview is the real video. */
  previewUrl: string | null;
  /** Total media length in seconds, for laying out the timeline. */
  duration: number;
  edited: boolean;
  onChange: (cues: Cue[]) => void;
  onRevert: () => void;
  onDownload: () => void;
};

/**
 * Cue editor.
 *
 * The job here is the one thing the read-only track list cannot do: fix a cue.
 * That means three linked views of the same timeline — the video with the cue
 * burned over it, the cue itself, and every cue laid out in time — where
 * selecting in any one moves the other two.
 *
 * Edits are held by the caller and serialised back to SRT on download, so what
 * you see on the frame is what lands in the file.
 */
export function Editor({
  track,
  cues,
  sourceCues,
  previewUrl,
  duration,
  edited,
  onChange,
  onRevert,
  onDownload,
}: Props) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const rowRefs = useRef<Record<number, HTMLButtonElement | null>>({});
  const [selected, setSelected] = useState(0);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);

  const index = Math.min(selected, Math.max(0, cues.length - 1));
  const cue = cues[index];

  // Timeline length. The upload endpoint knows the real duration; fall back to
  // the last cue's out-point so the track still lays out without it.
  const total = useMemo(() => {
    if (duration > 0) return duration;
    const last = cues.at(-1);
    return last ? timecodeToSeconds(last.end) : 0;
  }, [duration, cues]);

  const seek = useCallback((seconds: number) => {
    const video = videoRef.current;
    const at = Math.max(0, seconds);
    if (video) video.currentTime = at;
    setTime(at);
  }, []);

  const select = useCallback(
    (next: number, alsoSeek = true) => {
      const clamped = Math.max(0, Math.min(cues.length - 1, next));
      setSelected(clamped);
      if (alsoSeek && cues[clamped]) {
        seek(timecodeToSeconds(cues[clamped].start));
      }
      rowRefs.current[clamped]?.scrollIntoView({ block: "nearest" });
    },
    [cues, seek],
  );

  // Arrow keys step cues and space toggles playback, the way every subtitle
  // tool works — but only when focus is not in a text field, or typing a cue
  // would scrub the video instead of writing.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (
        target &&
        (target.isContentEditable ||
          ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
      ) {
        return;
      }
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        select(index + (event.key === "ArrowDown" ? 1 : -1));
      } else if (event.code === "Space") {
        event.preventDefault();
        setPlaying((p) => !p);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [index, select]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    if (playing) video.play().catch(() => setPlaying(false));
    else video.pause();
  }, [playing]);

  const patch = (changes: Partial<Cue>) => {
    const next = cues.slice();
    next[index] = { ...next[index], ...changes };
    onChange(next);
  };

  const nudge = (field: "start" | "end", delta: number) => {
    if (!cue) return;
    patch({ [field]: secondsToTimecode(timecodeToSeconds(cue[field]) + delta) });
  };

  // What is actually on screen right now — during playback that is whatever
  // the playhead is inside, not whatever row is selected.
  const liveCue = cues.find(
    (c) =>
      time >= timecodeToSeconds(c.start) && time <= timecodeToSeconds(c.end),
  );
  const overlay = playing ? liveCue : cue;

  const cps = cue ? charsPerSecond(cue) : 0;
  const span = cue
    ? timecodeToSeconds(cue.end) - timecodeToSeconds(cue.start)
    : 0;
  const inverted = span <= 0;
  const overlaps =
    cue && cues[index + 1]
      ? timecodeToSeconds(cue.end) > timecodeToSeconds(cues[index + 1].start)
      : false;

  if (!cue) {
    return (
      <Card className="glass p-8 text-center text-sm text-muted-foreground">
        This track has no timed cues to edit.
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,26rem)]">
        {/* ---------------------------------------------------------------
            Preview: the real video, with the cue over it exactly where a
            player would put it. A mock can get away with a black box; the
            point of checking a subtitle is seeing it against the frame.
        --------------------------------------------------------------- */}
        <Card className="glass flex flex-col gap-3 p-4">
          <div className="relative aspect-video w-full overflow-hidden rounded-lg bg-ink">
            {previewUrl ? (
              <video
                ref={videoRef}
                src={previewUrl}
                playsInline
                className="absolute inset-0 size-full object-contain"
                onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
                onEnded={() => setPlaying(false)}
              />
            ) : (
              <div className="absolute inset-0 grid place-items-center font-mono text-[0.6875rem] tracking-[0.2em] text-paper/25 uppercase">
                no preview
              </div>
            )}
            {overlay && (
              <p className="caption-text absolute inset-x-0 bottom-[9%] z-10 px-[6%] text-center text-base leading-snug font-semibold text-white sm:text-lg">
                {overlay.text}
              </p>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="icon"
              onClick={() => setPlaying((p) => !p)}
              aria-label={playing ? "Pause" : "Play"}
              disabled={!previewUrl}
            >
              {playing ? <PauseIcon /> : <PlayIcon />}
            </Button>
            <span className="font-mono text-[0.8125rem] tabular-nums">
              {secondsToTimecode(time).slice(3, 8)}
            </span>
            <span className="font-mono text-[0.8125rem] tabular-nums text-muted-foreground">
              / {secondsToTimecode(total).slice(3, 8)}
            </span>
            <div className="ms-auto flex gap-1.5">
              <Button
                variant="outline"
                size="sm"
                onClick={() => select(index - 1)}
                disabled={index === 0}
              >
                <ChevronLeftIcon data-icon="inline-start" aria-hidden />
                Prev
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => select(index + 1)}
                disabled={index === cues.length - 1}
              >
                Next
                <ChevronRightIcon data-icon="inline-end" aria-hidden />
              </Button>
            </div>
          </div>
        </Card>

        {/* Inspector for the selected cue. */}
        <Card className="glass flex flex-col gap-4 p-4">
          <div className="flex items-baseline justify-between gap-2">
            <h3 className="font-mono text-[0.6875rem] tracking-[0.18em] text-muted-foreground uppercase">
              Cue {cue.index.toString().padStart(2, "0")}
            </h3>
            <Badge variant="outline" className="font-mono text-[0.625rem]">
              {track.label}
            </Badge>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <TimecodeField
              label="In"
              value={cue.start}
              invalid={inverted}
              onCommit={(v) => patch({ start: v })}
              onNudge={(d) => nudge("start", d)}
            />
            <TimecodeField
              label="Out"
              value={cue.end}
              invalid={inverted}
              onCommit={(v) => patch({ end: v })}
              onNudge={(d) => nudge("end", d)}
            />
          </div>

          <Field>
            <FieldLabel htmlFor="cue-text">Text</FieldLabel>
            <Textarea
              id="cue-text"
              value={cue.text}
              lang={track.lang}
              dir="auto"
              rows={3}
              className="glass-control resize-y"
              onChange={(e) => patch({ text: e.target.value })}
            />
          </Field>

          <Separator />

          <div className="flex gap-6">
            <Stat label="Duration" value={`${span.toFixed(1)}s`} />
            <Stat
              label="Chars"
              value={String(cue.text.replace(/\s+/g, " ").length)}
            />
            <Stat
              label="Chars / sec"
              value={cps.toFixed(1)}
              tone={cps > CPS_LIMIT ? "text-destructive" : undefined}
            />
          </div>

          {inverted ? (
            <Problem>
              Out is at or before In, so this cue never shows. Move Out later.
            </Problem>
          ) : overlaps ? (
            <Problem>
              This cue runs past the start of the next one. Players will drop or
              overlap them.
            </Problem>
          ) : cps > CPS_LIMIT ? (
            <Problem>
              Above {CPS_LIMIT} chars/sec — too fast to read comfortably. Extend
              the cue or shorten the line.
            </Problem>
          ) : (
            <FieldDescription>
              Within a comfortable reading speed.
            </FieldDescription>
          )}
        </Card>
      </div>

      {/* -----------------------------------------------------------------
          Timeline. Deliberately NOT a waveform: decoding the audio to draw
          one would mean pulling the whole track through the Web Audio API,
          and a *fake* waveform in a real tool is worse than none — it looks
          like evidence. These blocks are the cues themselves, which is the
          thing you are actually editing.
      ----------------------------------------------------------------- */}
      <Card className="glass flex flex-col gap-2 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="font-mono text-[0.6875rem] tracking-[0.18em] text-muted-foreground uppercase">
            Timeline
          </h3>
          <span className="font-mono text-[0.6875rem] text-muted-foreground">
            click a cue to select · click the track to scrub
          </span>
        </div>

        <div
          role="presentation"
          onClick={(event) => {
            const box = event.currentTarget.getBoundingClientRect();
            seek(((event.clientX - box.left) / box.width) * total);
          }}
          className="relative h-24 cursor-pointer overflow-hidden rounded-md border bg-ink/50"
        >
          <div className="absolute inset-x-0 top-0 flex h-5 border-b">
            {Array.from({ length: 8 }, (_, i) => (
              <span
                key={i}
                className="flex-1 border-s ps-1 font-mono text-[0.625rem] text-muted-foreground"
              >
                {secondsToTimecode((total / 8) * i).slice(3, 8)}
              </span>
            ))}
          </div>

          <div className="absolute inset-x-0 top-7 bottom-0">
            {cues.map((c, i) => {
              const from = timecodeToSeconds(c.start);
              const to = timecodeToSeconds(c.end);
              if (!(total > 0) || !(to > from)) return null;
              return (
                <button
                  key={c.index}
                  type="button"
                  title={c.text}
                  onClick={(event) => {
                    event.stopPropagation();
                    select(i);
                  }}
                  style={{
                    left: `${(from / total) * 100}%`,
                    width: `${Math.max(((to - from) / total) * 100, 0.4)}%`,
                  }}
                  className={cn(
                    "absolute top-2 h-10 overflow-hidden rounded-[3px] border px-1 text-start font-mono text-[0.625rem] transition-colors",
                    i === index
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-white/15 bg-white/8 text-muted-foreground hover:bg-white/15",
                  )}
                >
                  {c.index.toString().padStart(2, "0")}
                </button>
              );
            })}
          </div>

          {total > 0 && (
            <span
              aria-hidden
              style={{ left: `${Math.min((time / total) * 100, 100)}%` }}
              className="absolute inset-y-0 w-0.5 bg-primary shadow-[0_0_12px_var(--color-caption)]"
            />
          )}
        </div>
      </Card>

      {/* Every cue, as a table. Clicking a row selects and seeks. */}
      <Card className="glass flex min-h-0 flex-col overflow-hidden p-0">
        <div className="flex items-center justify-between gap-2 px-4 py-2">
          <div className="flex items-center gap-2">
            <Badge variant="ghost" className="font-mono text-[0.6875rem]">
              {cues.length} cues
            </Badge>
            {edited && (
              <Badge variant="secondary" className="font-mono text-[0.6875rem]">
                edited
              </Badge>
            )}
          </div>
          <div className="flex gap-1.5">
            {edited && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button variant="ghost" size="sm" onClick={onRevert}>
                    <RotateCcwIcon data-icon="inline-start" aria-hidden />
                    Revert
                  </Button>
                </TooltipTrigger>
                <TooltipContent>
                  Discard every edit on this track and go back to what the
                  server returned.
                </TooltipContent>
              </Tooltip>
            )}
            <Button variant="outline" size="sm" onClick={onDownload}>
              <DownloadIcon data-icon="inline-start" aria-hidden />
              Download .srt
            </Button>
          </div>
        </div>
        <Separator />

        <ScrollArea className="max-h-[22rem] min-h-0 flex-1">
          {cues.map((c, i) => {
            const hot = charsPerSecond(c) > CPS_LIMIT;
            return (
              <button
                key={c.index}
                type="button"
                ref={(node) => {
                  rowRefs.current[i] = node;
                }}
                onClick={() => select(i)}
                aria-current={i === index}
                className={cn(
                  "grid w-full grid-cols-[2.5rem_8.5rem_1fr] items-baseline gap-x-3 border-b px-4 py-2.5 text-start transition-colors last:border-b-0 hover:bg-muted/40",
                  sourceCues && "sm:grid-cols-[2.5rem_8.5rem_1fr_1fr]",
                  i === index && "bg-primary/10",
                )}
              >
                <span className="font-mono text-[0.6875rem] tabular-nums text-muted-foreground">
                  {c.index.toString().padStart(2, "0")}
                </span>
                <span className="flex items-center gap-1 font-mono text-[0.6875rem] tabular-nums text-muted-foreground">
                  {shortTimecode(c.start)}
                  <span aria-hidden>→</span>
                  {shortTimecode(c.end)}
                  {hot && (
                    <TriangleAlertIcon
                      className="size-3 text-destructive"
                      aria-label="Above the reading-speed limit"
                    />
                  )}
                </span>
                {sourceCues && (
                  <span className="hidden text-[0.875rem] leading-6 text-muted-foreground sm:block">
                    {sourceCues[i]?.text ?? ""}
                  </span>
                )}
                <span
                  lang={track.lang}
                  dir="auto"
                  className="wrap-anywhere text-[0.875rem] leading-6 text-foreground/90"
                >
                  {c.text}
                </span>
              </button>
            );
          })}
        </ScrollArea>
      </Card>
    </div>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <span>
      <span
        className={cn(
          "block font-mono text-xl font-semibold tabular-nums",
          tone,
        )}
      >
        {value}
      </span>
      <span className="text-[0.6875rem] tracking-[0.08em] text-muted-foreground uppercase">
        {label}
      </span>
    </span>
  );
}

function Problem({ children }: { children: React.ReactNode }) {
  return (
    <p className="flex items-start gap-2 text-[0.8125rem] leading-5 text-destructive">
      <TriangleAlertIcon className="mt-0.5 size-3.5 shrink-0" aria-hidden />
      {children}
    </p>
  );
}

/**
 * A timecode input that lets you type freely.
 *
 * Committing on every keystroke makes the field unusable — deleting one digit
 * of `00:00:12,400` briefly produces garbage and the cue jumps. So the draft
 * is local and only lands when it parses, on blur or Enter.
 */
function TimecodeField({
  label,
  value,
  invalid,
  onCommit,
  onNudge,
}: {
  label: string;
  value: string;
  invalid: boolean;
  onCommit: (value: string) => void;
  onNudge: (delta: number) => void;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const shown = draft ?? value;
  const bad = Number.isNaN(timecodeToSeconds(shown));

  const commit = () => {
    if (draft === null) return;
    if (!Number.isNaN(timecodeToSeconds(draft))) onCommit(draft);
    setDraft(null);
  };

  return (
    <Field data-invalid={bad || invalid ? true : undefined}>
      <FieldLabel htmlFor={`tc-${label}`}>{label}</FieldLabel>
      <div className="flex items-center gap-1">
        <Input
          id={`tc-${label}`}
          value={shown}
          aria-invalid={bad || invalid}
          inputMode="numeric"
          spellCheck={false}
          className="glass-control font-mono text-[0.8125rem] tabular-nums"
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              commit();
            } else if (e.key === "Escape") {
              setDraft(null);
            }
          }}
        />
        <div className="flex flex-col">
          <Button
            variant="ghost"
            size="icon-xs"
            aria-label={`${label} later by 0.1 seconds`}
            onClick={() => onNudge(0.1)}
          >
            +
          </Button>
          <Button
            variant="ghost"
            size="icon-xs"
            aria-label={`${label} earlier by 0.1 seconds`}
            onClick={() => onNudge(-0.1)}
          >
            −
          </Button>
        </div>
      </div>
    </Field>
  );
}
