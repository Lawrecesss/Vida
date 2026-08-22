"use client";

import { ThemeProvider as NextThemeProvider } from "next-themes";

/**
 * Theme state, in one place.
 *
 * `attribute="class"` is what the rest of the styling depends on: the shadcn
 * components are full of `dark:` variants, and `@custom-variant dark` in
 * globals.css resolves those against a `.dark` ancestor. next-themes putting
 * that class on <html> is the whole mechanism.
 *
 * `enableColorScheme` writes `color-scheme` onto the same element, so native
 * scrollbars, form controls, and the browser's own chrome follow the choice —
 * which the static `viewport.colorScheme` in layout.tsx can no longer do now
 * that the answer is only known at runtime.
 *
 * `disableTransitionOnChange` suppresses transitions for the instant the class
 * flips. Without it every transition-bearing element cross-fades independently
 * and the switch looks like a page load rather than a change of light.
 */
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  return (
    <NextThemeProvider
      attribute="class"
      defaultTheme="system"
      enableSystem
      enableColorScheme
      disableTransitionOnChange
      storageKey="vida-theme"
    >
      {children}
    </NextThemeProvider>
  );
}
