// Shared by dashboards, T90 pages, player review and the statistics table.
import { fmtTime } from './state.js';
import { t } from './i18n.js';

export const TC_IDLE_TIP = 'Time with at least one completed TC neither training nor researching, until the owner first reaches {target} living villagers or the match population limit. Overlapping idle TCs count once. Gaps under 1s count as working; housed time is separate and queued housing/population blocks are excluded.';

export function tcIdleTooltip(s = {}) {
  const g = s.tc_idle_growth;
  if (!g) return t('Growth-phase TC idle unavailable; reload with the current server.');
  const reason = g.reason === 'villagers' ? t('{target} living villagers', { target: g.villager_target }) : t('Match population limit');
  const cutoff = g.cutoff_ms == null
    ? t('Cutoff not reached; counted through {time}.', { time: fmtTime(g.through_ms) })
    : t('Cutoff: {time} ({reason}).', { time: fmtTime(g.cutoff_ms), reason });
  return `${t(TC_IDLE_TIP, { target: g.villager_target })} ${cutoff} ${t('Whole-game window: {time}.', { time: fmtTime((s.tc_idle_whole_seconds || 0) * 1000) })}`;
}
