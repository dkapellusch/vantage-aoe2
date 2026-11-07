/** Owners in the current selection, including dead units retained for review. */
export function selectedOwners(state) {
  const rows = new Map((state.view?.entities || []).map(row => [row[0], row[1]]));
  return new Set([...state.selection].map(id => rows.get(id) ?? state.selectionInfo.get(id)?.owner).filter(owner => owner > 0));
}

/** A conversion matters to both the monk's owner and the converted unit's owner. */
export function eventOwners(event) {
  return event.kind === 'conversion' ? [event.player, event.from] : [event.player];
}

export function eventAllowed(mode, event, perspective, owners, visible) {
  if (mode === 'none') return false;
  if (mode === 'all') return true;
  if (mode === 'screen') return visible;
  const selected = eventOwners(event).some(owner => owners.has(owner));
  if (mode === 'selectedOwners') return selected;
  if (mode === 'screenOrSelectedOwners') return visible || selected;
  return !perspective || eventOwners(event).includes(perspective);
}

export class AlertCadence {
  constructor() { this.last = -Infinity; }
  allow(now, interval) {
    if (now - this.last < interval) return false;
    this.last = now;
    return true;
  }
}
