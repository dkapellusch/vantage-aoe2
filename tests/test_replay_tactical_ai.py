"""Native Tactical AI slices, independently captured references, and bounded edge cases."""

from __future__ import annotations

import base64
import hashlib
import struct
import zlib
from typing import Any

import pytest

from vantage.replay_binary import SaveDecodeError, SaveReader
from vantage.replay_tactical_ai import read_tactical_ai

# Original portable v54800 byte slices; inputs/offsets/capture oracles are in
# artifacts/game-internals/2026-10-18-player-ai/tactical/report.json.
_NATIVE_CASES: list[dict[str, Any]] = [
    {
        "offset": 8541177,
        "end_offset": 8549749,
        "num_players": 4,
        "sha256": "3541c4ca3d900d1e5b01c7755da54a4d1c8af8d5843da845b1e7bbba2178949d",
        "first_ids": (5632, 5634, 5642),
        "second_ids": (5648,),
        "tc_xy_words": (1122893824, 1117388800),
        "data": (
            "c-rk*y-"
            "EW?5T3owA*@0IhCmP`*l3}J_XH9|gn)wh^8yiVECnCIC$P}wz?bk1wA9`{qGDxbbAD%Lb#v~X7cHHEFT3~c-"
            "^}dn57~y%1ZfdPfN9Z)WF8S-c;ST?UU=b!7hZVbg%@6U;e{7oc;ST?UU=ch<5Q#X+bH}C?~~MIs5-"
            "}AT_9p)V@Qqb=V=18`Fjef0eXPqysfw6jM3+O6427NA?`;7-"
            "W5VtP5|0zA3J&1*3j5_o!pit_fuy(sYKsgaz9wx2F{$t0UNB3G?&*Y{Ep)Ci)vWb=JqC_Q@=!Co7aUht4GK`"
            ")(*oyG3=*>Kn(eGOPsozb+Cw>es6#`;EeOWzGpprvoK$Zzpo~VZV?>!@i4DAcJuVaiDlci&1w9@`XJ9(#Ia!"
            "GK|AZg^<$4g?8mY<G&gR@8RK&<SH9-vqmRJ+=ka4a?L*R}>e84edeG%-"
            "g(|GUqJR6`xAMerS^s5om5GS_GfB<&J3*CoZO=|kRc;yd3&Gu_!rA`!aYp5(J50~JA*-"
            "!6Gq@AHswH3<NU(#h;?!Hi3AGN-"
            "Y~p0u!Va~KooWx|`@jKq&O@X}*b$H6xeMSL?e4%o;sko4wEj$|(@oXc7^oVpM+xmlF<sWehIPz4<|hGG"
        ),
    },
    {
        "offset": 10427575,
        "end_offset": 10436147,
        "num_players": 4,
        "sha256": "91c4a8964ab7f85b41b1254ef5d805797f3802964c143868e621bfcf6f129aa5",
        "first_ids": (5636, 5638, 5644),
        "second_ids": (5650,),
        "tc_xy_words": (1111752704, 1122500608),
        "data": (
            "c-rk*y-EW?5T4E5DXf76J%k`gu+c&b?+GLX2?P|xpBIQ|V=4FuK7ozRfiK}3XsNw@f?8VHoZp#QUC-"
            "U~qNOwNW%s`Qo0*;cA=}ge5ry+aQ$QWCC3A@I!V53F@WKl(yzs&cFTC)=3opFz!V53F@WKl}8J}u}-"
            "`T>y@GePphN?^a)d6aZYyt_nex4>ki@)ngHP8nX=S{smYm5Qs6OWdr4RJrp^RD2tavBJ%_K}shZS{?v*U4>("
            "xt|8xNhSK`lKa8fHnip}^4MT}6mWTi{O>3>zpBP%EpD$pIt@znHTj@WX7up+$Jn9SCz}1V;)x-"
            "bZi!VlU>yu<R=>BvD{#SiSKo^cJ}%6c;_vGjqB{h~Lp07Sj@>*xvtrq_ZE+g?us+B!7I7??cnGZZVEeJpAog"
            "R~8=4(AWR3ALmm8mR^WKMN{`2_Jj`lu@sk$_miAF*BTA>PSu;||b_pKZ;T-JZtTxB96|4dT-"
            "{Z3G2U7NErpenZv`i0<bQsHd>`#4{v+Zm^$j?ZeN%>wQOFKP`~2NLX{U7UKGIH7v*%r;Jz9qdrM*r^Useh3_"
            "4=R8Jwf*tV`p1TBY(C!}mBTk?vN*m8~J{PO@)=-7it0lBwi|8u!8`jou1}Oms"
        ),
    },
    {
        "offset": 15498923,
        "end_offset": 15507507,
        "num_players": 7,
        "sha256": "6943ccba590a8593794bfe3c8e2e8bd4b694f62bfb98442e0b5fe693adea8862",
        "first_ids": (9737, 9739, 9759),
        "second_ids": (9771,),
        "tc_xy_words": (1106247680, 1117126656),
        "data": (
            "c-rk*y-EW?5T3ouA#Q{Oye0@5EL2bn?+G-"
            "B1Of`;&kIDfu@rm+pCFCRfiK}3XsNxuq81ibHs^O{R+n@4ylCkReA&Hk|7K=qf5<j<NJQgvM0H>WuqAVd@WK"
            "l(yzs&cFTC)=3opFz!V53F@WKl(yzs&cKN_EEh2O=(zwj<eb%v_5{M7*hMmB=fxPG1{K#RX8kZPa@D9)RDyV"
            "e+e&L<u%O&j8Vl;>T+XXO|WTJ0k%Z`<k{JFk=55_3Ndwv$Tq%_aAPvF+ZPv&dtE@lnX-"
            "4f4OE*!+?jmbJLO_UP0v(bwd|LYdLS=O1H-W}j&G(}E|4T)HJz-H>%K2&{gufj3~lc~{@l4n8i-"
            "m*VfsI?)Y+<1QNJ6~}I#o?5YN+O{~2epnym7>hU-Ogx0vda(W2V-"
            "WkX><!J18?wguoXgd(x%ueBGyi$~Xh(aW#8h3H^F$9}`C6e0Yq03wKKHF0F<jPv*<58JBL7TM{ryf*WnG)IG"
            "o&iF4ElxOZc^cF|NA(8d088#gO1MwMzbm04_?(WumU95P1kV(Zs4@)!b@8?Wwx<f?O@m1NBIG8h+Xsu=`nW4"
            "6L|3)xI(*I@Q*l+o+xcR)7fOK+MD;PM%^Hxy&$5Cn%~H_eg~5v0o4"
        ),
    },
    {
        "offset": 17343174,
        "end_offset": 17351758,
        "num_players": 7,
        "sha256": "dc91c1b2c9c5dad3cc8769825561962818ac9f10375d81f4772806fe43dce70f",
        "first_ids": (9741, 9743, 9761),
        "second_ids": (9773,),
        "tc_xy_words": (1118830592, 1104674816),
        "data": (
            "c-rk*y-EW?5T4ED5LV>^UK0d~7HVM%?+G-"
            "B1Of`;&kIDfu@rm+pTNfEz!$Le4YbtG!akywRyOB%W>%MT_q=H741C$WZ~tayXMe~xbU;Lt^F$Fa3)qr5M0n"
            "wa7hZVbg%@6U;e{7oc;ST?UU=b!7hZVbg&&PiwZd<^@GrbeQk|jd9Dj9y8Y3G)>Rdlh6QIf86G%1C0~F^?y&"
            "Y?eKIapUmZlAHKg#p2;IncJ2(0#@mA7s6jh)xYZHc*`i0z~jeRIkEU~C&$a~67RFg^;nJR<))ip?*nVOf*gY"
            "mZL-"
            "5`9fRD3lpJeEu<ZX!eO_KP`G<$fa9i)eTq&gPPUv4e$n>ao*MUjDwF0^QHLvYMkg6!SN6d^NM3PPfx5^Hf@`"
            "nhCi$ia*RbB3nm@{YdzS0>@kS_SoVfy#|>Fye9q;{*W7&c;hFzDezc>#PhzSrjRm5|pnR=Rg*908Z=d^Cju<"
            "ZMzih5D5s`l;ss4T^sIsoj*%?rkTL%3?a5t%Nw*P$`zg%{P>HVtD14grH+z(z=8(0Ps?51lt0oQR_b>XE=oH"
            "AS3t+ugi?V)@hIKVD?i1Y}%<1xH=4qT(%9r!1lM$eQ+FLXK;tJcOq)u~%cXtx&9Mcr>?OTPp4X942"
        ),
    },
    {
        "offset": 18924744,
        "end_offset": 18933328,
        "num_players": 7,
        "sha256": "65a3f4df2dd979a04f38a829539492e57941fbeed804a46c773274f0b6429d52",
        "first_ids": (9745, 9747, 9763),
        "second_ids": (9775,),
        "tc_xy_words": (1125974016, 1113587712),
        "data": (
            "c-rk*y-"
            "EW?5T3owA*@0oUK2zK3TmN<_XH9}0s#f_r?rS^V=4FuK7ozRfiK}3XsNw@L@ljs&hN~uF6Zre(b5_CvU}hD&"
            "CJgJkZl-EMB{Tr6TmFsN?IVo3opFz!V53F@WKl(yzs&cFTC)=3opFz!V53_aC~AEewTCq!WT(mQdFJcuQm`c"
            "(jlbA^|Levn*2S6)Bs&Tao*P3b;js%KK5v7+YtAoJnsrVD@OqBv=5!UYpZYUtWIW2#QoISPAbtilgtm+w!Sl"
            "Gp~nX6BhBS?^1q|F{Gu9^HMza<=+rCG*XDJu%<AFukF~?FPYnBM!4pG8y2Vai%{o{FPQSOn8*st-qQ0jK_$W"
            "7DiodT%iS7^_58)uMICiu2%!y^&w#jMu!}_3tv4~^A#)Ed&gX_mGgV>K{Z)k4ZkTb^TT&{l2%|{=e`Oo6V6t"
            "wqAMAfA+PxPqE*9uiwgL(h<xNlVu!)5)K%~dKQ^3NnO-|qxf*0nu5HC4G~&@TjclL}}1-"
            "^cOG)Y>3DX!|^1HJil!;8iUFD?p6hbR8$)22QIEytIW=W*fWJ4tA}5lpg{|*hP<#o?v%8g%>Y@8??Iz|Af=%"
            "nUeYooliunwb@rS>I5<E1tDG4{6@CSJEO(`<^"
        ),
    },
    {
        "offset": 20768744,
        "end_offset": 20777332,
        "num_players": 7,
        "sha256": "18cd9fd0c080c9ef99c9acc55f992b0b992a6f0223287a0d7971abea2e0a7ce1",
        "first_ids": (9700, 9749, 9751, 9765),
        "second_ids": (9777,),
        "tc_xy_words": (1121583104, 1126760448),
        "data": (
            "c-rk*OG*Pl5UrjMLMtTThy+1`5I>-c%n2ll1Of`;=K>MkxD-"
            "5sCvf9tz)N@oUFud`3K4bb%FX!3RBJO%kE1TFf|u@j{i~|3{*bQgfQar}L=&?_lRyiwB`px)g%@6U;e{7oc;"
            "ST?UU=b!7hZVbg%@6U;e{9eXMCa+e%rZ!;fo~EDXPx!R|oJI=?^5}`dJzS4gMZOs(~J$IB)80TVwP&A3L-"
            "(ZHW6(j&}u@l_P*}wGXYlZL4eStWIW2#QoIRPAbtilgtmswt+Qgp~D8_BcID_<bFr7`9(D>YjAt*(5YXdugU"
            "wlGNXsfKgJHtKGE!_c}ENt=@wgceb&Liv--UPUV&527xg_|z(=|HQv7`}N_36jxC@7Q#j%^E$5t$xwhd0hZ`"
            "KDDj71y^CLVliJ=lKiF^K(G_J(H14OwG+%;oau+`RYUnExz(bU}NUL{wesb3_k*`C6e0YcTKMKKHE(Vz{jTv"
            "bjn{ME;p1`s<yb%DOgZr%zRG8T1Rm-K4_V{`Ya*a@!fE3o9-"
            "U7|o_|KX_3~KpTj$o37#nT*GPAg_kyP%4}k{+QP22i}F2SAG_!Q(nIWyNAThqaEW#|;2&`sJyBA7rjzkVHP;"
            "6!psp9wju+B-;5M?U-vB*40)h"
        ),
    },
    {
        "offset": 22351225,
        "end_offset": 22359809,
        "num_players": 7,
        "sha256": "9b6b8901c389cd668bd87394f9d2d70eb14e25246d04b42d4b939f97626e706e",
        "first_ids": (9753, 9755, 9767),
        "second_ids": (9779,),
        "tc_xy_words": (1109655552, 1125122048),
        "data": (
            "c-rk*y-"
            "EW?5T3ouA*@0IrU?NFBE~`s&liv=5(p@WKQ9o`#!~PRd;%Mr17E^7&{BJQMJ=st&Tq}EF6Zuf(b5_CvU}hD&"
            "CJgJkZtIgh+6YRZJ-Odl6ypW;e{7oc;ST?UU=b!7hZVbg%@6U;e{7oc;ST~kI%Hi?@Hlcc%NiCN7Y&W>H!fW"
            "A46(f-"
            "=wK|2jK51q#76iiu1PKt~17v^Jzd!+lIIw6?j(&Svdj3PW!~kyS9eLHg$|GP41`8c2bGHMvNb<Z4b_zB>@|("
            "k76#bQ}`Xl<rmecti|nhK&N4ezBV5h%B&tC|5!UT`$V&!76LKk(=B!C#;k)y<n((3yaDH&_w_yF;hTl|Qv7{"
            "2Npy?gxKBoT#j$JBQzw>f+ZLzE59@<GV-d%KjfdD-"
            "53U~v3}Qc)y`i~rL(UkVbGiC8Hy?cj=HJAR_OuU4ld4OjOY|6*uNA7W28;e3a^K1m!)5)K%~dWU^3NpG-"
            "|qxf*0nu5W2$n?pkD~?CKb;1zmF4^xgPIfYatI<&Dyvhys9N&8A!34uHyvUz-iTom$q=qY-"
            "6|D!LGHB@&n)yyXX<pW9*J6@Ztq<jdpk7pKuyIQ&xYWv+1VlY(A(O^`n&bqJ%DMVIw>G9XVkDwE"
        ),
    },
]


