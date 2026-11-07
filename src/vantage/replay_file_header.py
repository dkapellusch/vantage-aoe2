"""Structural initial replay header for DE build54800/save68.9/options1123.

Native140fbe670 calls GameOptions1413d2300/1413d88f0, then hands the same
stream directly to outer World14169bd10. This reader stops before World's
flag. Original native evidence is retained in world-envelope/header and
player-ai/file-header artifacts. No record search or runtime fixup occurs.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Literal

from vantage.replay_binary import SaveDecodeError, SaveReader

HeaderFieldKind = Literal["u8", "u32", "i32", "u64", "f32", "de_string", "guid", "fixed"]


@dataclass(frozen=True, slots=True)
class SavedReplayHeaderField:
    """A native wire field; f32 values retain their unsigned bit patterns.

    DE strings retain their bytes without decoding or dropping wire NULs;
    ``raw`` additionally retains marker/length order. GUIDs remain16 bytes.
    """

    name: str
    offset: int
    end_offset: int
    kind: HeaderFieldKind
    value: int | bytes
    raw: bytes

    @property
    def float_value(self) -> float:
        if self.kind != "f32":
            raise ValueError(f"{self.name} is not a saved f32")
        return float(struct.unpack("<f", self.raw)[0])


@dataclass(frozen=True, slots=True)
class SavedReplayHeaderSection:
    name: str
    native_reader: int
    offset: int
    end_offset: int
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedHeaderVector:
    section: SavedReplayHeaderSection
    count_width: int
    count: int
    values: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class SavedHeaderUniqueFile:
    """Reflection property order is Crc then PathSpec, despite registration order."""

    section: SavedReplayHeaderSection
    crc: int
    path_bytes: bytes


@dataclass(frozen=True, slots=True)
class SavedHeaderFileEntry:
    reference: SavedHeaderUniqueFile
    raw_data: int


@dataclass(frozen=True, slots=True)
class SavedHeaderFileArray:
    section: SavedReplayHeaderSection
    capacity: int
    entries: tuple[SavedHeaderFileEntry, ...]


@dataclass(frozen=True, slots=True)
class SavedHeaderDlcOptions:
    section: SavedReplayHeaderSection
    version: int
    dataset_id: int
    ids: SavedHeaderVector


@dataclass(frozen=True, slots=True)
class SavedGameOptionsPlayer:
    """Version15 lobby slot, with native member names and raw wire fields.

    Scenario player index and slot colour override are distinct saved words.
    The leading word is the record version; it is not a DLC identifier.
    """

    section: SavedReplayHeaderSection
    slot: int
    version: int
    scenario_player_index: int
    civilization_mode_id: int
    civilization_id: int
    random_civ_choices: SavedHeaderVector
    humanity: int
    world_player_index: int
    fields: dict[str, SavedReplayHeaderField]


@dataclass(frozen=True, slots=True)
class SavedReplayGameOptions:
    section: SavedReplayHeaderSection
    version_word: int
    dlc: SavedHeaderDlcOptions
    num_players_excluding_gaia: int
    max_players_for_lobby: int
    players: tuple[SavedGameOptionsPlayer, ...]
    resource_files: tuple[SavedHeaderUniqueFile, ...]
    resource_raw_data: tuple[int, ...]
    custom_map_pool: tuple[tuple[SavedHeaderFileEntry, SavedHeaderFileEntry], ...]
    standard_map_pool: SavedHeaderVector
    custom_ai_files: SavedHeaderFileArray
    custom_xs_files: SavedHeaderFileArray
    civilizations: SavedHeaderVector
    civilizations_pompeii: SavedHeaderVector
    fields: dict[str, SavedReplayHeaderField]


@dataclass(frozen=True, slots=True)
class SavedReplayFileHeader:
    offset: int
    end_offset: int
    game_version: bytes
    save_version: int
    build_word: int
    build: int
    date_time_played: int
    options: SavedReplayGameOptions
    save_game_name: bytes
    random_seed: int
    game_duration_word: int
    time_of_save: int
    fields: dict[str, SavedReplayHeaderField]
    sections: dict[str, SavedReplayHeaderSection]
    raw: bytes


class _Fields:
    def __init__(
        self,
        reader: SaveReader,
        fields: dict[str, SavedReplayHeaderField],
        sections: dict[str, SavedReplayHeaderSection],
        prefix: str = "",
    ) -> None:
        self.r = reader
        self.fields = fields
        self.sections = sections
        self.prefix = prefix

    def _record(self, label: str, start: int, kind: HeaderFieldKind, value: int | bytes) -> None:
        name = self.prefix + label
        self.fields[name] = SavedReplayHeaderField(
            name, start, self.r.pos, kind, value, self.r.data[start : self.r.pos]
        )

    def word(
        self, name: str, width: int = 4, *, signed: bool = False, float_word: bool = False
    ) -> int:
        start = self.r.pos
        value = int.from_bytes(self.r.take(width), "little", signed=signed)
        kind: HeaderFieldKind = "f32" if float_word else "u32"
        if not float_word:
            if width == 1:
                kind = "u8"
            elif width == 8:
                kind = "u64"
            elif signed:
                kind = "i32"
        self._record(name, start, kind, value)
        return value

    def words(self, names: str, width: int = 4) -> tuple[int, ...]:
        return tuple(self.word(name, width) for name in names.split())

    def fixed(self, name: str, size: int, *, guid: bool = False) -> bytes:
        start = self.r.pos
        value = self.r.take(size)
        self._record(name, start, "guid" if guid else "fixed", value)
        return value

    def string(self, name: str) -> bytes:
        start = self.r.pos
        value = self.r.de_bytes()
        self._record(name, start, "de_string", value)
        return value

    def strings(self, names: str) -> None:
        for name in names.split():
            self.string(name)

    def expected(self, name: str, value: int, *, float_word: bool = False) -> int:
        start = self.r.pos
        actual = self.word(name, float_word=float_word)
        if actual != value:
            raise SaveDecodeError(f"unsupported {self.prefix}{name} {actual:#x}", start)
        return actual

    def marker(self, name: str) -> None:
        self.expected("marker." + name, 155555)

    def section(self, name: str, native: int, start: int) -> SavedReplayHeaderSection:
        name = self.prefix + name
        result = SavedReplayHeaderSection(
            name, native, start, self.r.pos, self.r.data[start : self.r.pos]
        )
        self.sections[name] = result
        return result

    def count(self, name: str, width: int, minimum_item_size: int) -> int:
        start = self.r.pos
        count = self.word(name, width)
        if count > self.r.remaining // minimum_item_size:
            raise SaveDecodeError(f"invalid {self.prefix}{name} {count}", start)
        return count

    def vector(self, name: str, native: int, *, count_width: int = 4) -> SavedHeaderVector:
        start = self.r.pos
        count = self.count(name + ".count", count_width, 4)
        # The u32-count StdSerializer helpers cap elements at0x6400000;
        # the two manual u64-count civilization loops use the byte bound above.
        if count_width == 4 and count > 0x6400000:
            raise SaveDecodeError(f"invalid {self.prefix}{name} count {count}", start)
        values = tuple(self.word(f"{name}[{i}]") for i in range(count))
        return SavedHeaderVector(self.section(name, native, start), count_width, count, values)

    def unique_file(self, name: str) -> SavedHeaderUniqueFile:
        start = self.r.pos
        # Reflect14098f420 traverses its strcmp-ordered property tree:
        # Crc14094c540 before PathSpec14094c580→140944630→DEstring140a1bdf0.
        crc = self.word(name + ".Crc")
        path = self.string(name + ".PathSpec")
        return SavedHeaderUniqueFile(self.section(name, 0x14098F420, start), crc, path)

    def file_entry(self, name: str) -> SavedHeaderFileEntry:
        reference = self.unique_file(name)
        # The rawData word is serialized again after the reflected reference.
        return SavedHeaderFileEntry(reference, self.word(name + ".rawData"))

    def file_array(self, name: str) -> SavedHeaderFileArray:
        start = self.r.pos
        capacity = self.count(name + ".capacity", 8, 12)
        entries = tuple(self.file_entry(f"{name}[{i}]") for i in range(capacity))
        return SavedHeaderFileArray(self.section(name, 0x1413D88F0, start), capacity, entries)


def read_file_header(reader: SaveReader) -> SavedReplayFileHeader:
    """Read an inflated initial header, leaving the outer World flag unread.

    Only the proven VER9.4/save68.9/build54800/options1123/player15 profile
    is accepted. The saved version must equal ``reader.version``. Failure
    restores the whole caller cursor; ``reader.version`` is never changed.
    Every string, list and scalar is read structurally with checked bounds.
    This does not resolve asset IDs, sanitize names or emulate native fixups.
    """
    start = reader.pos
    try:
        return _read_file_header(reader)
    except SaveDecodeError:
        reader.pos = start
        raise


def _read_file_header(r: SaveReader) -> SavedReplayFileHeader:
    start = r.pos
    if r.version != 0x44E666:
        raise SaveDecodeError(f"unsupported file-header save version {r.version:#x}", start)
    b = _Fields(r, {}, {})
    version = b.fixed("game_version", 8)
    if version != b"VER 9.4\0":
        raise SaveDecodeError("unsupported replay game-version bytes", start)
    b.expected("legacy_save_version", 0xBF800000, float_word=True)
    save_version = b.word("save_version")
    if save_version != r.version:
        raise SaveDecodeError(
            f"saved file version {save_version:#x} differs from reader version {r.version:#x}",
            r.pos - 4,
        )
    # The proven native54800 build word includes the bit17 flag. Other flag
    # encodings are deliberately outside this initial-header profile.
    build_word = b.expected("build", 0x2D610)
    date = b.word("date_time_played")
    b.section("header.prefix", 0x140FBE670, start)
    options = _read_options(b)
    tail_start = r.pos
    save_name = b.string("save_game_name")
    seed = b.word("random_seed")
    duration = b.word("game_duration", float_word=True)
    time_of_save = b.word("time_of_save", 8)
    b.section("header.tail", 0x140FBE670, tail_start)
    b.section("header", 0x140FBE670, start)
    return SavedReplayFileHeader(
        start,
        r.pos,
        version,
        save_version,
        build_word,
        build_word & 0x1FFFF,
        date,
        options,
        save_name,
        seed,
        duration,
        time_of_save,
        b.fields,
        b.sections,
        r.data[start : r.pos],
    )


def _read_player(parent: _Fields, slot: int) -> SavedGameOptionsPlayer:
    r = parent.r
    start = r.pos
    b = _Fields(r, parent.fields, parent.sections, f"player[{slot}].")
    version = b.expected("version", 15)
    scenario_index = b.word("mScenarioPlayerIndex", signed=True)
    b.words("mOverrideScenarioColorTableId mUserChosenTeam mResolvedTeam", 1)
    b.word("mDatFileCrc")
    b.word("mMultiPlayerGameVersion", 1)
    choice_start = r.pos
    mode = b.word("mCivilizationModeId")
    civilization = b.word("civilization_id")
    choices = b.vector("random_civ_choices", 0x1413A18C0)
    b.section("civilization_choice", 0x1413A2B10, choice_start)
    b.string("mAiScriptBaseName")
    b.word("mAiCivNameIndex", 1)
    b.strings("mAiPlayerName mHumanSanitizedPlayerName mHumanUnsanitizedPlayerName")
    humanity = b.word("mHumanity")
    b.word("mRlProfileId", 8)
    world_index = b.word("mWorldPlayerArrayIndexIncludingGaia", signed=True)
    b.words("mPrefersRandomCivs mIsCustomAI", 1)
    b.word("mSlotColorOverride", signed=True)
    b.word("mHandicap")
    b.word("mPlayerPlatform")
    b.string("mPlayfabUserId")
    # Keep local native-member keys as well as the globally qualified header keys.
    fields = {
        name[len(b.prefix) :]: field
        for name, field in b.fields.items()
        if name.startswith(b.prefix)
    }
    return SavedGameOptionsPlayer(
        parent.section(f"player[{slot}]", 0x1413EDC90, start),
        slot,
        version,
        scenario_index,
        mode,
        civilization,
        choices,
        humanity,
        world_index,
        fields,
    )


def _read_options(b: _Fields) -> SavedReplayGameOptions:
    r = b.r
    start = r.pos
    first_field = len(b.fields)
    # GameOptions1413d2300 reads this float before the1413d88f0 body.
    options_word = b.expected("options_version", 0x448C6000, float_word=True)
    body_start = r.pos
    dlc_start = r.pos
    dlc_version = b.expected("dlc_options.version", 1000)
    dataset = b.word("dlc_options.dataset")
    ids = b.vector("dlc_options.ids", 0x140D9B820)
    dlc = SavedHeaderDlcOptions(
        b.section("dlc_options", 0x140F80910, dlc_start), dlc_version, dataset, ids
    )
    b.words(
        "mDifficulty mMapSize mUserChosenMapType mResolvedMapType mVisibilityType "
        "victory_type mResourceLevel mStartingAge mEndingAge mGameMode"
    )
    b.marker("after_game_mode")
    b.marker("after_legacy_resource_names")
    b.word("mGameSpeed", float_word=True)
    b.words("mTreatyLength mPopulationLimit")
    num_players = b.word("mNumPlayersExcludingGaia")
    lobby_at = r.pos
    capacity = b.word("mMaxPlayersForLobby", 1)
    if capacity > 8 or capacity > r.remaining // 79:
        raise SaveDecodeError(f"invalid lobby player capacity {capacity}", lobby_at)
    b.words("unusedPlayerColor victory_amount")
    b.marker("after_victory_amount")
    b.words(
        "mTradingEnabled mTeamBonusesDisabled mRandomizePositions mFullTechTreeEnabled "
        "mNumberOfStartingUnits mTeamsLocked mSpeedLocked isMultiPlayer mCheatsEnabled "
        "mRecordGameEnabled mAnimalsEnabled mPredatorsEnabled mTurboEnabled "
        "mSharedExploration mTeamPositions",
        1,
    )
    b.words("mSubGameModeFlag mBattleRoyaleTime")
    b.words("mHandicap mWalkableFarms", 1)
    b.marker("after_game_flags")
    players = tuple(_read_player(b, slot) for slot in range(capacity))
    b.word("dummyNumberOfMapTiles")
    b.word("mVersion", float_word=True)
    b.words("dummyIsRestoreGame mFogOfWarEnabled mCheatNotificationsEnabled mColoredChatEnabled", 1)
    b.marker("after_lobby_players")
    b.words("mIsRanked mAllowSpectators", 1)
    b.word("mLobbyVisibility")
    b.words("mHideCivNames mIsAutomatch", 1)
    b.word("mSpectatorDelay")
    b.word("mIsUsingScenarioCiv", 1)
    resources = tuple(
        b.unique_file(name)
        for name in (
            "mCustomScenarioOrCampaignFile",
            "mCustomRandomMapFile",
            "mCustomRandomMapScenarioFile",
        )
    )
    raw_data = b.words("scenario_rawData random_map_rawData random_map_scenario_rawData")
    map_pool = tuple(
        (b.file_entry(f"mCustomMapPool[{i}][0]"), b.file_entry(f"mCustomMapPool[{i}][1]"))
        for i in range(10)
    )
    standard_pool = b.vector("mStandardMapPool", 0x140E311E0)
    ai_files = b.file_array("mCustomAIFiles")
    xs_files = b.file_array("mCustomXSFiles")
    b.fixed("mGameId", 16, guid=True)
    b.string("mGameTitle")
    b.word("mMatchType", 8)  # Native1413ad1a0 sets R9D=8, despite enum-like usage.
    b.string("mModdedDatasetTitle")
    b.word("mModdedDatasetWorkshopId", 8)
    b.word("mModdedDatasetCrc")
    b.word("mDatasetIsOfficial", 1)
    b.word("mSelectedContentMode")
    b.word("mIsFreeHost", 1)
    for slot in range(capacity):
        b.word(f"player[{slot}].getInLobby", 1)
    b.word("mStartButtonPressed", 1)
    b.string("mCampaignKey")
    b.word("mMapStyleType")
    b.words("mCollideAndCorrecting mVillagerForceDrop mBlockHumanityTeamChange", 1)
    b.words("mCoopCampaignIndex mCoopScenarioIndex")
    b.fixed("mGameSessionId", 16, guid=True)
    b.word("mRandomMapSeed")
    b.word("mPlaySlideshows", 1)
    b.word("mOtherPlayers")
    for i in range(8):
        b.word(f"mMapFilters[{i}]", 1)
    b.words("mControllerOnlyScenario mKeyboardAndMouseOnlyScenario mGameWasSaved", 1)
    b.word("mCampaignDifficultyModifier")
    b.word("mIsEventScenario", 1)
    b.word("mAllowedCivsOption")
    b.word("mAntiquityMode", 1)
    civilizations = b.vector("civilizations", 0x1413D88F0, count_width=8)
    pompeii = b.vector("civilizations_pompeii", 0x1413D88F0, count_width=8)
    b.strings("mPlayfabPartyName mPlayfabPartyDescriptor")
    b.section("options.body", 0x1413D88F0, body_start)
    fields = dict(tuple(b.fields.items())[first_field:])
    return SavedReplayGameOptions(
        b.section("options", 0x1413D2300, start),
        options_word,
        dlc,
        num_players,
        capacity,
        players,
        resources,
        raw_data,
        map_pool,
        standard_pool,
        ai_files,
        xs_files,
        civilizations,
        pompeii,
        fields,
    )
