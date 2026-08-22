"use client";

import {
  startTransition,
  useCallback,
  useRef,
  useState,
  ViewTransition,
} from "react";
import {
  AlertCircleIcon,
  ArrowUpRightIcon,
  PencilIcon,
  CaptionsIcon,
  LanguagesIcon,
  ServerIcon,
  SparklesIcon,
  SquareIcon,
  WandSparklesIcon,
  XIcon,
} from "lucide-react";
import { toast } from "sonner";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
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
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { ThemeToggle } from "./components/theme-toggle";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { CHIP, SEGMENT } from "./lib/ui";
import { Letterbox, type UploadInfo } from "./components/letterbox";
import { TrackPanel, type Track } from "./components/tracks";
import { Editor } from "./components/editor";
import {
  buildSrt,
  downloadText,
  languageTag,
  parseSrt,
  subtitleFilename,
  type Cue,
} from "./lib/subtitles";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

// Source languages are ISO-639-1 codes because that is what the ASR model
// takes; the translate list below is free text because that goes to an LLM.
// Whisper knows a hundred languages — these are the ones worth a click.
const SOURCE_LANGUAGES = [
  { code: "ar", label: "Arabic" },
  { code: "my", label: "Burmese" },
  { code: "zh", label: "Chinese" },
  { code: "en", label: "English" },
  { code: "fr", label: "French" },
  { code: "de", label: "German" },
  { code: "hi", label: "Hindi" },
  { code: "id", label: "Indonesian" },
  { code: "it", label: "Italian" },
  { code: "ja", label: "Japanese" },
  { code: "ko", label: "Korean" },
  { code: "ms", label: "Malay" },
  { code: "pt", label: "Portuguese" },
  { code: "ru", label: "Russian" },
  { code: "es", label: "Spanish" },
  { code: "tl", label: "Tagalog" },
  { code: "th", label: "Thai" },
  { code: "vi", label: "Vietnamese" },
];

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
  | "idle"
  | "uploading"
  | "working"
  | "done"
  | "cancelled"
  | "failed";

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
  // "auto" leaves it to Whisper's detector, which is the weakest step in the
  // pipeline: on noisy speech it has called the same recording English, Malay,
  // and Burmese depending on which 30 seconds it heard. Naming the language
  // skips the guess entirely.
  const [sourceLanguage, setSourceLanguage] = useState("auto");
  const [wantAnalysis, setWantAnalysis] = useState(false);
  const [targets, setTargets] = useState<string[]>([]);
  const [query, setQuery] = useState("");

  const [transcript, setTranscript] = useState("");
  const [transcriptSrt, setTranscriptSrt] = useState("");
  const [detectedLanguage, setDetectedLanguage] = useState("");
  // Every language heard, when the recording turned out to be bilingual.
  const [heardLanguages, setHeardLanguages] = useState<string[]>([]);
  const [translations, setTranslations] = useState<Translation[]>([]);
  const [summary, setSummary] = useState("");
  // A stage that ran and produced nothing still deserves a track: without this
  // we cannot tell "no analysis requested" from "analysed, found nothing".
  const [transcribed, setTranscribed] = useState(false);
  const [analyzed, setAnalyzed] = useState(false);
  const [activeTab, setActiveTab] = useState("");
  const [view, setView] = useState<"run" | "editor">("run");
  // Cue edits, per track id. A track absent here is untouched, which is what
  // lets "Revert" be a delete rather than a second copy of the original.
  const [edits, setEdits] = useState<Record<string, Cue[]>>({});

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
    setHeardLanguages([]);
    setError("");
    setStage("");
    // A new run replaces every track, so edits against the old ones are moot.
    setEdits({});
  };

  const chooseFile = (chosen: File) => {
    if (preview) URL.revokeObjectURL(preview);
    setPreview(URL.createObjectURL(chosen));
    setFile(chosen);
    setUpload(null);
    setStatus("idle");
    reset();
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
          language: sourceLanguage === "auto" ? null : sourceLanguage,
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
      let produced = 0;

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
              produced += 1;
              startTransition(() => {
                setTranscript(event.text);
                setTranscriptSrt(event.srt ?? "");
                setDetectedLanguage(event.language ?? "");
                setHeardLanguages(event.languages ?? []);
                setTranscribed(true);
                if (event.text) setActiveTab("source");
              });
              break;
            case "translation":
              produced += 1;
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
              produced += 1;
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
      toast.success(
        `${produced} ${produced === 1 ? "track" : "tracks"} ready`,
        { description: file.name },
      );
    } catch (caught: unknown) {
      if (caught instanceof Error && caught.name === "AbortError") {
        setStatus("cancelled");
        toast("Run cancelled", {
          description: "Nothing further was sent to the server.",
        });
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
  }, [file, upload, wantTranscript, wantAnalysis, targets, query, sourceLanguage]);

  const tracks: Track[] = [
    ...(transcribed
      ? [
          {
            id: "source",
            label:
              heardLanguages.length > 1
                ? `Source (${heardLanguages.join(" + ")})`
                : detectedLanguage
                  ? `Source (${detectedLanguage})`
                  : "Source",
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

  // Only cue-bearing tracks can be edited; the analysis is prose.
  const editable = tracks.filter((t) => t.kind === "subtitle" && t.srt);
  const editTrack =
    editable.find((t) => t.id === visibleTrack?.id) ?? editable[0];

  /** Edited cues if this track has been touched, otherwise the server's. */
  const cuesFor = (track: Track): Cue[] =>
    edits[track.id] ?? parseSrt(track.srt ?? "");

  const downloadTrack = (track: Track) =>
    downloadText(
      subtitleFilename(
        upload?.filename,
        track.id === "source" ? detectedLanguage || "source" : track.label,
      ),
      // Edits win: the file has to match what the editor showed.
      edits[track.id] ? buildSrt(edits[track.id]) : (track.srt ?? ""),
    );

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
    // No ground colour here: body owns it, and an opaque wrapper would
    // paint straight over the backdrop.
    <div className="min-h-svh">
      {/*
        A 72px bar that stays put: on a page this tall the run controls and the
        status chip are the two things you need while scrolling a transcript,
        and hunting back to the top for them is the whole reason a header goes
        sticky. It is translucent rather than solid so the aurora keeps moving
        underneath it instead of being cut off by an opaque band.
      */}
      <header className="sticky top-0 z-40 border-b border-border/80 bg-background/75 backdrop-blur-xl backdrop-saturate-150">
        <div className="container-page flex h-18 items-center justify-between gap-4">
          <div className="flex items-center gap-2.5">
            {/* The one place the brand blue appears as a fill rather than as
                a state: a mark, so the wordmark itself can stay plain type. */}
            <span
              aria-hidden
              className="grid size-7 shrink-0 place-items-center rounded-lg bg-primary text-primary-foreground"
            >
              <CaptionsIcon className="size-4" />
            </span>
            <span className="font-display text-wordmark font-semibold">
              Vida
            </span>
          </div>

          <div className="flex min-w-0 items-center gap-2">
            {/* Run / Editor. Hidden until there is something to edit, so it
                never offers a screen that would open empty. */}
            {editable.length > 0 && (
              <ToggleGroup
                type="single"
                variant="outline"
                size="sm"
                value={view}
                onValueChange={(v) => v && setView(v as "run" | "editor")}
              >
                <ToggleGroupItem value="run" className={SEGMENT}>
                  Run
                </ToggleGroupItem>
                <ToggleGroupItem value="editor" className={SEGMENT}>
                  <PencilIcon data-icon="inline-start" aria-hidden />
                  Editor
                </ToggleGroupItem>
              </ToggleGroup>
            )}
            {/* The status chip is the one place the run state is visible
                without looking at the frame. */}
            {status !== "idle" && (
              <Badge
                variant={
                  status === "failed"
                    ? "destructive"
                    : busy
                      ? "outline"
                      : "secondary"
                }
                className="h-7 min-w-0 px-3"
              >
                {busy && <Spinner data-icon="inline-start" />}
                {/* "Translating → Portuguese" is longer than a phone header
                    has room for, and the bar must not scroll sideways. */}
                <span className="truncate">{caption}</span>
              </Badge>
            )}
            {/* Which backend is being talked to is reference information, not
                a control: first thing to go when the bar runs out of room. */}
            <Tooltip>
              <TooltipTrigger asChild>
                <Badge
                  variant="ghost"
                  className="hidden h-7 px-3 font-mono text-meta text-muted-foreground md:inline-flex"
                >
                  <ServerIcon data-icon="inline-start" aria-hidden />
                  {API_BASE.replace(/^https?:\/\//, "")}
                </Badge>
              </TooltipTrigger>
              <TooltipContent>
                Requests go to this backend. Set NEXT_PUBLIC_API_URL to change
                it.
              </TooltipContent>
            </Tooltip>
            <ThemeToggle />
          </div>
        </div>
      </header>

      {view === "editor" && editTrack ? (
        <main id="main" className="container-page py-12 lg:py-16">
          <h1 className="sr-only">Cue editor</h1>
          <Editor
            track={editTrack}
            cues={cuesFor(editTrack)}
            sourceCues={
              editTrack.id === "source"
                ? undefined
                : transcriptSrt
                  ? parseSrt(transcriptSrt)
                  : undefined
            }
            previewUrl={preview}
            duration={upload?.duration ?? 0}
            edited={Boolean(edits[editTrack.id])}
            onChange={(next) =>
              setEdits((prev) => ({ ...prev, [editTrack.id]: next }))
            }
            onRevert={() =>
              setEdits((prev) => {
                const next = { ...prev };
                delete next[editTrack.id];
                return next;
              })
            }
            onDownload={() => downloadTrack(editTrack)}
          />
        </main>
      ) : (
      <>
      {/*
        The page headline. One H1, set in the display step — tight tracking,
        0.98 line-height — and held to a short measure so it breaks into two
        or three dense lines rather than one thin ribbon across a wide
        display. Left-aligned rather than centred: everything below it is a
        working tool on a left edge, and a centred headline over a
        left-aligned layout reads as a template.
      */}
      <section className="container-page pt-14 pb-10 lg:pt-20 lg:pb-14">
        <p className="eyebrow text-muted-foreground">Subtitle pipeline</p>
        <h1 className="mt-4 max-w-3xl font-display text-display font-semibold">
          Subtitles in any language, with the timing intact.
        </h1>
        <p className="mt-5 max-w-2xl text-lead text-muted-foreground">
          Drop in a video. Vida transcribes what is said, translates it into as
          many languages as you pick, and hands back a subtitle track per
          language — plus, if you want it, a description of what the video
          shows.
        </p>
      </section>

      <main
        id="main"
        className="container-page grid gap-10 pb-20 lg:grid-cols-[minmax(0,25rem)_1fr] lg:items-start lg:gap-16 lg:pb-28"
      >
        {/* The only element on the page allowed the deep shadow: it is the
            control surface, and depth here is hierarchy rather than style. */}
        <div className="glass glass-panel rounded-2xl p-6 lg:sticky lg:top-24 lg:p-7">
          <h2 className="sr-only">Job setup</h2>

          <FieldGroup>
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

            <FieldSet>
              <FieldLegend
                variant="label"
                className="eyebrow text-muted-foreground"
              >
                Output
              </FieldLegend>
              <FieldGroup className="gap-3">
                <Field orientation="horizontal">
                  <FieldContent>
                    <FieldLabel htmlFor="want-transcript">
                      <CaptionsIcon
                        className="size-4 text-muted-foreground"
                        aria-hidden
                      />
                      Transcript
                    </FieldLabel>
                    <FieldDescription>
                      Timed cues in the spoken language
                    </FieldDescription>
                  </FieldContent>
                  <Switch
                    id="want-transcript"
                    checked={wantTranscript}
                    onCheckedChange={setWantTranscript}
                  />
                </Field>

                <Field orientation="horizontal">
                  <FieldContent>
                    <FieldLabel htmlFor="want-analysis">
                      <SparklesIcon
                        className="size-4 text-muted-foreground"
                        aria-hidden
                      />
                      Visual analysis
                    </FieldLabel>
                    <FieldDescription>
                      A description of what the video shows
                    </FieldDescription>
                  </FieldContent>
                  <Switch
                    id="want-analysis"
                    checked={wantAnalysis}
                    onCheckedChange={setWantAnalysis}
                  />
                </Field>
              </FieldGroup>
            </FieldSet>

            {/* Only meaningful when something is actually transcribed, and it
                appears with the same motion the focus box uses. */}
            {(wantTranscript || targets.length > 0) && (
              <ViewTransition default="none" enter="slide-up" exit="fade-out">
                <Field>
                  <FieldLabel htmlFor="source-language">
                    Spoken language
                  </FieldLabel>
                  <Select
                    value={sourceLanguage}
                    onValueChange={setSourceLanguage}
                  >
                    <SelectTrigger
                      id="source-language"
                      className="glass-control w-full"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectGroup>
                        <SelectItem value="auto">Detect it for me</SelectItem>
                        {SOURCE_LANGUAGES.map((language) => (
                          <SelectItem key={language.code} value={language.code}>
                            {language.label}
                          </SelectItem>
                        ))}
                      </SelectGroup>
                    </SelectContent>
                  </Select>
                  <FieldDescription>
                    Detection is a guess, and a wrong one turns speech into
                    invented words in the wrong language. Naming the language
                    skips it.
                  </FieldDescription>
                </Field>
              </ViewTransition>
            )}

            {/* The focus box only exists once analysis is on, so it appears
                with the same motion the tracks panel uses. */}
            {wantAnalysis && (
              <ViewTransition default="none" enter="slide-up" exit="fade-out">
                <Field>
                  <FieldLabel htmlFor="focus">Focus the analysis</FieldLabel>
                  <Input
                    id="focus"
                    type="text"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="What should it look for?"
                    className="glass-control"
                  />
                  <FieldDescription>
                    Optional. A question here narrows the description instead of
                    summarising the whole clip.
                  </FieldDescription>
                </Field>
              </ViewTransition>
            )}

            <Separator />

            <FieldSet>
              <div className="flex items-center justify-between gap-2">
                <FieldLegend
                  variant="label"
                  className="eyebrow flex items-center gap-2 text-muted-foreground"
                >
                  <LanguagesIcon className="size-3.5" aria-hidden />
                  Translate into
                </FieldLegend>
                {targets.length > 0 && (
                  <Button
                    variant="ghost"
                    size="xs"
                    onClick={() => setTargets([])}
                    className="text-muted-foreground"
                  >
                    <XIcon data-icon="inline-start" aria-hidden />
                    Clear {targets.length}
                  </Button>
                )}
              </div>
              {/* ToggleGroup gives roving focus and pressed state for free —
                  this used to be eleven buttons with hand-written aria. */}
              <ToggleGroup
                type="multiple"
                variant="outline"
                size="sm"
                value={targets}
                onValueChange={setTargets}
                className="flex w-full flex-wrap"
              >
                {LANGUAGES.map((language) => (
                  <ToggleGroupItem
                    key={language}
                    value={language}
                    aria-label={`Translate into ${language}`}
                    className={CHIP}
                  >
                    {language}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
            </FieldSet>

            <Field>
              <div className="flex gap-2">
                <Button
                  onClick={run}
                  disabled={!file || busy || nothingSelected}
                  size="lg"
                  className="flex-1"
                >
                  {busy ? (
                    <Spinner data-icon="inline-start" />
                  ) : (
                    <WandSparklesIcon data-icon="inline-start" aria-hidden />
                  )}
                  {busy ? "Working…" : actionLabel}
                </Button>
                {busy && (
                  <Button
                    variant="destructive"
                    size="lg"
                    onClick={() => abortRef.current?.abort()}
                  >
                    <SquareIcon data-icon="inline-start" aria-hidden />
                    Cancel
                  </Button>
                )}
              </div>

              {nothingSelected && file && (
                <FieldDescription>
                  Pick at least one output to generate.
                </FieldDescription>
              )}

              <p role="status" aria-live="polite" className="sr-only">
                {caption}
              </p>

              {status === "failed" && error && (
                <Alert variant="destructive">
                  <AlertCircleIcon />
                  <AlertTitle>Run failed</AlertTitle>
                  <AlertDescription className="wrap-anywhere">
                    {error}
                  </AlertDescription>
                </Alert>
              )}
            </Field>
          </FieldGroup>
        </div>

        {tracks.length > 0 ? (
          <ViewTransition key="tracks" default="none" enter="slide-up">
            <TrackPanel
              tracks={tracks}
              activeId={visibleTrack?.id ?? ""}
              onSelect={(id) => startTransition(() => setActiveTab(id))}
              onDownload={downloadTrack}
            />
          </ViewTransition>
        ) : (
          <ViewTransition key="skeleton" default="none" exit="slide-down">
            <Card className="glass rounded-2xl flex min-h-[28rem] flex-col gap-0 overflow-hidden p-0 lg:min-h-[34rem]">
              <div className="px-4 py-2">
                <Badge
                  variant="ghost"
                  className="font-mono text-meta text-muted-foreground"
                >
                  no cues
                </Badge>
              </div>
              <Separator />

              {/* Ghost cue rows, so the shape of the answer is visible before
                  there is one. */}
              <ol aria-hidden className="select-none">
                {[1, 2, 3, 4, 5].map((row) => (
                  <li
                    key={row}
                    className="grid grid-cols-[2.5rem_9rem_1fr] items-center gap-x-3 border-b px-4 py-2.5"
                  >
                    <span className="font-mono text-meta tabular-nums text-muted-foreground/30">
                      {row.toString().padStart(2, "0")}
                    </span>
                    <Skeleton className="h-2 w-20" />
                    <Skeleton
                      className="h-2"
                      style={{ width: `${70 - row * 9}%` }}
                    />
                  </li>
                ))}
              </ol>

              <Empty className="flex-1 border-0">
                <EmptyHeader>
                  <EmptyMedia variant="icon">
                    <CaptionsIcon />
                  </EmptyMedia>
                  <EmptyTitle>No tracks yet</EmptyTitle>
                  <EmptyDescription>
                    Every language you pick becomes a track here, with timecodes
                    you can check against the video and an .srt to download.
                  </EmptyDescription>
                </EmptyHeader>
              </Empty>
            </Card>
          </ViewTransition>
        )}
      </main>
      </>
      )}

      <footer className="border-t">
        <div className="container-page flex flex-col gap-8 py-12 sm:flex-row sm:items-start sm:justify-between">
          <div className="max-w-sm">
            <p className="font-display text-wordmark font-semibold">Vida</p>
            <p className="mt-2 text-sm text-muted-foreground">
              A transcription, translation, and video-analysis pipeline you run
              on your own machine.
            </p>
          </div>

          <div className="grid gap-8 sm:grid-cols-2 sm:gap-16">
            <div>
              <p className="eyebrow text-muted-foreground">Built on</p>
              <a
                href="https://pypi.org/project/vida-sdk/"
                className="arrow-link mt-3 inline-flex items-center gap-1.5 text-sm font-medium hover:text-primary"
              >
                vida-sdk on PyPI
                <ArrowUpRightIcon className="size-4" aria-hidden />
              </a>
            </div>
            <div>
              <p className="eyebrow text-muted-foreground">Where it runs</p>
              <p className="mt-3 wrap-anywhere font-mono text-meta text-muted-foreground">
                {API_BASE.replace(/^https?:\/\//, "")}
              </p>
              <p className="mt-1 text-sm text-muted-foreground">
                Files are processed on your own server.
              </p>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}
