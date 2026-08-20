"use client";

import {
  startTransition,
  useCallback,
  useRef,
  useState,
  ViewTransition,
} from "react";
import { Letterbox, type UploadInfo } from "./components/letterbox";
import { TrackPanel, type Track } from "./components/tracks";
import { downloadText, languageTag, subtitleFilename } from "./lib/subtitles";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

const LANGUAGES = [
  "Spanish",
  "French",
  "German",
  "Japanese",
  "Korean",
  "Chinese",
  "Burmese",
  "Thai",
  "Hindi",
  "Arabic",
  "Portuguese",
];

type Status =
  "idle" | "uploading" | "working" | "done" | "cancelled" | "failed";

type Translation = { language: string; text: string; srt: string };

const NO_SPEECH =
  "No speech was detected. Silent clips, music, and background noise all produce an empty transcript.";

export default function Home() {
  const [file, setFile] = useState<File | null>(null);
  // The frame shows the real video, so the page keeps an object URL alongside
  // the file and revokes the previous one whenever the choice changes.
  const [preview, setPreview] = useState<string | null>(null);
  const [upload, setUpload] = useState<UploadInfo | null>(null);
  const [status, setStatus] = useState<Status>("idle");
  const [stage, setStage] = useState("");
  const [error, setError] = useState("");

  const [wantTranscript, setWantTranscript] = useState(true);
  const [wantAnalysis, setWantAnalysis] = useState(false);
  const [targets, setTargets] = useState<string[]>([]);
  const [query, setQuery] = useState("");

  const [transcript, setTranscript] = useState("");
  const [transcriptSrt, setTranscriptSrt] = useState("");
  const [detectedLanguage, setDetectedLanguage] = useState("");
  const [translations, setTranslations] = useState<Translation[]>([]);
  const [summary, setSummary] = useState("");
  // A stage that ran and produced nothing still deserves a track: without this
  // we cannot tell "no analysis requested" from "analysed, found nothing".
  const [transcribed, setTranscribed] = useState(false);
  const [analyzed, setAnalyzed] = useState(false);
  const [activeTab, setActiveTab] = useState("");

  const abortRef = useRef<AbortController | null>(null);
  const busy = status === "uploading" || status === "working";
  const nothingSelected =
    !wantTranscript && !wantAnalysis && targets.length === 0;

  const reset = () => {
    setTranscript("");
    setTranscriptSrt("");
    setTranslations([]);
    setSummary("");
    setTranscribed(false);
    setAnalyzed(false);
    setDetectedLanguage("");
    setError("");
    setStage("");
  };

  const chooseFile = (chosen: File) => {
    if (preview) URL.revokeObjectURL(preview);
    setPreview(URL.createObjectURL(chosen));
    setFile(chosen);
    setUpload(null);
    setStatus("idle");
    reset();
  };

  const toggleTarget = (language: string) => {
    setTargets((current) =>
      current.includes(language)
        ? current.filter((item) => item !== language)
        : [...current, language],
    );
  };

  const run = useCallback(async () => {
    if (!file) return;

    abortRef.current = new AbortController();
    const { signal } = abortRef.current;
    reset();
    setStatus("uploading");

    try {
      let media = upload;

      // Skip re-uploading if this file is already on the server.
      if (!media) {
        const form = new FormData();
        form.append("file", file);
        const response = await fetch(`${API_BASE}/upload`, {
          method: "POST",
          body: form,
          signal,
        });
        if (!response.ok) {
          throw new Error(
            (await response.json()).detail ?? "The upload was rejected.",
          );
        }
        media = (await response.json()) as UploadInfo;
        setUpload(media);
      }

      setStatus("working");
      setStage("starting");

      const response = await fetch(`${API_BASE}/process/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          video_path: media.video_path,
          transcribe: wantTranscript || targets.length > 0,
          analyze: wantAnalysis,
          translate_to: targets,
          query: query.trim() || null,
        }),
        signal,
      });
      if (!response.ok || !response.body) {
        throw new Error("The server rejected the request.");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      // SSE frames can straddle a network read, so hold a buffer and only
      // consume complete `\n\n`-terminated frames.
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";

        for (const frame of frames) {
          const line = frame.trim();
          if (!line.startsWith("data: ")) continue;
          const payload = line.slice(6);
          if (payload === "[DONE]") continue;

          const event = JSON.parse(payload);
          switch (event.event) {
            case "status":
              setStage(
                event.language
                  ? `translating → ${event.language}`
                  : event.stage,
              );
              break;
            case "transcript":
              startTransition(() => {
                setTranscript(event.text);
                setTranscriptSrt(event.srt ?? "");
                setDetectedLanguage(event.language ?? "");
                setTranscribed(true);
                if (event.text) setActiveTab("source");
              });
              break;
            case "translation":
              startTransition(() => {
                setTranslations((current) => [
                  ...current,
                  {
                    language: event.language,
                    text: event.text,
                    srt: event.srt,
                  },
                ]);
              });
              break;
            case "analysis":
              startTransition(() => {
                setSummary(event.summary);
                setAnalyzed(true);
              });
              break;
            case "error":
              throw new Error(event.detail);
          }
        }
      }

      setStage("");
      setStatus("done");
    } catch (caught: unknown) {
      if (caught instanceof Error && caught.name === "AbortError") {
        setStatus("cancelled");
        return;
      }
      const reason = caught instanceof Error ? caught.message : String(caught);
      setError(
        // fetch() rejects with a bare TypeError when the API is unreachable —
        // wrong host, backend down, CORS. Name the thing to check.
        caught instanceof TypeError
          ? `Could not reach the API at ${API_BASE}. Check that the backend is running and that this origin is allowed.`
          : reason,
      );
      setStatus("failed");
    }
  }, [file, upload, wantTranscript, wantAnalysis, targets, query]);

  const tracks: Track[] = [
    ...(transcribed
      ? [
          {
            id: "source",
            label: detectedLanguage ? `Source (${detectedLanguage})` : "Source",
            kind: "subtitle" as const,
            text: transcript,
            srt: transcriptSrt,
            lang: detectedLanguage || undefined,
            emptyMessage: NO_SPEECH,
          },
        ]
      : []),
    ...translations.map((item) => ({
      id: item.language,
      label: item.language,
      kind: "subtitle" as const,
      text: item.text,
      srt: item.srt,
      lang: languageTag(item.language),
      emptyMessage: `Nothing came back for ${item.language}. The source transcript was empty, so there was nothing to translate.`,
    })),
    ...(analyzed
      ? [
          {
            id: "analysis",
            label: "Analysis",
            kind: "analysis" as const,
            text: summary,
            emptyMessage:
              "The analysis came back empty. Try again, or ask a specific question to focus it.",
          },
        ]
      : []),
  ];

  // What the user picked, if it is still on screen; otherwise the first track
  // with something in it. Landing on an empty track while a filled one sits
  // next to it is how a silent video came to look like a total failure.
  const visibleTrack =
    tracks.find((track) => track.id === activeTab) ??
    tracks.find((track) => track.text) ??
    tracks[0];

  const caption = (() => {
    if (status === "failed") return "Run failed";
    if (status === "cancelled") return "Cancelled";
    if (status === "uploading") return "Uploading";
    if (status === "working") {
      if (!stage || stage === "starting") return "Starting";
      const [verb, language] = stage.split(" → ");
      const titled = verb.charAt(0).toUpperCase() + verb.slice(1);
      return language ? `${titled} → ${language}` : titled;
    }
    if (status === "done") {
      return `Done · ${tracks.length} ${tracks.length === 1 ? "track" : "tracks"}`;
    }
    return file ? "Ready to generate" : "Drop a video here";
  })();

  const captionTone =
    status === "failed"
      ? "failed"
      : busy
        ? "running"
        : status === "done"
          ? "done"
          : "idle";

  const actionLabel =
    wantAnalysis && !wantTranscript && targets.length === 0
      ? "Analyze video"
      : "Generate subtitles";

  return (
    <div className="min-h-svh bg-stage">
      <header className="border-b border-edge">
        <div className="mx-auto flex max-w-6xl flex-wrap items-end justify-between gap-4 px-6 py-6">
          <div>
            <h1 className="font-display text-3xl font-extrabold leading-none tracking-[-0.03em] text-paper">
              Vida
            </h1>
            <p className="mt-2 text-sm text-muted">
              Subtitles in any language, with the timing intact.
            </p>
          </div>
          <p className="font-mono text-[0.6875rem] text-muted">
            <span className="text-muted">api</span>{" "}
            {API_BASE.replace(/^https?:\/\//, "")}
          </p>
        </div>
      </header>

      <main
        id="main"
        className="mx-auto grid max-w-6xl gap-8 px-6 py-8 lg:grid-cols-[minmax(0,460px)_1fr] lg:items-start lg:gap-10"
      >
        <div className="space-y-7 lg:sticky lg:top-8 lg:border-e lg:border-edge lg:pe-10">
          <h2 className="sr-only">Job setup</h2>
          <Letterbox
            file={file}
            upload={upload}
            preview={preview}
            caption={caption}
            tone={captionTone}
            busy={busy}
            onFile={chooseFile}
            onReject={(message) => {
              setError(message);
              setStatus("failed");
            }}
          />

          <fieldset>
            <legend className="mb-3 font-mono text-[0.6875rem] uppercase tracking-[0.18em] text-muted">
              Output
            </legend>
            <div className="space-y-2">
              <Toggle
                checked={wantTranscript}
                onChange={setWantTranscript}
                label="Transcript"
                hint="Timed cues in the spoken language"
              />
              <Toggle
                checked={wantAnalysis}
                onChange={setWantAnalysis}
                label="Visual analysis"
                hint="A description of what the video shows"
              />
            </div>
          </fieldset>

          <fieldset>
            <legend className="mb-3 font-mono text-[0.6875rem] uppercase tracking-[0.18em] text-muted">
              Translate into
            </legend>
            <div className="flex flex-wrap gap-1.5">
              {LANGUAGES.map((language) => {
                const selected = targets.includes(language);
                return (
                  <button
                    key={language}
                    type="button"
                    aria-pressed={selected}
                    onClick={() => toggleTarget(language)}
                    className={`rounded-sm border px-2.5 py-1.5 text-[0.8125rem] transition-colors ${
                      selected
                        ? "border-caption bg-caption/15 text-caption"
                        : "border-line text-muted hover:border-muted hover:text-paper"
                    }`}
                  >
                    {language}
                  </button>
                );
              })}
            </div>
          </fieldset>

          {wantAnalysis && (
            <div>
              <label
                htmlFor="focus"
                className="mb-2 block font-mono text-[0.6875rem] uppercase tracking-[0.18em] text-muted"
              >
                Focus the analysis
              </label>
              <input
                id="focus"
                type="text"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="What should it look for?"
                className="w-full rounded-sm border border-line bg-panel px-3 py-2 text-sm text-paper outline-none placeholder:text-muted focus:border-caption"
              />
            </div>
          )}

          <div className="space-y-3">
            <div className="flex gap-2">
              <button
                onClick={run}
                disabled={!file || busy || nothingSelected}
                className={`flex-1 rounded-sm px-5 py-2.5 text-sm font-semibold transition-colors ${
                  !file || busy || nothingSelected
                    ? "cursor-not-allowed border border-line text-muted"
                    : "bg-caption text-ink hover:bg-caption/90"
                }`}
              >
                {busy ? "Working…" : actionLabel}
              </button>
              {busy && (
                <button
                  onClick={() => abortRef.current?.abort()}
                  className="rounded-sm border border-line px-4 py-2.5 text-sm font-medium text-muted transition-colors hover:border-alert hover:text-alert"
                >
                  Cancel
                </button>
              )}
            </div>

            {nothingSelected && file && (
              <p className="text-[0.8125rem] text-muted">
                Pick at least one output to generate.
              </p>
            )}

            <p role="status" aria-live="polite" className="sr-only">
              {caption}
            </p>

            {status === "failed" && error && (
              <p
                role="alert"
                className="wrap-anywhere rounded-sm border border-alert/40 bg-alert/10 px-3 py-2 text-[0.8125rem] leading-5 text-alert"
              >
                {error}
              </p>
            )}
          </div>
        </div>

        {tracks.length > 0 ? (
          <ViewTransition key="tracks" default="none" enter="slide-up">
            <TrackPanel
              tracks={tracks}
              activeId={visibleTrack?.id ?? ""}
              onSelect={(id) => startTransition(() => setActiveTab(id))}
              onDownload={(track) =>
                downloadText(
                  subtitleFilename(
                    upload?.filename,
                    track.id === "source"
                      ? detectedLanguage || "source"
                      : track.label,
                  ),
                  track.srt ?? "",
                )
              }
            />
          </ViewTransition>
        ) : (
          <ViewTransition key="skeleton" default="none" exit="slide-down">
            <section className="flex min-h-[28rem] flex-col rounded-sm border border-edge bg-panel/40 lg:min-h-[34rem]">
              <div className="border-b border-edge px-4 py-2">
                <p className="font-mono text-[0.6875rem] text-muted">no cues</p>
              </div>
              <ol aria-hidden className="select-none">
                {[1, 2, 3, 4, 5].map((row) => (
                  <li
                    key={row}
                    className="grid grid-cols-[2.5rem_9rem_1fr] items-baseline gap-x-3 border-b border-edge/40 px-4 py-2.5 font-mono text-[0.6875rem] text-muted/25"
                  >
                    <span>{row.toString().padStart(2, "0")}</span>
                    <span>--:-- → --:--</span>
                    <span
                      className="h-1.5 rounded-full bg-current"
                      style={{ width: `${70 - row * 9}%` }}
                    />
                  </li>
                ))}
              </ol>
              <p className="max-w-[42ch] px-4 py-6 text-sm leading-6 text-muted">
                Every language you pick becomes a track here, with timecodes you
                can check against the video and an .srt to download.
              </p>
            </section>
          </ViewTransition>
        )}
      </main>

      <footer className="mx-auto max-w-6xl px-6 pb-10 pt-2">
        <p className="wrap-anywhere font-mono text-[0.6875rem] text-muted">
          Powered by{" "}
          <a
            href="https://pypi.org/project/vida-sdk/"
            className="text-muted underline-offset-4 hover:text-caption hover:underline"
          >
            vida-sdk
          </a>
          . Files are processed on your own server.
        </p>
      </footer>
    </div>
  );
}

function Toggle({
  checked,
  onChange,
  label,
  hint,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label: string;
  hint: string;
}) {
  return (
    <label
      className={`flex cursor-pointer items-start gap-3 rounded-sm border px-3 py-2.5 transition-colors ${
        checked
          ? "border-caption/50 bg-caption/5"
          : "border-edge hover:border-muted/60"
      }`}
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="sr-only"
      />
      <span
        aria-hidden
        className={`mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-[3px] border transition-colors ${
          checked ? "border-caption bg-caption" : "border-muted/60"
        }`}
      >
        {checked && (
          <svg
            viewBox="0 0 10 8"
            className="size-2.5 fill-none stroke-ink stroke-2"
          >
            <path
              d="M1 4l2.5 2.5L9 1"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        )}
      </span>
      <span>
        <span className="block text-sm text-paper">{label}</span>
        <span className="mt-0.5 block text-[0.75rem] leading-4 text-muted">
          {hint}
        </span>
      </span>
    </label>
  );
}
