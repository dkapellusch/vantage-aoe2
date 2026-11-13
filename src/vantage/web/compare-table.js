// A small side-against-side table: one row per metric, a column per side,
// the better value marked and the worse one in amber when the row asks for it.
// Used by the Focus slot's Eco card, the Review cards and the phone's Bank sheet.

import { esc, playerStats, playerMarkColor, playerTextColor, playerName, teamName } from './state.js';
import { t } from './i18n.js';

const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);

/** Which column is best and which is worst (indexes; null when the values tie or are missing). */
export function rank(values, lower = false, margin = 0) {
  const known = values.map(num);
  const vs = known.filter((v) => v != null);
  // A gap no bigger than the row's margin (89 % against 90 %) is a tie, not a lead.
  if (vs.length < 2 || Math.max(...vs) - Math.min(...vs) <= margin) return { best: null, worst: null };
  const best = lower ? Math.min(...vs) : Math.max(...vs), worst = lower ? Math.max(...vs) : Math.min(...vs);
  return { best: known.indexOf(best), worst: known.indexOf(worst) };
}

export function sideLabel(side) { return side.solo || side.players.length === 1 ? playerName(side.players[0].id) : teamName(side); }
export function sideStats(side) { return side.players.map((p) => playerStats(p.id)).filter(Boolean); }

/**
 * rows: [{ label, detail?, values: [number | null per side], text?: [string per side], lower?, warnWorst?, series?, pid? }].
 * A row with `series` is a button that opens Statistics on that series.
 */
export function compareTableHtml(sides, rows, { caption = '', headers = true } = {}) {
  const head = headers ? `<tr><th scope="col"><span class="sr-only">${esc(t('Metric'))}</span></th>${sides.map((s) => `<th scope="col" style="color:${playerTextColor(s.players[0].id)}"><i style="background:${playerMarkColor(s.players[0].id)}"></i>${esc(sideLabel(s))}</th>`).join('')}</tr>` : '';
  const body = rows.filter((r) => r.values.some((v) => v != null)).map((r) => {
    const { best, worst } = rank(r.values, r.lower, r.margin || 0);
    const cells = r.values.map((v, i) => `<td class="${i === best ? 'best' : ''}${i === worst && r.warnWorst ? ' worst' : ''}">${v == null ? '–' : esc(r.text ? r.text[i] : String(v))}</td>`).join('');
    const name = r.series
      ? `<button type="button" class="ct-open" data-series="${r.series}" data-pid="${sides[0].players[0].id}" aria-label="${esc(`${t(r.label)}: ${t('open in Statistics')}`)}">${esc(t(r.label))}</button>`
      : esc(t(r.label));
    return `<tr data-ui-key="${esc(r.label)}"><th scope="row"${r.detail ? ` title="${esc(t(r.detail))}"` : ''}>${name}</th>${cells}</tr>`;
  }).join('');
  return `<table class="ctable">${caption ? `<caption>${esc(caption)}</caption>` : ''}<thead>${head}</thead><tbody>${body}</tbody></table>`;
}
