// What the viewer set up in the Selection panel, kept in the settings so it
// applies to every later selection and survives a reload: which sections are
// open (Details, the group sections, farm grants), whether the Relevant
// upgrades overflow is shown, the activity scope (Life / 60s), and whether a
// preset that shows the one-line chip opens the full panel instead.
// Where the panel sits and how big it is are in settings.panelSizes.unitpanel,
// with every other placed panel.

import { settings, saveSettings } from './state.js';
import { SELECTION_DEFAULTS, normalizeSelectionPanel } from './hud-model.js';
import { readUpgradeOverflow, writeUpgradeOverflow } from './upgrade-overflow.js';

const memory = () => normalizeSelectionPanel(settings.selectionPanel);
function update(patch) {
  settings.selectionPanel = { ...memory(), ...patch };
  saveSettings();
}

/** Open sections by name, for selection-panel.js (get: undefined when the viewer never touched one). */
export const sectionStore = {
  get: (key) => memory().open[key],
  set: (key, open) => { if (memory().open[key] !== !!open) update({ open: { ...memory().open, [key]: !!open } }); },
};

/** The Relevant upgrades overflow ("+N more"). Before it lived in the settings it had its own storage key. */
export function upgradesExpanded() {
  const stored = memory().upgrades;
  return stored == null ? readUpgradeOverflow() : stored;
}
export function setUpgradesExpanded(on) { update({ upgrades: !!on }); writeUpgradeOverflow(!!on); }

/** The activity scope to start on. An interval ("Fight") belongs to one investigation and is not kept. */
export function storedScope() { return memory().scope; }
export function rememberScope(scope) { if (scope === 'life' || scope === 'minute') update({ scope }); }

/** Minimal and Caster: the full panel instead of the chip, until "compact" is pressed. */
export function chipExpanded() { return memory().expanded; }
export function setChipExpanded(on) { if (memory().expanded !== !!on) update({ expanded: !!on }); }

/** Everything above back to its default (Customize → Reset Selection panel). */
export function resetSelectionMemory() {
  settings.selectionPanel = { ...SELECTION_DEFAULTS, open: {}, upgrades: false };
  writeUpgradeOverflow(false);
  saveSettings();
}
