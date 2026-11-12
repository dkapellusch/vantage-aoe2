// One preference for this viewer origin, shared across selections and matches.
const KEY = 'vantage.relevantUpgrades.expanded';
export function readUpgradeOverflow() {
  try { return globalThis.localStorage.getItem(KEY) === 'true'; }
  catch { return false; }
}
export function writeUpgradeOverflow(expanded) {
  try { globalThis.localStorage.setItem(KEY, String(Boolean(expanded))); }
  catch { /* Private/blocked/full storage must not prevent inspecting upgrades. */ }
}