@pytest.mark.parametrize("case", _NATIVE_CASES)
def test_native_tactical_records(case: dict[str, Any]) -> None:
    raw = zlib.decompress(base64.b85decode(case["data"]))
    assert hashlib.sha256(raw).hexdigest() == case["sha256"]
    assert len(raw) == case["end_offset"] - case["offset"]
    reader = SaveReader(b"prefix" + raw + b"\x10\x0a\x20\x0a", 6)
    saved = read_tactical_ai(reader, case["num_players"])
    assert saved.raw == raw
    assert len(raw) == (
        6388
        + 4 * saved.num_players
        + 4 * sum(len(v) for k, v in saved.vectors.items() if k != 0x2CF0)
        + 24 * len(saved.discarded_records_24)
        + sum(len(g.raw) for g in saved.groups)
        + 4 * len(saved.pairs)
        + 4 * len(saved.final_words)
    )
    assert (saved.offset, saved.end_offset, reader.pos) == (6, 6 + len(raw), 6 + len(raw))
    assert saved.num_players == case["num_players"]
    assert saved.vectors[0xC0] == case["first_ids"]
    assert saved.vectors[0xF0] == case["second_ids"]
    assert saved.counts[0x1F8] == len(saved.vectors[0x1F8]) == 511
    assert saved.static_records_24 == (b"\xff" * 20 + b"\0" * 4,) * 250
    assert saved.vectors[0x2CF0] == (0,) * case["num_players"]
    assert (saved.fields[0x2E7C], saved.fields[0x2E84]) == case["tc_xy_words"]
    assert saved.group_count == saved.discarded_count == 0
    assert saved.groups == saved.discarded_records_24 == ()
    assert saved.pair_count == 27
    assert saved.pairs[:3] == ((12, 500), (45, 500), (49, 500))
    assert saved.pairs[-3:] == ((584, 50), (598, 5), (1187, 10))
    assert saved.final_words == ()
    assert reader.take(4) == b"\x10\x0a\x20\x0a"  # Following empty Trade AI.


