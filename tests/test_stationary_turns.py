"""A replay track retains a unit's turn between matching keyframes."""

from tests.helpers import delta, set_entity, snapshot_frame
from vantage.frames import Frame
from vantage.gamedata import GameData
from vantage.timeline import Timeline


def test_unit_track_keeps_turns_without_position_changes():
    timeline = Timeline(GameData(None))
    timeline.feed(snapshot_frame(0))

    def feed(time, *edits):
        timeline.feed(Frame(time=time, patch=delta(time, *edits).forward()))

    feed(1000)
    feed(1100, set_entity(104, "Entity", "facet", "UInt8", 5))
    feed(1300, set_entity(104, "Entity", "facet", "UInt8", 0))
    feed(1500, set_entity(104, "Entity", "hp", "Float", 80.0))
    feed(2000)

    start = timeline.view_at(1000)
    end = timeline.view_at(2000)
    assert start is not None and end is not None
    assert [row[7] for row in start["entities"] if row[0] == 104] == [0]
    assert [row[7] for row in end["entities"] if row[0] == 104] == [0]
    assert start["unit_track"] == [
        [1100, [[104, 3.0, 3.0, 5]]],
        [1300, [[104, 3.0, 3.0, 0]]],
    ]
