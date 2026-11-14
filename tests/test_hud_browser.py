"""The customizable HUD in a real browser (headless Chromium, via Playwright).

Skipped unless Playwright and its Chromium are installed (they are not a
dependency of Vantage)::

    uv run --with playwright python -m playwright install chromium   # once
    uv run --with playwright pytest tests/test_hud_browser.py

The pages load a small synthetic match from an in-process server: offline and
deterministic, like the rest of the suite.
"""

from __future__ import annotations

import json
import threading
import urllib.request
from collections.abc import Iterator
from typing import Any

import pytest

from tests.helpers import game_frames
from vantage.frames import RecordingWriter
from vantage.gamedata import GameData
from vantage.server import Session, serve

sync_api = pytest.importorskip("playwright.sync_api")

SEEN = {"seenTutorial": True, "seenRorTutorial": True}
QUIET = {**SEEN, "hud": {"hintSeen": True}}
KEY = "vantage.settings.v1"
VISIBLE = """() => [...document.querySelectorAll('#hud .panel[id]')].filter((e) =>
  e.getClientRects().length && !e.classList.contains('empty')
  && !(e.classList.contains('panel-auto') && getComputedStyle(e).opacity === '0'))
  .map((e) => e.id).sort()"""
RECT = """(id) => { const r = document.getElementById(id).getBoundingClientRect();
  return [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)]; }"""


