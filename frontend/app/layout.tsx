import type { Metadata, Viewport } from "next";
import {
  Bricolage_Grotesque,
  IBM_Plex_Mono,
  IBM_Plex_Sans,
} from "next/font/google";
import "./globals.css";
import { cn } from "@/lib/utils";
import { Backdrop } from "./components/backdrop";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";

// One quirky voice against two engineered ones: Bricolage carries the wordmark
// and headings, Plex Sans reads long transcripts without drawing attention, and
// Plex Mono handles everything that is really data — timecodes, cue numbers,
// file sizes.
const display = Bricolage_Grotesque({
  variable: "--font-display",
  subsets: ["latin"],
});

const body = IBM_Plex_Sans({
  variable: "--font-body",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

const code = IBM_Plex_Mono({
  variable: "--font-code",
  subsets: ["latin"],
  weight: ["400", "500"],
});

export const metadata: Metadata = {
  title: "Vida — subtitles in any language",
  description:
    "Upload a video and get subtitle tracks with the timing intact, plus a description of what the video shows.",
};

// The interface is dark-only, so tell the browser: native scrollbars, form
// controls, and the address bar all follow.
export const viewport: Viewport = {
  colorScheme: "dark",
  themeColor: "#141920",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      // `dark` is not a toggle here — it is what switches on the `dark:`
      // variants inside the shadcn components. The tokens themselves are
      // dark at :root either way.
      className={cn(
        "dark h-full",
        display.variable,
        body.variable,
        code.variable,
      )}
    >
      <body className="min-h-full">
        {/* Keyboard users land here first and can jump past the header. */}
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:start-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-primary focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-primary-foreground"
        >
          Skip to content
        </a>
        <Backdrop />
        <TooltipProvider>{children}</TooltipProvider>
        <Toaster position="bottom-right" closeButton />
      </body>
    </html>
  );
}
