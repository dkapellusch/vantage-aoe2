"""Original binary32 angle functions used by the bounded movement reconstruction.

Small-angle sin/cos accepts the native |x| < f32 pi/4 branch; turn sin/cos
also implements the native reductions covering [-pi, pi]. Other range
reduction is explicitly unsupported.
Default native MXCSR (nearest-even, no DAZ/FTZ) is assumed.
"""

from __future__ import annotations

from vantage.replay_movement_geometry import _bits, _float, _op, _sqrt, _word

_ONE = 0x3F800000
_HALF = 0x3F000000
_PI_HALF = 0x3FC90FDA
_ACOS_SMALL = 0x32800000
_ACOS_EPSILON = 0x33A22168
_A = 0xBD2F13BA
_B = 0x3C0DD36B
_C = 0x3E2AAA75
_D = 0x3F34E5AE


def _ratio(z: int) -> int:
    numerator = _op(_A, _op(z, _B, "*"), "-")
    numerator = _op(_op(numerator, z, "*"), _C, "+")
    numerator = _op(numerator, z, "*")
    denominator = _op(_ONE, _op(z, _D, "*"), "-")
    return _op(numerator, denominator, "/")


def native_acos_bits(value: int) -> int:
    """Original140a81450, with f32 rounding at every SSE scalar operation.

    The complete raw-word domain includes the native invalid/NaN results.
    Endpoints retain the original truncated pi constants. Host math.acos
    would change both ordinary rounding and these endpoint words.
    """
    _word(value)
    absolute = value & 0x7FFFFFFF
    if absolute >= _ONE:
        if absolute == _ONE:
            return 0x40490FDA if value & 0x80000000 else 0
        return _op(0, _op(value, value, "-"), "/")
    if absolute < _HALF:
        if absolute <= _ACOS_SMALL:
            return _PI_HALF
        ratio = _ratio(_op(value, value, "*"))
        correction = _op(_ACOS_EPSILON, _op(ratio, value, "*"), "-")
        return _op(_PI_HALF, _op(value, correction, "-"), "-")
    if value & 0x80000000:
        z = _op(_op(value, _ONE, "+"), _HALF, "*")
        root = _sqrt(z)
        correction = _op(_op(_ratio(z), root, "*"), _ACOS_EPSILON, "-")
        correction = _op(correction, root, "+")
        angle = _op(_PI_HALF, correction, "-")
    else:
        z = _op(_op(_ONE, value, "-"), _HALF, "*")
        root = _sqrt(z)
        high = root & 0xFFFFF000
        residual = _op(z, _op(high, high, "*"), "-")
        residual = _op(residual, _op(high, root, "+"), "/")
        angle = _op(_op(_op(_ratio(z), root, "*"), residual, "+"), high, "+")
    return _op(angle, angle, "+")


def _small(value: int) -> int:
    _word(value)
    absolute = value & 0x7FFFFFFF
    if absolute >= 0x3F490FDB:
        raise ValueError("angle is outside the supported native small-angle branch")
    return absolute


def native_cos_small_bits(value: int) -> int:
    """Original140a81ca0's small-angle branch and88-byte binary64 polynomial."""
    if _small(value) < 0x39800000:
        return _ONE
    return _cos_polynomial(_float(value))


def _cos_polynomial(x: float) -> int:
    z = x * x
    square = z * z
    high = z * float.fromhex("0x1.99342e0ee5069p-16")
    high = high - float.fromhex("0x1.6c087e80f1e27p-10")
    cube = square * z
    low = square * float.fromhex("0x1.55553e1053a42p-5")
    first = 1.0 - z * float.fromhex("0x1.ffffffd0c5e81p-2")
    high = high * cube
    first = first + low
    return _bits(high + first)


def native_sin_small_bits(value: int) -> int:
    """Original140a82a10's small-angle branch and84-byte binary64 polynomial."""
    if _small(value) < 0x39800000:
        return value
    return _sin_polynomial(_float(value))


def _sin_polynomial(x: float) -> int:
    z = x * x
    square = z * z
    odd = z * x
    low = z * float.fromhex("0x1.11110896efbb2p-7")
    high = z * float.fromhex("0x1.6cd878c3b46a7p-19")
    low = low - float.fromhex("0x1.5555554cbac77p-3")
    high = high - float.fromhex("0x1.a00f9e2cae774p-13")
    square = square * odd
    low = low * odd
    square = square * high
    low = low + x
    return _bits(square + low)


def _turn(value: int) -> int:
    _word(value)
    absolute = value & 0x7FFFFFFF
    if absolute > 0x40490FDB:
        raise ValueError("angle is outside the supported native turn range [-pi, pi]")
    return absolute


def native_cos_turn_bits(value: int) -> int:
    """Original cosine branches covering every f32 angle in [-pi, pi].

    Native binary64 reductions precede the same original polynomials. The
    caller's f32 pi approximation is preserved when reducing by binary64 pi.
    """
    absolute = _turn(value)
    if absolute < 0x3F490FDB:
        return native_cos_small_bits(value)
    x = _float(value)
    if absolute < 0x4016CBE4:
        half_pi = float.fromhex("0x1.921fb54442d18p+0")
        reduced = x + half_pi if value & 0x80000000 else half_pi - x
        return _sin_polynomial(reduced)
    pi = float.fromhex("0x1.921fb54442d18p+1")
    reduced = x + pi if value & 0x80000000 else x - pi
    return _cos_polynomial(reduced) ^ 0x80000000


def native_sin_turn_bits(value: int) -> int:
    """Original sine branches covering every f32 angle in [-pi, pi]."""
    absolute = _turn(value)
    if absolute < 0x3F490FDB:
        return native_sin_small_bits(value)
    x = _float(value)
    if absolute < 0x4016CBE4:
        half_pi = float.fromhex("0x1.921fb54442d18p+0")
        if value & 0x80000000:
            return _cos_polynomial(x + half_pi) ^ 0x80000000
        return _cos_polynomial(x - half_pi)
    pi = float.fromhex("0x1.921fb54442d18p+1")
    reduced = x + pi if value & 0x80000000 else x - pi
    return _sin_polynomial(reduced) ^ 0x80000000
