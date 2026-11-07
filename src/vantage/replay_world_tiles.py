"""Logical ordered World tile membership, from141037630/141037ae0 (build54800).

Models the used pointer vectors and the separate positive-master80 byte plane.
Tokens represent object identity, not saved IDs; zero is a null vector entry.
The backing pool, unused slots, allocation failures and destructor141037940 are
outside this logical layer. No saved-position grouping or callback execution is
implied. See world-tile-initial-chronology-v1 in the native world-envelope proof.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

_U32 = 0xFFFFFFFF
_U64 = 0xFFFFFFFFFFFFFFFF


def _integer(value: int, maximum: int, label: str) -> None:
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(f"{label} must be an unsigned integer <= {maximum}")


def _dimensions(width: int, height: int) -> int:
    for value in (width, height):
        if type(value) is not int or not 1 <= value < 1 << 31:
            raise ValueError("tile dimensions must be positive signed32 values")
    cells = width * height
    if cells > 1 << 24:
        raise ValueError("logical tile backing is limited to 2**24 cells")
    return cells


@dataclass(frozen=True, slots=True)
class ReplayWorldTileSnapshot:
    """Explicit logical input/output, retaining independent byte-plane values.

    Missing tile keys mean count zero. A present tuple is the used vector only,
    and can contain duplicates/nulls. Counts through255 can be restored even
    though append stops at250. Radius words are current decoded master80 bits;
    they are not inferred from baseline data or saved entity geometry.
    """

    width: int
    height: int
    tiles: Mapping[int, tuple[int, ...]]
    positive_counts: bytes
    radius_z_bits: Mapping[int, int]

    def __post_init__(self) -> None:
        cells = _dimensions(self.width, self.height)
        if type(self.positive_counts) is not bytes or len(self.positive_counts) != cells:
            raise ValueError("every positive-count plane byte must be supplied")
        if not isinstance(self.tiles, Mapping) or not isinstance(self.radius_z_bits, Mapping):
            raise ValueError("tiles and current radius words must be mappings")
        radii = dict(self.radius_z_bits)
        for token, bits in radii.items():
            _integer(token, _U64, "object token")
            if token == 0:
                raise ValueError("null has no current master")
            _integer(bits, _U32, "current radiusZ word")
        tiles = dict(self.tiles)
        for index, tokens in tiles.items():
            _integer(index, cells - 1, "tile index")
            if type(tokens) is not tuple or len(tokens) > 255:
                raise ValueError("used tile vectors must be tuples with a u8 count")
            for token in tokens:
                _integer(token, _U64, "tile object token")
                if token and token not in radii:
                    raise ValueError("each nonnull tile occupant needs its current radiusZ")
        object.__setattr__(self, "tiles", MappingProxyType({k: v for k, v in tiles.items() if v}))
        object.__setattr__(self, "radius_z_bits", MappingProxyType(radii))


@dataclass(frozen=True, slots=True)
class ReplayWorldTileMutation:
    """Python mutation receipt; both original native tile helpers return void.

    A skipped append does not mean that its caller skips position/tile-pointer
    commit. The receipt describes membership and the byte-plane write only.
    """

    changed: bool
    count: int
    plane_index: int
    plane_written: bool


class ReplayWorldTileRegistry:
    """Mutable logical vectors with bounded O(count) native recounts.

    Snapshot construction validates all backing before publishing the registry.
    Float comparisons assume native default MXCSR: masked exceptions, DAZ/FTZ
    off. FP status/cipher high words are not modeled. NaN is unordered,
    +infinity is positive, and signed zeros are not positive. No complete native
    World initialization is asserted.
    """

    def __init__(self, state: ReplayWorldTileSnapshot) -> None:
        if type(state) is not ReplayWorldTileSnapshot:
            raise ValueError("an explicit typed tile snapshot is required")
        self._width = state.width
        self._height = state.height
        self._cells = self.width * self.height
        self._tiles = {index: list(tokens) for index, tokens in state.tiles.items()}
        self._positive_counts = bytearray(state.positive_counts)
        self._radii = dict(state.radius_z_bits)

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    @classmethod
    def empty(
        cls, width: int, height: int, radius_z_bits: Mapping[int, int]
    ) -> ReplayWorldTileRegistry:
        """Explicitly request empty vectors/zero plane; never derive this from saves."""
        cells = _dimensions(width, height)
        return cls(ReplayWorldTileSnapshot(width, height, {}, bytes(cells), radius_z_bits))

    def _tile(self, index: int) -> None:
        _integer(index, self._cells - 1, "tile index")

    def _plane(self, coordinates: tuple[int, int]) -> int:
        if type(coordinates) is not tuple or len(coordinates) != 2:
            raise ValueError("plane coordinates must be two signed32 integers")
        for value in coordinates:
            if type(value) is not int or not -(1 << 31) <= value < 1 << 31:
                raise ValueError("plane coordinate must be signed32")
        # Native IMUL32/ADD32 precede sign extension. Coordinates and the Tile*
        # are independent arguments; do not silently substitute tile_index.
        x, y = coordinates
        word = (y * self.width + x) & _U32
        index = word if word < 1 << 31 else word - (1 << 32)
        if not 0 <= index < self._cells:
            raise ValueError("native plane address would leave the supplied backing")
        return index

    def tokens(self, tile_index: int) -> tuple[int, ...]:
        """Read the current used order, with no exposure of mutable storage."""
        self._tile(tile_index)
        return tuple(self._tiles.get(tile_index, ()))

    def positive_count(self, tile_index: int) -> int:
        self._tile(tile_index)
        return self._positive_counts[tile_index]

    def bind_radius_z(self, object_token: int, radius_bits: int) -> None:
        """Supply a new/current master80 word; no membership or plane write occurs."""
        _integer(object_token, _U64, "object token")
        if object_token == 0:
            raise ValueError("null has no current master")
        _integer(radius_bits, _U32, "current radiusZ word")
        self._radii[object_token] = radius_bits

    def _count(self, tokens: list[int]) -> int:
        # For validated u32 bits under DAZ-off IEEE comparison, exactly these
        # encodings are ordered >0: positive nonzero finite values and +Inf.
        # No host float conversion is needed; NaNs and both zeros are excluded.
        return sum(token != 0 and 0 < self._radii[token] <= 0x7F800000 for token in tokens)

    def append(
        self, tile_index: int, object_token: int, *, plane_coordinates: tuple[int, int]
    ) -> ReplayWorldTileMutation:
        """Logical141037630, assuming successful backing-pool allocation.

        Empty vectors write plane1 only for a positive new radius. Nonempty
        vectors below250 append without deduplication and recount current radii.
        Counts250..255 do nothing, without reading the target master. A null
        append is supported on a nonempty tile, where the recount skips it;
        the empty-tile branch requires a nonnull backed object. This does not
        assign the object's tile link.
        """
        self._tile(tile_index)
        plane = self._plane(plane_coordinates)
        _integer(object_token, _U64, "object token")
        tokens = self._tiles.get(tile_index)
        count = len(tokens) if tokens is not None else 0
        if count >= 250:
            return ReplayWorldTileMutation(False, count, plane, False)
        if (not count and not object_token) or (object_token and object_token not in self._radii):
            raise ValueError("a dereferenced append target needs its current radiusZ")
        if not count:
            self._tiles[tile_index] = [object_token]
            written = 0 < self._radii[object_token] <= 0x7F800000
            if written:
                self._positive_counts[plane] = 1
        else:
            assert tokens is not None
            tokens.append(object_token)
            self._positive_counts[plane] = self._count(tokens)
            written = True
        return ReplayWorldTileMutation(True, count + 1, plane, written)

    def remove(
        self, tile_index: int, object_token: int, *, plane_coordinates: tuple[int, int]
    ) -> ReplayWorldTileMutation:
        """Logical141037ae0: first identity match, swap last, then recount.

        An absent identity does nothing. Removing the last entry writes plane0.
        Null entries may be removed; no entity dereference is required. This
        does not clear the object's tile link or invoke any destructor/callback.
        """
        self._tile(tile_index)
        plane = self._plane(plane_coordinates)
        _integer(object_token, _U64, "object token")
        tokens = self._tiles.get(tile_index)
        count = len(tokens) if tokens is not None else 0
        if not tokens or object_token not in tokens:
            return ReplayWorldTileMutation(False, count, plane, False)
        at = tokens.index(object_token)
        tokens[at] = tokens[-1]
        tokens.pop()
        self._positive_counts[plane] = self._count(tokens)
        if not tokens:
            del self._tiles[tile_index]
        return ReplayWorldTileMutation(True, count - 1, plane, True)

    def snapshot(self) -> ReplayWorldTileSnapshot:
        return ReplayWorldTileSnapshot(
            self.width,
            self.height,
            {index: tuple(tokens) for index, tokens in self._tiles.items()},
            bytes(self._positive_counts),
            self._radii,
        )
