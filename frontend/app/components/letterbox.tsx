"use client";

import { useState } from "react";
import {
  AudioLinesIcon,
  ClockIcon,
  FilmIcon,
  HardDriveIcon,
  UploadCloudIcon,
  VolumeXIcon,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { formatDuration } from "../lib/subtitles";

export type UploadInfo = {
  video_path: string;
  filename: string;
  size_mb: number;
  duration: number;
  has_audio: boolean;
};

type Props = {
  file: File | null;
  /** Object URL for `file`, owned by the caller so nothing leaks on replace. */
  preview: string | null;
  upload: UploadInfo | null;
  caption: string;
  tone: "idle" | "running" | "done" | "failed";
  busy: boolean;
  onFile: (file: File) => void;
  onReject: (message: string) => void;
};

/**
 * The signature element: a real video frame.
 *
 * It is the drop target, the progress indicator, and the status line all in one
 * place — but each of those gets its own slot rather than sharing one. The
 * caption line, in the lower third and in the amber, says what the run is
 * doing; the slate strip underneath says what the file is.
 *
 * The frame itself stays hand-built — no component library ships a viewfinder —
 * but everything around it is shadcn, so the badges and tooltips here match the
 * rest of the page exactly.
 */
export function Letterbox({
  file,
  upload,
  preview,
  caption,
  tone,
  busy,
  onFile,
  onReject,
}: Props) {
  const [dragging, setDragging] = useState(false);

  const accept = (candidate: File | undefined) => {
    if (!candidate) return;
    if (
      !candidate.type.startsWith("video/") &&
      !candidate.type.startsWith("audio/")
    ) {
      onReject(`${candidate.name} is not a video or audio file.`);
      return;
    }
    onFile(candidate);
  };

  return (
    <div className="flex flex-col gap-2">
      <input
        id="source-file"
        type="file"
        accept="video/*,audio/*"
        className="sr-only"
        onChange={(event) => accept(event.target.files?.[0])}
      />
      <label
        htmlFor="source-file"
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          accept(event.dataTransfer.files?.[0]);
        }}
        className={cn(
          "control safe-area relative flex aspect-video w-full cursor-pointer flex-col justify-end overflow-hidden rounded-lg bg-ink transition-all",
          "focus-within:outline focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-ring",
          dragging
            ? "ring-2 ring-primary scale-[1.01]"
            : "ring-1 ring-border hover:ring-input",
        )}
      >
        {preview && (
          <>
            {/* #t=0.1 nudges the decoder past frame zero, which is often blank. */}
            <video
              src={`${preview}#t=0.1`}
              muted
              playsInline
              preload="metadata"
              aria-hidden
              className="absolute inset-0 size-full object-contain"
            />
            {/* Captions have to stay legible over any frame. */}
            <span
              aria-hidden
              className="absolute inset-0 bg-gradient-to-t from-ink via-ink/30 to-ink/10"
            />
          </>
        )}

        {/* Frame furniture: a corner marker, the way a slate or viewfinder has. */}
        <Badge
          variant="outline"
          aria-hidden
          className="absolute end-3 top-3 border-paper/25 bg-ink/40 font-mono text-[0.625rem] tracking-[0.18em] text-paper/70 uppercase backdrop-blur-sm"
        >
          {file ? <FilmIcon data-icon="inline-start" /> : null}
          {file ? "source" : "no source"}
        </Badge>

        <p
          className={cn(
            "caption-text relative z-10 px-6 pb-[9%] text-center text-lg leading-snug font-medium sm:text-xl",
            tone === "failed"
              ? "text-destructive"
              : tone === "idle" && !file
                ? "text-paper/70"
                : "text-caption",
          )}
        >
          {caption}
        </p>

        {!file && (
          // Two lines on purpose: the instruction reads as a sentence, the
          // formats as a spec. One line wraps and drops the icon mid-phrase.
          <span className="relative z-10 flex flex-col items-center gap-1 px-6 pb-4 text-center font-mono tracking-wide">
            <span className="flex items-center gap-1.5 text-[0.6875rem] text-paper/65">
              <UploadCloudIcon className="size-3.5" aria-hidden />
              drag it in, or click to browse
            </span>
            <span className="text-[0.625rem] text-paper/40">
              mp4 · mov · mkv · mp3 · wav
            </span>
          </span>
        )}

        {/* Progress lives on the frame edge, like a playhead on a scrubber. */}
        <span
          aria-hidden
          className={cn(
            "absolute inset-x-0 bottom-0 h-px overflow-hidden bg-border",
            busy ? "" : "opacity-0",
          )}
        >
          <span className="playhead block h-full w-1/4 bg-primary" />
        </span>
      </label>

      {/* The slate: what the file is, in the font data belongs in. */}
      <div className="flex flex-wrap items-center gap-1.5">
        {file ? (
          <>
            <Tooltip>
              <TooltipTrigger asChild>
                <Badge
                  variant="outline"
                  className="max-w-[22ch] font-mono text-[0.6875rem]"
                >
                  <span className="truncate" dir="auto">
                    {file.name}
                  </span>
                </Badge>
              </TooltipTrigger>
              <TooltipContent>{file.name}</TooltipContent>
            </Tooltip>

            <Badge
              variant="ghost"
              className="font-mono text-[0.6875rem] text-muted-foreground"
            >
              <HardDriveIcon data-icon="inline-start" aria-hidden />
              {(file.size / 1024 / 1024).toFixed(1)} MB
            </Badge>

            {upload && (
              <>
                <Badge
                  variant="ghost"
                  className="font-mono text-[0.6875rem] text-muted-foreground"
                >
                  <ClockIcon data-icon="inline-start" aria-hidden />
                  {formatDuration(upload.duration)}
                </Badge>
                {/* A missing audio track is the single best predictor of an
                    empty transcript, so it is the one chip that shouts. */}
                <Badge
                  variant={upload.has_audio ? "ghost" : "destructive"}
                  className="font-mono text-[0.6875rem]"
                >
                  {upload.has_audio ? (
                    <AudioLinesIcon data-icon="inline-start" aria-hidden />
                  ) : (
                    <VolumeXIcon data-icon="inline-start" aria-hidden />
                  )}
                  {upload.has_audio ? "audio track" : "no audio track"}
                </Badge>
              </>
            )}
          </>
        ) : (
          <Badge
            variant="ghost"
            className="font-mono text-[0.6875rem] text-muted-foreground"
          >
            awaiting a file
          </Badge>
        )}
      </div>
    </div>
  );
}