@pytest.fixture(scope="module")
def base(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    tmp = tmp_path_factory.mktemp("hud")
    patch = pytest.MonkeyPatch()
    patch.setenv("VANTAGE_DATA_DIR", str(tmp / "data"))
    rec = tmp / "recs"
    rec.mkdir()
    path = rec / "game.vrec"
    with RecordingWriter(path, {"source": "test"}) as w:
        for f in game_frames(12):
            w.write(f)
    session = Session(GameData(None), rec)
    srv = serve("127.0.0.1", 0, session, [])
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    req = urllib.request.Request(
        url + "/api/open",
        data=json.dumps({"path": str(path)}).encode(),
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(req, timeout=5).read()
    assert session._thread is not None
    session._thread.join(10)
    try:
        yield url
    finally:
        session.stop()
        srv.shutdown()
        srv.server_close()
        patch.undo()


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_api.sync_playwright() as pw:
        try:
            b = pw.chromium.launch(args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        except Exception as error:  # the browser is not installed
            pytest.skip(f"Chromium is not installed for Playwright: {error}")
        yield b
        b.close()


def open_page(
    browser: Any,
    url: str,
    saved: dict[str, Any] | None = QUIET,
    size: tuple[int, int] = (1920, 1080),
    touch: bool = False,
    init: str = "",
) -> Any:
    """A paused page on the synthetic match. saved=None is a brand-new viewer."""
    ctx = browser.new_context(
        viewport={"width": size[0], "height": size[1]}, has_touch=touch, is_mobile=touch
    )
    if saved is not None:
        ctx.add_init_script(
            f"if (!localStorage.getItem('{KEY}')) localStorage.setItem('{KEY}', "
            f"{json.dumps(json.dumps(saved))});"
        )
    if init:
        ctx.add_init_script(init)
    page = ctx.new_page()
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    page.goto(url)
    ready(page)
    return page


def ready(frame: Any) -> None:
    frame.wait_for_function(
        "document.body.dataset.startup === 'ready' && window.vantage && window.vantage.S.view",
        timeout=30000,
    )
    frame.evaluate("() => { window.vantage.S.playing = false; }")
    frame.wait_for_function("document.body.dataset.hudPreset")
    frame.wait_for_timeout(400)


def preset(page: Any) -> str:
    return str(page.evaluate("document.body.dataset.hudPreset"))


def saved_hud(page: Any) -> dict[str, Any]:
    hud: dict[str, Any] = page.evaluate(f"JSON.parse(localStorage.getItem('{KEY}')).hud")
    return hud


# -- which preset a viewer starts on -----------------------------------------------------------


def test_desktop_app_starts_on_full_and_a_hub_embed_on_minimal(browser: Any, base: str) -> None:
    desktop = open_page(browser, base, saved=None)
    assert preset(desktop) == "full"
    desktop.context.close()

    host = browser.new_context(viewport={"width": 1600, "height": 900}).new_page()
    host.set_content(f'<iframe src="{base}/" style="width:1500px;height:800px"></iframe>')
    frame = host.frames[1]
    ready(frame)
    assert frame.evaluate("document.body.dataset.hudPreset") == "minimal"
    shown = frame.evaluate(VISIBLE)
    assert "pulse" in shown and "minimap-wrap" in shown and "scoreboard" not in shown
    host.context.close()


def test_new_touch_viewer_on_a_narrow_screen_gets_the_phone_layout(browser: Any, base: str) -> None:
    # Full has no phone layout: at 390 px its time controls start off-screen. A new viewer on a
    # phone opening the page directly starts on Minimal, which has one.
    page = open_page(browser, base, saved=None, size=(390, 844), touch=True)
    assert preset(page) == "minimal"
    page.wait_for_function("document.body.classList.contains('hud-phone')")
    page.wait_for_selector("#phone-tabs:not(.hidden)")
    cut = page.evaluate(
        """() => [...document.querySelectorAll('#hud .panel[id], #hud button')].filter((e) => {
          if (!e.getClientRects().length) return false;
          const r = e.getBoundingClientRect();
          return r.left < -1 || r.right > innerWidth + 1; }).map((e) => e.id || e.className)"""
    )
    assert cut == [], cut
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.context.close()

    # A touch tablet is wide enough for Full, and a saved Full stays Full on a phone.
    tablet = open_page(browser, base, saved=None, size=(1024, 768), touch=True)
    assert preset(tablet) == "full"
    tablet.context.close()
    kept = open_page(browser, base, saved=QUIET, size=(390, 844), touch=True)
    assert preset(kept) == "full"
    kept.context.close()


def test_existing_settings_keep_full_inside_an_embed(browser: Any, base: str) -> None:
    ctx = browser.new_context(viewport={"width": 1600, "height": 900})
    ctx.add_init_script(
        f"if (!localStorage.getItem('{KEY}')) localStorage.setItem('{KEY}', "
        f"{json.dumps(json.dumps({**SEEN, 'settingsVersion': 9, 'useMinimalUi': True}))});"
    )
    host = ctx.new_page()
    host.set_content(f'<iframe src="{base}/" style="width:1500px;height:800px"></iframe>')
    frame = host.frames[1]
    ready(frame)
    assert frame.evaluate("document.body.dataset.hudPreset") == "full"
    assert "scoreboard" in frame.evaluate(VISIBLE)
    ctx.close()


def test_blocked_storage_still_boots(browser: Any, base: str) -> None:
    block = (
        "Object.defineProperty(window, 'localStorage', "
        "{ get() { throw new DOMException('denied', 'SecurityError'); } });"
    )
    page = open_page(browser, base, saved=None, init=block)
    assert preset(page) == "full"
    page.keyboard.press("F6")
    page.wait_for_function("document.body.dataset.hudPreset === 'minimal'")
    assert page.errors == []
    page.context.close()


# -- presets, their keys, hold-to-peek ---------------------------------------------------------


def test_preset_keys_and_peek(browser: Any, base: str) -> None:
    page = open_page(browser, base)
    full = page.evaluate(VISIBLE)
    assert "scoreboard" in full and "pulse" not in full

    page.keyboard.press("F6")
    page.wait_for_function("document.getElementById('pulse')?.textContent.trim()")
    assert preset(page) == "minimal"
    assert page.evaluate(VISIBLE) == ["minimap-wrap", "pulse", "timebar"]  # paused: time controls
    for key, name in (("F7", "caster"), ("F8", "review"), ("F9", "analyst")):
        page.keyboard.press(key)
        assert preset(page) == name
        assert saved_hud(page)["preset"] == name
    page.keyboard.press("Escape")  # Analyst docked the Statistics window
    page.keyboard.press("F6")

    # Hold-to-peek: Full while the key is down, the preset again on release.
    page.keyboard.down("Backquote")
    assert preset(page) == "full"
    assert "scoreboard" in page.evaluate(VISIBLE)
    page.keyboard.up("Backquote")
    assert preset(page) == "minimal"
    assert saved_hud(page)["preset"] == "minimal"

    page.keyboard.press("Shift+F6")
    assert preset(page) == "full"
    assert page.evaluate(VISIBLE) == full, "Full is exactly what it was"
    assert page.errors == []
    page.context.close()


def test_minimal_ui_checkbox_is_the_minimal_preset(browser: Any, base: str) -> None:
    page = open_page(browser, base)
    page.click("#btn-settings")
    box = page.locator("#set-minimal-ui")
    assert not box.is_checked()
    box.check()
    assert preset(page) == "minimal"
    box.uncheck()
    assert preset(page) == "full"
    page.context.close()


def test_toggle_keys_do_not_move_other_panels_or_resize_the_map(browser: Any, base: str) -> None:
    page = open_page(browser, base, saved={**SEEN, "hud": {"preset": "caster", "hintSeen": True}})
    page.wait_for_function("document.getElementById('focus')")
    before = {i: page.evaluate(RECT, i) for i in ("pulse", "minimap-wrap")}
    canvas = page.evaluate("[document.getElementById('world').width, innerWidth]")
    page.keyboard.press("Alt+k")
    assert "focus" not in page.evaluate(VISIBLE)
    page.keyboard.press("Alt+b")
    assert "dashboard" in page.evaluate(VISIBLE)
    page.keyboard.press("Alt+g")
    assert "pulse" not in page.evaluate(VISIBLE)
    page.keyboard.press("Alt+g")
    page.keyboard.press("Alt+k")
    page.keyboard.press("Alt+b")
    assert {i: page.evaluate(RECT, i) for i in ("pulse", "minimap-wrap")} == before
    assert page.evaluate("[document.getElementById('world').width, innerWidth]") == canvas
    assert saved_hud(page).get("edits", {}) == {}, "back to the stock preset"
    page.context.close()


# -- the Customize drawer ----------------------------------------------------------------------


def test_customize_drawer_dialog_keyboard_and_toggles(browser: Any, base: str) -> None:
    page = open_page(browser, base)
    button = page.locator("#btn-panels")
    assert button.get_attribute("aria-expanded") == "false"
    assert button.is_visible(), "the Customize entry is in the toolbar"
    page.keyboard.press("Alt+v")
    drawer = page.locator("#panels-menu")
    drawer.wait_for(state="visible")  # the drawer's code loads on first use
    assert drawer.get_attribute("role") == "dialog"
    assert drawer.get_attribute("aria-labelledby") == "customize-title"
    assert button.get_attribute("aria-expanded") == "true"
    # Focus moves into the drawer, onto the current preset; arrows walk the radio group.
    assert page.evaluate("document.activeElement.dataset.preset") == "full"
    page.keyboard.press("ArrowLeft")
    assert preset(page) == "analyst"
    assert page.evaluate("document.activeElement.getAttribute('aria-checked')") == "true"
    page.keyboard.press("Escape")  # the drawer; the docked Statistics window stays
    page.keyboard.press("Escape")
    page.keyboard.press("Alt+v")
    page.click('#panels-menu [data-preset="caster"]')
    assert preset(page) == "caster"

    # Tick a panel on and a metric off: the HUD follows, the preset shows as changed.
    page.check('#panels-menu [data-cz-show="events"]')
    assert "events" in page.evaluate(VISIBLE)
    page.uncheck('#panels-menu [data-cz-metric="pop"]')
    assert "Pop" not in page.inner_text("#pulse")
    assert page.locator('#panels-menu [data-preset="caster"] .cz-dot').count() == 1
    assert saved_hud(page)["edits"]["caster"]["panels"][-1] == "events"
    # Every checkbox has a text label; the hotkeys sit beside the panels.
    unlabeled = page.evaluate(
        "[...document.querySelectorAll('#panels-menu input[type=checkbox]')]"
        ".filter((c) => !c.closest('label')?.textContent.trim()).length"
    )
    assert unlabeled == 0
    assert "Alt+B" in page.inner_text("#panels-menu")

    page.click('#panels-menu [data-cz="restore"]')
    assert "events" not in page.evaluate(VISIBLE)
    assert saved_hud(page)["edits"] == {}

    # Esc closes it and the focus returns to the toolbar button.
    page.focus('#panels-menu [data-cz-show="pulse"]')
    page.keyboard.press("Escape")
    assert not drawer.is_visible()
    assert page.evaluate("document.activeElement.id") == "btn-panels"
    assert button.get_attribute("aria-expanded") == "false"
    assert page.errors == []
    page.context.close()


def test_share_link_round_trip_and_obs_overlay(browser: Any, base: str) -> None:
    page = open_page(browser, base, saved={**SEEN, "hud": {"preset": "caster", "hintSeen": True}})
    page.keyboard.press("Alt+v")
    page.check('#panels-menu [data-cz-show="dashboard"]')
    page.uncheck('#panels-menu [data-cz-metric="mil"]')
    page.click('#panels-menu [data-cz-sec="share"] summary')
    link = page.input_value("#cz-link")
    obs = page.input_value("#cz-obs")
    assert link.endswith("#hud=c1.pu-fo-et-sc-mm-da.age-vil-army-idle-pop-bank-rate")
    assert len(link.split("#")[1]) < 120
    assert "?overlay=1#hud=c1." in obs
    page.keyboard.press("Escape")
    shown = page.evaluate(VISIBLE)
    pulse = page.inner_text("#pulse")
    page.context.close()

    # Someone else (their own saved Full setup) opens the link: the same HUD, nothing saved.
    other = open_page(browser, link)
    other.wait_for_function("document.getElementById('pulse')?.textContent.trim()")
    assert preset(other) == "custom"
    assert other.evaluate(VISIBLE) == shown
    assert other.inner_text("#pulse") == pulse
    assert saved_hud(other).get("preset", "full") == "full"
    # Their first change makes it theirs, and a reload without the link keeps it.
    other.keyboard.press("Alt+e")
    assert saved_hud(other)["preset"] == "custom"
    other.goto(base + "/")
    ready(other)
    assert preset(other) == "custom"
    assert "events" in other.evaluate(VISIBLE)
    other.context.close()

    # The OBS page: the same hash, a transparent page, nothing that moves or resizes.
    overlay = open_page(browser, obs)
    overlay.wait_for_function("document.getElementById('pulse')?.textContent.trim()")
    assert overlay.evaluate("document.body.classList.contains('overlay-mode')")
    assert overlay.evaluate("document.body.classList.contains('hud-locked')")
    assert overlay.locator("#hud-hint").count() == 0
    assert "pulse" in overlay.evaluate(VISIBLE) and "dashboard" in overlay.evaluate(VISIBLE)
    assert "minimap-wrap" not in overlay.evaluate(VISIBLE)
    overlay.context.close()


def test_first_run_hint_shows_once(browser: Any, base: str) -> None:
    page = open_page(browser, base, saved=SEEN)
    hint = page.locator("#hud-hint")
    hint.wait_for(state="visible")
    assert "F6" in hint.inner_text() and "Shift+F6" in hint.inner_text()
    page.click('#hud-hint [data-hint="dismiss"]')
    assert hint.count() == 0
    assert saved_hud(page)["hintSeen"] is True
    page.reload()
    ready(page)
    assert page.locator("#hud-hint").count() == 0
    page.context.close()


def test_reset_hud_to_defaults(browser: Any, base: str) -> None:
    page = open_page(browser, base, saved={**SEEN, "hud": {"preset": "review", "hintSeen": True}})
    page.keyboard.press("Alt+v")
    page.check('#panels-menu [data-cz-show="events"]')
    page.click('#panels-menu [data-cz="reset-hud"]')
    assert preset(page) == "full"
    assert saved_hud(page)["edits"] == {}
    page.context.close()


# -- the Statistics window ---------------------------------------------------------------------


def test_statistics_window_moves_resizes_docks_and_remembers(browser: Any, base: str) -> None:
    page = open_page(browser, base)
    page.keyboard.press("Control+Alt+s")
    win = page.locator("#overlay-stats")
    page.wait_for_selector("#overlay-stats #chart")
    assert "stats-window" in (win.get_attribute("class") or "")
    assert win.get_attribute("role") == "dialog" and win.get_attribute("aria-modal") == "false"
    assert page.locator("#stats-tc").count() == 0, "no second playback bar"
    shadow = page.evaluate("getComputedStyle(document.getElementById('overlay-stats')).boxShadow")
    assert "100vmax" not in shadow and "0px 0px 0px" not in shadow, "the page is not dimmed"
    # The HUD beside it still takes clicks.
    page.click("#btn-fog")
    left, top, width, height = page.evaluate(RECT, "overlay-stats")
    chart = page.evaluate(RECT, "chart")

    # Drag by the title bar.
    page.mouse.move(left + 200, top + 20)
    page.mouse.down()
    page.mouse.move(left + 80, top + 100, steps=4)
    page.mouse.up()
    moved = page.evaluate(RECT, "overlay-stats")
    assert moved[2:] == [width, height] and moved[0] < left and moved[1] > top

    # Dragged far outside, it stays inside the window with its title bar reachable.
    page.mouse.move(moved[0] + 200, moved[1] + 20)
    page.mouse.down()
    page.mouse.move(5000, 5000, steps=4)
    page.mouse.up()
    x, y, w, h = page.evaluate(RECT, "overlay-stats")
    assert x >= 8 and y >= 8 and x + w <= 1920 - 8 and y + h <= 1080 - 8

    # The keyboard moves it too; an edge handle resizes it and the chart follows.
    page.focus("#stats-title")
    page.keyboard.press("ArrowLeft")
    page.keyboard.press("ArrowUp")
    x2, y2, _, _ = page.evaluate(RECT, "overlay-stats")
    assert (x2, y2) == (x - 10, y - 10)
    page.mouse.move(x2 + 300, y2 + 300)
    edge = page.locator('#panel-resize-handles [data-corner="w"]')
    box = edge.bounding_box()
    assert box is not None
    page.mouse.move(box["x"] + 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] - 198, box["y"] + box["height"] / 2, steps=4)
    page.mouse.up()
    resized = page.evaluate(RECT, "overlay-stats")
    assert resized[2] == w + 200 and resized[3] == h
    wider = f"document.getElementById('chart').getBoundingClientRect().width > {chart[2]}"
    page.wait_for_function(wider)

    # Esc closes; it reopens where it was, after a reload too.
    page.keyboard.press("Escape")
    assert not win.is_visible()
    page.keyboard.press("Control+Alt+s")
    page.wait_for_selector("#overlay-stats #chart")
    assert page.evaluate(RECT, "overlay-stats") == resized
    page.reload()
    ready(page)
    page.keyboard.press("Control+Alt+s")
    page.wait_for_selector("#overlay-stats #chart")
    assert page.evaluate(RECT, "overlay-stats") == resized

    # Dock right: full height beside the map, and the minimap moves in beside it.
    page.click('#overlay-stats [data-win="dock"]')
    docked = page.evaluate(RECT, "overlay-stats")
    assert docked[0] + docked[2] == 1920 - 8 and docked[1] + docked[3] == 1080 - 8
    minimap = page.evaluate(RECT, "minimap-wrap")
    assert minimap[0] + minimap[2] < docked[0]
    page.click('#overlay-stats [data-win="dock"]')
    assert page.evaluate(RECT, "overlay-stats") == resized
    assert page.errors == []
    page.context.close()


# -- the layout editor and saved layouts -------------------------------------------------------


def test_layout_editor_move_resize_undo_and_exit(browser: Any, base: str) -> None:
    page = open_page(browser, base, saved={**SEEN, "hud": {"preset": "caster", "hintSeen": True}})
    page.wait_for_function("document.getElementById('focus')")
    start = page.evaluate(RECT, "focus")

    # Outside the editor a panel body does not drag.
    page.mouse.move(start[0] + 150, start[1] + 12)
    page.mouse.down()
    page.mouse.move(start[0] + 400, start[1] - 300, steps=4)
    page.mouse.up()
    assert page.evaluate(RECT, "focus") == start

    page.keyboard.press("Alt+l")
    page.wait_for_selector("#le-bar")
    assert page.evaluate("document.body.classList.contains('hud-editor')")
    assert page.locator("#le-bar").get_attribute("role") == "toolbar"
    assert page.evaluate("document.activeElement.textContent").startswith("Done")
    page.click('#le-lib [data-le-fold="lib"]')

    # Drag the Focus slot: it moves, snaps to the grid, and is stored as an anchor and fractions.
    page.mouse.move(start[0] + 150, start[1] + 12)
    page.mouse.down()
    page.mouse.move(start[0] + 453, start[1] - 153, steps=6)
    page.mouse.up()
    moved = page.evaluate(RECT, "focus")
    assert moved[0] > start[0] + 200 and moved[1] < start[1] - 100
    assert moved[0] % 8 == 0 and moved[1] % 8 == 0
    stored = page.evaluate("window.vantage.settings.panelSizes.focus")
    assert stored["anchor"] == "bl" and 0 < stored["w"] < 1 and "left" not in stored
    assert "Focus slot" in page.inner_text("#le-insp")

    # The keyboard: arrows move the selected panel, Alt+arrows resize it.
    page.focus("#focus")
    page.keyboard.press("Shift+ArrowRight")
    assert page.evaluate(RECT, "focus")[0] == moved[0] + 1
    page.keyboard.press("Alt+ArrowRight")
    assert page.evaluate(RECT, "focus")[2] == moved[2] + 10

    # The inspector: an anchor, a scene, a scale.
    page.click('#le-insp [data-le-anchor="tl"]')
    assert page.evaluate("window.vantage.settings.panelSizes.focus.anchor") == "tl"
    page.uncheck('#le-insp [data-le-scene-show="fight"]')
    assert page.evaluate("window.vantage.settings.hud.sceneHide.focus") == ["fight"]
    page.click('#le-bar [data-le-scene="fight"]')
    assert "focus" not in page.evaluate(VISIBLE), "previewing the Fight scene hides it"
    page.click('#le-bar [data-le-scene=""]')
    assert "focus" in page.evaluate(VISIBLE)

    # Undo walks back; Reset puts everything in its place.
    page.keyboard.press("Control+z")
    assert page.evaluate("window.vantage.settings.hud.sceneHide.focus") is None
    for _ in range(8):
        page.keyboard.press("Control+z")
    assert page.evaluate(RECT, "focus") == start
    assert page.evaluate("window.vantage.settings.panelSizes.focus") is None

    # Esc leaves the editor; nothing drags afterwards.
    page.keyboard.press("Escape")
    assert not page.evaluate("document.body.classList.contains('hud-editor')")
    assert not page.locator("#le-bar").is_visible()
    assert page.errors == []
    page.context.close()


def test_layout_editor_keeps_sizes_focuses_on_click_and_has_a_grip(browser: Any, base: str) -> None:
    page = open_page(browser, base, saved={**SEEN, "hud": {"preset": "caster", "hintSeen": True}})
    page.wait_for_function("document.getElementById('ticker')")
    page.keyboard.press("Alt+l")
    page.wait_for_selector("#le-bar")

    # A panel with nothing to show (the Event ticker between events) keeps a size to grab, and
    # dragging it moves it without collapsing it to its padding.
    x, y, w, h = page.evaluate(RECT, "ticker")
    assert w >= 200 and h >= 30, (w, h)
    page.mouse.move(x + 40, y + 12)
    page.mouse.down()
    page.mouse.move(x - 260, y + 212, steps=10)
    page.mouse.up()
    moved = page.evaluate(RECT, "ticker")
    assert moved[0] < x - 200 and moved[1] > y + 150
    assert moved[2] >= 200 and moved[3] >= 30, moved

    # The press gave it the keyboard focus: the arrows act on what was just clicked.
    assert page.evaluate("document.activeElement.id") == "ticker"
    page.keyboard.press("ArrowLeft")
    assert page.evaluate(RECT, "ticker")[0] == moved[0] - 10
    page.keyboard.press("Alt+ArrowLeft")
    page.keyboard.press("Alt+ArrowLeft")
    for _ in range(40):
        page.keyboard.press("Alt+ArrowUp")
    small = page.evaluate(RECT, "ticker")
    assert small[2] >= 220 and small[3] >= 30, "resizing stops at the panel's minimum"

    # The inspector cannot make it smaller than that either.
    page.fill('#le-insp [data-le-num="width"]', "1")
    page.keyboard.press("Tab")
    page.fill('#le-insp [data-le-num="height"]', "1")
    page.keyboard.press("Tab")
    page.wait_for_timeout(200)
    tiny = page.evaluate(RECT, "ticker")
    assert tiny[2] >= 220 and tiny[3] >= 30, tiny

    # A panel under the inspector pane: select it in the library, then drag its grip.
    page.click('#le-lib [data-le-add="minimap"]')
    grip = page.locator("#le-grip")
    grip.wait_for(state="visible")
    assert "Minimap" in grip.inner_text()
    box = grip.bounding_box()
    assert box is not None and box["x"] + box["width"] <= 1920 - 258, (
        "the grip stays clear of the panes"
    )
    before = page.evaluate(RECT, "minimap-wrap")
    page.mouse.move(box["x"] + 20, box["y"] + 8)
    page.mouse.down()
    page.mouse.move(box["x"] - 380, box["y"] - 292, steps=8)
    page.mouse.up()
    after = page.evaluate(RECT, "minimap-wrap")
    assert after[0] < before[0] - 300 and after[1] < before[1] - 200
    assert after[2:] == before[2:], "moved, not resized"
    assert page.errors == []
    page.context.close()


def test_a_panel_hidden_in_a_scene_keeps_its_size_across_a_reload(browser: Any, base: str) -> None:
    page = open_page(browser, base)
    page.keyboard.press("Alt+l")
    page.wait_for_selector("#le-bar")
    page.click('#le-insp [data-le-fold="insp"]')
    x, y, _, _ = page.evaluate(RECT, "events")
    page.mouse.move(x + 40, y + 10)
    page.mouse.down()
    page.mouse.up()
    page.click("#le-insp-tab")
    page.fill('#le-insp [data-le-num="height"]', "30")
    page.keyboard.press("Tab")
    page.wait_for_timeout(200)
    sized = page.evaluate(RECT, "events")
    assert abs(sized[3] - 324) <= 2
    page.uncheck('#le-insp [data-le-scene-show="break"]')
    page.click('#le-bar [data-le-scene="break"]')
    assert "events" not in page.evaluate(VISIBLE)
    page.click('#le-bar [data-le-scene=""]')
    page.keyboard.press("Escape")
    assert page.evaluate(RECT, "events") == sized
    page.reload()
    ready(page)
    assert page.evaluate(RECT, "events") == sized
    assert page.evaluate("window.vantage.settings.hud.sceneHide.events") == ["break"]
    page.context.close()


def test_layout_save_load_and_survive_another_window_size(browser: Any, base: str) -> None:
    page = open_page(browser, base, saved={**SEEN, "hud": {"preset": "caster", "hintSeen": True}})
    page.wait_for_function("document.getElementById('focus')")
    start = page.evaluate(RECT, "focus")
    page.keyboard.press("Alt+l")
    page.wait_for_selector("#le-bar")
    page.click('#le-lib [data-le-fold="lib"]')
    page.mouse.move(start[0] + 150, start[1] + 12)
    page.mouse.down()
    page.mouse.move(start[0] + 450, start[1] - 150, steps=6)
    page.mouse.up()
    placed = page.evaluate(RECT, "focus")
    page.keyboard.press("Escape")

    page.keyboard.press("Alt+v")
    page.check('#panels-menu [data-cz-show="events"]')
    page.evaluate("document.querySelector('#panels-menu [data-cz-sec=layout]').open = true")
    page.fill("#cz-layout-name", "Cast A")
    page.click('#panels-menu [data-cz="save-layout"]')
    assert "Cast A" in saved_hud(page)["layouts"]

    # Wreck it, then load the saved layout back.
    page.click('#panels-menu [data-cz="reset-hud"]')
    assert preset(page) == "full"
    assert "Cast A" in saved_hud(page)["layouts"], "reset keeps saved layouts"
    page.select_option("#cz-layout-list", "Cast A")
    page.click('#panels-menu [data-cz="load-layout"]')
    page.wait_for_function("document.getElementById('focus')?.getClientRects().length")
    assert preset(page) == "caster"
    assert "events" in page.evaluate(VISIBLE)
    assert page.evaluate(RECT, "focus") == placed

    # The same layout in a 1280x720 window: the same anchor and proportions, still on screen.
    page.keyboard.press("Escape")
    page.set_viewport_size({"width": 1280, "height": 720})
    page.wait_for_timeout(1200)
    x, y, w, h = page.evaluate(RECT, "focus")
    assert abs(x - placed[0] * 1280 / 1920) <= 2
    assert abs((720 - y - h) - (1080 - placed[1] - placed[3]) * 720 / 1080) <= 2
    assert x >= 0 and y >= 0 and x + w <= 1280 and y + h <= 720

    # A reload keeps it; a link can name it.
    page.reload()
    ready(page)
    assert saved_hud(page)["layoutName"] == "Cast A"
    assert "events" in page.evaluate(VISIBLE)
    page.context.close()


def test_pixel_rectangles_from_older_builds_land_where_they_were(browser: Any, base: str) -> None:
    old = {"left": 700, "top": 300, "width": 520, "height": 240, "moved": True}
    page = open_page(browser, base, saved={**QUIET, "panelSizes": {"dashboard": old}})
    assert page.evaluate(RECT, "dashboard") == [700, 300, 520, 240]
    page.keyboard.press("Alt+b")  # any save writes the new schema
    stored = page.evaluate(f"JSON.parse(localStorage.getItem('{KEY}')).panelSizes.dashboard")
    assert stored["anchor"] == "c" and "left" not in stored
    page.context.close()


# -- accessibility and stream safety -----------------------------------------------------------


def test_pulse_strip_labels_and_text_sizes(browser: Any, base: str) -> None:
    for size, minimum in (((1920, 1080), (18, 14)), ((1280, 720), (16, 12))):
        page = open_page(browser, base + "/?hud=minimal", size=size)
        page.wait_for_function("document.getElementById('pulse')?.textContent.trim()")
        pulse = page.locator("#pulse")
        assert pulse.get_attribute("role") == "region" and pulse.get_attribute("aria-label")
        labels = page.evaluate(
            "[...document.querySelectorAll('#pulse button')]"
            ".map((b) => b.getAttribute('aria-label'))"
        )
        assert labels and all(labels), "every number is a labelled button"
        assert any(label.startswith("Villagers ") for label in labels)
        assert any(label.startswith("Army value ") for label in labels)
        assert any("per minute" in label for label in labels), "the bank says its rate"
        sizes = page.evaluate(
            """() => { const px = (s) => [...document.querySelectorAll(s)].map((e) =>
              parseFloat(getComputedStyle(e).fontSize));
              return [Math.min(...px('#pulse .pm-v')), Math.min(...px('#pulse .pm-l'))]; }"""
        )
        assert sizes[0] >= minimum[0] and sizes[1] >= minimum[1], (size, sizes)
        # Keyboard: after the four skip links, Tab reaches the strip, with a visible focus ring.
        for _ in range(5):
            page.keyboard.press("Tab")
        ring = page.evaluate(
            """() => { const e = document.activeElement, s = getComputedStyle(e);
              return [!!e.closest('#pulse'), s.outlineStyle, parseFloat(s.outlineWidth)]; }"""
        )
        assert ring[0] and ring[1] != "none" and ring[2] >= 2, ring
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.context.close()


def test_new_panels_keep_contrast_in_the_default_and_high_contrast_skins(
    browser: Any, base: str
) -> None:
    contrast = """() => {
      const lum = (c) => { const v = c.match(/[\\d.]+/g).slice(0, 3).map((x) => { x /= 255;
        return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; });
        return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]; };
      const bg = (e) => { for (; e; e = e.parentElement) {
        const c = getComputedStyle(e).backgroundColor, a = c.match(/[\\d.]+/g);
        if (a && (a.length < 4 || +a[3] > 0.5)) return c; } return 'rgb(13,15,18)'; };
      const out = [];
      const texts = '#pulse .pm-l, #pulse .pm-v, #pulse .pl-clock, #pulse .pl-sub,'
        + ' #focus .fs-title';
      for (const e of document.querySelectorAll(texts)) {
        const a = lum(getComputedStyle(e).color), b = lum(bg(e));
        out.push((Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05));
      }
      return Math.min(...out); }"""
    for skin in ("default", "contrast"):
        saved = {**SEEN, "skin": skin, "hud": {"preset": "caster", "hintSeen": True}}
        page = open_page(browser, base, saved=saved)
        page.wait_for_function("document.getElementById('focus')")
        assert page.evaluate(contrast) >= 4.5, skin
        page.context.close()


DASH = "\u2013"  # the en dash in the fight card's time ranges
FIGHTS = """() => { const S = window.vantage.S;
  const kill = (t, owner) => ({ t, kind: 'kill', cat: 'combat', friendly: false, x: 20, y: 30,
    victim: { owner, master: 4, kind: 'unit', cost: { food: 25, wood: 45 } } });
  for (const t of [20000, 21000, 60000, 61000, 62000]) S.events.push(kill(t, t % 2000 ? 2 : 1));
  S.events.sort((a, b) => a.t - b.t); }"""


def test_focus_slot_has_no_tech_card_and_the_fight_card_picks_any_fight(
    browser: Any, base: str
) -> None:
    saved = {**SEEN, "hud": {"preset": "caster", "hintSeen": True, "focus": "techs"}}
    page = open_page(browser, base, saved=saved)
    page.wait_for_function("document.querySelector('#focus .fs-tabs')")
    # The research card is gone, and a saved Tech card opens on the Fight card.
    cards = page.eval_on_selector_all("#focus [data-focus]", "bs => bs.map((b) => b.dataset.focus)")
    assert cards == ["production", "eco", "fight", "none"]
    assert page.get_attribute('#focus [data-focus="fight"]', "aria-pressed") == "true"
    assert "No fight yet" in page.inner_text("#focus .fs-body")

    # The Eco card keeps its rows and adds the new ones the recording has.
    page.click('#focus [data-focus="eco"]')
    page.wait_for_selector("#focus .ctable")
    rows = page.eval_on_selector_all(
        "#focus .ctable tbody th", "ths => ths.map((th) => th.textContent)"
    )
    for label in ("Gatherers F / W / G / S", "Idle villagers", "Idle TC (growth)", "Banked"):
        assert label in rows, rows
    page.click('#focus [data-focus="fight"]')

    # Two fights (kills ten seconds apart or more are separate); the clock is after both.
    page.evaluate(FIGHTS)
    page.evaluate("() => { window.vantage.S.t = 90000; }")
    page.wait_for_selector("#fs-fight-pick")
    labels = page.eval_on_selector_all("#fs-fight-pick option", "os => os.map((o) => o.text)")
    assert labels == [
        "Latest",
        f"1:00{DASH}1:02 · 3 kills · 210 res",
        f"0:20{DASH}0:21 · 2 kills · 140 res",
    ]
    assert page.input_value("#fs-fight-pick") == "latest"
    assert page.inner_text("#focus .fs-fight-when").startswith(f"1:00{DASH}1:02")

    # Pick the older one: it stays picked, in the same <select>, across re-renders.
    page.evaluate("() => { document.getElementById('fs-fight-pick').marked = true; }")
    page.select_option("#fs-fight-pick", "20000")
    page.wait_for_function(
        "document.querySelector('#focus .fs-fight-when').textContent.startsWith('0:20')"
    )
    page.evaluate("() => { window.vantage.S.t = 95000; }")
    page.wait_for_timeout(600)
    assert page.input_value("#fs-fight-pick") == "20000"
    assert page.evaluate("document.getElementById('fs-fight-pick').marked") is True
    assert page.inner_text("#focus .fs-fight-when").startswith(f"0:20{DASH}0:21")
    # Its jump button seeks to three seconds before it (this recording ends sooner).
    page.click("#focus .fs-fight-when")
    page.wait_for_function("window.vantage.S.t === Math.min(17000, window.vantage.S.end)")
    # Seeking back before the picked fight falls back to Latest (and to no fight at all here).
    page.wait_for_function(
        "document.querySelector('#focus .fs-body').textContent.includes('No fight yet')"
    )
    page.evaluate("() => { window.vantage.S.t = 90000; }")
    page.wait_for_function("document.getElementById('fs-fight-pick')?.value === 'latest'")
    assert page.inner_text("#focus .fs-fight-when").startswith(f"1:00{DASH}1:02")
    # Latest from the list again after a pick.
    page.select_option("#fs-fight-pick", "20000")
    page.select_option("#fs-fight-pick", "latest")
    page.wait_for_function(
        "document.querySelector('#focus .fs-fight-when').textContent.startsWith('1:00')"
    )
    assert not page.errors
    page.context.close()


def test_obs_overlay_is_transparent_and_carries_nothing_of_its_own(browser: Any, base: str) -> None:
    page = open_page(browser, base + "/?overlay=1#hud=caster")
    page.wait_for_function("document.getElementById('pulse')?.textContent.trim()")
    styles = page.evaluate(
        """() => { const h = getComputedStyle(document.documentElement);
          const b = getComputedStyle(document.body);
          return [h.colorScheme, h.backgroundColor, b.backgroundColor]; }"""
    )
    # A dark colour scheme on the root makes the browser paint a dark canvas behind the page.
    assert styles == ["normal", "rgba(0, 0, 0, 0)", "rgba(0, 0, 0, 0)"], styles
    for stray in ("#viewer-build", "#skip-links", "#hud-hint", "#minimap-wrap", "#status-line"):
        assert not page.locator(stray).is_visible(), stray
    page.context.close()


def test_glyph_buttons_have_names_and_skip_links_shorten_the_keyboard_path(
    browser: Any, base: str
) -> None:
    page = open_page(browser, base, size=(1280, 720))
    names = page.evaluate(
        """() => [...document.querySelectorAll('#time-controls button, #time-controls2 button,'
          + ' #event-filters button, .dash-nav, #minimap-tools button, #minimap-tools a')]
          .filter((e) => e.getClientRects().length)
          .map((e) => (e.getAttribute('aria-label') || e.textContent).trim())"""
    )
    assert names and all(len(name) > 3 for name in names), [n for n in names if len(n) <= 3]

    # In a 720p window nothing is drawn under 12 px.
    small = page.evaluate(
        """() => { const out = [];
          const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
          let n; while ((n = w.nextNode())) { const e = n.parentElement;
            if (!n.nodeValue.trim() || !e.getClientRects().length) continue;
            const s = getComputedStyle(e); if (s.visibility === 'hidden') continue;
            if (parseFloat(s.fontSize) < 11.99)
              out.push(n.nodeValue.trim().slice(0, 20) + ' ' + s.fontSize); }
          return out; }"""
    )
    assert small == [], small[:10]

    # The first Tab stops are the skip links; they reach what used to be 34 to 71 stops away.
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.dataset.skip") == "time"
    assert page.locator("#skip-links").bounding_box()["y"] >= 0, "visible while focused"
    page.keyboard.press("Enter")
    assert page.evaluate("document.activeElement.id") == "tc-play"
    page.focus('#skip-links [data-skip="customize"]')
    page.keyboard.press("Enter")
    page.locator("#panels-menu").wait_for(state="visible")
    assert page.evaluate("!!document.activeElement.closest('#panels-menu')")
    page.keyboard.press("Escape")

    # Statistics opened from the keyboard takes the focus: Tab walks the window.
    page.keyboard.press("Control+Alt+s")
    page.wait_for_selector("#overlay-stats #chart")
    assert page.evaluate("document.activeElement.id") == "stats-title"
    for _ in range(6):
        page.keyboard.press("Tab")
        assert page.evaluate("!!document.activeElement.closest('#overlay-stats')")
    assert page.errors == []
    page.context.close()


# -- the Selection panel remembers what the viewer set up ----------------------------------------

PANEL_STATE = """() => { const e = document.getElementById('unitpanel');
  const d = e.querySelector('details[data-panel-detail]');
  const b = e.querySelector('[data-upgrades-toggle]');
  return { shown: e.getClientRects().length > 0, details: d ? d.open : null,
    overflow: b ? b.getAttribute('aria-expanded') : null }; }"""
OWNED = """() => { const v = window.vantage, seen = new Set(), out = [];
  for (const r of v.world.currentRows()) {
    if (r[1] > 0 && !seen.has(r[2])) { seen.add(r[2]); out.push(r[0]); } }
  return out; }"""


def select(page: Any, entity: int) -> None:
    page.evaluate("(id) => { window.vantage.S.selection = new Set([id]); }", entity)
    page.wait_for_function(
        "(id) => document.getElementById('unitpanel').getClientRects().length > 0"
        " && document.querySelector('#unitpanel details[data-panel-detail]')",
        arg=entity,
    )
    page.wait_for_timeout(600)


def test_selection_panel_keeps_sections_place_and_size_across_selections_and_reload(
    browser: Any, base: str
) -> None:
    page = open_page(browser, base)
    ids = page.evaluate(OWNED)
    assert len(ids) >= 2, "the synthetic match has two kinds of owned object"
    first, second = ids[0], ids[1]
    third = ids[2] if len(ids) > 2 else ids[0]

    select(page, first)
    assert page.evaluate(PANEL_STATE)["details"] is False
    page.click("#unitpanel details[data-panel-detail] > summary")
    has_overflow = page.locator("#unitpanel [data-upgrades-toggle]").count() > 0
    if has_overflow:
        page.click("#unitpanel [data-upgrades-toggle]")

    # Drag it by the grip in its hover toolbar.
    x, y, _, _ = page.evaluate(RECT, "unitpanel")
    page.mouse.move(x + 100, y + 30)
    grip = page.locator('#panel-tools [data-pt="move"]')
    grip.wait_for(state="visible")
    box = grip.bounding_box()
    assert box is not None
    page.mouse.move(box["x"] + 5, box["y"] + 5)
    page.mouse.down()
    page.mouse.move(box["x"] - 700, box["y"] - 400, steps=8)
    page.mouse.up()
    moved = page.evaluate(RECT, "unitpanel")
    assert moved[0] < x - 500 and moved[1] < y
    stored = page.evaluate("window.vantage.settings.panelSizes.unitpanel")
    assert len(stored["anchor"]) == 2, "a natural-size panel holds on to a corner, not the centre"

    # Another object, a third, and a selection made after clearing it: the same corner, the same
    # sections, whatever height the content has.
    for entity in (second, third):
        select(page, entity)
        assert page.evaluate(RECT, "unitpanel")[:2] == moved[:2]
        state = page.evaluate(PANEL_STATE)
        assert state["details"] is True
        assert state["overflow"] in ("true", None)
    page.evaluate("() => { window.vantage.S.selection = new Set(); }")
    page.wait_for_timeout(500)
    select(page, first)
    assert page.evaluate(RECT, "unitpanel")[:2] == moved[:2]

    # Resize it: the size holds for every later selection.
    page.mouse.move(moved[0] + 60, moved[1] + 40)
    handle = page.locator('#panel-resize-handles [data-corner="se"]')
    handle.wait_for(state="visible")
    hbox = handle.bounding_box()
    assert hbox is not None
    page.mouse.move(hbox["x"] + 7, hbox["y"] + 7)
    page.mouse.down()
    page.mouse.move(moved[0] + 432, moved[1] + 472, steps=6)
    page.mouse.up()
    sized = page.evaluate(RECT, "unitpanel")
    assert sized[:2] == moved[:2] and abs(sized[2] - 432) <= 8 and abs(sized[3] - 472) <= 8
    select(page, second)
    assert page.evaluate(RECT, "unitpanel") == sized

    # A reload: the same rectangle, the same sections, for whatever is selected next.
    saved = page.evaluate(f"JSON.parse(localStorage.getItem('{KEY}'))")
    assert saved["selectionPanel"]["open"] == {"details": True}
    assert saved["panelSizes"]["unitpanel"]["moved"] is True
    page.reload()
    ready(page)
    select(page, third)
    assert page.evaluate(RECT, "unitpanel") == sized
    state = page.evaluate(PANEL_STATE)
    assert state["details"] is True and state["overflow"] in ("true", None)

    # A smaller window: clamped on screen.
    page.set_viewport_size({"width": 1280, "height": 720})
    page.wait_for_timeout(1000)
    left, top, width, height = page.evaluate(RECT, "unitpanel")
    assert left >= 0 and top >= 0 and left + width <= 1280 and top + height <= 720
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.wait_for_timeout(600)

    # Customize -> Reset Selection panel puts all of it back.
    page.keyboard.press("Alt+v")
    page.locator("#panels-menu").wait_for(state="visible")
    page.evaluate("document.querySelector('#panels-menu [data-cz-sec=layout]').open = true")
    page.click('#panels-menu [data-cz="reset-selection"]')
    page.keyboard.press("Escape")
    page.wait_for_timeout(600)
    assert page.evaluate("window.vantage.settings.panelSizes.unitpanel") is None
    assert page.evaluate("window.vantage.settings.selectionPanel.open") == {}
    select(page, first)
    assert page.evaluate(PANEL_STATE)["details"] is False
    assert page.evaluate(RECT, "unitpanel")[0] > moved[0] + 300, "back in its default place"
    assert page.errors == []
    page.context.close()


def test_minimal_details_view_stays_open_for_later_selections(browser: Any, base: str) -> None:
    page = open_page(browser, base, saved={**SEEN, "hud": {"preset": "minimal", "hintSeen": True}})
    ids = page.evaluate(OWNED)
    page.evaluate("(id) => { window.vantage.S.selection = new Set([id]); }", ids[0])
    page.click("#selchip [data-chip]")
    select(page, ids[0])
    page.click("#unitpanel details[data-panel-detail] > summary")
    # Nothing selected, then something else: the full panel again, with Details open.
    page.evaluate("() => { window.vantage.S.selection = new Set(); }")
    page.wait_for_timeout(500)
    select(page, ids[1])
    assert page.evaluate(PANEL_STATE)["details"] is True
    page.reload()
    ready(page)
    select(page, ids[0])
    assert page.evaluate(PANEL_STATE)["details"] is True
    # "compact" returns to the one-line chip, and that is remembered too.
    page.click("#selchip [data-chip-back]")
    page.wait_for_function("document.getElementById('unitpanel').getClientRects().length === 0")
    assert page.evaluate("window.vantage.settings.selectionPanel.expanded") is False
    page.context.close()


# -- the phone layout --------------------------------------------------------------------------


def test_phone_layout_tabs_sheet_and_no_sideways_scroll(browser: Any, base: str) -> None:
    page = open_page(browser, base + "/?hud=minimal", size=(390, 844), touch=True)
    page.wait_for_function("document.body.classList.contains('hud-phone')")
    page.wait_for_selector("#phone-tabs:not(.hidden)")
    page.wait_for_function("document.getElementById('story')?.getClientRects().length")
    assert page.evaluate(VISIBLE) == ["pulse", "story"]
    assert page.locator("#phone-tabs").get_attribute("role") == "tablist"
    targets = page.evaluate(
        """() => [...document.querySelectorAll('#phone-tabs button, #story .st-bar button')]
          .filter((b) => b.getClientRects().length).map((b) => {
            const r = b.getBoundingClientRect(); return Math.min(r.width, r.height); })"""
    )
    assert targets and min(targets) >= 44, targets
    fits = (
        "document.documentElement.scrollWidth <= innerWidth"
        " && document.body.scrollWidth <= innerWidth"
    )
    assert page.evaluate(fits)

    for tab in ("bank", "table", "unit", "more"):
        page.tap(f'#phone-tabs [data-tab="{tab}"]')
        sheet = page.locator("#phone-sheet")
        assert sheet.is_visible()
        assert page.get_attribute(f'#phone-tabs [data-tab="{tab}"]', "aria-selected") == "true"
        over = page.evaluate(
            "[...document.querySelectorAll('#phone-sheet *')]"
            ".filter((e) => e.getBoundingClientRect().right > innerWidth + 1).length"
        )
        assert over == 0, tab
        assert page.evaluate(fits), tab
    assert "Customize" in page.inner_text("#phone-sheet")
    page.tap('#phone-sheet [data-more="customize"]')
    drawer = page.locator("#panels-menu")
    drawer.wait_for(state="visible")
    box = drawer.bounding_box()
    assert box is not None and box["x"] >= 0 and box["x"] + box["width"] <= 390
    page.keyboard.press("Escape")
    page.tap('#phone-tabs [data-tab="table"]')
    assert "Villagers" in page.inner_text("#phone-sheet")
    page.tap("#phone-sheet .ph-close")
    assert not page.locator("#phone-sheet").is_visible()

    # Full is not a phone layout: the old HUD comes back, panels in their places.
    page.evaluate("window.vantage.actions.hudPresetFull()")
    page.wait_for_function("!document.body.classList.contains('hud-phone')")
    assert page.evaluate("document.getElementById('overview').parentElement.id") == "leftcol"
    assert page.errors == []
    page.context.close()


@pytest.mark.parametrize("gpu", [False, True], ids=["canvas", "webgl"])
def test_zoomed_game_art_draws_entities_not_only_selection_rings(
    browser: Any, base: str, gpu: bool
) -> None:
    """Real drawSprites path, synthetic art; no game installation required."""
    import base64

    page = browser.new_page(viewport={"width": 1280, "height": 800})
    page.errors = []
    page.on("pageerror", lambda error: page.errors.append(str(error)))
    page.goto(base)
    page.wait_for_function("window.vantage?.S.view && document.body.dataset.startup === 'ready'")
    page.evaluate("vantage.S.playing = false")
    # A generated solid square, not a game asset. Initially missing strips must
    # also survive a frame (the branch with the stale `failed` reference).
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAAL0lEQVR4nO3OIQEAAAgDMCIRjYg0gxg3E/Or7bmkEhAQEBAQEBAQEBAQEBAQSAceUUZ8iO1NzJQAAAAASUVORK5CYII="
    )
    page.route(
        "**/sprite/**",
        lambda route: route.fulfill(
            body=png,
            content_type="image/png",
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Expose-Headers": "X-Sprite-Meta",
                "X-Sprite-Meta": json.dumps(
                    {
                        "cw": 32,
                        "ch": 32,
                        "ax": 16,
                        "ay": 28,
                        "n": 1,
                        "step": 1,
                        "per": 1,
                        "duration": 0,
                        "pc": False,
                    }
                ),
            },
        ),
    )
    before = page.evaluate(
        """gpu => {
      const {S, settings, world} = vantage;
      window.spriteBlits = 0;
      const draw = CanvasRenderingContext2D.prototype.drawImage;
      CanvasRenderingContext2D.prototype.drawImage = function(...args) {
        if (new Error().stack.includes('drawSprites')) window.spriteBlits++;
        return draw.apply(this, args);
      };
      S.gameArt = true; settings.gameGraphics = true; settings.gpuSprites = gpu;
      settings.waitForGraphics = false;
      for (const r of S.view.entities) r[8] = [[900001, 0, 0, 0]];
      S.view = { ...S.view }; S.nextView = null;
      world.setCamera(2, 2, 1.2);
      return { frames: world.drawTimes.n, instances: world.gpuSpriteStats().instances };
    }""",
        gpu,
    )
    for _ in range(100):
        page.wait_for_timeout(100)
        stats = page.evaluate("""() => ({
          sprites: vantage.world.spritesOn(), missing: vantage.world.spriteStats.missing,
          frames: vantage.world.drawTimes.n, gpu: vantage.world.gpuSpriteStats(),
          blits: window.spriteBlits,
        })""")
        drawn = stats["gpu"]["instances"] - before["instances"] if gpu else stats["blits"]
        if page.errors or (drawn > 0 and stats["frames"] > before["frames"]):
            break
    try:
        assert not page.errors, (page.errors, stats)
        assert stats["sprites"]
        assert stats["frames"] > before["frames"], stats
        assert drawn > 0, f"No entities drawn, even if missing == 0: {stats}"
    finally:
        page.context.close()


