// What a wheel event on the map means. A mouse wheel zooms, as it always has. A
// trackpad sends the same event for two things a mouse cannot do: two fingers
// moving (deltaX and deltaY in pixels, many small events, then more from inertia
// after the fingers lift) and a pinch (a wheel event with ctrlKey set, though no
// key is down). Two fingers pan the map and a pinch zooms it, as in any map on
// a laptop; treated as a wheel they zoomed, eased over a second, and the map
// could only be moved by a two-finger click-drag.
//
// Kept apart from the DOM so the rules can be tested with recorded event values.

const GESTURE_GAP_MS = 150; // a longer silence starts a new gesture

/**
 * Is this wheel event from a trackpad (or another device that scrolls in
 * pixels), rather than a notched mouse wheel?
 * - Lines or pages (deltaMode 1, 2): a mouse wheel (Firefox reports mice so).
 * - Sideways movement: a trackpad (or a tilt wheel, which should move sideways).
 * - Chromium and Safari also give the legacy wheelDeltaY: 120 per notch of a
 *   mouse wheel whatever deltaY is, but on a Mac trackpad exactly -3 x deltaY.
 * - Without wheelDeltaY (Firefox, pixels): whole steps of 50 px or more are a
 *   wheel, anything finer a trackpad.
 */
export function fromTrackpad(e) {
  if (e.deltaMode) return false;
  if (e.deltaX) return true;
  const legacy = e.wheelDeltaY;
  if (typeof legacy === 'number' && legacy !== 0) {
    if (legacy === -3 * e.deltaY) return true;
    return legacy % 120 !== 0;
  }
  return !(Number.isInteger(e.deltaY) && Math.abs(e.deltaY) >= 50);
}

/**
 * 'pinch' | 'pan' | 'zoom' for a wheel event. `memory` is an object this keeps
 * between events ({}), `now` a clock in ms, `mode` the setting ('auto', or
 * 'zoom' / 'pan' to say what two-finger scrolling does whatever the device
 * looks like), `ctrlHeld` whether a Control key is really down.
 *
 * One gesture is one kind: a trackpad's stream holds the odd event that looks
 * like a wheel notch (deltaY of exactly 40), and a zoom step in the middle of a
 * pan would be a lurch. `memory.started` is when the gesture began, so the
 * caller can tell inertia that outlives a camera jump from a new gesture.
 */
export function wheelKind(e, memory, now, mode = 'auto', ctrlHeld = false) {
  const fresh = memory.at == null || now - memory.at > GESTURE_GAP_MS;
  memory.at = now;
  // A pinch: ctrlKey without the key. (With the key held it is Ctrl + wheel.)
  const kind = e.ctrlKey && !ctrlHeld ? 'pinch'
    : mode === 'zoom' ? 'zoom'
      : mode === 'pan' ? 'pan'
        : fromTrackpad(e) ? 'pan' : 'zoom';
  if (fresh || (kind === 'pinch') !== (memory.kind === 'pinch')) {
    memory.kind = kind;
    memory.started = now;
  }
  return memory.kind;
}

/** The zoom factor of one pinch event (deltaY is small: a few units per event). */
export function pinchFactor(deltaY, speed = 1) {
  // Capped per event: a Ctrl + mouse wheel notch that got here is 100 units.
  const d = Math.max(-30, Math.min(30, deltaY));
  return Math.exp(-d * 0.01 * speed);
}
