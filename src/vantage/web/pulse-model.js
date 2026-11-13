// What one Pulse strip cell shows and says. No DOM, so it is unit-tested.

import { fmtNum, fmtStock } from './state.js';
import { t } from './i18n.js';
import { METRICS } from './metrics.js';
import { sumStat, compare } from './team-board.js';

// Pulse metric id -> the registered metric it shows.
const STAT = { vil: 'villagers', mil: 'military', army: 'army_value', idle: 'idle_villagers', pop: 'population', banksum: 'banked', ratesum: 'rate', score: 'score' };
const DELTA = new Set(['army', 'ratesum']);

/**
 * One metric cell. value: the side's number; other: the opposing side's (null
 * in a free-for-all, where no delta is shown).
 */
export function cellModel(id, stats, otherStats, players) {
  const m = METRICS[STAT[id]];
  if (!m) return null;
  const value = sumStat(stats, m.f);
  if (value == null) return null;
  const other = otherStats ? sumStat(otherStats, m.f) : null;
  const cmp = other == null ? null : compare(value, other, m.lower);
  // A delta only where the lead is the story: army value and the collection rate.
  const leads = DELTA.has(id) && !!cmp && cmp.lead === 'a' && cmp.diff > 0;
  const cap = m.cap ? sumStat(stats, m.cap) : null;
  // More than two idle per player, as on the Team board: two idle villagers in a 1v1 is ordinary.
  const warn = !!m.warnEach && value > m.warnEach * players;
  const housed = id === 'pop' && stats.some((s) => s && s.housed);
  const stock = id === 'banksum';
  const shown = stock ? fmtStock(value) : fmtNum(value);
  let spoken = `${t(m.label)} ${shown}${cap != null ? ` ${t('of')} ${cap}` : ''}`;
  if (leads) spoken += `, ${t('ahead by {n}', { n: fmtNum(cmp.diff) })}`;
  if (warn) spoken += `, ${t('more than {n} per player', { n: m.warnEach })}`;
  if (housed) spoken += `, ${t('Housed')}`;
  return { id, short: m.short, series: m.series || null, shown, cap, delta: leads ? fmtNum(cmp.diff) : null, warn, housed, spoken };
}
