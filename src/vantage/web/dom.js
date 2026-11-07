// Live HUD updates keep their DOM nodes: changing a number must not reload
// images, lose keyboard focus, or remove a button between pointerdown and click.
const sources = new WeakMap();
const keys = ['data-ui-key', 'data-panel-detail', 'data-dash-page', 'data-review-scope',
  'data-dash-metric', 'data-tech', 'data-mid', 'data-inspect', 'data-full-tree',
  'data-moment', 'data-bookmark', 'data-delete', 'data-cat', 'data-hl', 'data-hero', 'data-line', 'data-pid'];

function key(node) {
  if (node.nodeType !== 1) return null;
  if (node.id) return `id:${node.id}`;
  for (const attr of keys) if (node.hasAttribute(attr)) {
    return `${attr}:${node.getAttribute(attr)}:${node.getAttribute('data-pid') || node.getAttribute('data-owner') || node.getAttribute('data-team') || ''}`;
  }
  return null;
}

function compatible(a, b) {
  return a && a.nodeType === b.nodeType && a.nodeName === b.nodeName
    && a.namespaceURI === b.namespaceURI && key(a) === key(b);
}

function patchNode(node, next) {
  if (node.nodeType !== 1) {
    if (node.nodeValue !== next.nodeValue) node.nodeValue = next.nodeValue;
    return;
  }
  // Details are user-controlled. New selections explicitly reset their nodes.
  const preserve = name => node.nodeName === 'DETAILS' && name === 'open';
  for (const attr of [...node.attributes]) {
    if (!preserve(attr.name) && !next.hasAttribute(attr.name)) node.removeAttribute(attr.name);
  }
  for (const attr of [...next.attributes]) {
    if (!preserve(attr.name) && node.getAttribute(attr.name) !== attr.value) node.setAttribute(attr.name, attr.value);
  }
  patchChildren(node, next);
}

export function patchChildren(parent, next) {
  const keyed = new Map([...parent.childNodes].map(node => [key(node), node]).filter(([k]) => k != null));
  let current = parent.firstChild;
  for (const wanted of [...next.childNodes]) {
    let node = compatible(current, wanted) ? current : keyed.get(key(wanted));
    if (!compatible(node, wanted)) node = wanted.cloneNode(true);
    if (node !== current) parent.insertBefore(node, current);
    patchNode(node, wanted);
    keyed.delete(key(wanted));
    current = node.nextSibling;
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