def _group(unit_count: int = 2) -> bytes:
    """Independent modern 140cab4b0 recipe, including the one-byte field."""
    raw = struct.pack("<IIi", 1, 2, unit_count)
    raw += struct.pack(f"<{unit_count}I", *range(unit_count))
    raw += struct.pack("<5I", *range(100, 105))  # 660..670
    raw += struct.pack("<8I", *range(200, 208))  # 674/684 two 16-byte blocks
    raw += struct.pack("<6I", *range(300, 306))  # 694,698,69c,568,56c,6a0
    raw += b"\xfe" + struct.pack("<I", 400)  # 6a4 u8, 6a8 u32
    raw += struct.pack("<21I", *range(500, 521))  # 6ac block80, 6fc
    raw += struct.pack("<5I", *range(600, 605))  # 700,704 block12,710
    raw += struct.pack(f"<{unit_count}I", *(1000 + i for i in range(unit_count)))
    raw += struct.pack("<5I", *range(700, 705))  # 804 block12,810,818
    # Shared native path14106e770: scalar, counted3-word points, four scalars,
    # and counted references. All words, including NaN/sign bits, remain raw.
    raw += struct.pack(
        "<II6I4II2I", 0x80000000, 2, 1, 2, 3, 4, 5, 6, 11, 12, 13, 14, 2, 0x7FC01234, 0xFFFFFFFF
    )
    assert len(raw) == 245 + 8 * unit_count + 32
    return raw


