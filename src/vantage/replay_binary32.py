"""Integer scalar binary32 arithmetic for the replay simulator.

Legacy SSE ADDSS/SUBSS/MULSS/DIVSS low-word results with masked exceptions,
nearest-even rounding and DAZ/FTZ off. NaNs choose destination first and are
quieted; invalid arithmetic returns the x86 indefinite word. Comparisons leave
input words untouched. Floating-point status, traps and upper lanes are excluded.
No operation depends on the Python host's floating-point environment.
"""

from __future__ import annotations

_SIGN = 0x80000000
_INF = 0x7F800000
_INVALID = 0xFFC00000


def _word(value: int) -> None:
    if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("binary32 value must be a raw unsigned32 word")


def _nan(value: int) -> bool:
    return value & 0x7FFFFFFF > _INF


def _round(magnitude: int, exponent: int, negative: bool) -> int:
    """Round exact magnitude*2**exponent, including gradual under/overflow."""
    sign = _SIGN if negative else 0
    if not magnitude:
        return sign
    shift = max(magnitude.bit_length() - 24, -149 - exponent)
    if shift > 0:
        rounded, remainder = divmod(magnitude, 1 << shift)
        half = 1 << (shift - 1)
        if remainder > half or (remainder == half and rounded & 1):
            rounded += 1
    else:
        rounded = magnitude << -shift
    if not rounded:
        return sign
    scale = exponent + shift
    top = rounded.bit_length() - 1 + scale
    if top > 127:
        return sign | _INF
    if top < -126:
        return sign | (rounded << (scale + 149))
    # A rounding carry can produce25 bits. It has no discarded nonzero bits.
    align = rounded.bit_length() - 24
    significand = rounded >> align if align >= 0 else rounded << -align
    return sign | (top + 127) << 23 | (significand & 0x7FFFFF)


def _parts(value: int) -> tuple[int, int]:
    exponent, fraction = value >> 23 & 255, value & 0x7FFFFF
    return (fraction | 0x800000, exponent - 150) if exponent else (fraction, -149)


def _units(value: int) -> int:
    significand, exponent = _parts(value)
    magnitude = significand << (exponent + 149)
    return -magnitude if value & _SIGN else magnitude


def _add(left: int, right: int) -> int:
    if _nan(left):
        return left | 0x400000
    if _nan(right):
        return right | 0x400000
    a, b = left & 0x7FFFFFFF, right & 0x7FFFFFFF
    if a == _INF:
        return _INVALID if b == _INF and (left ^ right) & _SIGN else left
    if b == _INF:
        return right
    total = _units(left) + _units(right)
    negative = total < 0 or (not total and bool(left & right & _SIGN))
    return _round(abs(total), -149, negative)


def add_binary32(left: int, right: int) -> int:
    """One legacy ADDSS; exact input words, one nearest-even rounding."""
    _word(left)
    _word(right)
    return _add(left, right)


def subtract_binary32(left: int, right: int) -> int:
    """One legacy SUBSS, preserving the original source NaN's sign/payload."""
    _word(left)
    _word(right)
    if _nan(left):
        return left | 0x400000
    if _nan(right):
        return right | 0x400000
    return _add(left, right ^ _SIGN)


def multiply_binary32(left: int, right: int) -> int:
    """One legacy MULSS, including signed zero and gradual underflow."""
    _word(left)
    _word(right)
    if _nan(left):
        return left | 0x400000
    if _nan(right):
        return right | 0x400000
    a, b = left & 0x7FFFFFFF, right & 0x7FFFFFFF
    negative = bool((left ^ right) & _SIGN)
    if a == _INF or b == _INF:
        return _INVALID if not a or not b else (_SIGN if negative else 0) | _INF
    x, xe = _parts(left)
    y, ye = _parts(right)
    return _round(x * y, xe + ye, negative)


def compare_binary32(left: int, right: int) -> int | None:
    """Ordered -1/0/1, or None for unordered, without quieting input NaNs."""
    _word(left)
    _word(right)
    if _nan(left) or _nan(right):
        return None
    a, b = left & 0x7FFFFFFF, right & 0x7FFFFFFF
    if left == right or a == b == 0:
        return 0
    if (left ^ right) & _SIGN:
        return -1 if left & _SIGN else 1
    result = (a > b) - (a < b)
    return -result if left & _SIGN else result


def signed16_binary32(value: int) -> int:
    """Exact low-lane CVTDQ2PS of a sign-extended signed16 input."""
    if type(value) is not int or not -32768 <= value <= 32767:
        raise ValueError("binary32 conversion requires a signed16 integer")
    return _round(abs(value), 0, value < 0)


def signed32_binary32(value: int) -> int:
    """Low-lane CVTDQ2PS of signed32, with one nearest-even rounding."""
    if type(value) is not int or not -(1 << 31) <= value < 1 << 31:
        raise ValueError("binary32 conversion requires a signed32 integer")
    return _round(abs(value), 0, value < 0)


def divide_binary32(left: int, right: int) -> int:
    """One legacy DIVSS, rounding an exact integer ratio once to nearest-even."""
    _word(left)
    _word(right)
    if _nan(left):
        return left | 0x400000
    if _nan(right):
        return right | 0x400000
    a, b = left & 0x7FFFFFFF, right & 0x7FFFFFFF
    sign = (left ^ right) & _SIGN
    if a == b == 0 or a == b == _INF:
        return _INVALID
    if a == _INF or not b:
        return sign | _INF
    if not a or b == _INF:
        return sign
    numerator, ae = _parts(left)
    denominator, be = _parts(right)
    exponent = ae - be
    top = numerator.bit_length() - denominator.bit_length()
    if top >= 0:
        top -= numerator < denominator << top
    else:
        top -= numerator << -top < denominator
    scale = max(top + exponent - 23, -149)
    shift = exponent - scale
    if shift >= 0:
        numerator <<= shift
    else:
        denominator <<= -shift
    rounded, remainder = divmod(numerator, denominator)
    if 2 * remainder > denominator or (2 * remainder == denominator and rounded & 1):
        rounded += 1
    return _round(rounded, scale, bool(sign))


def unsigned64_binary32(value: int) -> int:
    """Native sticky-half CVTSI2SS64/ADDSS sequence for an unsigned64 input.

    The high-bit path rounds ((value>>1)|(value&1)) as signed64, then doubles
    that binary32 value. This preserves the source's two instruction results.
    """
    if type(value) is not int or not 0 <= value < 1 << 64:
        raise ValueError("binary32 conversion requires an unsigned64 integer")
    if value < 1 << 63:
        return _round(value, 0, False)
    half = _round((value >> 1) | (value & 1), 0, False)
    return _add(half, half)
