"""Original visibility circle row selection and clipping, with signed-i32 additions.

Only the row geometry shared by native141352430/141355210 is represented.
No visibility counter, global-disable gate, tile/cell access or callback runs.
The42 row masks come from original static data, not a Euclidean approximation.
"""

from __future__ import annotations

import base64
import hashlib
import struct
import zlib

VisibilityRowSpan = tuple[int, int, int]
"""A row `(y, x_low, x_high)`; both x endpoints are inclusive."""


class UnsupportedReplayVisibilityGeometry(ValueError):
    """An input lies outside the safe native-i32 storage profile of this helper."""


_I32_MAX = 0x7FFFFFFF
_RAW_MASKS_SHA256 = "6e12cd3f9e6ed880fa4f2f41fd59838a9db839a9fdc6cd5f729d246c357c20f8"
# Each of2*21 blocks: u8 record count, then signed-i32(dY,low,high) records.
# The final record has dY999. Its complete12 original bytes are retained.
_ENCODED_MASKS = (
    b"c-nQ?*K#6R7KPy^Es%Kic+=zE`@hrNbd`ijpNNSQktgO0LgY>TB|)CO*AgK8$q!urP5;l?W4;#i7a}iU"
    b"pHO`Agz#_pe=>hF@&Zm?+-P~{MxWd$d@X!0J~r|KPB<Waalm@wfIBz+gv0m4<Ffflkr!~n!6}@*ICwL%"
    b"&BS4M4h!E8kIUzqL=IQv1)RVs!(|MVlZpfF1_l}#V&dRC93C5<Q_RCf4p-y_oWLoAW^m5X#fw1?J%bJm"
    b"Ix^hEKzBGiFFe1ThmIVs$O|}uQx?eJoCOLNC|@ja>R6y>fq?}^hMpMo4u^Y$doAZ>B8MyT0#4wR#WFZ&"
    b"v4X`)7F)hp?8lbHI+p2KW?+Glp(pqbhx>*5uI42phb!^|PT-V<GdPC}mM>X;$?~fg3;(j=h1;@l$HF}e"
    b"4=gsa%mjz~h5N4OLnA-na7A9g37o<iq2zEu5G6q@31USMYu-o<;@34nGz8JIe8=)V3lH$fk`o;69nPrc"
    b"P$ECza7A9g37o<i0p)N(Kqb5+tQBFc38;Dz&~I-9R1;7`KrI1vgwhkl0FNv`!Qq^6-ewLf@&gW6<OQ6-"
    b"DVz~p4i^Mh!b^f%5!{;KDuUa*2=4b+g1hmustK+kxR&5L!s-cVAczs3;BaO*dpn01`2mM3@&Zoa6wU}V"
    b"hYPqQ+$Djo2y{)L6@hMe*=}D1`o{}_UJ3L@h&3TLgxC^dM_4^P5YPxua5z8Av75t<{D8w1c>yPI3TFhJ"
    b"!v$Ot^b%eX`kK%yLf;VjmY{bpg8tK)pf3b{CFmPL*96@VbW6A$A@=Y<a3egyVU{q{ehxkI0}fZ@1)RVs"
    b"oKZjy7jQ`dOL#>AYYM0+U_$|03fNJ={zU<Q`JjL^1zafLO6WI2uL->&=oan>w}%G;9pMQMbA|a1a~Y8z"
    b"aJV8b-~>+LjAC-QfJ=&5!Yhhd!xbfMC}~ScJBry;%;7~be|x8x4~jWc%!OjE6mz4Pnlc&+XyJ~~dw3w|"
    b"5uV^MW0>_gmlXK{hb!^|PT&;IC@hByxTLTpyrQr*Tv6DD!nPE)qp&@N9VqPhqOgB_=dYA^K6pQP`#MwD"
    b"g_5q6bfcIWZYZXufDY~neSk+e%ot`p&5K0-gdcFYA}`<sPT>sBDYbx0cuA=%culDlMQ-3NrS2$oPmu@S"
    b"9*_JYaN@5ui~QF&iu_KI?-cpLtL;pY7mB=6-i`8V3Txn&k~+Aji~%0uFmIUqZ7wzPC;WiJ6?p+Ca0+K|"
    b"PQe9S!b=KX!D|Yx;0<MODR@W0dkQ}Asy$NhiGtr=6#So`Dfk-&f2ZJg3jUzrGX-BL_)5VyO06lffm_P!"
    b";GU8Oc!b03VTT{*vLk=O4>(+r7jOcna0cfTU%(~2r1%xQruYipQ2dtScND*;_yffsDgH$9ZxsLIi{g`4"
    b"@-~g~_6Owc^Mmr}Ru#4jgzW-h`>Zm{J5Pw-R7sm4X%i%Ef~0-E>1yJpcW(4K|9~rIQ^ahFm`xG0(E@*U"
    b"ST%Ck#7*yTl(88yHbcf{$k=FvCyelf5&mk3?Z6Nt2TvS!hogYa5wJM|Hb=l}hcg6hw8PVr9ey5e-!t66"
    b"a3cdv3~`5}bS;ps1=6)Zx@wAZq^qVl!xX2O;^(1{9X~fcgANQgGSCD^2dQW+5v?VnwM4X*h}II(S|C~r"
    b"L~D*{jn?@7g=>6kS*Bx|o@E9W7#Vbe@AD^ta&?JZT_RVP$kiosb%|Upk*m=l_ZZ{>gFIr8zgqGa4NJBx"
    b"*|Av9G6OuazywF3x<aU~5UMML>I$K{La0WY++vg4C!1U%R7-@aHaVL=M!s79S2fEwEZ?$x$HF~J4)Dlg"
    b"6C5S#8i~3_qOOssYb5F#iK<y%AyGBUOC)ME%N=I9e=^G%X8Adk-`ohL=109Dl$KCBg6LU(V961l;3!Tj"
    b"#A$^%tq`Xb;<Q4XYMIxF(>3CBjX2dZFR{!embsV%8lEikb6CH-64s5dY65Bqs3o9|AbNOU`4OJrC`&iU"
    b"(hah7gDl-3OE<_;jdO)8t&pYBIM*2G8spqxoLh`@hjAXBjPrAdf4K1Rb|u6cA=ZT05MoPk9Rc<5Kqw;|"
    b"U7dn-iy+-1NVf>mErN85Al)KJw+PY=f>irlAxNWruCdPz_PNDAcTe^?pMUk8zAy<toeB3sxL3lx5ok@I"
    b"4I#F0M~FQ<5Y`As52qB}Aw_pc(H&BBhZNl*MR!Qi9a40Q6xBp;kfNIC3MpD4Mb}7CO>~Kg&gZ`|z6$-%"
    b"AB2A9ee*)-S3<uLdQH#`;kIx`xIMuQ@CZl8rU>05LidQ!JtB0E2;Cz>_lVFvB6Noc-62AEh)}Kc1`!&q"
    b"^bIRrW2KuXD_zb7^jPVy%J}O$WqeS^nYWY+Wn3xaMj15)G!)PhbO-kYI=~}5&40x!KM%;y1M>5L{5&8("
    b"56I60^7DZF+#^5t$j?3UbBFxgAwM<L8w_=Yp<ZLCS938fhPua4e^t`ozf;mXC4ErRnPM&!bETLY#nhD1"
    b"z%2!Ia8J+!Ji<|U9ub~Lgy#|Ac|>>~5uQhc=Mmu<ZS_00`W;*Sj;;Q{R)1it&)DiSw)%ptzGACy*y<Wv"
    b"-D0bIZ1q>={qq~;eW$#4%KM<aGv!?<?@D<$3acrpfm@2{;GO~oc!Z<mJRvzxNX`?I^MvF)AvsS-&J&VT"
    b"bA3c|9+8}y>jRQgbG=7$Mst0BGS^$o^#*fY%|+Hv=6Z>_E-=^6rT+V8O8rKu-+8Nir_>LMJX7R_BCnKp"
    b"gKNrbD5-@zxTlx_9^oi9-w>N`h|M>|<{M)34YB!#*nC55YOzm<%@bl%i+x0F9ub>I#HJQ|kJ#KJHg|~4"
    b"En-uPy`Bqho-B5O#eOdPe+PgWqW"
)


