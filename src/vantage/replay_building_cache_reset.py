"""Native-derived scalar storage patch for the Building sentinel reset profile.

Models1412baf10 and genuine getter1412b5bd0 with explicit current premises:
writable disjoint object/sentinel storage, readable dispatch/constants, callable
Building getter, self-linked sentinel and masked nearest-even native FP controls.
Integer rounding avoids dependence on the Python host's floating-point state.
All220 observed native payloads match; see building-cache-reset-observed-v1.
FP status flags and excluded callbacks/partial failures are not modeled. Admission
happens before applying the patch. Current Game binding, complete transformation
and independent playback remain unfinished.
"""

from __future__ import annotations

from dataclasses import dataclass


def _word(value: int, maximum: int, name: str) -> None:
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(f"{name} must be an unsigned word no greater than {maximum}")


def _round_binary32(significand: int, exponent: int) -> int:
    """Round exact nonnegative significand*2**exponent, normal results only.

    This profile produces zero or a positive normal value in both conversion
    and multiplication. Integer arithmetic makes rounding independent of the
    ambient Python process's floating-point environment.
    """
    if not significand:
        return 0
    shift = significand.bit_length() - 24
    if shift > 0:
        rounded, remainder = divmod(significand, 1 << shift)
        halfway = 1 << (shift - 1)
        if remainder > halfway or (remainder == halfway and rounded & 1):
            rounded += 1
        if rounded == 1 << 24:
            rounded >>= 1
            shift += 1
    else:
        rounded = significand << -shift
    encoded_exponent = exponent + shift + 150
    assert 1 <= encoded_exponent <= 254
    return (encoded_exponent << 23) | (rounded & 0x7FFFFF)


@dataclass(frozen=True, slots=True)
class ReplayBuildingCacheResetContext:
    """Caller-established current storage, dispatch and native FP premises.

    Disjoint backing covers the complete object, separate sentinel, vtable and
    code/constants. The sentinel's three links point to itself. The original
    branch reads the marker rather than the object's separate728 count word;
    this context imposes no initial count value. Getter binding means the exact
    original Building virtual1d0, not another virtual implementation.
    """

    sentinel_marker: int
    sentinel_links_self: bool
    disjoint_backing: bool
    building_getter_bound: bool
    mxcsr: int

    def __post_init__(self) -> None:
        _word(self.sentinel_marker, 255, "sentinel marker")
        _word(self.mxcsr, 0xFFFFFFFF, "MXCSR")
        for name in ("sentinel_links_self", "disjoint_backing", "building_getter_bound"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"explicit bool required for {name}")


@dataclass(frozen=True, slots=True)
class ReplayBuildingCacheResetPatch:
    # Ordered object writes: byte offset, width, raw scalar bits. Sentinel
    # links are reset between the first five writes and the final three.
    object_writes: tuple[tuple[int, int, int], ...]
    sentinel_self_links: tuple[int, ...]


def reset_replay_building_cache(
    context: ReplayBuildingCacheResetContext, *, field760: int, field75c_bits: int
) -> ReplayBuildingCacheResetPatch:
    """Admit the resolved profile and return its complete scalar storage patch.

    Only control bits matching1f80 are supported. Sticky status bits0..5 do
    not affect this path's scalar results; their preservation/addition is not
    modeled here. All actual native matrix calls began with exact1f80.
    """
    if not isinstance(context, ReplayBuildingCacheResetContext):
        raise ValueError("explicit current Building cache context required")
    if not context.disjoint_backing or not context.sentinel_links_self:
        raise ValueError("separate backed object and self-linked sentinel required")
    if not context.sentinel_marker:
        raise ValueError("nonempty tree destruction remains unresolved")
    if not context.building_getter_bound:
        raise ValueError("genuine Building virtual1d0 getter binding required")
    if context.mxcsr & ~0x3F != 0x1F80:
        raise ValueError("masked nearest-even MXCSR controls1f80 required")
    if type(field760) is not int or not -(1 << 31) <= field760 < (1 << 31):
        raise ValueError("field760 must be signed32 for the original getter")
    _word(field75c_bits, 0xFFFFFFFF, "field75c binary32 bits")
    nan = field75c_bits & 0x7F800000 == 0x7F800000 and bool(field75c_bits & 0x7FFFFF)
    if not field75c_bits & 0x80000000 and not nan and field75c_bits > 0x33D6BF95:
        raise ValueError("required visibility callbacks remain unresolved")
    # MOVSXD produces a sign-extended qword, converted as UNSIGNED64. Under
    # nearest-even, every negative i32 rounds to2^64. Positive i32 is rounded
    # exactly by the same integer routine. Scale3d4ccccd = cccccd *2**-28.
    converted = _round_binary32(field760 if field760 >= 0 else 1 << 64, 0)
    if converted:
        significand = (converted & 0x7FFFFF) | 0x800000
        exponent = (converted >> 23) - 178
        bits = _round_binary32(significand * 0xCCCCCD, exponent)
    else:
        bits = 0
    return ReplayBuildingCacheResetPatch(
        (
            (0x6AC, 8, 0),
            (0x6B8, 8, 0),
            (0x6C4, 8, 0),
            (0x6D0, 8, 0),
            (0x6D8, 4, 0),
            (0x728, 8, 0),
            (0x680, 8, 0),
            (0x6B4, 4, bits),
        ),
        (8, 0, 0x10),
    )
