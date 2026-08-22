"use client";

import * as React from "react";
import { MonitorIcon, MoonIcon, SunIcon } from "lucide-react";
import { useTheme } from "next-themes";

import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { SEGMENT } from "../lib/ui";

const OPTIONS = [
  { value: "light", label: "Light", Icon: SunIcon },
  { value: "dark", label: "Dark", Icon: MoonIcon },
  { value: "system", label: "System", Icon: MonitorIcon },
] as const;

/**
 * Light / Dark / System.
 *
 * Three states rather than a two-way flip, because "follow the OS" is a real
 * preference and a flip has no way back to it: once you touch a two-way
 * toggle you are pinned to whichever side you landed on until you clear site
 * data.
 *
 * The stored value is what this reflects, not the resolved one — with System
 * selected on a dark OS, the highlight belongs on System, not on Dark.
 */
/**
 * False while rendering on the server and through hydration, true afterwards.
 *
 * `useSyncExternalStore` rather than the usual `useState` + `useEffect` mount
 * flag: setting state from an effect body triggers a cascading render, which
 * the react-hooks lint now rejects. The store never emits, so the subscribe
 * callback is a no-op and the two snapshots do all the work.
 */
function useHydrated() {
  return React.useSyncExternalStore(
    () => () => {},
    () => true,
    () => false,
  );
}

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();

  // `theme` is only knowable in the browser: it comes from localStorage or a
  // media query, neither of which the server can see. Rendering the real state
  // before hydration would mean rendering a guess and then correcting it, so
  // the first paint is a same-sized inert copy and nothing shifts when it
  // resolves.
  const hydrated = useHydrated();

  if (!hydrated) {
    return (
      <div
        aria-hidden
        className="h-8 w-[6.75rem] rounded-full border border-border/60"
      />
    );
  }

  return (
    <ToggleGroup
      type="single"
      variant="outline"
      size="sm"
      value={theme ?? "system"}
      // Radix clears the value when the active item is pressed again; keep the
      // current one rather than falling through to an unset theme.
      onValueChange={(next) => next && setTheme(next)}
      aria-label="Colour theme"
    >
      {OPTIONS.map(({ value, label, Icon }) => (
        <Tooltip key={value}>
          <TooltipTrigger asChild>
            <ToggleGroupItem
              value={value}
              aria-label={label}
              className={SEGMENT}
            >
              <Icon aria-hidden />
            </ToggleGroupItem>
          </TooltipTrigger>
          <TooltipContent>{label}</TooltipContent>
        </Tooltip>
      ))}
    </ToggleGroup>
  );
}