def _synthetic(
    *, num_players: int = 4, groups: tuple[bytes, ...] = (), negative: bool = False
) -> tuple[bytes, dict[str, int]]:
    """Original wire fixture with unique values at each native boundary."""
    out = bytearray()
    marks: dict[str, int] = {}

    def pack(fmt: str, *values: int) -> None:
        out.extend(struct.pack("<" + fmt, *values))

    def marker(label: str, value: int = 0xAA0) -> None:
        marks[label] = len(out)
        pack("H", value)

    def vector(label: str, values: tuple[int, ...]) -> None:
        marks[label] = len(out)
        pack("i", -3 if negative else len(values))
        if not negative:
            pack(f"{len(values)}I", *values)

    marker("entry", 0xA10)
    vector("first", (10, 20, 20))
    vector("second", (0xFFFFFFFF,))
    pack("II", 111, 222)
    marks["static"] = len(out)
    out.extend(bytes(range(24)) * 250)
    marker("after_static")
    for i in range(9):
        vector(f"pre_{i}", (i + 100,))
    marker("after_pre")
    marks["flat_count"] = len(out)
    pack("i3I", 3, 0xFFFFFFFF, 0x80000000, 0x7FC01234)
    marker("after_flat")
    for i in range(3):
        vector(f"post_{i}", (3, 1, 3))
    marks["discarded_count"] = len(out)
    pack("i", -4 if negative else 1)
    if not negative:
        out.extend(bytes(range(24)))
    marker("after_post")
    pack("20I", *range(1000, 1020))
    marker("after_fixed_arrays")
    pack("I", 333)
    marks["group_count"] = len(out)
    pack("i", -1 if negative else len(groups))
    marks["group_start"] = len(out)
    if not negative:
        for group in groups:
            out.extend(group)
    pack("11I", *range(1100, 1111))
    marker("after_groups")
    pack("12I", *range(2000, 2012))
    marker("after_position")
    pack("11I", *range(3000, 3011))
    pack(f"{num_players}I", *range(num_players))
    pack("12I", *range(4000, 4012))
    marks["pairs"] = len(out)
    pack("h", -2 if negative else 3)
    if not negative:
        pack("6H", 2, 0xFFFF, 1, 100, 2, 123)
    vector("late_first", (8, 8))
    vector("late_second", (9,))
    pack("II", 5000, 5001)
    marks["final_count"] = len(out)
    pack("Q3I", 3, 7, 1, 7)
    marker("exit", 0xA20)
    return bytes(out), marks