def _load_masks() -> tuple[tuple[tuple[VisibilityRowSpan, ...], ...], ...]:
    raw = zlib.decompress(base64.b85decode(_ENCODED_MASKS))
    if hashlib.sha256(raw).hexdigest() != _RAW_MASKS_SHA256:
        raise RuntimeError("visibility static row data digest mismatch")
    offset = 0
    tables = []
    for _mode in range(2):
        masks = []
        for _radius in range(21):
            count = raw[offset]
            offset += 1
            if not 1 <= count <= 64:
                raise RuntimeError("visibility static record count")
            rows = tuple(struct.unpack_from("<iii", raw, offset + i * 12) for i in range(count))
            offset += count * 12
            if rows[-1][0] != 999 or any(row[0] == 999 for row in rows[:-1]):
                raise RuntimeError("visibility static sentinel placement")
            masks.append(rows[:-1])
        tables.append(tuple(masks))
    if offset != len(raw):
        raise RuntimeError("visibility static trailing data")
    return tuple(tables)


_MASKS = _load_masks()


def _i32_input(value: int, name: str) -> None:
    if type(value) is not int or not -0x80000000 <= value <= _I32_MAX:
        raise UnsupportedReplayVisibilityGeometry(f"{name} must be a signed-i32 integer")


def _add_i32(left: int, right: int) -> int:
    return ((left + right + 0x80000000) & 0xFFFFFFFF) - 0x80000000


def replay_visibility_rows(
    center_x: int,
    center_y: int,
    radius: int,
    mode_flag: int,
    *,
    width: int,
    height: int,
) -> tuple[VisibilityRowSpan, ...]:
    """Return clipped inclusive spans in the exact original static table order.

    Native signed-i32 radius is capped at20; a negative native index is unsafe
    and is rejected. Zero mode selects table14408d1a0; any nonzero i32 selects
    table14408d250. Center+offset additions wrap at32 bits before signed clips.

    Positive width/height and width*height<=INT_MAX are caller storage premises,
    not extra native bounds checks. They exclude linear-index overflow while
    allowing large maps. This helper allocates at most41 spans, never a grid.
    Global disable/counter state and the rest of either native function remain
    the caller's responsibility. A geometry result does not imply visibility.
    """
    for name, value in (
        ("center_x", center_x),
        ("center_y", center_y),
        ("radius", radius),
        ("mode_flag", mode_flag),
        ("width", width),
        ("height", height),
    ):
        _i32_input(value, name)
    if radius < 0:
        raise UnsupportedReplayVisibilityGeometry(
            "radius must be nonnegative; unsafe native table index"
        )
    if width <= 0 or height <= 0 or width * height > _I32_MAX:
        raise UnsupportedReplayVisibilityGeometry(
            "positive width/height with width*height<=INT_MAX are required storage premises"
        )
    result = []
    for dy, low, high in _MASKS[int(mode_flag != 0)][min(radius, 20)]:
        y = _add_i32(center_y, dy)
        if 0 <= y < height:
            x_low = max(0, _add_i32(center_x, low))
            x_high = min(width - 1, _add_i32(center_x, high))
            if x_low <= x_high:
                result.append((y, x_low, x_high))
    return tuple(result)
