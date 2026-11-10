// Compact team and member labels for the scoreboard and team board.
//
// A team is otherwise named by every player name joined with " + ", and two
// copies of one AI also get their civilisation appended, so a 2v2 of AI builds
// read "Immortal v0d10f (Franks) + Immortal v0d10f (Mongols)". These rules keep
// only the part that tells the teams apart. Pure: no DOM, no settings.

const MAX_NAMES = 2;

/** One team's base label: a shared name once, else up to two names and a count. */
export function baseTeamLabel(names) {
  const unique = [...new Set(names.filter(Boolean))];
  if (unique.length <= 1) return unique[0] || '';
  const shown = unique.slice(0, MAX_NAMES).join(' + ');
  return unique.length > MAX_NAMES ? `${shown} +${unique.length - MAX_NAMES}` : shown;
}

/** True when every player of the team has the same name (copies of one AI). */
export function isTwinTeam(names) {
  return names.length > 1 && new Set(names).size === 1;
}

/**
 * Labels for all teams of a game, in the given order. `teams` is a list of
 * player-name lists. When every team is a twin team, the leading words all
 * their names share are dropped ("Immortal v0d10f" vs "Immortal v0d9" →
 * "v0d10f" vs "v0d9"). Labels that still collide fall back to `fallback(i)`.
 */
export function compactTeamLabels(teams, fallback = (i) => `Team ${i + 1}`) {
  const labels = teams.map(baseTeamLabel);
  if (teams.length > 1 && teams.every(isTwinTeam)) {
    const words = labels.map((l) => l.split(/\s+/));
    let k = 0;
    while (words.every((w) => w.length > k + 1 && w[k] === words[0][k])) k++;
    if (k) for (let i = 0; i < labels.length; i++) labels[i] = words[i].slice(k).join(' ');
  }
  if (new Set(labels).size < labels.length || labels.some((l) => !l)) return teams.map((_, i) => fallback(i));
  return labels;
}

/**
 * A member's label inside its team: its own name, or, when teammates share
 * that name, its civilisation (the player number when that is shared too).
 * `member` is {id, name, civ}; `team` is the list of all members.
 */
export function memberLabel(member, team) {
  const same = team.filter((m) => m.name === member.name);
  if (same.length < 2) return member.name;
  if (member.civ && same.filter((m) => m.civ === member.civ).length === 1) return member.civ;
  return `P${member.id}`;
}
