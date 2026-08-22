# Vida frontend

A Next.js UI for the demo backend in `../backend`. Upload a video, pick
outputs (transcript, translations, visual analysis), run the pipeline, and
get back subtitle tracks you can preview against the video and edit cue by
cue.

## Run it

```bash
npm install
npm run dev      # http://localhost:3000
```

Talks to the backend at `NEXT_PUBLIC_API_URL`, defaulting to
`http://localhost:8000/api/v1`. Start `../backend` first (see its README) —
there's nothing here to fall back to without it.

```bash
npm run build     # production build
npm run lint      # eslint
```

## Stack

Next.js 16 / React 19, Tailwind v4, shadcn/ui components in
`components/ui/`. **This Next.js version has breaking changes relative to
older conventions** — see `AGENTS.md` and read the relevant guide in
`node_modules/next/dist/docs/` before writing code against its APIs.

## Structure

```
app/
  page.tsx                 the whole run flow: upload, options, run, results
  layout.tsx                fonts, theme provider, page chrome
  globals.css               design tokens — colour, type scale, radius, motion
  components/
    letterbox.tsx            the upload/preview frame with the status caption
    tracks.tsx                output tabs — one per transcript/translation/analysis
    editor.tsx                per-cue subtitle editor
    backdrop.tsx              decorative page-ground layers (aurora, grid, grain)
    theme-provider.tsx        next-themes wrapper
    theme-toggle.tsx          light/dark/system switch
  lib/
    subtitles.ts              SRT/VTT parsing and building, cue helpers
    ui.ts                     shared className recipes (segmented control, chip)
components/ui/                shadcn primitives (button, card, tabs, ...)
```

## Talking to the backend

Every SSE-driven state in `page.tsx` (`status`, `stage`, per-track results)
mirrors what `POST /api/v1/process/stream` emits — see `../backend/README.md`
for the event shape. A run is cancelled by aborting the fetch
(`abortRef.current?.abort()`); the backend has no separate cancel endpoint,
so this only stops the client from listening, not the server-side job.

## Design tokens

`app/globals.css` is the one place colour, type scale, radius, and motion are
defined — components should pull from it (`bg-primary`, `text-caption`,
`text-display`, `.glass`, `.eyebrow`, etc.) rather than hardcoding values.
Two themes are supported (`:root` / `.dark`); every semantic token has to
move in both when it changes. See the file's own comments for why specific
values are what they are — several are calibrated contrast ratios, not
guesses.

## Notes for changes here

- Pipeline logic belongs in `vida/` or `../backend`, not here — this app only
  renders what those return.
- New colours, spacing, or radii go into the token layer in `globals.css`
  first; reach for an arbitrary Tailwind value only when nothing in the scale
  fits, and say why in a comment if so.
- `lib/ui.ts` holds className recipes used in more than one place (e.g. the
  segmented-control and language-chip states). Add to it rather than
  duplicating a `data-[state=on]:...` string in two components.