def test_nonempty_group_and_path_preserve_native_widths_and_all_bits() -> None:
    raw, _ = _synthetic(groups=(_group(),))
    saved = read_tactical_ai(SaveReader(raw), 4)
    assert saved.group_count == 1 and len(saved.groups) == 1
    group = saved.groups[0]
    assert group.unit_count == 2
    assert group.vectors == {0x570: (0, 1), 0x714: (1000, 1001)}
    assert group.fields[0x560] == 1 and group.fields[0x564] == 2
    assert group.fields[0x660] == 100 and group.fields[0x670] == 104
    assert group.fields[0x674] == 200 and group.fields[0x690] == 207
    assert group.fields[0x568] == 303 and group.fields[0x56C] == 304
    assert group.fields[0x6A4] == 0xFE and group.fields[0x6A8] == 400
    assert group.fields[0x6AC] == 500 and group.fields[0x6FC] == 520
    assert group.fields[0x700] == 600 and group.fields[0x710] == 604
    assert group.fields[0x804] == 700 and group.fields[0x818] == 704
    assert group.path.fields == {0: 0x80000000, 4: 11, 8: 12, 12: 13, 16: 14}
    assert group.path.points == ((1, 2, 3), (4, 5, 6))
    assert group.path.reference_words == (0x7FC01234, 0xFFFFFFFF)
    assert group.raw == raw[group.offset : group.end_offset] == _group()
    assert saved.raw == raw


