"use client";

import { ViewTransition } from "react";
import {
  CaptionsOffIcon,
  DownloadIcon,
  EyeIcon,
  SearchXIcon,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
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

// Four bands of the prism, spread as far apart in hue as the source allows
// (36° / 168° / 210° / 340°) so two tracks are never confusable at a glance.
const TONES = [
  "text-caption",
  "text-teal",
  "text-blue",
  "text-magenta",
] as const;

/** Prism-palette colour per subtitle track; the analysis stays neutral. */
export function toneFor(track: Track, index: number): string {
  return track.kind === "analysis"
    ? "text-foreground"
    : TONES[index % TONES.length];
}

type Props = {
  tracks: Track[];
  activeId: string;
  onSelect: (id: string) => void;
  onDownload: (track: Track) => void;
};

/**
 * Output tracks, one tab each.
 *
 * The tablist is Radix's via shadcn `Tabs`, which is the whole reason this file
 * no longer hand-rolls arrow-key handling, roving tabindex, and the
 * aria-controls wiring — all of that is now the primitive's problem.
 */
export function TrackPanel({ tracks, activeId, onSelect, onDownload }: Props) {
  return (
    <Card
      aria-labelledby="tracks-heading"
      // Glass, not a slab: the backdrop's light bleeds through so the
      // panel sits *in* the room rather than on top of it. The blur
      // flattens whatever is behind, so cue text keeps full contrast.
      className="glass flex min-h-[28rem] flex-col gap-0 overflow-hidden p-0 lg:min-h-[34rem]"
    >
      <h2 id="tracks-heading" className="sr-only">
        Output tracks
      </h2>

      <Tabs
        value={activeId}
        onValueChange={onSelect}
        className="flex min-h-0 flex-1 flex-col gap-0"
      >
        <TabsList
          variant="line"
          aria-label="Output tracks"
          // The height override needs the same variant prefix the component
          // uses (`group-data-horizontal/tabs:h-8`) or it loses to it, and a
          // wrapped second row of tabs spills into the cue list below.
          // Eight tracks is an ordinary run here, so it wraps often.
          className="h-auto w-full flex-wrap justify-start gap-x-1 gap-y-1.5 border-b px-2 py-2 group-data-horizontal/tabs:h-auto"
        >
          {tracks.map((track, index) => {
            const selected = track.id === activeId;
            return (
              <TabsTrigger
                key={track.id}
                value={track.id}
                className={cn(
                  "flex-none data-active:after:bg-current",
                  selected && toneFor(track, index),
                )}
              >
                <span
                  aria-hidden
                  className={cn(
                    "size-1.5 rounded-full bg-current",
                    toneFor(track, index),
                    selected ? "" : "opacity-50",
                  )}
                />
                {track.label}
              </TabsTrigger>
            );
          })}
        </TabsList>

        {/* One transition for the whole panel, keyed on which track is
            showing — not one per TabsContent. Per-content transitions fire
            when a *hidden* panel mounts mid-run, and the browser paints that
            snapshot over the panel: a new translation arriving made the
            visible track flash to the new one and back. */}
        <ViewTransition
          key={activeId}
          default="none"
          enter="fade-in"
          exit="fade-out"
        >
          <div className="flex min-h-0 flex-1 flex-col">
            {tracks.map((track, index) => (
              <TabsContent
                key={track.id}
                value={track.id}
                className="flex min-h-0 flex-1 flex-col"
              >
                <TrackBody
                  track={track}
                  tone={toneFor(track, index)}
                  onDownload={() => onDownload(track)}
                />
              </TabsContent>
            ))}
          </div>
        </ViewTransition>
      </Tabs>
    </Card>
  );
}

/**
 * Kept separate so the SRT is only parsed for the track actually on screen —
 * Radix unmounts the inactive panels, so this never runs for them.
 */
function TrackBody({
  track,
  tone,
  onDownload,
}: {
  track: Track;
  tone: string;
  onDownload: () => void;
}) {
  if (track.kind === "analysis") {
    return (
      <ScrollArea className="min-h-0 flex-1">
        <div className="px-6 py-6">
          <p className="mb-3 flex items-center gap-2 font-mono text-[0.6875rem] tracking-[0.18em] text-muted-foreground uppercase">
            <EyeIcon className="size-3.5" aria-hidden />
            What the video shows
          </p>
          {track.text ? (
            <p className="wrap-anywhere max-w-[68ch] text-[0.9375rem] leading-7 whitespace-pre-wrap text-foreground/90">
              {track.text}
            </p>
          ) : (
            <Empty className="border-0">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <SearchXIcon />
                </EmptyMedia>
                <EmptyTitle>Nothing to describe</EmptyTitle>
                <EmptyDescription>{track.emptyMessage}</EmptyDescription>
              </EmptyHeader>
            </Empty>
          )}
        </div>
      </ScrollArea>
    );
  }

  const cues = track.srt ? parseSrt(track.srt) : [];

  return (
    <>
      <div className="flex items-center justify-between gap-2 px-4 py-2">
        <Badge variant="ghost" className="font-mono text-[0.6875rem]">
          {cues.length > 0 ? `${cues.length} cues` : "no cues"}
        </Badge>
        {track.srt && cues.length > 0 && (
          <Button variant="outline" size="sm" onClick={onDownload}>
            <DownloadIcon data-icon="inline-start" aria-hidden />
            Download .srt
          </Button>
        )}
      </div>
      <Separator />

      <ScrollArea className="min-h-0 flex-1">
        {cues.length > 0 ? (
          <ol>
            {cues.map((cue) => (
              <li
                key={cue.index}
                className="grid grid-cols-[2.5rem_1fr] items-baseline gap-x-3 border-b px-4 py-2.5 transition-colors last:border-b-0 hover:bg-muted/40 sm:grid-cols-[2.5rem_9rem_1fr]"
              >
                <span className="font-mono text-[0.6875rem] tabular-nums text-muted-foreground">
                  {cue.index.toString().padStart(2, "0")}
                </span>
                <span
                  className={cn(
                    "font-mono text-[0.6875rem] tabular-nums",
                    tone,
                  )}
                >
                  {shortTimecode(cue.start)}
                  <span className="px-1 text-muted-foreground" aria-hidden>
                    →
                  </span>
                  {shortTimecode(cue.end)}
                </span>
                {/* dir="auto" so Arabic and other RTL translations read
                    correctly; lang so they are pronounced correctly. */}
                <span
                  lang={track.lang}
                  dir="auto"
                  className="wrap-anywhere col-span-2 text-[0.9375rem] leading-6 text-foreground/90 sm:col-span-1"
                >
                  {cue.text}
                </span>
              </li>
            ))}
          </ol>
        ) : track.text ? (
          // A track with text but no parseable timings still has to render.
          <p
            lang={track.lang}
            dir="auto"
            className="wrap-anywhere px-4 py-4 text-[0.9375rem] leading-7 whitespace-pre-wrap text-foreground/90"
          >
            {track.text}
          </p>
        ) : (
          <Empty className="border-0 py-10">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <CaptionsOffIcon />
              </EmptyMedia>
              <EmptyTitle>No cues on this track</EmptyTitle>
              <EmptyDescription>{track.emptyMessage}</EmptyDescription>
            </EmptyHeader>
          </Empty>
        )}
      </ScrollArea>
    </>
  );
}
