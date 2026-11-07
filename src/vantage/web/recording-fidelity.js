// What a recording's own header says about how far it can be trusted. The label
// lives in the file, so it survives copying, renaming and every way of opening it.

export const INCOMPLETE_TITLE = 'INCOMPLETE-checksum-prefix';
const RECORDING_MODES = new Set(['recording', 'native_replay']);

/** The notice to show for a session description, or null for an ordinary recording. */
export function fidelityNotice(desc) {
  if (!desc || !RECORDING_MODES.has(desc.mode)) return null;
  const header = (desc.source && desc.source.header) || {};
  const fidelity = header.fidelity;
  if (fidelity && typeof fidelity === 'object' && fidelity.simulation === 'approximate') {
    return 'Approximate replay: checksums were ignored, so state after the first divergence may differ from the original game';
  }
  if (header.title === INCOMPLETE_TITLE) {
    return 'Incomplete replay preview: the match continues beyond this recording';
  }
  return null;
}
