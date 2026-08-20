"use client";

import { useState } from "react";
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
 * caption line, in the lower third and in caption yellow, says what the run is
 * doing; the slate strip underneath says what the file is.
 */
export function Letterbox({ file, upload, preview, caption, tone, busy, onFile, onReject }: Props) {
  const [dragging, setDragging] = useState(false);

  const accept = (candidate: File | undefined) => {
    if (!candidate) return;
    if (!candidate.type.startsWith("video/") && !candidate.type.startsWith("audio/")) {
      onReject(`${candidate.name} is not a video or audio file.`);
      return;
    }
    onFile(candidate);
  };

  const captionTone =
    tone === "failed" ? "text-alert" : tone === "idle" && !file ? "text-paper/70" : "text-caption";

  return (
    <div>
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
        className={`control safe-area relative flex aspect-video w-full cursor-pointer flex-col justify-end overflow-hidden rounded-sm bg-ink transition-colors focus-within:outline focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-caption ${
          dragging ? "ring-2 ring-caption" : "ring-1 ring-edge"
        }`}
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
        <span
          aria-hidden
          className="absolute end-3 top-3 font-mono text-[0.625rem] uppercase tracking-[0.2em] text-paper/60"
        >
          {file ? "source" : "no source"}
        </span>

        <p
          className={`caption-text relative z-10 px-6 pb-[9%] text-center text-lg leading-snug font-medium sm:text-xl ${captionTone}`}
        >
          {caption}
        </p>

        {!file && (
          <span className="relative z-10 px-12 pb-4 text-center font-mono text-[0.6875rem] tracking-wide text-paper/60">
            drag it in, or click to browse · mp4 mov mkv mp3 wav
          </span>
        )}

        {/* Progress lives on the frame edge, like a playhead on a scrubber. */}
        <span
          aria-hidden
          className={`absolute inset-x-0 bottom-0 h-px overflow-hidden bg-edge ${busy ? "" : "opacity-0"}`}
        >
          <span className="playhead block h-full w-1/4 bg-caption" />
        </span>
      </label>

      {/* The slate: what the file is, in the font data belongs in. */}
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[0.6875rem] text-muted">
        {file ? (
          <>
            <span className="max-w-[22ch] truncate text-paper" title={file.name} dir="auto">
              {file.name}
            </span>
            <span aria-hidden>·</span>
            <span>{(file.size / 1024 / 1024).toFixed(1)} MB</span>
            {upload && (
              <>
                <span aria-hidden>·</span>
                <span>{formatDuration(upload.duration)}</span>
                <span aria-hidden>·</span>
                <span className={upload.has_audio ? "" : "text-alert"}>
                  {upload.has_audio ? "audio track" : "no audio track"}
                </span>
              </>
            )}
          </>
        ) : (
          <span>awaiting a file</span>
        )}
      </div>
    </div>
  );
}
