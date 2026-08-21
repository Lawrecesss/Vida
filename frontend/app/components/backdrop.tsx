/**
 * The page ground.
 *
 * Three things stacked, none of them interactive:
 *
 *  1. Aurora — slow-drifting blooms in the prism palette. These are the only
 *     saturated colour on the page outside the tracks themselves, kept far
 *     below text contrast so they read as light in a room, not as decoration.
 *  2. Scanlines and grain — a subtitling tool should look like video. This is
 *     the cheap version of that: a 3px line cycle and a static noise field,
 *     both at the threshold of visibility.
 *  3. Vignette — pulls the corners down so the centre column stays the
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
      <div className="aurora aurora-caption absolute -top-[30vmax] -left-[20vmax] size-[70vmax] rounded-full" />
      <div className="aurora aurora-cyan absolute -right-[25vmax] top-[10vmax] size-[60vmax] rounded-full" />
      <div className="aurora aurora-blue absolute -bottom-[35vmax] left-[15vmax] size-[65vmax] rounded-full" />

      <div className="scanlines absolute inset-0" />
      <div className="grain absolute inset-0" />
      <div className="vignette absolute inset-0" />
    </div>
  );
}
