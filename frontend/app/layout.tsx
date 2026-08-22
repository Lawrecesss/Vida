import type { Metadata, Viewport } from "next";
import { IBM_Plex_Mono, Inter, Inter_Tight } from "next/font/google";
import "./globals.css";
import { cn } from "@/lib/utils";
import { Backdrop } from "./components/backdrop";
import { ThemeProvider } from "./components/theme-provider";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";

// One grotesk in two cuts, plus a mono. Inter Tight carries the wordmark and
// the headline — at display sizes its narrower cut and tighter default fit are
// what let the negative tracking in globals.css land without the letters
// colliding — Inter reads long transcripts without drawing attention, and Plex
// Mono handles everything that is really data: timecodes, cue numbers, file
// sizes. Two cuts of one family rather than two families, because the page is
// meant to read as one voice at different volumes.
const display = Inter_Tight({
  variable: "--font-display",
  subsets: ["latin"],
});

const body = Inter({
  variable: "--font-body",
  subsets: ["latin"],
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

// Both themes are supported, so the document declares both and next-themes
// narrows `color-scheme` to the resolved one at runtime (see theme-provider).
// themeColor is the address-bar colour and cannot be resolved at runtime the
// same way, so it is given per media query and matches each theme's --stage.
export const viewport: Viewport = {
  colorScheme: "light dark",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#0a0a0b" },
  ],
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      // next-themes writes `class` and `style` on this element before paint,
      // which the server could not have known about. Without this React logs
      // a hydration mismatch for the one element that is legitimately allowed
      // to differ.
      suppressHydrationWarning
      className={cn("h-full", display.variable, body.variable, code.variable)}
    >
      <body className="min-h-full">
        {/* Keyboard users land here first and can jump past the header. */}
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:start-4 focus:top-4 focus:z-50 focus:rounded-full focus:bg-primary focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-primary-foreground"
        >
          Skip to content
        </a>
        <ThemeProvider>
          <Backdrop />
          <TooltipProvider>{children}</TooltipProvider>
          <Toaster position="bottom-right" closeButton />
        </ThemeProvider>
      </body>
    </html>
  );
}
