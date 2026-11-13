// Live HUD updates keep their DOM nodes: changing a number must not reload
// images, lose keyboard focus, or remove a button between pointerdown and click.
const sources = new WeakMap();
const keys = ['data-ui-key', 'data-panel-detail', 'data-dash-page', 'data-review-scope',
  'data-dash-metric', 'data-tech', 'data-mid', 'data-inspect', 'data-full-tree',
  'data-moment', 'data-bookmark', 'data-delete', 'data-cat', 'data-hl', 'data-hero', 'data-line', 'data-pid'];

const keyRank = new Map(keys.map((name, i) => [name, i]));

// Called several times per node of every patched panel, four times a second:
// one pass over the node's own attributes (most have one or two), not a
// hasAttribute call per key name (17 of them, a third of a HUD render).
function key(node) {
  if (node.nodeType !== 1) return null;
  if (node.id) return `id:${node.id}`;
  const attrs = node.attributes;
  let best = -1;
  for (let i = 0; i < attrs.length; i++) {
    const rank = keyRank.get(attrs[i].name);
    if (rank !== undefined && (best < 0 || rank < best)) best = rank;
  }
  if (best < 0) return null;
  const attr = keys[best];
  return `${attr}:${node.getAttribute(attr)}:${node.getAttribute('data-pid') || node.getAttribute('data-owner') || node.getAttribute('data-team') || ''}`;
}

function sameKind(a, b) {
  return a.nodeType === b.nodeType && a.nodeName === b.nodeName && a.namespaceURI === b.namespaceURI;
}

function patchNode(node, next) {
  if (node.nodeType !== 1) {
    if (node.nodeValue !== next.nodeValue) node.nodeValue = next.nodeValue;
    return;
  }
  // Details are user-controlled. New selections explicitly reset their nodes.
  const details = node.nodeName === 'DETAILS';
  const have = node.attributes, want = next.attributes;
  for (let i = have.length - 1; i >= 0; i--) {
    const name = have[i].name;
    if (!(details && name === 'open') && !next.hasAttribute(name)) node.removeAttribute(name);
  }
  for (let i = 0; i < want.length; i++) {
    const { name, value } = want[i];
    if (!(details && name === 'open') && node.getAttribute(name) !== value) node.setAttribute(name, value);
  }
  patchChildren(node, next);
}

export function patchChildren(parent, next) {
  // Keyed children are looked up only when a wanted node does not line up with
  // the current one: the map (of the children not yet placed) is built on first
  // need, and most patches never need it.
  let keyed = null;
  let current = parent.firstChild;
  const lookup = (k) => {
    if (!keyed) {
      keyed = new Map();
      for (let n = current; n; n = n.nextSibling) { const nk = key(n); if (nk != null) keyed.set(nk, n); }
    }
    return keyed.get(k);
  };
  let wanted = next.firstChild;
  while (wanted) {
    const following = wanted.nextSibling; // before a clone or a move can change it
    const k = key(wanted);
    let node = current && sameKind(current, wanted) && key(current) === k ? current : null;
    if (!node) {
      const found = lookup(k);
      node = found && sameKind(found, wanted) && key(found) === k ? found : wanted.cloneNode(true);
    }
    if (node !== current) parent.insertBefore(node, current);
    patchNode(node, wanted);
    if (keyed) keyed.delete(k);
    current = node.nextSibling;
    wanted = following;
  }
  while (current) { const nextSibling = current.nextSibling; parent.removeChild(current); current = nextSibling; }
}

export function patchHtml(el, html, reset = false, force = false) {
  if (!reset && !force && sources.get(el) === html) return;
  const active = el.ownerDocument.activeElement;
  const hadFocus = active && el.contains(active);
  // Table fragments need their table parsing context (implicit tbody, etc.).
  const shell = el.cloneNode(false);
  shell.innerHTML = html;
  if (reset) el.replaceChildren(...shell.childNodes);
  else patchChildren(el, shell);
  if (hadFocus && el.contains(active) && el.ownerDocument.activeElement !== active) active.focus({preventScroll:true});
  sources.set(el, html);
}

/**
 * How a list window moved: `next` is `shown` with `drop` rows gone from the front
 * and `add` appended (rows compared by identity), or null when it did not just
 * slide forward (a seek back, a filter change, new data) and needs a rebuild.
 * Lets a long log append its new rows instead of re-rendering every row.
 */
export function listDelta(shown, next) {
  if (!next.length) return { drop: shown.length, add: [] };
  const j = shown.indexOf(next[0]);
  if (j < 0) return shown.length ? null : { drop: 0, add: next.slice() };
  const keep = shown.length - j;
  if (keep > next.length) return null;
  for (let i = 0; i < keep; i++) if (shown[j + i] !== next[i]) return null;
  return { drop: j, add: next.slice(keep) };
}
