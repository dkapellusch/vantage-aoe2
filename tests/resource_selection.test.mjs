import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Element, Text } from './dom_helper.mjs';

// Exercise the real picker and selection/panel path with a minimal canvas DOM.
const ctx = new Proxy({}, {
  get: (o, p) => o[p] ?? (() => {}),
  set: (o, p, v) => (o[p] = v, true),
});
const canvas = {
  getContext: () => ctx, style: {}, width: 100, height: 100,
  classList: { add() {}, remove() {} }, addEventListener() {},
};
const classes = new Set(['hidden']);
// These picker/markup checks retain raw generated HTML; DOM identity is tested
// separately with parsed nodes and in the real browser.
class MarkupPanel extends Element {
  set innerHTML(html){this.replaceChildren(new Text(html));}
  get innerHTML(){return this.firstChild?.nodeValue || '';}
  cloneNode(){return new MarkupPanel();}
  addEventListener(){}
}
const panel = new MarkupPanel();
panel.setAttribute('id','unitpanel');
panel.classList={add:c=>classes.add(c),remove:c=>classes.delete(c)};
globalThis.document = {
  getElementById: (id) => id === 'unitpanel' ? panel : canvas,
  createElement: () => canvas, addEventListener() {}, body: { appendChild() {} },
};
globalThis.window = { addEventListener() {}, devicePixelRatio: 1 };
const { S } = await import('../src/vantage/web/state.js');
const world = await import('../src/vantage/web/world.js');
const panels = await import('../src/vantage/web/panels.js');

const carcass = (id = 7, x = 10) => [id, 0, 1060, x, 10, 0, 256, 0, [], 0, ['food', 40]];
const villager = () => [8, 1, 83, 10, 10, 1, 0, 0, [], 0, 0];
const townCenter = () => [9, 1, 109, 10, 10, 1, 1, 0, [], 0, 0];

function scene({ entities = [], remains = [carcass()], zoom = 1 } = {}) {
  S.view = { time: 0, entities, remains, gatherers: { 7: { 1: 3 } } };
  S.nextView = null; S.t = 0;
  S.camera = { x: 10, y: 10, zoom };
  S.selection = new Set(); S.selectionInfo = new Map(); S.followSelection = false;
  world.draw(1 / 60);
  return world.entityScreen(carcass());
}

test('carcass picking scales with zoom and retains a usable target when zoomed out', () => {
  for (const zoom of [0.3, 1, 2, 3]) {
    const [x, y] = scene({ zoom });
    assert.equal(world.pick(x + 10 * zoom, y)?.[0], 7);
    const reach = Math.max(12, 16 * zoom);
    assert.equal(world.pick(x + reach + 1, y), null);
  }
});

test('a carcass can be selected beneath a gathering villager', () => {
  for (const zoom of [1, 3]) {
    const [x, y] = scene({ entities: [villager()], zoom });
    assert.equal(world.pick(x, y)?.[0], 7);
    // The standing villager remains selectable by clicking its own body.
    assert.equal(world.pick(x, y - 12 * zoom)?.[0], 8);
  }
});

test('a town centre footprint does not block a carcass at the same position', () => {
  const [x, y] = scene({ entities: [townCenter()] });
  assert.equal(world.pick(x, y)?.[0], 7);
});

test('the nearest carcass wins even when another carcass is also in range', () => {
  const near = carcass(7), far = carcass(10, 10.5);
  const [x, y] = scene({ remains: [near, far] });
  assert.equal(world.pick(x, y)?.[0], 7);
  const [fx, fy] = world.entityScreen(far);
  assert.equal(world.pick(fx, fy)?.[0], 10);
});

test('depleted corpses and rubble stay unselectable', () => {
  const empty = carcass(); empty[10] = 0;
  const rubble = carcass(10); rubble[1] = 1; rubble[10] = 0;
  const [x, y] = scene({ remains: [empty, rubble] });
  assert.equal(world.pick(x, y), null);
});

test('ordinary units remain selectable without a carcass nearby', () => {
  const [x, y] = scene({ entities: [villager()], remains: [] });
  assert.equal(world.pick(x, y - 12)?.[0], 8);
});

test('selecting a carcass opens its food and gatherer panel and keeps it selected', () => {
  const [x, y] = scene({ entities: [villager(), townCenter()], zoom: 3 });
  const picked = world.pick(x, y);
  assert.equal(picked?.[0], 7);
  S.selection = new Set([picked[0]]);
  panels.rememberSelection();
  panels.renderUnitPanel();
  assert.equal(classes.has('hidden'), false);
  assert.match(panel.innerHTML, /Carcass/);
  assert.match(panel.innerHTML, />40<\/b>/);
  assert.match(panel.innerHTML, /food/);
  assert.match(panel.innerHTML, /×3/);
  assert.deepEqual(world.selectedRows().map((r) => r[0]), [7]);
  S.view.remains = [carcass()]; S.view.remains[0][10][1] = 30;
  panels.renderUnitPanel();
  assert.match(panel.innerHTML, />30<\/b>/);
});

test('same-team owners retain separate compact identities and age icons', () => {
  S.match = { players: { 1: {id:1,name:'Alice',civ:1,color:'#2244ff',team_key:1}, 2: {id:2,name:'Bob',civ:2,color:'#ff2222',team_key:1} } };
  scene({ entities: [[11,1,38,10,10,1,2,0,[],0,0], [12,2,38,11,10,1,2,0,[],0,0]], remains: [] });
  S.view.players = { 1:{age:1}, 2:{age:2} };
  S.selection = new Set([11,12]); panels.rememberSelection(); panels.renderUnitPanel();
  assert.equal((panel.innerHTML.match(/class="review-owner"/g)||[]).length, 2);
  assert.match(panel.innerHTML,/Alice/); assert.match(panel.innerHTML,/Bob/);
  assert.match(panel.innerHTML,/Feudal/); assert.match(panel.innerHTML,/Castle/);
  assert.equal((panel.innerHTML.match(/class="review-performance"/g)||[]).length, 2);
});

test('owned cards wait for replay-specific stats instead of presenting the catalog HP as current', () => {
  S.catalog.units[83] = { name:'Villager', cls:4, kind:'unit', icon:1, hp:25, stats:{hp:25} };
  scene({entities:[[555,1,83,10,10,1,4,0,[],0,0]],remains:[]});
  S.view.players = {1:{age:1}}; S.selection = new Set([555]); panels.renderUnitPanel();
  assert.match(panel.innerHTML, /HP – \/ –/);
  assert.doesNotMatch(panel.innerHTML, /HP 25 \/ 25/);
});
