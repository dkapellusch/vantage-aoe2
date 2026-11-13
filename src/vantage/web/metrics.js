// The metric registry: one name per metric. The Team board, the dashboard
// columns, the Statistics series, the Pulse strip, the Review cards and the
// single-metric widgets all take their label from here, so "Army value" is
// never "MIL VALUE" in one panel and "Military value" in another.
//
// label: the full name (tooltips, tables, screen readers); short: the column
// or strip abbreviation; series: the key in S.series; f(stats): the value at
// the viewed time; lower: fewer is better; unit: '' | 'time' (seconds) | '%'.

const sum4 = (o) => (o ? (o.food || 0) + (o.wood || 0) + (o.gold || 0) + (o.stone || 0) : null);

export const METRICS = {
  age: { label: 'Age', short: 'Age', series: 'age', f: (s) => s.age },
  villagers: { label: 'Villagers', short: 'Vil', series: 'villagers', f: (s) => s.villagers, detail: 'Including garrisoned ones, as the game counts them' },
  military: { label: 'Military', short: 'Mil', series: 'military', f: (s) => s.military, detail: 'Military units' },
  army_value: { label: 'Army value', short: 'Army', series: 'army_value', f: (s) => s.army_value, detail: 'Resources spent on the living army' },
  idle_villagers: { label: 'Idle villagers', short: 'Idle', series: 'idle', f: (s) => s.idle_villagers, lower: true, warnEach: 2 },
  population: { label: 'Population', short: 'Pop', series: 'pop', f: (s) => s.pop, cap: (s) => s.pop_cap, detail: 'Counts units in training, as the game does' },
  banked: { label: 'Banked', short: 'Bank', f: (s) => sum4(s.resources), lower: true, detail: 'Resources in the stockpile, not yet spent' },
  rate: { label: 'Collection rate', short: '/min', series: 'rate_total', f: (s) => s.collected_rate?.total, detail: 'Resources gathered per minute over the last game minute. Bonus and trade income is not included' },
  collected: { label: 'Collected', short: 'Coll.', series: 'col_total', f: (s) => s.collected?.total, detail: 'Gathered by villagers and fishing ships since the start. Bonus, relic, trade and market income is not included' },
  bonus: { label: 'Bonus resources', short: 'Bonus', series: 'bonus_total', f: (s) => s.resource_income?.total, detail: 'Civilization, technology and event grants, including the starting bonus' },
  kills: { label: 'Kills', short: 'K', series: 'kills', f: (s) => s.kills },
  losses: { label: 'Losses', short: 'L', series: 'deaths', f: (s) => s.deaths, lower: true, detail: 'Including those to animals and other non-player causes' },
  score: { label: 'Score', short: 'Score', series: 'score', f: (s) => s.score_total },
  eapm: { label: 'eAPM', short: 'eAPM', series: 'eapm', detail: 'Effective actions per minute' },
  tc_idle: { label: 'Idle TC (growth)', short: 'Idle TC', series: 'tc_idle', lower: true, unit: 'time' },
  housed: { label: 'Housed time', short: 'Housed', series: 'housed', lower: true, unit: 'time' },
  efficiency: { label: 'Worker efficiency', short: 'Eff.', series: 'efficiency', unit: '%', detail: 'Share of villager time spent working' },
};

/** Kills and losses shown as one pair. */
export const KILLS_LOSSES = { label: 'Kills / Losses', short: 'K / L' };

/** The English label of a metric (translate it with t() where it is shown). */
export function metricLabel(id) { return METRICS[id] ? METRICS[id].label : id; }
export function metricShort(id) { return METRICS[id] ? METRICS[id].short : id; }

/** The label of a Statistics series that is a registered metric; null otherwise. */
const BY_SERIES = Object.fromEntries(Object.values(METRICS).filter((m) => m.series).map((m) => [m.series, m.label]));
export function seriesMetricLabel(key) { return BY_SERIES[key] || null; }
