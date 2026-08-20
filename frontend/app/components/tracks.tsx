"use client";

import { useRef, ViewTransition } from "react";
import { parseSrt, shortTimecode } from "../lib/subtitles";

export type Track = {
  id: string;
  label: string;
  /** Subtitle tracks render as cues; the analysis is prose and says so. */
  kind: "subtitle" | "analysis";
  text: string;
  srt?: string;
  /** BCP-47 tag, so screen readers pronounce a translation correctly. */
  lang?: string;
  emptyMessage: string;
};

const TONES = [
  "text-caption",
  "text-cyan",
  "text-mint",
  "text-orchid",
] as const;

/** Caption-palette colour per subtitle track; the analysis stays neutral. */
export function toneFor(track: Track, index: number): string {
  return track.kind === "analysis" ? "text-paper" : TONES[index % TONES.length];
}

const tabId = (id: string) => `track-tab-${id}`;
const panelId = (id: string) => `track-panel-${id}`;

type Props = {
  tracks: Track[];
  activeId: string;
  onSelect: (id: string) => void;
  onDownload: (track: Track) => void;
};

export function TrackPanel({ tracks, activeId, onSelect, onDownload }: Props) {
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  const activeIndex = Math.max(
    0,
    tracks.findIndex((track) => track.id === activeId),
  );
  const active = tracks[activeIndex];
  const cues = active?.srt ? parseSrt(active.srt) : [];

  // Arrow keys move between tabs, Home/End jump to the ends. Without this a
  // tablist is a worse keyboard experience than plain buttons would have been.
  const onKeyDown = (event: React.KeyboardEvent) => {
    const last = tracks.length - 1;
    const next =
      event.key === "ArrowRight"
        ? (activeIndex + 1) % tracks.length
        : event.key === "ArrowLeft"
          ? (activeIndex + last) % tracks.length
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? last
              : null;
    if (next === null) return;

    event.preventDefault();
    const target = tracks[next];
    onSelect(target.id);
    tabRefs.current[target.id]?.focus();
  };

  return (
    <section
      aria-labelledby="tracks-heading"
      className="flex min-h-[28rem] flex-col overflow-hidden rounded-sm border border-edge bg-panel lg:min-h-[34rem]"
    >
      <h2 id="tracks-heading" className="sr-only">
        Output tracks
      </h2>

      <div
        role="tablist"
        aria-label="Output tracks"
        onKeyDown={onKeyDown}
        className="flex flex-wrap items-center gap-1 border-b border-edge px-2 py-2"
      >
        {tracks.map((track, index) => {
          const selected = track.id === active?.id;
          return (
            <button
              key={track.id}
              id={tabId(track.id)}
              ref={(node) => {
                tabRefs.current[track.id] = node;
              }}
              role="tab"
              aria-selected={selected}
              aria-controls={panelId(track.id)}
              tabIndex={selected ? 0 : -1}
              onClick={() => onSelect(track.id)}
              className={`flex items-center gap-2 rounded-sm px-3 py-1.5 text-[0.875rem] transition-colors ${
                selected
                  ? "bg-raised text-paper"
                  : "text-muted hover:bg-raised/60 hover:text-paper"
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

      {!active ? null : (
        <ViewTransition
          key={active.id}
          default="none"
          enter="fade-in"
          exit="fade-out"
        >
          <div
            id={panelId(active.id)}
            role="tabpanel"
            aria-labelledby={tabId(active.id)}
            // Focusable so a keyboard user can scroll a long cue list.
            tabIndex={0}
            className="flex min-h-0 flex-1 flex-col"
          >
            {active.kind === "analysis" ? (
              <div className="flex-1 overflow-y-auto px-6 py-6">
                <p className="mb-3 font-mono text-[0.6875rem] uppercase tracking-[0.18em] text-muted">
                  What the video shows
                </p>
                {active.text ? (
                  <p className="wrap-anywhere max-w-[68ch] whitespace-pre-wrap text-[0.9375rem] leading-7 text-paper/90">
                    {active.text}
                  </p>
                ) : (
                  <p className="max-w-[52ch] text-[0.875rem] leading-6 text-muted">
                    {active.emptyMessage}
                  </p>
                )}
              </div>
            ) : (
              <>
                <div className="flex items-center justify-between border-b border-edge px-4 py-2">
                  <p className="font-mono text-[0.6875rem] text-muted">
                    {cues.length > 0 ? `${cues.length} cues` : "no cues"}
                  </p>
                  {active.srt && cues.length > 0 && (
                    <button
                      onClick={() => onDownload(active)}
                      className="rounded-sm border border-line px-3 py-1 font-mono text-[0.6875rem] text-paper transition-colors hover:border-caption hover:text-caption"
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
                          className="grid grid-cols-[2.5rem_1fr] items-baseline gap-x-3 border-b border-edge/60 px-4 py-2.5 transition-colors hover:bg-raised/40 sm:grid-cols-[2.5rem_9rem_1fr]"
                        >
                          <span className="font-mono text-[0.6875rem] tabular-nums text-muted">
                            {cue.index.toString().padStart(2, "0")}
                          </span>
                          <span
                            className={`font-mono text-[0.6875rem] tabular-nums ${toneFor(active, activeIndex)}`}
                          >
                            {shortTimecode(cue.start)}
                            <span className="px-1 text-muted" aria-hidden>
                              →
                            </span>
                            {shortTimecode(cue.end)}
                          </span>
                          {/* dir="auto" so Arabic and other RTL translations read
                            correctly; lang so they are pronounced correctly. */}
                          <span
                            lang={active.lang}
                            dir="auto"
                            className="wrap-anywhere col-span-2 text-[0.9375rem] leading-6 text-paper/90 sm:col-span-1"
                          >
                            {cue.text}
                          </span>
                        </li>
                      ))}
                    </ol>
                  ) : active.text ? (
                    // A track with text but no parseable timings still has to render.
                    <p
                      lang={active.lang}
                      dir="auto"
                      className="wrap-anywhere whitespace-pre-wrap px-4 py-4 text-[0.9375rem] leading-7 text-paper/90"
                    >
                      {active.text}
                    </p>
                  ) : (
                    <p className="max-w-[52ch] px-4 py-6 text-[0.875rem] leading-6 text-muted">
                      {active.emptyMessage}
                    </p>
                  )}
                </div>
              </>
            )}
          </div>
        </ViewTransition>
      )}
    </section>
  );
}
