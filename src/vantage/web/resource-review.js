import { esc, fmtNum, fmtTime, tip } from './state.js';
import { t } from './i18n.js';

export const RESOURCE_ORDER = ['food', 'wood', 'gold', 'stone'];

export function resourceNumbers(values = {}) {
  return RESOURCE_ORDER.map((resource) => `<span class="review-resource-number" ${tip(t(resource))}><img src="/ui/resource_${resource}.png" alt="${esc(t(resource))}"><b>${values[resource] == null ? '–' : fmtNum(values[resource])}</b></span>`).join('');
}

export function resourceTotalsHtml(totals, villager = false) {
  if (!totals || (!villager && !totals.is_drop_site)) return '';
  const partial = totals.has_gaps || totals.observed_from_ms > 0 || totals.ambiguous_dropoffs > 0;
  const label = villager ? t('Collected') : t('Delivered');
  const detail = villager
    ? t('Gathered by this worker, including resources still carried. Estimated from carry changes, deliveries and shared direct-farming receipts; excludes extra drop-off yield.')
    : t('Full stockpile receipts, including extra yield. Attribution to this drop-off site is approximate; ambiguous deliveries are excluded.');
  const coverage = partial ? ` · ${t('Partial history')}${totals.observed_from_ms > 0 ? ` · ${fmtTime(totals.observed_from_ms)}` : ''}` : '';
  const credited = villager ? `<div class="hint" ${tip(t('Credited'), t('Resources from this worker added to the stockpile, including direct farming and drop-off bonuses. Excludes resources still carried. Attribution is approximate.') + coverage)}>${t('Credited')} ≈</div><div class="review-resource-numbers">${resourceNumbers(totals.credited)}</div>` : '';
  return `<div class="review-resource-totals" data-ui-key="resource-totals"><div class="hint" ${tip(label, detail + coverage)}>${label} <span>${partial ? '≥' : totals.estimated || villager ? '≈' : ''}</span></div><div class="review-resource-numbers">${resourceNumbers(villager ? totals.collected : totals.dropped_off)}</div>${credited}</div>`;
}

