import { esc, fmtNum, fmtTime, tip } from './state.js';
import { t } from './i18n.js';

const foodNum = n => Number.isInteger(n) ? fmtNum(n) : Number(n).toFixed(1);

// A farmer is named by what the unit is ("Farmer", numbered when there are several), never by its
// internal id. An entry is an id, or { id, name } when the caller knows the unit's name.
function farmerChip(farmer, i, n) {
  const id = typeof farmer === 'object' ? farmer.id : farmer;
  const name = (typeof farmer === 'object' && farmer.name) || t('Farmer');
  return `<button data-inspect="${id}" ${tip(name, t('Select this villager'))}>${esc(name)}${n > 1 ? ` ${i + 1}` : ''}</button>`;
}

export function farmReviewHtml(stats, { techName = id => String(id), farmers = [] } = {}) {
  const farm = stats?.farm, site = stats?.folwark;
  if (!farm && !site) return '';
  const row = (label, value, detail = '') => `<div class="review-farm-row" ${detail ? tip(t(label), t(detail)) : ''}><span>${esc(t(label))}</span><b>${value}</b></div>`;
  const grants = farm?.grants || site?.grants || [];
  const partial = stats.resource_totals?.has_gaps || stats.resource_totals?.observed_from_ms > 0;
  const coverage = partial ? `<p class="hint">${t('Partial history')}</p>` : '';
  const receiptList = grants.length ? `<details class="review-details"><summary>${t('Farm grants')} (${grants.length})</summary><div class="review-farm-grants">${grants.map(g => `<div><time>${fmtTime(g.time)}</time><span>${t('Farm')} #${g.farm}</span><b>+${foodNum(g.food)} ${t('food')}${g.folwarks.length > 1 ? ' *' : ''}</b></div>`).join('')}</div></details>` : '';
  if (site) return `<section class="review-farm" data-ui-key="folwark-review"><h4>${t('Poles Folwark bonus food')}</h4>${row('Granted food', foodNum(site.food))}${row('Farms triggered', fmtNum(site.farms))}${site.shared_food ? `<p class="hint">${t('Shared range; building attribution unknown')}: ${foodNum(site.shared_food)} ${t('food')}</p>` : ''}<p class="hint">${t('Next farm')}: +${foodNum(site.next_food)} ${t('food')} · ${t('Reach')}: ${site.reach} ${t('tiles')}</p><p class="hint">${t('Bonus food is separate from gathering and collection rates.')}</p>${coverage}${receiptList}</section>`;
  const chips = farm.upgrades.map(up => `<span class="review-farm-tech ${up.done ? 'done' : 'later'}" data-farm-tech="${up.tech}" ${tip(up.label ? t(up.label) : techName(up.tech), up.done ? up.researched_ms == null ? t('Already present when recording began') : `${t('Researched')}: ${fmtTime(up.researched_ms)}` : t('Not yet'))}><span>${esc(up.label ? t(up.label) : techName(up.tech))}</span><small>${up.done ? '✓ ' + (up.researched_ms == null ? t('Already present') : fmtTime(up.researched_ms)) : t('Not yet')}</small></span>`).join('');
  return `<section class="review-farm" data-ui-key="farm-review">${row('Food remaining', t('Not recorded'), 'The recording contains a gathering buffer, not the food remaining in this farm.')}${row('New farm capacity', `${foodNum(farm.capacity)} ${t('food')}`, 'Existing farms receive partial upgrade top-ups; their current maximum is not recorded.')}${farm.capacity_at_build != null ? row('Capacity when built', `${foodNum(farm.capacity_at_build)} ${t('food')}`) : ''}${row('Farm age', farm.age_ms != null ? fmtTime(farm.age_ms) : t('Not recorded'))}${farm.auto_reseed != null ? row('Automatic reseeding', t(farm.auto_reseed ? 'On' : 'Off')) : ''}<div class="review-farm-farmers"><span>${t('Working farmers')}</span>${farmers.length ? farmers.map((farmer, i) => farmerChip(farmer, i, farmers.length)).join('') : `<span class="hint">${t('None observed')}</span>`}</div><h4>${t('Farm upgrades')}</h4><div class="review-farm-techs">${chips}</div>${coverage}${receiptList}</section>`;
}
