"use client";

import { parseSrt, shortTimecode } from "../lib/subtitles";

export type Track = {
  id: string;
  label: string;
  /** Subtitle tracks render as cues; the analysis is prose and says so. */
  kind: "subtitle" | "analysis";
  text: string;
  srt?: string;
  emptyMessage: string;
};

const TONES = ["text-caption", "text-cyan", "text-mint", "text-orchid"] as const;

/** Caption-palette colour per subtitle track; the analysis stays neutral. */
export function toneFor(track: Track, index: number): string {
  return track.kind === "analysis" ? "text-paper" : TONES[index % TONES.length];
}

type Props = {
  tracks: Track[];
  activeId: string;
  onSelect: (id: string) => void;
  onDownload: (track: Track) => void;
};

export function TrackPanel({ tracks, activeId, onSelect, onDownload }: Props) {
  const activeIndex = Math.max(
    0,
    tracks.findIndex((track) => track.id === activeId),
  );
  const active = tracks[activeIndex];
  const cues = active?.srt ? parseSrt(active.srt) : [];

  return (
    <section className="flex min-h-[28rem] flex-col overflow-hidden rounded-sm border border-edge bg-panel lg:min-h-[34rem]">
      <div
        role="tablist"
        aria-label="Output tracks"
        className="flex flex-wrap items-center gap-1 border-b border-edge px-2 py-2"
      >
        {tracks.map((track, index) => {
          const selected = track.id === active?.id;
          return (
            <button
              key={track.id}
              role="tab"
              aria-selected={selected}
              onClick={() => onSelect(track.id)}
              className={`group flex items-center gap-2 rounded-sm px-3 py-1.5 text-sm transition-colors ${
                selected ? "bg-raised text-paper" : "text-muted hover:bg-raised/60 hover:text-paper"
              }`}
            >
              <span
                aria-hidden
                className={`size-1.5 rounded-full bg-current ${toneFor(track, index)} ${
                  selected ? "" : "opacity-50"
                }`}
              />
              {track.label}
            </button>
          );
        })}
      </div>

      {!active ? null : active.kind === "analysis" ? (
        <div className="flex-1 overflow-y-auto px-6 py-6">
          <p className="mb-3 font-mono text-[11px] uppercase tracking-[0.18em] text-muted">
            What the video shows
          </p>
          {active.text ? (
            <p className="max-w-[68ch] whitespace-pre-wrap text-[15px] leading-7 text-paper/90">
              {active.text}
            </p>
          ) : (
            <p className="max-w-[52ch] text-sm leading-6 text-muted">{active.emptyMessage}</p>
          )}
        </div>
      ) : (
        <>
          <div className="flex items-center justify-between border-b border-edge px-4 py-2">
            <p className="font-mono text-[11px] text-muted">
              {cues.length > 0 ? `${cues.length} cues` : "no cues"}
            </p>
            {active.srt && cues.length > 0 && (
              <button
                onClick={() => onDownload(active)}
                className="rounded-sm border border-edge px-3 py-1 font-mono text-[11px] text-paper transition-colors hover:border-caption hover:text-caption"
              >
                Download .srt
              </button>
            )}
          </div>

          <div className="cue-list flex-1 overflow-y-auto">
            {cues.length > 0 ? (
              <ol>
                {cues.map((cue) => (
                  <li
                    key={cue.index}
                    className="group grid grid-cols-[2.5rem_1fr] items-baseline gap-x-3 border-b border-edge/60 px-4 py-2.5 transition-colors hover:bg-raised/40 sm:grid-cols-[2.5rem_9rem_1fr]"
                  >
                    <span className="font-mono text-[11px] tabular-nums text-muted/70">
                      {cue.index.toString().padStart(2, "0")}
                    </span>
                    <span
                      className={`font-mono text-[11px] tabular-nums ${toneFor(active, activeIndex)}`}
                    >
                      {shortTimecode(cue.start)}
                      <span className="px-1 text-muted/50">→</span>
                      {shortTimecode(cue.end)}
                    </span>
                    <span className="col-span-2 text-[15px] leading-6 text-paper/90 sm:col-span-1">
                      {cue.text}
                    </span>
                  </li>
                ))}
              </ol>
            ) : active.text ? (
              // A track with text but no parseable timings still has to render.
              <p className="whitespace-pre-wrap px-4 py-4 text-[15px] leading-7 text-paper/90">
                {active.text}
              </p>
            ) : (
              <p className="max-w-[52ch] px-4 py-6 text-sm leading-6 text-muted">
                {active.emptyMessage}
              </p>
            )}
          </div>
        </>
      )}
    </section>
  );
}
