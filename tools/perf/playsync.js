// The page-side half of playsync.py: evaluated once playback is under way, it
// installs window.__perf.watch (probe.js calls it after every frame of the
// viewer) and checks the rows the world just drew against the clock.
([maxSpeed, slack]) => {
  const P = window.__perf, V = window.vantage, S = V.S;
  const prev = new Map(); // id -> [x, y, view time, next time, frame]
  const st = P.sync = {
    frames: 0, advancing: 0, noBracket: 0, noBracketGameMs: 0, staleView: 0,
    teleports: 0, teleportUnits: new Set(), teleportFrames: 0, bigJumps: 0,
    runInPlace: 0, runInPlaceFrames: 0, walkingUnitFrames: 0,
    backwards: 0, viewBack: 0, badPair: 0, gfxWait: 0, dataWait: 0, held: 0,
    timeline: [], examples: [], gameMs: 0, wallMs: 0,
    // Why a walking unit held still: its keyframes say it stood (the game's own
    // stop), it is gone from the next one, the frame had nothing to interpolate
    // between, or the interpolation stopped it (arrived, still in its walk).
    ripWhy: { noBracket: 0, notInNext: 0, standsInData: 0, interpolated: 0 },
  };
  let lastT = null, lastView = null, lastWall = null, frame = 0;
  let nextIds = null, nextOf = null, viewIds = null, viewOf = null;
  const byId = (view) => new Map(view.entities.map((r) => [r[0], r]));
  const examples = (kind) => st.examples.filter((e) => e.kind === kind).length;
  const r2 = (x) => Math.round(x * 100) / 100;
  // The unit moves somewhere along the view's track (between the two keyframes).
  const tracked = (v, id, a) => (v.unit_track || []).some(([, us]) =>
    us.some((u) => u[0] === id && a && (u[1] !== a[3] || u[2] !== a[4])));

  function whyStill(v, n, id, x, y, t) {
    if (nextOf !== n) { nextOf = n; nextIds = byId(n); }
    if (viewOf !== v) { viewOf = v; viewIds = byId(v); }
    const q = nextIds.get(id), a = viewIds.get(id);
    if (!q) return 'notInNext';
    if (a && q[3] === a[3] && q[4] === a[4] && !tracked(v, id, a)) return 'standsInData';
    if (examples('rip') < 20) {
      st.examples.push({ kind: 'rip', id, t: Math.round(t), view: v.time, next: n.time,
        a: a && [a[3], a[4], a[9]], q: [q[3], q[4], q[9]], drawn: [r2(x), r2(y)] });
    }
    return 'interpolated';
  }

  P.watch = (now) => {
    frame++;
    if (!S.playing || !S.view) { lastT = null; return; }
    const t = S.t, v = S.view, n = S.nextView;
    st.frames++;
    const dT = lastT == null ? 0 : t - lastT;
    if (lastWall != null) st.wallMs += now - lastWall;
    lastWall = now;
    if (dT > 0) { st.advancing++; st.gameMs += dT; }
    if (dT < 0) st.backwards++;
    if (dT === 0) st.held++;
    if (S.gfxWait) st.gfxWait++;
    if (S.dataWait) st.dataWait++;
    if (lastView && v.time < lastView.time) st.viewBack++;
    if (n && n.time <= v.time) st.badPair++;
    const bracket = !!n && t >= v.time && t <= n.time && n.time > v.time;
    if (dT > 0 && !bracket) { st.noBracket++; st.noBracketGameMs += dT; }
    if (t - v.time > 1500) st.staleView++;
    let tele = 0, rip = 0, walking = 0;
    const rows = V.world.currentRows();
    const bound = dT > 0 ? maxSpeed * dT / 1000 + slack : slack;
    for (let i = 0; i < rows.length; i++) {
      const r = rows[i];
      if (r[0] < 0 || (r[6] & 1)) continue; // projectiles, buildings
      const id = r[0], x = r[3], y = r[4];
      const p = prev.get(id);
      if (p && p[4] === frame - 1 && dT > 0) {
        const d = Math.hypot(x - p[0], y - p[1]);
        if (d > bound) {
          tele++; st.teleportUnits.add(id);
          if (d > 6) st.bigJumps++;
          if (examples('teleport') < 40) {
            st.examples.push({ kind: 'teleport', id, owner: r[1], mid: r[2], name: S.catalog.units[r[2]]?.name,
              d: r2(d), bound: r2(bound), from: [r2(p[0]), r2(p[1])], to: [r2(x), r2(y)], act: r[9],
              t: Math.round(t), dT: Math.round(dT), view: v.time, next: n ? n.time : null, prevView: p[2], prevNext: p[3] });
          }
        }
        if (r[9] === 1) { // walking (world.py ACT_MOVING)
          walking++;
          if (d < 1e-6 && dT >= 20) {
            rip++;
            st.ripWhy[bracket ? whyStill(v, n, id, x, y, t) : 'noBracket']++;
          }
        }
      }
      if (p) { p[0] = x; p[1] = y; p[2] = v.time; p[3] = n ? n.time : null; p[4] = frame; }
      else prev.set(id, [x, y, v.time, n ? n.time : null, frame]);
    }
    st.teleports += tele; if (tele) st.teleportFrames++;
    st.runInPlace += rip; if (rip) st.runInPlaceFrames++;
    st.walkingUnitFrames += walking;
    if (st.timeline.length < 20000) {
      st.timeline.push([Math.round(now), Math.round(t), v.time, n ? n.time : -1,
        (S.gfxWait ? 1 : 0) + (S.dataWait ? 2 : 0), tele, rip, walking]);
    }
    lastT = t; lastView = v;
  };
}
