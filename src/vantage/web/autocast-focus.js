import { eventIndexAfter } from './playback.js';
// Observed participants, with nearby active combatants as a bounded estimate.
const near = (a, b, radius) => Number.isFinite(a.x) && Number.isFinite(a.y)
  && (a.x - b.x) ** 2 + (a.y - b.y) ** 2 <= radius ** 2;

export function chooseFight(events, at) {
  // Only the last 20 s of the time-sorted log (it was filtered whole, every frame
  // while no fight was found).
  const window = events.slice(eventIndexAfter(events, at - 20000), eventIndexAfter(events, at));
  const recent = window.filter(e => Number.isFinite(e.x) && Number.isFinite(e.y) && !e.friendly);
  const kills = recent.filter(e => e.kind === 'kill');
  const candidates = kills.length ? kills : recent.filter(e => e.kind === 'under_attack' && e.t > at - 8000);
  let best = null, score = -1;
  for (const event of candidates) {
    const n = candidates.filter(other => near(other, event, 8)).length;
    if (n > score || (n === score && event.t > best.t)) { best = event; score = n; }
  }
  return best;
}

export function fightParticipants(focus, events, rows, at) {
  const info = new Map();
  const add = ref => {
    if (ref?.id != null && ref.owner > 0 && ref.master != null)
      info.set(ref.id, { owner: ref.owner, mid: ref.master });
  };
  for (const e of events) {
    if (e.t > at || e.t < at - 20000 || e.friendly || !near(e, focus, 10)) continue;
    if (e.kind === 'kill') { add(e.killer); add(e.victim); }
    if (e.kind === 'under_attack') add(e.unit);
  }
  // A selected dead victim stays available for loss and cost review. Do not
  // include idle bystanders just because they are close to a battle.
  for (const row of rows) {
    if (!(row[1] > 0) || row[5] <= 0 || (row[6] & 512)) continue;
    if (info.has(row[0]) || ([8, 15].includes(row[9]) && near({ x: row[3], y: row[4] }, focus, 10)))
      info.set(row[0], { owner: row[1], mid: row[2] });
  }
  return info;
}

export function highlightParticipants(hero, element, focus, events, rows, at) {
  const live = new Map(rows.map(row => [row[0], row]));
  const info = element.kind === 'birth' ? new Map() : fightParticipants(focus, events, rows, at);
  const add = ref => {
    if (ref?.id == null || !(ref.owner > 0)) return;
    const row = live.get(ref.id);
    info.set(ref.id, { owner: row?.[1] ?? ref.owner, mid: row?.[2] ?? ref.master ?? ref.mid });
  };
  add(hero);
  if (element.kind === 'death') add(element.killer);
  // Story victims that are already present in this fight can be inspected
  // before the blow lands; membership stays fixed for the highlight element.
  for (const event of element.kills || []) {
    const row = live.get(event.victim?.id);
    if (row && near({ x: row[3], y: row[4] }, focus, 10)) add(event.victim);
  }
  return info;
}

export class FightSelection {
  constructor() { this.enabled = true; this.owned = null; this.focus = null; this.at = null; }
  resume(selection) { this.enabled = true; this.owned = new Set(selection); this.focus = null; }
  observe(selection) {
    if (this.owned && (selection.size !== this.owned.size || [...selection].some(id => !this.owned.has(id)))) {
      this.enabled = false; this.owned = null;
    }
  }
  select(focus, events, rows, at) {
    if (!this.enabled) return null;
    const sameFight = this.focus && near(focus, this.focus, 8)
      && at >= this.at && at - this.at < 30000;
    this.at = at;
    if (sameFight) return null;
    const info = fightParticipants(focus, events, rows, at);
    if (!info.size) return null;
    this.focus = { x: focus.x, y: focus.y };
    this.owned = new Set(info.keys());
    return info;
  }
}
