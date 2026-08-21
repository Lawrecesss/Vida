/**
 * Turning the SRT the API returns back into structured cues.
 *
 * The server already owns subtitle formatting, so the UI never builds SRT — it
 * only reads it back to display timings the user can check against the video.
 */

export type Cue = {
  index: number;
  start: string;
  end: string;
  text: string;
};

const CUE_TIMING = /^(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})/;

/**
 * Parse an SRT body into cues, tolerating CRLF and a missing trailing newline.
 * Returns an empty array for anything that is not SRT, so callers can fall back
 * to rendering plain text rather than showing nothing.
 */
export function parseSrt(srt: string): Cue[] {
  if (!srt) return [];

  const cues: Cue[] = [];
  for (const block of srt.replace(/\r\n/g, "\n").trim().split(/\n{2,}/)) {
    const lines = block.split("\n");
    // The counter line is optional in the wild; find the timing line instead.
    const timingAt = lines.findIndex((line) => CUE_TIMING.test(line));
    if (timingAt === -1) continue;

    const timing = lines[timingAt].match(CUE_TIMING);
    if (!timing) continue;

    const text = lines
      .slice(timingAt + 1)
      .join("\n")
      .trim();
    if (!text) continue;

    cues.push({
      index: cues.length + 1,
      start: timing[1].replace(".", ","),
      end: timing[2].replace(".", ","),
      text,
    });
  }

  return cues;
}

/** `00:01:23,456` → `01:23` — enough precision for a cue list. */
export function shortTimecode(timecode: string): string {
  const match = timecode.match(/^(\d{2}):(\d{2}):(\d{2})/);
  if (!match) return timecode;
  const [, hours, minutes, seconds] = match;
  return hours === "00" ? `${minutes}:${seconds}` : `${hours}:${minutes}:${seconds}`;
}

/** Seconds → `m:ss`, for durations reported by the upload endpoint. */
export function formatDuration(seconds: number): string {
  const total = Math.round(seconds);
  const minutes = Math.floor(total / 60);
  return `${minutes}:${(total % 60).toString().padStart(2, "0")}`;
}

export function downloadText(filename: string, body: string) {
  const url = URL.createObjectURL(new Blob([body], { type: "text/plain" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

/** `talk.mp4` + `Spanish` → `talk.spanish.srt`, matching what the SDK writes. */
export function subtitleFilename(source: string | undefined, language: string): string {
  const stem = (source ?? "subtitles").replace(/\.[^.]+$/, "");
  return `${stem}.${language.toLowerCase().replace(/\s+/g, "-")}.srt`;
}

/**
 * BCP-47 tags for the languages the UI offers, so translated tracks carry a
 * `lang` attribute. Screen readers switch voice on it, and without it Arabic
 * gets read with an English pronunciation engine.
 */
const LANGUAGE_TAGS: Record<string, string> = {
  Spanish: "es",
  French: "fr",
  German: "de",
  Japanese: "ja",
  Korean: "ko",
  Chinese: "zh",
  Burmese: "my",
  Thai: "th",
  Hindi: "hi",
  Arabic: "ar",
  Portuguese: "pt",
};

export function languageTag(name: string): string | undefined {
  return LANGUAGE_TAGS[name];
}

/** `00:01:23,456` → `83.456`. Returns NaN for anything unparseable. */
export function timecodeToSeconds(timecode: string): number {
  const match = timecode.match(/^(\d{2}):(\d{2}):(\d{2})[,.](\d{3})$/);
  if (!match) return NaN;
  const [, h, m, s, ms] = match;
  return +h * 3600 + +m * 60 + +s + +ms / 1000;
}

/** `83.456` → `00:01:23,456`, clamped at zero so a nudge cannot go negative. */
export function secondsToTimecode(seconds: number): string {
  const total = Math.max(0, seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = Math.floor(total % 60);
  const ms = Math.round((total - Math.floor(total)) * 1000);
  const p = (n: number, width = 2) => n.toString().padStart(width, "0");
  return `${p(h)}:${p(m)}:${p(s)},${p(ms, 3)}`;
}

/**
 * Cues back to an SRT body.
 *
 * The server owns subtitle formatting everywhere else, but once the user edits
 * a cue there is no round trip to ask — the file they download has to be built
 * from what is on screen. Indices are renumbered from 1 so a deleted cue does
 * not leave a hole that some players choke on.
 */
export function buildSrt(cues: Cue[]): string {
  return (
    cues
      .map((cue, i) => `${i + 1}\n${cue.start} --> ${cue.end}\n${cue.text}`)
      .join("\n\n") + "\n"
  );
}

/** Characters per second — the reading-speed number subtitlers actually check. */
export function charsPerSecond(cue: Cue): number {
  const span = timecodeToSeconds(cue.end) - timecodeToSeconds(cue.start);
  if (!(span > 0)) return 0;
  // Line breaks are not read, so they do not count against the budget.
  return cue.text.replace(/\s+/g, " ").length / span;
}

/**
 * 17 chars/sec is the usual adult reading-speed ceiling for subtitles (it is
 * what Netflix's English timed-text spec allows). Past it, a cue is on screen
 * too briefly to finish reading.
 */
export const CPS_LIMIT = 17;