@pytest.mark.parametrize("count", (0, 60))
def test_group_array_count_zero_and_native_capacity(count: int) -> None:
    raw, _ = _synthetic(groups=(_group(count),))
    group = read_tactical_ai(SaveReader(raw), 4).groups[0]
    assert len(group.vectors[0x570]) == len(group.vectors[0x714]) == count


def test_preserves_vectors_discarded_records_duplicate_pairs_and_set_order() -> None:
    raw, _ = _synthetic()
    saved = read_tactical_ai(SaveReader(raw), 4)
    assert saved.vectors[0xC0] == (10, 20, 20)
    assert saved.vectors[0x1F8] == (0xFFFFFFFF, 0x80000000, 0x7FC01234)
    assert saved.vectors[0x29F0] == (3, 1, 3)
    assert saved.discarded_count == 1 and saved.discarded_records_24 == (bytes(range(24)),)
    assert saved.pairs == ((2, 0xFFFF), (1, 100), (2, 123))
    assert saved.final_words == (7, 1, 7)
    # ASM 140c93c50/3d10/3dd0 proves this unusual five-array order.
    assert saved.fields[0x2AD0] == 1000
    assert saved.fields[0x2AE0] == 1004
    assert saved.fields[0x2AC0] == 1008
    assert saved.fields[0x2AF8] == 1012
    assert saved.fields[0x2B08] == 1016
    assert saved.fields[0x2CB8] == 2009 and saved.fields[0x2CB4] == 2010
    # Native subsequently zeros +2ce8 locally; preserve its original saved bits.
    assert saved.fields[0x2CE8] == 3010
    assert saved.fields[0x2170] == 5001


def test_native_nonpositive_vector_counts_skip_loops_and_remain_available() -> None:
    raw, _ = _synthetic(negative=True)
    saved = read_tactical_ai(SaveReader(raw), 4)
    assert all(v == -3 for k, v in saved.counts.items() if k != 0x1F8)
    assert all(not v for k, v in saved.vectors.items() if k not in {0x1F8, 0x2CF0})
    assert saved.discarded_count == -4 and saved.discarded_records_24 == ()
    assert saved.group_count == -1 and saved.fields[0x299C] == 0xFFFFFFFF
    assert saved.pair_count == -2 and saved.pairs == ()


