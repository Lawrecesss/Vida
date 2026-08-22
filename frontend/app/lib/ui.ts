/**
 * Class recipes shared by more than one component.
 *
 * These are here rather than in the components that use them because a
 * "selected" state that means one thing in the header and another in the
 * sidebar is how a design stops reading as one system — and both of these are
 * used in two places.
 */

/*
 * Segmented controls — Run / Editor, and the theme switch. The active state is
 * the foreground colour as a fill: the strongest contrast the palette has, and
 * it costs no blue. The blue is spent on the primary action and on selected
 * languages, and a third thing wearing it would stop it meaning anything.
 */
export const SEGMENT =
  "glass-control border-border data-[state=on]:border-foreground data-[state=on]:bg-foreground data-[state=on]:text-background";

/*
 * Language chips. A picked language commits to a whole track, so it gets the
 * accent — the stock "on" state is bg-muted, which is nearly invisible against
 * a white panel.
 */
export const CHIP =
  "glass-control border-border px-3.5 data-[state=on]:border-primary data-[state=on]:bg-primary/10 data-[state=on]:text-primary data-[state=on]:hover:bg-primary/15 data-[state=on]:hover:text-primary";
