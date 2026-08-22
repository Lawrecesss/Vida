/**
 * The page ground.
 *
 * Four things stacked, none of them interactive:
 *
 *  1. Aurora — slow-drifting blooms around the brand blue. These are the only
 *     saturated colour on the page outside the tracks themselves, kept far
 *     below text contrast so they read as light in a room, not as decoration.
 *  2. Grid — a 72px engineering grid under the top of the page, faded out
 *     before the fold. It says "technical tool" the way the old scanlines did,
 *     without turning a white page grey.
 *  3. Grain — a static noise field at the threshold of visibility, so large
 *     flat surfaces have a texture rather than looking like untouched CSS.
 *  4. Vignette — pulls the corners in so the centre column stays the
 *     brightest thing on screen.
 *
 * All CSS, no canvas and no JS: it costs one composited layer and animates on
 * transform only, so it never blocks a run in progress.
 */
export function Backdrop() {
  return (
    <div
      aria-hidden
      className="pointer-events-none fixed inset-0 -z-10 overflow-hidden"
    >
      {/* Aurora. Sized in vmax so the blooms stay off-centre on any aspect. */}
      <div className="aurora aurora-primary absolute -top-[30vmax] -left-[20vmax] size-[70vmax] rounded-full" />
      <div className="aurora aurora-cyan absolute -right-[25vmax] top-[10vmax] size-[60vmax] rounded-full" />
      <div className="aurora aurora-violet absolute -bottom-[35vmax] left-[15vmax] size-[65vmax] rounded-full" />

      <div className="grid-lines absolute inset-0" />
      <div className="grain absolute inset-0" />
      <div className="vignette absolute inset-0" />
    </div>
  );
}