# Frame time budgets for the big-scene check below, in ms of work inside the
# frame callback (median over ~90 frames), under software WebGL. Generous: eight
# to ten times what a busy development machine measures (1.1 ms zoomed in, 4 ms
# zoomed out, HUD tasks of 1-2.5 ms), so only a real regression (an all-rows pass
# that is no longer culled, a per-frame rebuild) trips them, not a slow CI runner.
BIG_SCENE_ROWS = 3000
BUDGET_ZOOMED_IN_MS = 10.0
BUDGET_ZOOMED_OUT_MS = 40.0
BUDGET_HUD_TASK_MS = 25.0
FRAME_PROBE = """
window.__frames = []; window.__hud = [];
const raf = window.requestAnimationFrame.bind(window);
window.requestAnimationFrame = (fn) => raf((now) => {
  const a = performance.now(); fn(now);
  if (fn.name === 'tick') window.__frames.push(performance.now() - a);
});
const MC = window.MessageChannel;
const onmessage = Object.getOwnPropertyDescriptor(MessagePort.prototype, 'onmessage');
window.MessageChannel = function () {
  const ch = new MC();
  Object.defineProperty(ch.port1, 'onmessage', { set(fn) {
    onmessage.set.call(ch.port1, (e) => {
      const a = performance.now(); fn(e); window.__hud.push(performance.now() - a);
    });
  } });
  return ch;
};
"""