// Income amounts are read from the game, while attribution without a dedicated
// source counter is an estimate. Unattributed income can include ordinary work
// and is deliberately excluded from the bonus total.
export function bonusIncomeHtml(players) {
  const sections = players.map(({ id, name, color, income }) => {
    if (!income) return '';
    const rows = (income.sources || []).filter((row) => row.category !== 'regular' && row.total !== 0)
      .sort((a, b) => (a.category === 'unattributed') - (b.category === 'unattributed') || b.total - a.total);
    const partial = income.has_gaps || income.observed_from_ms > 0;
    const sourceRows = (values) => values.map(row => {
      const detail = row.category === 'yield'
        ? t('Estimated share of observed gathering due to the resource-yield multiplier: gathered × (1 − 1 / multiplier). Includes carried resources. Separate from income and cost savings.')
        : row.category === 'handicap'
        ? t('Estimated gathered-resource contribution of the recorded lobby handicap. Excludes its work-speed effects. Separate from civilization extra yield, income and savings.')
        : row.category === 'exchange'
        ? `${t('Received resources from recorded market transactions; excluded from bonus income.')} ${t('Paid')}: ${RESOURCE_ORDER.filter(r => row.spent?.[r] > 0).map(r => `${fmtNum(row.spent[r])} ${t(r)}`).join(' · ')}`
        : row.category === 'return'
        ? t('Previously carried resources returned when villagers were deleted. Matched to delete commands, lost cargo and actual receipts. Excluded from bonus income; no drop-off building is credited.')
        : row.category === 'savings'
        ? t('Completed units, buildings and research compared with the neutral same-game cost. Production uses the owner’s cost at completion; paid research uses its observed in-progress cost. Starting objects and cancelled queues are excluded. Estimated savings, not resource income.')
        : row.category === 'assets'
        ? `${t('Observed free villagers matched to completed Wei economic-upgrade rewards. Resource columns show their neutral unit cost, not stockpile income.')} ${t('Villagers')}: ${fmtNum(row.count)}`
        : ['Camp construction', 'Town Center construction', 'Production-building construction', 'Building construction'].includes(row.source)
        ? t('Completion grants read from the building owner’s resource storage. Added directly to the stockpile; separate from villager deliveries and collected-resource counters.')
        : row.source === 'Poles Folwark bonus food'
        ? t('Bonus food from observed farm completions in Folwark range, confirmed by food receipts. Excluded from gathered food and collection rates; overlapping ranges are credited once.')
        : row.source === 'Age advancement' || row.source === 'Technology research'
        ? t('Direct stockpile grant from an executed civilization bonus. Separate from gathered resources; amounts use the supported game rules.')
        : row.category === 'unattributed'
        ? t('Income without a proven source, including ordinary work. Excluded from bonus totals.')
        : row.source === 'Building loot'
        ? t('Danish building loot: recorded receipts matched to building destruction. Separate from Varangian Gold Generation. Attribution is estimated.')
        : row.source === 'Varangian Gold Generation'
        ? t('Gold from Varangian Guards fighting units. Separate from Danish building loot. Attribution is estimated.')
        : row.source === 'Paper Money'
        ? t('Gold trickled directly into the stockpile by active lumberjacks after Paper Money. Separate from wood deliveries and relic or trade gold.')
        : row.estimated ? t('Recorded income matched to an eligible source in the same frame. Source attribution is approximate.')
        : t('Recorded by the game’s dedicated income counter.');
      const label = row.category === 'assets' ? `${t(row.source)} ×${fmtNum(row.count)}`
        : row.category === 'handicap' ? row.source.replace(/^Handicap · /, '')
        : row.category === 'exchange' ? t(row.source === 'Market sales' ? 'Sales' : 'Purchases')
        : row.source === 'Building loot' ? t('Building loot · Danes') : t(row.source);
      return `<tr data-ui-key="income-${id}-${esc(row.source)}" class="${row.category === 'unattributed' ? 'hint' : ''}"><td ${tip(label, detail)}>${row.estimated && row.category !== 'unattributed' ? '≈ ' : ''}${esc(label)}</td>${RESOURCE_ORDER.map(r => `<td>${row.resources?.[r] > 0 ? row.resources[r] < 1 || row.source === 'Poles Folwark bonus food' && !Number.isInteger(row.resources[r]) ? row.resources[r].toFixed(1) : fmtNum(row.resources[r]) : '·'}</td>`).join('')}</tr>`;
    }).join('');
    // Older backends labelled unproven global multipliers as civilization yield.
    const effects = [...(income.effects || []), ...(income.exchanges || [])].filter(row => row.total > 0
      && !['Resource yield', 'Other resource yield'].includes(row.source));
    const benefits = [['yield', t('Extra yield')], ['savings', t('Saved')], ['assets', t('Free units')], ['handicap', t('Handicap')], ['exchange', t('Market')], ['return', t('Returned')]].map(([category, label]) => {
      const group = effects.filter(row => row.category === category);
      return group.length ? `<tr class="review-income-category"><th colspan="5">${label} <span>${category === 'exchange' ? '' : '≈'}${fmtNum(group.reduce((sum, row) => sum + row.total, 0))}</span></th></tr>${sourceRows(group)}` : '';
    }).join('');
    return `<section class="review-income-player" data-ui-key="income-player-${id}"><div class="review-income-head"><b style="color:${esc(color)}">${esc(name)}</b><span class="hint" ${tip(t('Bonus income'), t('Attributed bonus income. Approximate source attribution; yield and savings are separate.'))}>${t('Income')} ≈ ${fmtNum(income.total)}</span></div>
      <div class="review-resource-numbers">${resourceNumbers(income.bonus)}</div>
      ${partial ? `<span class="hint" ${tip(t('Partial history'), t('The recording starts late or has missing frames.'))}>${t('Partial history')}</span>` : ''}
      <table><thead><tr><th>${t('Source')}</th>${RESOURCE_ORDER.map((r) => `<th><img src="/ui/resource_${r}.png" alt="${esc(t(r))}" ${tip(t(r))}></th>`).join('')}</tr></thead><tbody>${sourceRows(rows.filter(row => row.category !== 'unattributed'))}${benefits}${sourceRows(rows.filter(row => row.category === 'unattributed'))}${!rows.length && !benefits ? `<tr><td colspan="5" class="hint">${t('No attributed bonus income')}</td></tr>` : ''}</tbody></table></section>`;
  }).join('');
  return sections ? `<div class="review-income-grid">${sections}</div>` : `<p class="hint">${t('Resource source history is unavailable for this recording.')}</p>`;
}