@pytest.mark.parametrize(
    "label",
    (
        "entry",
        "after_static",
        "after_pre",
        "after_flat",
        "after_post",
        "after_fixed_arrays",
        "after_groups",
        "after_position",
        "exit",
    ),
)
def test_bad_markers_restore_callers_cursor(label: str) -> None:
    raw, marks = _synthetic()
    corrupt = bytearray(raw)
    corrupt[marks[label]] ^= 1
    reader = SaveReader(b"prefix" + corrupt, 6)
    with pytest.raises(SaveDecodeError, match="AI marker"):
        read_tactical_ai(reader, 4)
    assert reader.pos == 6


@pytest.mark.parametrize(
    "label",
    (
        "first",
        "second",
        "pre_0",
        "pre_8",
        "post_0",
        "post_2",
        "discarded_count",
        "group_count",
        "late_first",
        "late_second",
    ),
)
def test_impossible_counted_arrays_roll_back(label: str) -> None:
    raw, marks = _synthetic()
    corrupt = bytearray(raw)
    struct.pack_into("<i", corrupt, marks[label], 0x7FFFFFFF)
    reader = SaveReader(corrupt)
    with pytest.raises(SaveDecodeError):
        read_tactical_ai(reader, 4)
    assert reader.pos == 0


@pytest.mark.parametrize("count", (-1, 512))
def test_native_flat_array_capacity_is_bounded(count: int) -> None:
    raw, marks = _synthetic()
    corrupt = bytearray(raw)
    struct.pack_into("<i", corrupt, marks["flat_count"], count)
    reader = SaveReader(corrupt)
    with pytest.raises(SaveDecodeError, match="fixed-array count"):
        read_tactical_ai(reader, 4)
    assert reader.pos == 0


@pytest.mark.parametrize("count", (-1, 61))
def test_nested_group_capacity_failure_rolls_back_whole_tactical_ai(count: int) -> None:
    raw, marks = _synthetic(groups=(_group(),))
    corrupt = bytearray(raw)
    struct.pack_into("<i", corrupt, marks["group_start"] + 8, count)
    reader = SaveReader(corrupt)
    with pytest.raises(SaveDecodeError, match="fixed-array count"):
        read_tactical_ai(reader, 4)
    assert reader.pos == 0


@pytest.mark.parametrize(
    "label,fmt,count",
    (
        ("pairs", "h", 32767),
        ("final_count", "Q", 0xFFFFFFFFFFFFFFFF),
    ),
)
def test_impossible_pair_and_final_set_counts_roll_back(label: str, fmt: str, count: int) -> None:
    raw, marks = _synthetic()
    corrupt = bytearray(raw)
    struct.pack_into("<" + fmt, corrupt, marks[label], count)
    reader = SaveReader(corrupt)
    with pytest.raises(SaveDecodeError):
        read_tactical_ai(reader, 4)
    assert reader.pos == 0


def test_truncated_boundaries_and_nested_path_roll_back() -> None:
    raw, marks = _synthetic(groups=(_group(),))
    cuts = {0, 1, len(raw) - 1, len(raw) - 2, marks["static"] + 5999}
    for at in marks.values():
        cuts.update((at, at + 1))
    group_end = marks["group_start"] + len(_group())
    cuts.update(range(group_end - 61, group_end))
    for cut in sorted(cuts):
        reader = SaveReader(b"prefix" + raw[:cut], 6)
        with pytest.raises(SaveDecodeError):
            read_tactical_ai(reader, 4)
        assert reader.pos == 6, cut


@pytest.mark.parametrize("players", (0, -1, 100000))
def test_invalid_native_player_count(players: int) -> None:
    raw, _ = _synthetic()
    reader = SaveReader(raw)
    with pytest.raises(SaveDecodeError, match="native player count"):
        read_tactical_ai(reader, players)
    assert reader.pos == 0


@pytest.mark.parametrize("version", (0, 0x44E665, 0x44E667))
def test_exact_save_version_guard(version: int) -> None:
    raw, _ = _synthetic()
    reader = SaveReader(raw, version=version)
    with pytest.raises(SaveDecodeError, match="unsupported Tactical AI save version"):
        read_tactical_ai(reader, 4)
    assert reader.pos == 0