def test_zoomed_game_art_big_scene_stays_within_frame_budgets(browser: Any, base: str) -> None:
    """A late team game's worth of rows, zoomed in on game art and zoomed out.

    Synthetic art and rows (no game installation). Checks that what is off
    screen costs next to nothing (the zoomed-in frame draws a fraction of the
    rows and fits its budget), that a still picture uploads and fetches nothing,
    and that no HUD task is long enough to drop frames.
    """
    import base64

    page = browser.new_page(viewport={"width": 1280, "height": 800})
    page.errors = []
    page.on("pageerror", lambda error: page.errors.append(str(error)))
    page.add_init_script(FRAME_PROBE)
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAAL0lEQVR4nO3OIQEAAAgDMCIRjYg0gxg3E/Or7bmkEhAQEBAQEBAQEBAQEBAQSAceUUZ8iO1NzJQAAAAASUVORK5CYII="
    )
    meta = {"cw": 32, "ch": 32, "ax": 16, "ay": 28, "n": 1, "step": 1, "per": 1, "duration": 0}
    requests: list[str] = []

    def strip(route: Any) -> None:
        requests.append(route.request.url)
        route.fulfill(
            body=png,
            content_type="image/png",
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Expose-Headers": "X-Sprite-Meta",
                "X-Sprite-Meta": json.dumps({**meta, "pc": False}),
            },
        )

    page.route("**/sprite/**", strip)
    page.goto(base)
    page.wait_for_function("window.vantage?.S.view && document.body.dataset.startup === 'ready'")
    page.evaluate(
        """rows => {
      const {S, settings} = vantage;
      S.playing = false;
      S.gameArt = true; settings.gameGraphics = true; settings.gpuSprites = true;
      settings.waitForGraphics = false;
      // Copies of the match's own rows over a 70 x 70 tile field, in a fixed
      // pseudo-random order, with sixteen different pictures.
      const own = S.view.entities, out = [];
      let seed = 12345;
      const rnd = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
      for (let i = 0; i < rows; i++) {
        const r = own[i % own.length].slice();
        r[0] = 500000 + i; r[3] = rnd() * 70; r[4] = rnd() * 70;
        r[8] = [[900001 + (i % 16), 0, 0, 0]];
        out.push(r);
      }
      S.view = { ...S.view, entities: out }; S.nextView = null;
    }""",
        BIG_SCENE_ROWS,
    )

    def measure(zoom: float) -> dict[str, Any]:
        page.evaluate("z => vantage.world.setCamera(35, 35, z)", zoom)
        # Until the picture is complete and still.
        page.wait_for_function(
            """() => { const w = vantage.world, g = w.gpuSpriteStats();
              const now = g.uploads + ':' + w.spriteMemory().strips;
              const same = window.__still === now; window.__still = now;
              return same && w.initialFrameReady(); }""",
            polling=400,
            timeout=60000,
        )
        before = page.evaluate(
            "() => { window.__frames.length = 0; return vantage.world.gpuSpriteStats(); }"
        )
        fetched = len(requests)
        page.wait_for_function("window.__frames.length >= 90", timeout=120000)
        got = page.evaluate(
            """() => ({ work: [...window.__frames].sort((a, b) => a - b),
              gpu: vantage.world.gpuSpriteStats(), hud: Math.max(0, ...window.__hud) })"""
        )
        frames = len(got["work"])
        return {
            "median": got["work"][frames // 2],
            "instances": (got["gpu"]["instances"] - before["instances"]) / frames,
            "uploads": got["gpu"]["uploads"] - before["uploads"],
            "fetched": len(requests) - fetched,
            "hud": got["hud"],
        }

    near = far = None
    try:
        near = measure(3.5)
        far = measure(1.0)
        assert not page.errors, page.errors
        # Game art is drawn in both, and the zoomed-in view draws only its own part.
        assert near["instances"] >= 1, near
        assert far["instances"] > 5 * near["instances"], (near, far)
        # A still picture: nothing uploaded, nothing asked of the server.
        assert near["uploads"] == 0 and far["uploads"] == 0, (near, far)
        assert near["fetched"] == 0 and far["fetched"] == 0, (near, far)
        assert near["median"] < BUDGET_ZOOMED_IN_MS, near
        # Whatever the machine: a tenth of the rows on screen is well under the cost of all.
        assert near["median"] < 0.6 * far["median"], (near, far)
        assert far["median"] < BUDGET_ZOOMED_OUT_MS, far
        assert max(near["hud"], far["hud"]) < BUDGET_HUD_TASK_MS, (near, far)
    finally:
        print("big scene:", near, far)  # shown with -s, and on failure
        page.context.close()


def test_trackpad_scroll_pans_pinch_zooms_and_a_mouse_wheel_still_zooms(
    browser: Any, base: str
) -> None:
    """Wheel events as a trackpad and a mouse send them, on the real page."""
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    page.errors = []
    page.on("pageerror", lambda error: page.errors.append(str(error)))
    page.add_init_script(
        f"localStorage.setItem({json.dumps(KEY)}, "
        f"{json.dumps(json.dumps({**QUIET, 'cameraSmoothMs': 0}))})"
    )
    page.goto(base)
    page.wait_for_function("window.vantage?.S.view && document.body.dataset.startup === 'ready'")
    page.evaluate("() => { vantage.S.playing = false; vantage.world.setCamera(4, 4, 2); }")
    cdp = page.context.new_cdp_session(page)

    def wheel(dx: float, dy: float, ctrl: bool = False) -> None:
        cdp.send(
            "Input.dispatchMouseEvent",
            {"type": "mouseWheel", "x": 640, "y": 400, "deltaX": dx, "deltaY": dy}
            | ({"modifiers": 2} if ctrl else {}),
        )

    def camera() -> list[float]:
        return page.evaluate(
            "() => [vantage.S.camera.x, vantage.S.camera.y, vantage.S.camera.zoom]"
        )

    try:
        page.wait_for_timeout(300)  # the camera was just sent somewhere: let that settle
        x0, y0, z0 = camera()
        # Two fingers: pixel deltas with a sideways part. 60 px right, 24 px down in all.
        for _ in range(12):
            wheel(5, 2)
            page.wait_for_timeout(10)
        page.wait_for_timeout(100)
        x1, y1, z1 = camera()
        assert z1 == z0
        # Screen px the camera moved (tiles are 32 x 16 px at zoom 1).
        moved = [((x1 + y1) - (x0 + y0)) * 16 * z1, ((y1 - x1) - (y0 - x0)) * 8 * z1]
        assert abs(moved[0] - 60) < 1 and abs(moved[1] - 24) < 1, moved
        # A pinch (ctrl set, no key down): zooms in at once, the camera stays put
        # under the pointer at the centre.
        page.wait_for_timeout(250)
        for _ in range(10):
            wheel(0, -4, ctrl=True)
            page.wait_for_timeout(10)
        x2, y2, z2 = camera()
        assert z2 > z1 * 1.3, (z1, z2)
        assert abs(x2 - x1) < 0.01 and abs(y2 - y1) < 0.01
        # A mouse wheel notch zooms as it always did (out, here).
        page.wait_for_timeout(250)
        wheel(0, 100)
        page.wait_for_timeout(100)
        assert camera()[2] < z2
        # The setting can make two-finger scrolling zoom again.
        page.evaluate("() => { vantage.settings.twoFingerScroll = 'zoom'; }")
        page.wait_for_timeout(250)
        z3 = camera()[2]
        wheel(5, 2)
        page.wait_for_timeout(100)
        assert camera()[2] != z3
        assert not page.errors, page.errors
    finally:
        page.context.close()
