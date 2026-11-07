"""Native base-header bytes plus independent spectator bank values.

Compressed fixtures are original slices of owned replay headers, not generated
by the implementation. Exact source identities and inflated offsets are in
artifacts/game-internals/2026-10-18-world-restore/native/player-base/fixture-sources.json.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import struct
import zlib
from pathlib import Path

import pytest

from vantage.replay_binary import SaveDecodeError, SaveReader
from vantage.replay_players import (
    read_gaia_extension,
    read_player_ai_continuation,
    read_player_header,
    read_player_prefix,
)

_CASES = [
    {
        "sample": "3p",
        "player_id": 0,
        "num_players": 4,
        "name": "Gaia",
        "civilization": "GAIA",
        "factory_type": 2,
        "color": 8,
        "bank": [0.0, 0.0, 0.0, 0.0],
        "raw_size": 5068,
        "raw_sha256": "b72d853f9498643125c3b1a0f1790743f3b242a046b75b0cce8a5f29b4b38a2c",
        "resources_sha256": "b7d24ee8d8e140f07b5cb7f555937c60b444dd2f4825e05dcefc8087f095ee24",
        "secondary_sha256": "5f442100fe239d6eab57f013641cb364b9cc058cb8565d3fcefb210ec2dd24fe",
        "offsets": {
            "factory_type": 0,
            "name.length_including_nul": 27,
            "resource_count": 35,
            "base.after_resources_marker1": 4848,
            "saved_view_count_runtime_240": 4857,
            "equipped_skins.count": 4874,
            "localized_name.length_including_nul": 5038,
            "runtime_48c_count": 5047,
            "base.final_marker1": 5067,
        },
        "data": (
            "c-mv)W?*J!W@KPsU_ruQz{=pBn3>2R7RkiGpvXWHIN(5<{23<(hI2rC$_a-"
            "C2Q(TD7&+szY1Yh{b_@&+_QbpWf)j4_3mhPFFnKg}3YM<e^<gv5!2wlX-"
            "v!FXA9feaTp30I6~p0#BW^iZTz_yR&uo}}lr*y+A@AXYnMRP+QUieOL$(u7`Xw7YaK@A7?V*?mAmN1D8"
            "*7}QdBy>ESbI2)W{goV3dk+1C{c^8Ordr;LkoA0f>AIEM!_f;1*2dTjDq0|xEUBGIDzngATVSoVPHz&V"
            "qtK1^n~{CxjDGmfD{u{ITIAi0WmWWGlE4O94K-"
            "F533Bc+YE1xRzm3%C<XzL3qfo~Mg{?O28Mq?E+eWzRW1w+ya=xW0J(ieod"
        ),
    },
    {
        "sample": "3p",
        "player_id": 1,
        "num_players": 4,
        "name": "Shazama",
        "civilization": "KHITANS-CIV",
        "factory_type": 1,
        "color": 3,
        "bank": [200.0, 200.0, 200.0, 100.0],
        "raw_size": 5082,
        "raw_sha256": "83eba2d664b447c2c066849ea1e46e37ae68877156a0ccc8b44a9f3d633c4364",
        "resources_sha256": "1c5be70e2a5ccc33f93bf05d8fc78062f2a19c961f129523f283f503ef9e9ae9",
        "secondary_sha256": "5f442100fe239d6eab57f013641cb364b9cc058cb8565d3fcefb210ec2dd24fe",
        "offsets": {
            "factory_type": 0,
            "name.length_including_nul": 27,
            "resource_count": 38,
            "base.after_resources_marker1": 4851,
            "saved_view_count_runtime_240": 4860,
            "equipped_skins.count": 4884,
            "localized_name.length_including_nul": 5052,
            "runtime_48c_count": 5061,
            "base.final_marker1": 5081,
        },
        "data": (
            "c-mv+W@cb!W&i?4AZCGL5SxL6AvhzkDls>aK`fGqfkBah!NVDWPdG6!G}trX1Pu-hcmcZn8K8ORfcTUX"
            "rrKXX`xqP`_96p)Am70Of{mQ9yQjf^*36l9sB-"
            "w+4FVU?{I<Xm=ms|^+W{g6lSeaajffk%X_)rIfP(|7oAh0X3cCgt7lu&)1oh4g4V})En{&buPhdmi`hz"
            "2RX2bNOq?!E)c@HPdbcw8%8USP;vYoinuY&{mc06##?sqV-hhidtgcELWtbyit1_#_>?cp?<FGj&AAh)"
            "cdhJI{yEj7zCYP)+BjDk@x3P!;w7zLwX6bxs;&A?y+>?FPbcj$E)WEq$fxVRa-"
            "Jv>7k{epF!J;R{Nn7P@26cYnvIE+sW!UkbEAZCV&liO=fg)ul-"
            "WnjZ@5AMFG0SOi5mn4>?rZA)c*(p$E|A7F+W@Ka#P-kHH2jnuMnplN0D#Q%{LLXL`"
        ),
    },
    {
        "sample": "6p",
        "player_id": 5,
        "num_players": 7,
        "name": "Immortal v0d10f",
        "civilization": "MAYAN-CIV",
        "factory_type": 3,
        "color": 4,
        "bank": [150.0, 200.0, 200.0, 100.0],
        "raw_size": 5103,
        "raw_sha256": "f3f59e389d13f59033cc661d14e6aeefbdfd449cb021f16c89a869025029c6e6",
        "resources_sha256": "4d96d231ba8f40b4494549b78de2fad7310bdca3c5ab760fc7b3d60f3f8d1457",
        "secondary_sha256": "5f442100fe239d6eab57f013641cb364b9cc058cb8565d3fcefb210ec2dd24fe",
        "offsets": {
            "factory_type": 0,
            "name.length_including_nul": 42,
            "resource_count": 61,
            "base.after_resources_marker1": 4874,
            "saved_view_count_runtime_240": 4883,
            "equipped_skins.count": 4905,
            "localized_name.length_including_nul": 5073,
            "runtime_48c_count": 5082,
            "base.final_marker1": 5102,
        },
        "data": (
            "c-mv;W(ENUW(FW&LBotlG=l(xXKrqOQAuKsLYYB|p+OphSR@kzgCYZim@@-"
            "|2Na)hV!#U)IFKfP258<nAU=h~++RTZ7#tw>A_ILOzrg{5jX-RBOuY^Evu4h;Gd7-"
            "Vk1U4YZ5NzS)huuXy1@<MZjc;I9?dKj5jS+xFztr{2M1I)>AOJLAio~M>AVI$7lu&)42Q|i3=N&mlpA!"
            "y5tj@o-XL-"
            "J!I4Zy+M{By*nWh(hZC}0Fg@7Q3n_M@@b{zIi7Wj!IFN1S0c#g*VFzW}LopFR0(ZI6u*MmhXB=?F6>@l"
            "vf>AIEC@D8cRg1Muu_xVZdb@iRjDk@x3P!;w7zLwX6bxs;&A@OA*h$m`4;<t&tYlzK;NoQPb&PcM({=U"
            "?gDPU-"
            "W&=`843I%FLp2B+gyn#k87huChC>?g*b#moM8^ZMBtt0^OuU0b1WczuF$nwz0uY;#kwHM6f#DyJ%ZN6H"
            "fzt2g1^{3uUN8"
        ),
    },
]


def _raw(case: dict) -> bytes:
    return zlib.decompress(base64.b85decode(case["data"]))


@pytest.mark.parametrize("case", _CASES, ids=["gaia-3p", "human-3p", "ai-mayan-6p"])
def test_native_headers_match_exact_sections_and_independent_banks(case: dict) -> None:
    raw = _raw(case)
    assert len(raw) == case["raw_size"]
    assert hashlib.sha256(raw).hexdigest() == case["raw_sha256"]
    reader = SaveReader(b"prefix" + raw + b"\x0bderived", pos=6)
    player = read_player_header(reader, case["num_players"], player_id=case["player_id"])
    assert player.offset == 6
    assert player.end_offset == reader.pos == 6 + len(raw)
    assert reader.take(8) == b"\x0bderived"
    assert player.factory_type == case["factory_type"]
    assert player.name == case["name"]
    assert player.civilization == case["civilization"]
    assert player.color_table_id == case["color"]
    assert player.player_id == case["player_id"]
    assert player.resources[:4] == tuple(case["bank"])
    assert len(player.resources) == len(player.resource_words) == 601
    assert len(player.secondary_resource_words) == 601
    assert hashlib.sha256(player.sections["resources"]).hexdigest() == case["resources_sha256"]
    assert (
        hashlib.sha256(player.sections["secondary_resource_words"]).hexdigest()
        == (case["secondary_sha256"])
    )
    assert struct.pack("<601I", *player.resource_words) == player.sections["resources"]
    assert (
        struct.pack("<601I", *player.secondary_resource_words)
        == (player.sections["secondary_resource_words"])
    )
    assert player.raw == b"".join(player.sections.values()) == raw
    assert player.name_bytes.endswith(b"\0")
    assert player.selected_object_ids == ()


def test_factory_byte_can_be_owned_by_outer_structural_dispatch() -> None:
    case = _CASES[0]
    raw = _raw(case)
    reader = SaveReader(raw)
    factory_type = reader.u8()
    player = read_player_header(reader, 4, factory_type=factory_type)
    assert player.factory_type == 2
    assert player.offset == 1
    assert player.raw == raw[1:]
    assert reader.remaining == 0


@pytest.mark.parametrize("case", _CASES)
@pytest.mark.parametrize("field", ["base.after_resources_marker1", "base.final_marker1"])
def test_bad_native_marker_restores_outer_cursor(case: dict, field: str) -> None:
    raw = bytearray(_raw(case))
    raw[case["offsets"][field]] = 99
    reader = SaveReader(b"prefix" + bytes(raw), pos=6)
    with pytest.raises(SaveDecodeError, match="expected player marker") as error:
        read_player_header(reader, case["num_players"])
    assert error.value.offset == 6 + case["offsets"][field]
    assert reader.pos == 6


@pytest.mark.parametrize("length", [0, 2, 40, 2444, 5067])
def test_truncated_native_header_rolls_back(length: int) -> None:
    reader = SaveReader(_raw(_CASES[0])[:length])
    with pytest.raises(SaveDecodeError):
        read_player_header(reader, 4)
    assert reader.pos == 0


@pytest.mark.parametrize(
    "field,fmt,value",
    [
        ("name.length_including_nul", "h", -1),
        ("resource_count", "i", 0x7FFFFFFF),
        ("equipped_skins.count", "I", 0xFFFFFFFF),
        ("localized_name.length_including_nul", "I", 0xFFFFFFFF),
        ("runtime_48c_count", "i", 0x7FFFFFFF),
    ],
)
def test_invalid_count_cannot_consume_following_player(field: str, fmt: str, value: int) -> None:
    case = _CASES[0]
    raw = bytearray(_raw(case))
    struct.pack_into("<" + fmt, raw, case["offsets"][field], value)
    reader = SaveReader(bytes(raw))
    with pytest.raises(SaveDecodeError):
        read_player_header(reader, 4)
    assert reader.pos == 0


def test_nonempty_native_optional_vectors_are_consumed_at_their_own_boundaries() -> None:
    case = _CASES[1]
    original = _raw(case)
    edits = [
        (case["offsets"]["saved_view_count_runtime_240"], struct.pack("<i4I", 2, 1, 2, 3, 4)),
        (case["offsets"]["equipped_skins.count"], struct.pack("<I2I", 1, 55, 66)),
        (case["offsets"]["runtime_48c_count"], struct.pack("<i4i", 2, -1, 999, 20, -30)),
    ]
    raw = original
    for at, replacement in reversed(edits):
        raw = raw[:at] + replacement + raw[at + 4 :]
    reader = SaveReader(raw)
    player = read_player_header(reader, 4)
    assert reader.remaining == 0
    assert player.resources[:4] == (200, 200, 200, 100)
    assert player.fields[0x238] == (1, 2, 3, 4)
    assert player.equipped_skins_words == (55, 66)
    assert player.fields[0x2A0] == -1
    assert player.fields[0x488] == 999
    assert player.selected_object_ids == (20, -30)


def test_unverified_save_version_and_factory_variant_are_explicit() -> None:
    raw = _raw(_CASES[0])
    for reader in (SaveReader(raw, version=0x44CCCC), SaveReader(b"\x09" + raw[1:])):
        with pytest.raises(SaveDecodeError, match="unsupported"):
            read_player_header(reader, 4)
        assert reader.pos == 0


# Original native derived slices; provenance: player-base/derived-fixture-sources.json.
_PREFIX_CASES = [
    {
        "sample": "3p",
        "player_id": 0,
        "size": 180865,
        "raw_sha256": "6eb20f0c21bcf4f07e0244ae7d4b79a5479edd6233ce9743c196c35bcc5c124e",
        "research_sha256": "fa459532d14d867bd9ee93cc9ed68fca72e0d1f5055cef1d50a340ac4bfd0666",
        "history_rows": 0,
        "next_section": "outer_player",
        "next16_hex": "000000003b0000000000000000000000",
        "configuration_relative": 115684,
        "after_configuration_relative": 180844,
        "history_relative": 115097,
        "history_end_relative": 115276,
        "research_end_relative": 115093,
        "data": (
            "c-rk<34D}AvhV(8GBde2<PgNgl_=s7km!mmLC(zt0tyI35tJh#AoslpD(YS;io2fc@m5{0Wz}^7@p#X-"
            "uJ7$r1VsezbzM<G0YwD7kyrJ7{UtRYiISwc`7-JG{VLx~GO2%8AJtXW-PPHSIH*^KdTw#wL@IwT$7TuP"
            "li0r>Y5)H3_6L8$U-"
            "s{psXX!9{?9t_a{tl&RDWK>M81f9mSic{Fi|MtySaE3iNqc*UIiktmrusT=Zxk0B83-u)sELR(N-"
            "kRDdH>Fms~P-"
            "5{a)E>;CH+>Z?|~9MK>8mmIC?>)XsCk)7aT+)2nWm5e(vGHxm4`IU@Y*37t;U1vBncl3f9x{j!QbH~5o"
            "Dp!$+jN>U+H7ZloRh17Hpw1^0F*GXgwBQbpZ&T`C*0o%yPGS>__}a0eh)>3SNtU|joJQHF<nQ>VnE2FW"
            "=**5r%B#+OH6PkBXEu+{$rpV@&YU7$eWK2K!u|Jo2Fg`SUga>S<t!+&W2k|Tp-JeTT+B0uCZV0f#A|~n"
            "6B(EC@EQ)~a<(y=?)#HWG8PDVIahsw>3#*HJt2xir*k%dvG4qfqrM`d*l921uNALm@%F-"
            "rCVelWy~vGO>!4P><!Zj37rTZrkZ^4>guS>#WG>_JA~ryMWn7nJvVhu)?5o08Ulph&ujkQ{6;Su`h6Z7"
            "^aC&f@yf}ls^=L<!(QoDI6J<i)#>K0faBk<~RV17{82jqxl(8KVe7x#49wT>h)mOfV+{MMKP(<$Lo73V"
            "m!lzfmI<_^JD?BnTFVa;mJu=q8Hi<q|#8+Prhc61!6>O8(BSoR>U!@q~Tv4QJJl3OJc_Oxo$M&5jE*II"
            "4a`C!TWUuDp_1_}<u_C^?wqfXK%geT-*uOd1*viE@4>blo!Rf<Tonv`fUUnX`GKNIP4Whls%u0sS-"
            ")5`(GTT=zFO$4Dclb3fUSVxVyVlf@=g0JnM>oFuvb=0x4P|{b(zUsI?B*(=ySYl}ZmyExZmz~Kx~z530"
            "He6+KT^FtuZi77X*@$YB1hzjxKKLhvKaXgsx4IQMeJLy?J{{HwuOsVClTAqv&px>X)9!I(w`RKLzBvBp"
            "{>Yinq)#LpeO|trGN>gacqmp!L~m#d}F0t3=#38!ngE<V<rA$uB~|8MEqzTUeiR0i036k*}rl+gs&ZQ@"
            "NnbtJmtczKZz5#`b3e4cS`DVY3iYI%c#aJqZ+r2P2;-"
            "S=rnr}Bn^3mLK{s2jhopy$;7Kr#PWHLxw~?*9WU%75+`ZXAff1A<zli(^x)IpvF_p9ERGvp6aCXW#Xwl"
            "Y6?n`&w{I91)!|LQWE#8jXvu<AT$J82PQp|-"
            "1H$NafmJ+$N9S|}k0e&gr@yk<^eT8tBO9GwwJ90C*Y7A2vEfOkF|=I7&$j)`^0K_rOHX(yES$1rRSJtp"
            "IZ0vBB+e7v#-"
            "&w)QbJKmYDTH`p{Y(Habbhl+}{{t8g>lZ&3FxEwJEG)h?5s*EYFTd%gb&i4$l}0Yq`>HI~pcp$z8@{uV"
            "T#1xmw%0Mko?^U^>UhQm**hO(K3h53gY&OXU2HryV!oR;}OKHD1fBLHcPC8_TnO!usx(m+kkq?kz8SnE"
            "p^EfsVbvm$*6hA|tPtxOnA@*qe;ydW|n7ee7kv+oWO}xp<X`*ei_n^(q&yZX)(NW1m>hDB~s`Uild7c!"
            "TSj0^qfV@5+Ph|K%%J_CNTNpEr4yt6b10o@b0HFwH|a9<!h0lCiyr{GW}R9Q>Z10+IP~gQzdNKgja3yb"
            "k3xckf!gYI%j<N9MfdZkUjw$%oqdy-"
            "m)O9{Y1FFU!mBsYwG~<rwSO#d8NZ`c@>}N<lE)N<9S553iBv6o*d9x=yYvW;(c1AhJK=I#k<7<nH9+l`"
            "pclb8R9j5jmf7@hTMAJNSaYi5s~Nrss*=NU=3~YE$>I;<PrP@UHFLjPS|mE?7j1t?^o$8&<!pLFb6tFJ"
            "i?<CqvjLI*CL)z59e)_ct-"
            "#k9{*AulUo9yne&T>q?$^yRqC59s4Jbo@fl4h}`;m%LaihukiCK6+=W~CYN4qFXDe^v?rcn)c60x$ZIV"
            "luXT*|HHneeWIkUsK834X(7&cKmTMYgJ5Fb`ziwbG*H}9b9V#0jo@IT}LuP-"
            "S6HZ?=em<j~xFC!&=8M?5$@KTPM>DqL7{+;f0%N(xGnQ)<W4X?=bK1eL!(1#9h2h(np}D?f-"
            "D3(_jCFr!FnJs2?a86&U#dKom*r)7SzeZx<<;PMHHM94LNpal<Ktz01(R`ro*|7-"
            "oDtG;^$BUYerDi83vr0!IRhEv6D5pslR=E-"
            "8qBz^a3*89&SEUr5XN#1<>6)RFFQY4UY3{Tr4n284xgP<3gv3jE4>f+=ZLl<cUXf+(r*(7e{b@Rwjyg{"
            "_%4}iKnd*A(BCc+v1B;+Jj9B_Sgt-IHY=q5_H0IfXbz)4G?&q@oyW&3F`rS!pEK6|0!Cg78P5h@6uy36"
            "F3LpaBD=364egx9u;0Y;vb@rsmyKf{IvtG{i^o?K>GIuevJ;zR(I(Teyc%7<w{zN|s(Z(aSzW4pzW1W!"
            "L)ZdXOF|mJx-6sttjoEA6?r0l1!HjM7mNX!UvdSo3Pj>pjOF?@V}1RLv0U#kmh0a(P-"
            "J;oUY1t_HC{J2I{g)j+f~DRNVA*B+{|N7<cO9cdwG$rLx=SnLk)vhTI!trj56-"
            "uZ0#@0tAX19q7m?_f1t?nvb-"
            "82FB`c1p%`BxY{{)0uUwg`T$jbj2L^!;$mW$LGU~=FOC++3nSzIfBA&x1V<OjPEVH~UFU!jY{OoGAH7*"
            "V)7pFbJHg6ZQ&D+)5Id!&8@`H9xoyTK2$S8L41f9Byr6RK;-"
            "2+%Mq`d5$mZm4_?CCtq%l0qZj`qr2%PU=Y*`2`F=S%x?h1wUj<vJw&t1I51aY@pS$3wCi4Eoo_c7u)OW"
            "qH}P09*H=<<<B$#)fs1t>tBTv2CctEQzce=<T73G>A_W*6eqP^za{ZM45;Uw>sMLGNvcOV^5^=vWL~uj"
            "aOX`<>wYN*}m{*b`c-"
            "1IXt}bMN5&}H_65;`zjt@8(>b$d5?=%0VA(`(d2!;a&hshrcc=Hjdne)QS70t@f-"
            "!`zQ=Iwp|rkede~pWmMa8)hp=|ET~}y?yo4P?mY3yad0AeTmu{c0K*V0;iq#e{%4m66UJZp;ILCHZQ6l"
            "0a!?$Lb13D*DHn6yf2vtnfma75AM6GR7hs4xuvD$)$601$ac06DV*>!ijM!|S%wGi$4h0o6EFN%a5&9n"
            "B~A9SG{!^NwmkmuL1PeItVCd<q2U$uK4>^bQ}d(N;(#E(kv{l0GO(fU@Fm*r)7Szh*LZp-"
            "V?#M0_;xnUS%3N}`IX!{pm-gLgc+DPN8^(&XYbA}NuaVC*2=bAWmbf=p0``SH$jq>b#HN0fq?Luken3k"
            "92rHfZs=SPvYGFn~+&u_;+92;ZX*YQyeyy}pzBWD|5xpKGj@Zzrf8hr)Z@AcdFq3rja82f!;Nc(+zo&D"
            "bO`rf)PV(j<d(^qBf%T?nTvikmDe7<_@0q<7x9&o|vi;9r?+njZuCYL2IPIMBPn^MM5J$Q9v<kg3b7iW"
            "DX6EL=4<tbMZ>Whol56PG%O2^IqadO<$spSi6CvE&SE@}I)@#1dL#Or)58sHUHi#jBAKSX4{X`oNY+G?"
            "MC5!+BhxoXV|#?Z^*>-U`Xm4y1rd4;FGc-yg1BsOXrkDS(%2!oYUE=GyWe`>3*I=5pEc(~bb^YpJAF(R"
            "1NRiv9<Z9tJ7PV3zAvb-7!uf`CyO*=bhnkW#?zj)@MX(CTV-r?faR7C%+&Bkn8D-5-+dm)^6d7`7(j*-"
            "oLyrS=M+2oQj3!7G6_1YP*pYe8=8hJGay&5jNupa)S5KXpl#Q~%lUSYKXq+J!L&Yp;Tz_WsdyrNsVc(o"
            "Nd?{o3$#Kx-ut=wAs%kpZBylfo6^0M(9t0ye4@a_h03^o&Ixn#Y3m?dY>I6$3wHODwp(_$80)s(9qr=?"
            "^lPxfg(c~xh>cBGRh<PqayLU(=Htgh9p{YugFM?7^OR$isZt9^R&Do0*NH85Va-bLJ!aR+yM#$DH)?1`"
            "O2RIVJT`^@Ax{q<#UK(*sBRO7LeJxP=nr;-"
            "efAsMPMWY>NzFUu<p_J85&#hiBISk~}S=j0wa&d#;9$j+Nt+#up6q3HM1Go^?y@`^LnS1F#NA26;V><6"
            "&xwRWA))_r>Nsz<C=h}da7*&6XywlMOtH%o_#SDp7X<C>vt!js)n@vt{j9D)q7yje=~?X7I-"
            "$*UfF3z~{Zv-Iv0Va-"
            "%tisNx+(&`DzEA+g=dW&#a$2R6I$b5@yjl$kgX?ZmiJ;B%SanFNBzqWpJ?ZBiRLpHu@d0AeTm*r)7Sze"
            "Zx<z;zUUY1vgZi|aE`H$}2l@qvl6^Y!P$q>e@4v6vD{$<xiMT|36dt_2q{|akN)Q%y0W2}gM$F<Iv$G8"
            "?yV5Z;KMSuA(eqQ#Rbc5{ooHt(QHIy5#t&TR<SMwU<E$E@ptL}Q*48HuUM)qUcJ>Zs?<y9A6*>p&@7EG"
            "^9q3?CH5KI1slwH#|92sHx{h@nhAM_Wc>JMc#&<pF<_1p_z*aIZX%IX32gRkhZS#sB0RURiB4`}2A6#x"
            "|h^#>|;gqx_n0G>F#kA!C%sQhRyd>9CHHa0N)(kbWcjtBK}OO2FS3O_4=o(0+pza9=xEYCckvw$v(36T"
            "@U5Ab6M5bp0E1N1a}xgGFW0`KEMB|tmj^J4giCKKVqMxd3_<J=FZ2~annp-TML@V5j!Ujcd^Xq{74E;B"
            "WNBf&{bf}g{HrU7tQcy0i?4QLzCdmwP{ZSbQLd>DZL0{=4r{`WX|e*`?6!#^F5Lcp^#JUaq?Ej+>6z~3"
            "*%+KG5QZzs?<@V%x$hr{3UfOf<Cw(x8Vf9nO`TLqtc!1F`=f1p-)@&{-"
            "le5V8aZ7{qa4}aeU@5|vi8E7id44^0AZ;!+GK7#i<f%XD@3A6*~GoYa$$5@~VKofx`15E{51GElkJ<!W"
            "QTYyGo2(bWwF9IsU{;>(@In~3TQC;9<ps#?M0S!{MSO^8^1vDS%382S-"
            "7OM)&RU>07P+$1nx2lp>!}B%aRmy4bd=#Eb;kg#556~y@`D>tc(rdF9;kh2@C7}0!-"
            "Us>sXp8jv@P}9lK-"
            "++}1ML9%SamH2C<?S0J{Q9C44~dXeSt;+O$V9@G#h9x&_h6f0s1S@N^Ce_^BFw%I8}YfOmD?O=tQ@}&m"
            "BN5;aB?ry!aUSa1VUQ5T2m-Nw1*IfIbBp2%p~s>JIO_0ks6GfX{EJ25JwVUj^z2)DAu$1J6O&tAV-zWd"
            "O)Y@H`PHALuZkRyb6!#{=yHIvHp$Pz#_FutMQ~R>QL=JX^!_N#I)s?<;_&08Iy)1vDFIJ(PPpJih??8h"
            "bX-CqR3E#)Hh|K$C!`0Idaj5oiO@CZH1FI~|@^0Br>t4VADHo(rMZE&{q3sMlKnum-"
            "5N8d5L7KlOy?sY(T}fzMsw*+UJtr&MJ|)zCxbmZRo*99}q-"
            "(E>qTaf;IW3$WKKCHN807NDj;Lx5IEZ`jU*=R)l5KySn6-"
            "SGSdXDX<m2v#&!7*H>uK0y6|W&q6sngcWs=wYBofL1u3s#pa7-"
            "v_7%&@Dh?9Zx~;Rt@6!8#6r=Ysqm+)eMp|P^k%jW|*idq8sUfyHqd5o)Ezq0QJBqRdUH)Mj6S-"
            "5Hb>tx()nK)p(A?DXL|znvVU6uAQn&RPm_NQEj7&#y)~7^&T?NTB<?OTXkOS@KIEO*fFr-"
            "`v^@UInhKGsD(tPD-znf1^(Qw;QH611%K#8=H{4!D<V)*L#GPB^>_Oi$~fG0i<_u<B}ZEkq{KlAKl}<t"
            "!wzSWZpw&Rt)?zL@Q&M-"
            "j;MrpFaHq|RafRDHP+C2oG7a7sR}hSx6xIsNE8Pw{;2GBUadr)R}=T!1{=g3#BCyiK(>kS^?LFh9}<mu"
            "N1i2w{+{ncmb&fk+Tu7R9jB(Vn5dfjah^vj@G~`k;=JgfHHCAKuM=_vXU#YnP#FAyWw>5-"
            "JxAi?D4K2*Rp!5M_WOpUZ!qG3_NV9)HDwMKdRzhMGB5$SKd`uMm3QL!zJQt#a%<s1)k1xhEA!Nm^D338"
            "qqpBYrSv4|3-r^XXuUR9mU~lDg#NsJ!a*q=Z-"
            "CyQRForf(Pc#E37w=4$}~l@6wOdHJ<$|Ihh(~PK+v3XRx0N~Q}>NQ%Q&%&%I-"
            "VQ?Y_6AG|*Pb2N{?_pHgnNBe$hMj&!uCuS<a@xiF6Joo4x7oA0rqhxV-"
            "+4Zc0QTI%t5Fbsf7E#X;ZFDt#^h{4q9MrWHk+6j^BR0o}D>PWx(1MbZCxiZv^LB|{2m~!RHOjhp9ROQm"
            "lP;L!6;M<iGzDqgcUnplBT^w}6$16v?Tsh;DltVs6Ipk}VQ~siI%r_|K9Nivt%oi%>9NirBN_HxD=&WX"
            "HUchDwx;fwH;#B9}_$~@{z|np39q_t3;Zix`5#@|$5Qn^{a>{!t$Gnen&ig6ne1>w+XDKIrj&juJDQEp"
            "*<*+}Zoc0yUamNmUj{9!qyzi~XebUsulQ{3e53KSlRiw!g+Tf^u`A^l7j>y6=7TSYos$$UKKIQzQ<L^8"
            "DL!)FmtYFo&B8ufvuGft!&IVAqG@^u&qP{8$v{d=*U6h}V{`ErT<Lc5w8C81dCKU$sYa^nHIqx7?MGm4"
            "?s_|{Mxf8+mN){0{IV`P3JhPTY<#r-"
            "rR0TbI@x%EN?g+qP`)+5dP>~APTLsA+p(hLyknTF+#p4XY{ZuU`P)9#oEi`EAofr!Tn_-KJwdopz(sid"
            "i+wn2STYv!A#VVYq$uE#DwD4eYiR{gov9^ris!76+Lm7(`CCx*Y$Bk9$r_hGqW|~?}a$o2+I{BJvvog4"
            "W_2{T4+7*tj$d^0DOR7OdYtosf2{ofSIbExyRMX(c*qLk-"
            "K)qQx%9ZWOjk+i(=PG3aRkkNLqATJ=nTlGfR&w1nXdS5Ni^&d7D(X7nh1a#!?j^{#RiK7H72ayKGh7pD"
            "yI`B%rF<)GefLP@8w;RLPzxE_bkUEh8>1zD-}OzBfd|RWIapofM+N_-"
            ")S+uKqfydTlQrV<y)Q6g?iSu|0B4vcRP=}B@qrP8dtV0VL`4rvb_t;7NH6%J4HbhE5<@Z+^{2uM6ISXZ"
            "Zq%P3-+_U4-L7Klm1C6~6@6OyW&rhR;f1!e)i5qn$&&)@nk&5(S#5L8>Bx7NbD)-"
            "J?&~Gr3p^{zrzN^0YD<OMfoO^2b&eeDuJXiytWBgBs?>&xp*;C&0QE1@3yx|-"
            "EkwTg0o0}{q_1tfVi;4l3yhrmgtshTIm>aQp5fXM0a=@=O>5d}7=thJumEaYdZ9aQGaUv?WXAyNM74j-"
            "nWPD|PtcCIL#;<>L+l$w9IloTw6!NLeafzZnr$w<g$r${xSl6F2T%`_-"
            "cpG+RNM+8_XSXo5Z>0A6s<pmQS0OJ4cV+3t$(=A5rcs?**+la`NCU>(pJN00?LyEs4=zlr41D=dAT=$i"
            "tpR%l+_JAv<RTKP|JJTP;py=JRyLJab(>3rERWpU7OwkJNR$XTeZ?A>zT-RbwJi-"
            "(pxyyhKeg1vS&cnze{haRvRjAE0L`OvbK_5Si~t6sp}G4y2*_#?T}T+7JS{*N(3}wJBJU|jea~S57daU"
            "psaC5S>0F!?l?l!@dOp^h|0)7M1{GyP~E6jg_89j1hs>IvcgAwTJoW~QLQHw>URWnun5Rn!W{*9L!quG"
            "sJNW#bX8pNTU}}sRsMn3tf0;Gpzt=oR`y?R#MubAGB8$;Rl(uP{>zOzCn)C#;q6*TL2SdU9bCkZNn740"
            "18upD(N=P;p<`6djwProoj`lu!#G-"
            "I`(OOItU_!SL~P2a0h4~s?jbS`ltd#$Rgj4b(TypsSExG(>YKqHbR1(3I?b2!O@i3n3CP)wQO=(J7c)s"
            ")c5{f<L&P^Euhw(Fm>`HPgT1FYWAEwi*Xrk_Rx4yc#)*tFw($`kA~L=aL>$aLmvmE_;0+?@6Twl^fw5-"
            "W`f@%<<U}tjMdKaLShK}G;!YyttG-q3Bfi2YV-Fwk5h7#9pp0!8WptxAgZx7?1hrkTEjtQcO(44~)D6@"
            "c3CemOqpV&1FYYIZgMx@19p2h?zu249?D4@K)QPcX3;Z55nILuvA`W0gJjF-"
            "6kRWD60*H|aAL6M#Vj*eAlY%lH!Ps-U`G_-"
            "#j3)*Wk7umapZbW?2x5K^u`?rLp^rF=ARZP(OfVw$@)0Ky#8$!C`D;eRGknCk1hH#S#%xB!em>$Hg4j8"
            "TxRVjFzmGVBAnpqye#5BcihRU&WIUc6M9gCxj{|(f=|sl8LB!pRG7j_+9U^0kAYxla8B2V`DMZE-"
            "4nSn=IfHz}sRXfiBrqO(F>3O`KH}2^adl9}RgCR;rjK|nLF^fvt$HxZc$Sa&3_)xil<`Bxb{yg(&L)UY"
            "2BR*m7!fb=5%b9C7_T!Dj7I`xSs)U;QRNCqsoC+2Z8_AJa}%lAU351D{&FW{e|2|5e5x$vB?PrxXYIOt"
            "D+0Cqn)Hq?rPOXYW9<&}Yxi{`=Tx0?;&xOyJs{^7(mRrsBIi^_InVax{F2ByS*M)tuEi+<IsYxaBWNjd"
            "PG*#IxG(3sM9vvH<;1Y7oE4CBpY)E_rN}vhQO*&*ocoBJn3W<W0>k+_U@t<J<3;sTJobUiF-"
            "k9X=Tyn~Db;+4xQkiyxr|qkT75!j++{Z}SgROkeq84|_0NKc%T*30ZHOb0@Akk5!Tbx`gCpc4#t|~om-"
            "7_Tdv@xS)9oX>0&<?}c!z3JeJ@5iOMN+iLgd`5Q_gdc?-"
            "v0%PjkFO!zps^Wt8(AU(Rks&M$S!c`ow(Iw0rij&~?JMb0l7<viDyvpbP<htAy`qmb_>0Xc^|UTUBe`+"
            "WzaoTGd>M-VwN6G+O6Kj&*c0`3XOiJ1%b_^AGV3Vi?BLBJo(UgY`y7fXqpxQ$rbX%cr|ar3}>^k~Q1#-"
            "<I`-"
            "PhJMfI3DU($==G?Y!V@cAn!UEYPMEMkC+x(ZJqQ$4ilrq7}w6u7r>F<*XpRXo5~Tao3A156C&m@lrsf$"
            "T@*g&N056lZl)Yb;^mGAmyZhoEJJ?ii;FECo;-"
            ";er2SM$T?Z3oENzMSU}FHj+eqC)gNP&^8#PaX++KvYTt7EDRYAw0Y6}x9&P*m$GRT9s@eG}Sq7p{r>L$"
            "+&sei#eK{A9nsqa1(cK#{#)#XIKH@ThxJGB69fy3^2Kwy1j+bsGrO&Qmtl4qCoc9qq*XfiKw;#$E19IN"
            ")c<FRf<Xp!n=XhVv2Z)^Ob;^lHJ>`agoPTn>bU`U{u4j~Uf-mQCBInCG<;1PCa#KLgKRaGJq!c+{W|Xt"
            "cm-9g)C+5F!-"
            "izvy)75QTs~MkLeN<o0EsS!OS2sQ}0h=}rkGU!(rgx)qKJTcMZ#4cjDuYkXiN2g`X#^vxaqc`IHiTKJF"
            "nyP{k%CE^Bqj%=sGm4q!myN)vLMD+vlYIaJ4wx6q+QNM0XZ?2xhN>-"
            "MLOi%MdZZPG|pu)Jzk(I=f%~?d9jb`%eh#$oPR_xe4}HeR0Kx~F8tq15w-"
            "N7`vWzb1t|CXsD91ftD|PKBULr~fOa{T2jt8Fl;uG=AJ8FZE|K%kK}62IrIm<>5yXdrh{p&Gh%E@>vp%"
            "BG@H$|WxE_OX#21Vst~ZYOl5xbBjU#R}j`)gk#8-"
            "_YzGfWp4daM!8Ap7_IO4m;5x+Bzh$leJB1+?k5#xvn<A_<t5wndW<{C$AVH~lQam1e_Oe3CV9PxDHh~1"
            "4N_AriEXdLkj<A}YCBbFFP9Aq4EuyMpQjU%3A9C3(o#G%F!hZ#pa+c@HI<A@`SBaSqVSZW+`lySuKj3b"
            "UVj#y?KvD`S~MB|7R#t~;5N4&|nZ*_}t#9NIc-fkT64&#V_FphYqam2fgBi?Tu@lVDPmm5cX*f`=N#t~"
            "N-M_g?j@k!%||79F;nsLM##t~;4N1S6EajtR1`Nk0!7)M-"
            "U9Px7Fh*ua#Y@J~m@$*d6h(~6bM*Pyaj9(i^bd1+()Hq_yIAX#$Vy1D#Y~zS6j3c%(j@a5bVjJU#M;J$"
            "3Y8>$z<A}?QBVK15@wdhie`g%=2IGh~8b`d@IN~kF5eFDY#0#d}J8ZKt^%16Uz@)pF1QSzl7Q@%@j|J*"
            "R?UCxX?F3%&i&-"
            "Qw`xoYR#N3CNJ_S>CAMK}IZ!P$*+zh_T{qiSDm56we^H%94?83idA|y;(*vie0F1$<tn4%F=Wnkh8ym4"
            "fS@a_P?{NtEQ5D$Q0UUNK`fma`3!a+=YfoUi(krJj|$0O0r@F?9zpq2227788Hq#h2`M0m+|hpNhIt?o"
            "?21SPKkJufs}I4!CU@wN8rM-vvk#d@NT6~|tMN6+wVJ|^hEtk|~!Z38+N(<)+?Xv}+xnUwMN0lW*~2z4"
            "1FW*){o<d_c_^K@g*T&%V>>KZn@7!9-"
            "9VxC#d{EAu9^VHQ(ZPm3%nAa0CZDQ_A%tncsw=shlUP6HBZ!pz5=Elav;FzWx6K7*8YfLVU$(J!5GA1a"
            "-l);$97t`uuqFYP^i-}S(bt$Iy#MGB~Gz<@-"
            "VQxlD*oavKF|{COpTm@Nm~9VJ@L`rVOx=cQzc3#aCaJ=FO_;<9^BG~1Bh2@MNq{gP4kpRLTrrqL1~YzO"
            "8juN!Fk=L!k-"
            "&@!m}UVJdto{h%maYQ0Sa*>Yyx^tjp%1o$HxJ1GSF8*&4iaG6<ewhZ*~Hj4}_WT9|Kyf8YWk1gRMY);d"
            "kGv##jx{*M!#qcmczs@LUSdwLt4sp0gL>xgO{xpv^$<0lg3Of%Hb{hnOP_XdBRW=?%7zfj$8$gi1XFs5"
            "ekw$GawP6lP%onhrD*Xg1JXN6(SN80p(M#+?dp7;O@I@Ztn-rJu206IOy?wIKX;9K6dUSkIDrd`^>WSp"
            "=^i!RxOHFPq?@-"
            "gocS#!N|?>XRlZ#5u<4@8RWYk}sFw;e6&4d)ZG`Yr<<n@P?B18>R`bDZv{^@CIqZYewg1Syi8hOFeka3"
            "0|Vg9*}J`;T=Zs*7;dAHPvMcg7pfK?JG@qEeRglZ%%>Nc55}^wIX;GzI;)<qZ{v5!uuHafqH3%r+M+FD"
            "ohfAS6Ef3X&f(j!Rsq9Wj>~q#{}q@ARH6AVv1F?F)(RTx3}QK8sS~?fkyBP(!1E?RAuC^k=`X^Jye;VQ"
            "eb{6pt#aYsO!-f$yRz8t-sxP-zxSsJVTEK0_q9W3+Hs8en2yTW&zCsn&)^IaiBM{0RC^0^sZMxN8=-"
            ")Eo#hSYVcLkb3XdOa~{w_ytNVN7PL=*-"
            "qxgp+mm+LM0CbmqAJDU#)IT_FlD2*!E*#}4Z(Ys5s%KHXg@j|JiJph)#p(J?-?IY-loka`7yy8Qzf4kt"
            "fL85^D6tG>Y69UcB8hz$pI{#cHLLR&-"
            "AfgVU&yNU7SDN%qE)Js{_FrM8?`+BHKVl*{D4*jNlC+ctaWSsJ(-"
            "JpL@%=rn<}{SiLl39Ye6@`!__uuNFu>c*hdFCp62}kzhTh8S6NLg)sn~y0H_%LR{+ea$_A&uyTptM6ao"
            "B!Z^;T-_)Os>k@+3j}edhp%|;t*+)(wSba73krN5lx0>ZTiD03B6r9r%jO|7Jq}5e^btP6eMl9-"
            "6W6X~FWZZR_Pvar-K)G5=KDnrGdzxlDt~0@U)W6ME6IK_3wY1V6-sZyf(u8?3!CXsx+qX&EJ<r%Dsc-v"
            "Mm42+Wi#KWVpVm}^^_(W(sdr`D?MT7nys&$yNWGSu+Q!`J>1cw;h-N$dY=YHOvs}Xo-"
            "%~YXjUar_){Hfh_Is%ptCaBVQmKn0G&UuBYr;N<@a>_wPR}KLTWQ7`Mfg6Yx&6)~d^0r5HJb2^YQ`Ev_"
            "{KD2olp4230CD*U5vKR1q3Un%Acvk%GKn{WNNO%v4rpAn*01X!Z%y9T;mDfEX`OG2;Z)nvC0VFQ-"
            "}@j_rn6len{iQ`2k;$TP}LRLT7_m3#wvQm326uQE$+=Rj*3>bbAWkQpPr;enm+&ws(I`F_4cmw^;?@yG"
            "1kBB*GWtw|-n-"
            "2i9c5cStquHH@*nXe@eFz^CSx>q5eJa5ZubVw8)<^yiWBtV6D;<o&`xERGv%8jV@W1N%JZ=GB>m@7q=J"
            "h|2a_t0@+N`^;#2ar?Ei2-"
            "a@R_RVa<_Y<ktU!O~`zSfL2k6?YHxen(OzUws0wSZu~pjob;6TUBMmTMuwTCW*v5y5&%GuC2)^`2&|iw"
            "V~Inz1e+SRZJ{x|G^cnz5D;tj(ISt|M4mHDg^yus+m`bvd=MHDg^tu(oN&`USz-"
            "t{Ll>1Z#(8tX~nVk2Pccn$A^@Uaa2`Ea~W-"
            "E3YJc9nErGMX(~8<+_^ijcS%_DZ$FnEY~%JZ=q(nt|eGKHOsY(@I6DbT)(ApBF%FBj_~cRS+47;ucukA"
            "8wlUNn&rBYVD-"
            "~1*G+`)bj@<zOt5BXmg^S6ccx~!eowGwX_o6&!gsc2xo#s^b2Q6!JK;N5vs`!3n4V_2{)6y+NV8mjAXp"
            "D;mg`Q!_b-"
            "~|x{F{vqFJuH3E#hJmg|oMYlUXH?jd|vYL@F>g0)JsT=x;ai!{gCCQ^GtGu9Nsw})n|>4fhsnz3dOzIg"
            "sy=Nbo%&!6L%I~zU9(Z4U(Upx7|LAfq9i1nFf9d$p!+O1hfJwW*G(Ja@W2-"
            "aTBaxEu(+eXawjV7A0Xy0fWz|z?_nrW7c_KoJ6<)VF~mqEFD8<eY$LAm-Gl&haXx%wNFYl>zpn!{j@!8"
            ")94unvE3P_A1I%5|GTxo$To*IfqZ<&jZyby#W;>zt^$_Bz)f)>wmeIL;u}c!PB~!64R!2J3LDL98hT>u"
            "{PutSdFw;hzcCRR*!HF^IKHb9+&&8x3Nu2w+K#SSt-;tul!9tigWxoI$KL2C<$u*ykTMh_%UJ+~!q-"
            "zQa2PvEDa`^?^aGZ3eMEF^IL(Al7FFvGy3m+G`N&bAwpN8nov-"
            "8nm(V4a(Kopj@XLl&iZzxkhA|lWU|wtO*9O$_!%7G>A3JAl7dT>fS32VqIkr>uQ5oOATUOV-"
            "V|FgILSb6l<|Tz44$ytj7&v{oNqeGX}BN8pK*>5No4Btk(@<DUfXct^4Nx0c|u_f&"
        ),
    },
    {
        "sample": "3p",
        "player_id": 1,
        "size": 180873,
        "raw_sha256": "401b06fb6b3756ab0e9a0f8d55eac72ee95ccc54e782da9648b8c62dcc8834f2",
        "research_sha256": "54dee91d10f976179b689bad3bff3c8d83498dd55339eb9edec1d2262183ebd7",
        "history_rows": 1,
        "next_section": "outer_player",
        "next16_hex": "0bbe0a00000100000001000000010000",
        "configuration_relative": 115688,
        "after_configuration_relative": 180848,
        "history_relative": 115097,
        "history_end_relative": 115280,
        "research_end_relative": 115093,
        "data": (
            "c-"
            "rk<37nM0vG4w7c4qeCkV6oIQ9STimDNZH%T0EW1qDP_5tU<?UF5z)(0Jui@kl)5@uJ2nM2!)|<2_%9@8"
            "v0iB7%2}1{D-gL?GVss=lwk-I``mcDK6ucDCpDtNmtnXY1e9UEN((-"
            "Cdn8#a_MQ>bW5Yf5vKlFURHy5t7)o3u)J`Z+7WF;V-"
            "*(X;}E}@Mi;f`TyvDYCNwIqDUk@Nwbt|geVco?OeP{MQR5ZuVRtf$tPp#-"
            ";Cw@G=mp;)sNRy(NUz%DCH~HXIwIN6{*h|>;4N4UY-"
            "~T`X$Gx`uZxjROF|)7<U!&>>9>h85y?~@|+sRZFR;CR-KX1-0^ewpgN-"
            "d&7J&`t6ZfbHjbxUbqtve9?C}w7|th@)-"
            "B^coEH4<@l{6M%Z8Q<hm*v_QoeSqD&>>$>oiN<b55h|Q}Q=_Q%rJ7I&x-"
            "5Gv(D_T`hukESSYJ<`jv3qF{EZDV=EWIN|^MTnpu@C$CDF(+cL7x<1sz`%pEyCl~Pap=z{qn0T!b6(Z+"
            "C9$q7%T;3)|(|uQ(NycI!FX8D!YtVGRl+m6LgCaNPtN~-"
            "+`z41?#Ka)4vyi`1yjmqY3oo7yy@<}DFyX9&dTGlQe43ZIk};5QRrK0%jVKejSMzvqYoNYzu1PalK%GV"
            "Y<>|=v`YIeHujQEus-"
            "W)Wbxp!*;q>4*d2t4N8_|w1qu<Qaj#Xf3$XmGdtGn=S<>FN;yxSOcb$v$PjtM?qjp~oF+qvqiNW|{o;#"
            "DGIck<0?$>~kPo`^)>He9ag$hf%FRJqK^*Z|uk{y-"
            "^TeLWbxC`dQ3O%e~4Moz!VF~a$<U#_>8N64Ni7hObRDNh7_s<=etKf=Z9c9Fk~i`RdP{6|aq=Gvw)Mmt"
            "`v9mTHo>E>3hNZ4OZNWVCJ7&qoPUXGWWhn$QNk#UXaEOPVG(e$_3>b}D1s^evo7v~PY=EW<j?daB;n)3"
            "V@RbEkD3vj#~ujaTu)EweD5g5O4H&+?m%~eKsbCv14x!g>U9Trg5MRA)@Pi@qm*VOjXES{k}Q6RdAr0~"
            "a_+m~OQARi*Ng{reie8sh0ri(~y;NsO)BsTJF@-6l{3R##Arv>=XqGnp?C<<DpnNW%;N-"
            ";$#W<qHm+hPi^?GH>xZc?li!$k6+=q){AUrBzSYb#!Nkvy1(*Hlp^l3mh~)USd=qPNAl01r1Fsnvb&Zx"
            "Xv2xb-"
            "J>6qinvie%TcDVL@ZBW?v9aVzMETfsKs`lHcF?jT4O@`}W)QVk<+?y)?&ipTg8MLfsceL2~V7xojWW1="
            ">Ka36)8BvL(j#t9s~6Fs6g=HN!x)WGacF%Z=d10HiP>>tHNb$Bx%oyD#^TC!jjmu9z&)tKt$<ml;FC0f"
            "O&`{i1`ywMx=%S57_Z~V$<8&|<o8rAH^RhN?CTm6nwkr<g~id-xf$<v&EIbM!ec8wE33Jb3yU7NxpR!L"
            "G=v`F$qw{dBepp;RRvOS~J`_NQZkvgwQZ0>h44cCWV;s>|s&8Cc;u{_rw9j~Txh%q8#p^WHwFPo!1(ct"
            ">RL@b3@@4>GY^^ci(R~TE@h(rPpOy?L|#1n_;CT<YPYq=7;<%xpd^7tKVaI4mD+#0Xr)g=A2n2Y5(op8"
            "Rp<K^_;)xG1@Op@S4Ft+U{Zhnq0adYB%MqV#)@hTFD*BQ(83SUb4#EX2lNhQ{D@hTIEml*5oWiDRbMdD"
            "RPomkB%<2oK*MHuUNjfWQ|@+@4zcjZC;|MHb9|L<J&)mgN7noCB|iDwyO3QTqm_Q(8ZxMb`sV*lsjCVR"
            "i9r&#2E*d*%9?GJLi9It(O&E3D;xaxQ{@%7qzUy&+Bi}#J`y-"
            "UuM9s6?}FUQO63CxN!lf@#j%^&Z>3o06X2RQmxD#Oa#%P&rl4~-VMC=_`4@~9b!-"
            "k``0vc8imdCG+flK%luu%cY_6NOv3com8K%{-"
            "e=szsS7_?U}ViOAo=7X(gS&%>))bP<KILC)x@Pu(X5Wwil?cWoEuL{CP4!6H7$8L#!ZVf8bf4VAcvl^m"
            "0fpiXoZsbqHRgkSeJFy4=SBOkBiaz<XiX5@7l&%E7SZir6&gJ+y*4x5Pl`g+3!fgP{t^C}m^L}~`txY}"
            "7H|Hf!fJjFQP{|_Utm5jVrG1gZ#Bd<w(zG!kXSGhpHrZARkDq}lNW3<1nV=UKLHxKPA8z7nIe9?Vof1M"
            "FcUo?3R<2Z3{6lE+Di8IsL?{AM`Y{#=1=j{oM<r>deuF;I;I?K&zd%q5Ifk>4^Z)1kx`jQQgDdaKM{q1"
            "`4HqP6VBcWfaJdT&+<#;(>j+f)r<asrRjb%c#6khY=<$ML3ae!VCjZgHBXu0}Dv|K;7aOINN$MKxOjPZ"
            "#w#<<B4#&Qj1Tvs@Sv0SGzmTMSexrX!ba`u;-A002p%kff)E&4{!&MAj-wdj-"
            "G2mA{}M^QMUNhIlS4vB*skvOHJ$eS3wYfzg|0{blVw@XDL9nC!ti9t~;S3i-"
            "M8Bu?G7Nb8jo6#Sd!|2z}<>Qr_$0*}Z80&sMBd-OFX9Is4J-"
            "x3K6(V<`+t=ajoF=*7#PM>xvYwZVWA3{#8ZQ=4K3vL_7sDkxaY+_kG9Aau>AjoN_Ep_`LCoqx<@3E0Cm"
            "*5~z`7`+0j!H78o;`QD_GG*BrjzQ?);oFAoB~Z09LU`{gSa<zhbPfe=?TqEyi-"
            "a?E*!Pm*eGlHBsYreX|?CB5}KFbhD{;7rE<s?1=)=R^%@(HFfB)arM<ScxB~+#V$q}cdd8!m*dsMZ2-"
            "{>cr`vy<ajw=&5@T2+<sS#FBP@qR$fr9Tve`%6XXMfz`JGh$`d&a<CP~;`Gc5(hb1Cez$as>&}A%hyc{"
            "pb%LV-0YPB;ib}JXBJ;63_m$1#-b=o-"
            "%woQt3JEsu=(h?!I@dTZ^iA5r}D%%5CGNQcPoR+00>fGr($II!LYe#owuH%(0yxdM;=ksNKxgzb0x^nF"
            "k{pyA{X#6bg`r|%12@m>pf!ko?csX8fEx^@%WO+5ejj>VPWb1f2UThmGF-"
            "s!r2KwfAs3HsF6D520J4AN)j|HMaBu2V1+VN^4hp*NfyIC#k#?@xet09N-"
            "3kNaTzVK#NDIc%dJiLlTTT$3Q&BiPLavol5U`{J|hl^LS&Z`kwmy1M;ce!{Kv+=4!CtUVMx1QE4_E7He"
            "90ljT$7t=LbiQbI*k8hxD*}FpaCWp?S7?U3gzH0&m*eGlIbM#JX`ioHB%bGrbrdto=y*9^O@&u9ZOm?>"
            "Oe9A|??%A_7;|!E6N{UONX0}s%hk9u84;|nsK!K{ZPI|m)NHZZVz%?{F4ocLKI9V4)^ClX!SS3r)+n-"
            "W&qEP>snY;sdqf)Cjsr!hkYjlE0}O<*P@c`jtF4gdl(OhoGhJ(Pyxjg(cQcXO*J1FSVW~(Sl-"
            ">J%{n(@PtsF1M%kgr&+|AsM*S?9RHQ;i?DDHc7vD$sBUwnDf`E<2;)IGD_kF;>%lE{v=Io@+koMUv?J+"
            "F7TJ%P>g?0g-(WW()3>Ef7<m*ZuMS5)Umk+m{9UKY=9C*L2NVB6R6!5(-"
            "uAYVtpCcbhNZsy^|UH5zR6`bCix9=mV_gxwFz9gc0-"
            "`S+zJ6_*f_oa+_|1G*I>tC)t_8~Xk?~Tvbh<sMv^*!KH@Rf^myf@=-H(ti5o)>K}uk%w~Mee$cKGX<a-"
            "5GiHW8=kHU+EO|?U#AVm4^D_;`LoJ=85ugv%a4mH)TrYg8E6De1%Keer&wBTQv15UyEwIqH0k`r0$1_+"
            "}ADWgskuAQzQ~=_E4^R^MXF~V)XQ$v%b<$Uj;Am)E93%mWb3^WBrlSsuRM5g(&K~19G&;{fDvoYQ*Wq5"
            "|RHVkA4-1)Ag*bS!dNXp~w!Wb?$gMUQLBpbBNkzot-mP6btX4JoC_0(M81G;^Ng(#NRe%V>Yi9hI-"
            "e%5Z=FdqNCW3vGshs;_q<T<dX5!u2Ei%+8MBm@phLz@@fv_YE+}P_4XfyXt9AS4j}FDimDADvsS+v>~E"
            "tz5qpnk1q*q_H*)dnC<@-?;?<RnR})&fbvv6Juja_h#Q_{I7te9ygyR+6-"
            "QZE>B_dj1vQa+FMZN3ZaaB)VtufBjau5rzI?C0E(^4{$C;JSaylSvtJId=K<N@On!gPJPtgdye{YugDd"
            "pva?RbJ)Dt8;eqszhD~H8EcG-bLJ&aR+y2#$DH4-"
            "HDxjRIUQ3``q+6^Y!I!Kz02wQvI>3J4uukr;;r7AsMMY<ko&2FUKnj_J85&#ez=bSk~}y%qcu@oSSRwk"
            ")1bpP?Lz8L_+VU<w_A_<dtNquW~#^fAYAduphv!*Sd8+SNGY;s}ZqUArdF?WNXA**`mnH-"
            "L@1dUJc&UjBAFn1y6QM#lzi9u@5rD@@6S5iex5f$7|oMZ@0#CC#|wuC!(6Eyd3-"
            "EjI<jk9Iwdpis~)GQSIB9w;=Zot~H7x#+zAP-"
            "*&v3hTh|z2ZMfX<L27IY1fBbeAV%Cyc{pb%kgr&952Vq@p8NzuL#{1mt^uE{k<zkaq%h@g<I1Rj9Kj#<"
            "8%7u)<s2vGgf<G+LV4pH74r%kh?KfB);KV=j+0_7Eo+Q?;A3Hg)e?y?woX!)O*ewue&sr8?W6MZB19ZG"
            "{;-eBQdV}>uJ;Z@~>LikLmV+J6?`gLwMzf%u0aT$AmVRG~$&j%)Jg4;-"
            "bGI<?rbm@jd+Bld*dJe&4<F_xg)c=|sgI=($y^dhLWS>;RG#6^(%U&R6`fJh^R-"
            "Dvy_shct?Sih)Xj1_BN8grBUv7@j!AkAi0hsQh>#d>9OL8a6Qe(yK(3v|8tWsgZKa;b#@l(?A>H*CXMH"
            "<(Ug~D$vCVAqr5*PK6)CfN+oh*+9$T%bkG7MesfeR0gyaKA#W&&|)HdSPQg72Al@~wE*f4G+c?_9{!es"
            "=Sx7(0<H3D%VnnquqSw_YWO(<Xet1AgXbEcTYxqJy#oUG-2^|n!iSUbU*LaEhW|YR-"
            "X8$Z*6>e9q7d*r7M_O#eIWwDI>6sAz}krgnzt3`OZZ+(p#9-*U4XX3`;PGJ2!HDX-"
            "&+cwd&2X5{C}W!c=`uuB7El%_}fr;KOX+R4c=G6a}v-"
            "Lpy@!5!`~i*?|lI8w*u`1`V43b&?i8{L5{IN6M!ZHO#+$%v;t@q&}yI;fi?h*&Jkih0RI%I6!l{r&@)Q"
            "IpHeDtJkaMrt$>E8S}cJA^Z}X&^f=I?K<BFpD^xvWBT#?%-"
            "B+rTmcjEC5md@a@O%WGi{QBus2|Wr@c9d%RWfL^=i#{;=mns6fZhdq4`_o7bohO&1fWeon}N0feW+B+1"
            "BwH!htDPO><!cxs6WtXplLuefMx;B0eS%F&p>|xT7nG+Y(9bK4zE^+>}V@?LNC4<er^G33%~jrzy}=)A"
            "MSz=IU*4B9vKw070|~(gW>b*Kt14ncc8XFRq**W)j*x$^UFYo19gJWhr)9RYBkVtKsf+%3_OnpDgxRMs"
            "2z3{)Oet;fsO~-"
            "3DgGYD6CNUpJnju1<&^Id;<7Z!22qo$w1S9W&+IuS`Fpi49`!2zCg_e`Uq$T(0Gu!5~vzzGSEt(=YiG$"
            "tph3pzSH1&DbPlsF;EFx;kf{`b|KIOKz-f-fE7S}RhN1W{;3x{PgFzj3ix~+JbS9{_N1!JxaxX1xD}{*"
            "9=jKIWwb(YtT;i9`}0xj)gbr*&<3EEK*NBR%AniMh35j)cAz)m^LBWCi8B>cPz);?D-"
            "5U)P(PpnK+}O{0?h`R3-"
            "ln+LqHFE!BDXf{=XkkPoSHC#(Kd3y<Ihk{1yv=Uqi8$Jg;2MAO(ZfFcHoS6IDfYCmOg-"
            "X(?(#3}*lw2S%%sOYSntSWb?Rv3T5X;D4yb^CV7DZ41?O98PqdR9)f_k3%{R+c-"
            "p{j^L1b7wKqiRj25ylou5~jzb_S1~z;@VMrt|p2~w^A(iWkgf?$+IJYaff%Ry??|PBBIicW636wOTR2t"
            "ksU&m0!k-"
            "lr(Ld`1$#)=>%c2f8eRxlcNIE!>wM$9rbb(w+p{I>K&4ZME=kdQcZ<yNb{hSuXmQEN|CshPQhsba<A*k"
            "SQUjoJmZ5_?un+;3WJ5Wf?5hzSDOA;zcm<U1iG8uOk!RS5H%A3~P<?e5#+I3*pSrn7{oo%?Z~M=S6XHG"
            "kr~=%F=*b5J-"
            "Y6bR0m@p7Or_yfyutx`Qt;^Zh=t`)WBe`xlHhGb|kVuuc==rT2B4i#ox0Z<v30Q?_V+>XjS@j_ofO$de"
            "c@Sy53d{rv*)RS{-22;<h-aM(sNf<BCPm81V+FDueElCju^6G?#QhGrLy-"
            "p2Lo+w0@5uGP=k`7U(DVn8dhN9_-"
            "rXV^b)06{(=A5@gIS+=^Hvui<C30%icdoC#w`4TXM#%@M&7e;zH`|k&G9X8J#)hv8fvSBNFZ53HLa#0K"
            "*w91!O7(`&o?Rx*csv*ez(Fk)SY<D&alsQqsnd<lHg&X9BGakXooVVwzx*BU%(uBR)Qv&M8{L>n<;qM_"
            "?#vYB(o9!w4LabPl@q>AIpUuxXB=G|bi&6gN4!!w<JHO`pR646mC7l9UODD#lyi=54?5-"
            "xlyi=54tgb9l{<85D>W}*GwE*5x4AfVxi_JULLG2)pF#(`p-"
            "#9|j(AKt<2l43@1>mbKFTrgr=0Tv$~m8|9Q2vWNuRA8^|{Jfe^5E>4=JbpVdc1^LZIWmT{-"
            "VN>u{e8sdpOZJ@|oDewm6idBPYR9bf)awWKHVFpP!vAeyQeG`L4O|LFLKPXF*YnGUO1M_Lib@+jBqdKG"
            "5_s6rZ1!bnkn6$M(PeD>p%pN;<Y0_EeH8i#Uf$Dtck7%;4jm@4Mny<ipFi(09}x7p-"
            "R1e<GE#MI=ls2=gmdK#6RiG*<#^z6eA7fQHAgTwaS%v7Nw6Rxicl6k^R7(|oq8WF_fEW!OqEhbP$KVL0"
            "07}8FRg@etoLB-lk^+D;oQ-SUHs240i0POiHoM*@{kUq2sU~!4;^@O#yOyH_XDvU!}ixZ{oLsllORqDs"
            "khF|5{T21m_=r(#qhHA4WxPkTPsVCYMo~g)}-"
            "^a`9Kt*fPn`#I(r!F~ttEAje=f~KY?4Y6Es2t^*_T)xgsLQ!jnLst|$&KiXI8kPzmaCOqe+}9MD*9sb5"
            "HAyTl?cM?#%lLx$hVzV!yk)awb~nL2(^>mrgtdc%9!pRh<p<o>IAirVQeh=UR`~(EY#i5BpJMy+`PRVi"
            "^8bjKh<#Po6KmGbTed)_<Zltdd!_7*bU%~FocT!kUUcBF}U~TWRs}qVaek()B+g<UyPw*a6)28hNAvR1"
            "YyFOF^L=X2grA@)~=gXOueSBa-"
            "*V8D__@8mx~~@WvqsAkxCw;wQHdaR%DIMH9thY+q~UJiPqt`6ncTD#`#8x9*Ejjp&mj;i6c$+98_0%v?"
            "gl{8H6g0p<*aczO14CSq8yTW2m@!QWj~bEmcV0SbxPZrtGBkoO?vDEMGIraijM3Z3s=)R%+9lu^PtUi`"
            "-8`P0Ap2XKbd!V2M0jL!GGhuX)vmQ2Xh2#BFLl!Wd$I9dV>uMljZ%xb!KzX*Jtg1`8L)P;os^9;>15Cx"
            "fLDW2m?lM1HNI9w36PGZ~})Fvd|Ik8sFVb&UG^o9r<dXp@~aS<ex{LX@!@MiWpTuc0Q?(w8w*wB+SZ4H"
            "e&aG%2eedT67ewo%J_#!zuvf;>t?#W*r<{W3P!_^wS~%?|#n3|6g-$$AR%U8c!;wG0+cjiKU-"
            "hU}%u`ZpOY)fz*^Z6&h3CTlwxghjk^k-09xH8%ONr7g1d*g`lqwG-Ni*vaEV^`jq8$lXW8gf456QC2?|"
            "fjf>6bv!{uJEA5s5L00;E>u6NRi$M8J3&1pJXsN<E|+|$epKsmh58La9V#?g%ebQ;uPM~k1QnNay>5yN"
            "e(SjUM3ukeHB+~l?ia!4*BbrhMx2F!OSHavm<kTp=r1?wY+cUNMX+lj1F-}1=-?xMNZRrqskP-MMqA0Z"
            "h7MIVJC>j>@wE25i?O%N3cvUhS&P_8M{LPB0;a>7-"
            "9cm=EXjxvS3xE&L_emqTA^+ssITi9bOfUYofOLXIzjB=X>xXAl(Sd(#az;s-"
            "90kuA>wP2chvL0m?DU6b?s@*s69QxTKzYv)hemUIFV7t4k6+LM8?;2#G%}CNq038yhh}FT<;}^FxG6xP"
            "|o{_oajYmjClJq*6g4VaVwGW<<P1Q5np1Iv1f?*5Rvh4UB(WKGWyY*A>pAJg4#)M%fkilNFaMC)HT!^("
            "Ph1dQPytZ7k3fFAv)sW9&hdXU+hb2_DEfWx-!;mai~F)2;y-"
            "%;>nDNCxnRS5yYIBh8T<SA)Xi_mXLNlMwjsbM$PFSBF-"
            "Q(9<3uD$ylpD3K6Fg#3CK>SVqK>5OF3!+)qbLF(UQ}5vvJeJAHQkf)TNIh&YEJcGG3dXG9zjBF-"
            "j=$Lfe%84(ADh|>w;*E-"
            "^tjH6s>h}enr$K!RxE{y&0<PdQhk#VPvxSdhP!6BkYWNf1&c4U;XEJU14WISp&L`KaS5+Y6^h<#&Pf9%"
            "6Jk`E0LmlMQgx{OO1+wqhT@hXDYOP{TJGRk;ri1-"
            "viY_H4sK4Uu$3lV1##3%HqOFKrypM{8BNbeYLG7^kO0%e6330|vm1!UChc*eFI9?H3n)a*988v=j1l~G"
            "^)-"
            "4GuuOZg&#T4}O&eZEy%?Y<&|qe~gJTgh0vBf{E!mB=~8q@1`NRZi37{8R=<vNGhH!YJoyp`4!)IVYKv)"
            "8Dl?S(Ec^85}{&kaH5FoFhXy|3&1SZc<JRyULlGoL|e}XkCV!(;4MFJ(TlnA}400$cVsjzINM-kmm(a{"
            "S1$NFmsGDh~0U$GJZ@)K1AHcJo5RBA11Z>xG=cOZmwRd7-"
            "xRW<T~|_b;QLg2a_?xQOI|*)<ZD=!e+gPe8AX4Mul>oK(uG8NjZHT*`~>Pq8A*h&Gfw(<tz{7`~i`3r%"
            "5@_K)#=9a-QS`hlVrc+{q~C8KIoriJYIAl=DpF`-"
            "LXw553?}bcURtG0J&nC}$5M=N6N@IYuMjk2E<)dO>QS4Eucxqnx8dIZr2YVkVG`6@SjxJOtdK$%&Z@c7"
            "&+mehPg5$zH(k&0ger;TOw^oVbnH*l7}fUvX<~J$j56Y-"
            "2Nq>hEi7siB^&4rv?P*LIdZo1Nta2@8yk3S*G(__((B)C*E1WQ+=98CSx`gmP99Et+6bPTch(D>XT*y&"
            "wfdhMW@^<vcr-a}tqrqDeV%6Qr!x<UG#{Qe0%nIgwG$b7~@OM9xVj<viE-"
            "$22*octHw}On;0~&T~UKrxH2KsC~=rr_9ku1pI($dW`M&AM1Pcs%Gb@WEqG)jiUM<J!8#|4dt9qYSz!7"
            "MR#u`7$a^6hKN@a#1$rWb{z6usp;(9UXX4kLuXeo*6g@Y&U=WQt4zv?+YjaQnw<A~K{}lbIae{tIX;y0"
            "J|gF8lXBuwPq{{u^N(JTE+|9J)r@jZ2<2Q%<b2VjoVayXuG8fFlNY2z%8>I#MmZ}&IqxTOV*U&7owyk}"
            "{jqIh9sP4-"
            "h#Jbdfl<!Ny80(3U^6ztW3Ebx>D{QD&w4858;yUB&f$}DVkqZI8o`JgoI7`m4PjO)Oy6a!r(n`1iOInz"
            ">PKFXFf5~|%un#uY*i@dR#LM+H7@5uO-_tuF4X1xsR=o^5jin6jdyXvj2Gz3c|jd=UJ#;&a-"
            "MHm&Oaa+zA@2Ls`Q?M3;%ahL?aq>uU4~pfO2n$8rJOHCTcc6R$H_88JBahCT9VlEY{_`&xD+XM9x3yh@"
            "5*%YY_J%h!5z9hYACTZ3yDiA)+ww+O3!P9)oqn=d2^HwvPCMb;K8~Bd)cM_>y(Rm#rhdVjb}{>xgeyM|"
            "{gV;=imTeq$XGPk`D*l-"
            "3br))7<I5%a7g=37TBw2s)uI$}HPh(Acd@2n!8l(H@353S4C!@7(;t;<+qUB=$l5&Kw2EVGU{#5&?o>x"
            "idVM?BR!;xOxo!>uEZu#R||b;Oa@5l^>{ILbO=xpl<R))CLLjyT3TVuf|YO6!Odts_=hN1SEdUcJG(Z*"
            "`M(#G9=n-fA83HtUGLw~lzbb;LWZBi?Hr@sHLK7h6Ys&^qEn))61Jj=0P^;uF>p|I0e!RO^V-"
            "ts~B`jyT&o;vDOU^Q<Gzw~lyG(zb<siFL$Fts}P2vE7dU&b5trV4iKn&#cS%g>^*FdacH-BPOgPrmQ38"
            "T1U*cj@ZUJVms@I?X4qru#R|ub;L#15wEn4c(rxJYpf&wCeOBI^;_#QUS}Qgdh3WcT1ULeI^xOJ5%Gd4"
            "{|?)HOnrnY95CrFCc(tin}gtM_{U;(qxL9u+ja`C_{A)enEeZLJ7VrbOrL_Ox(^Q1uD2KbS8nRB%CP*Y"
            "awQ^O<h)S^3A^yGm<S2e7Pj-Vql+LD0H$cfR2i7K0&g6-NCbC)VE%E;C5Q(=Ft0hD%fPD-FySC3zQ8mT"
            "m`DlJuH%vDR(O<dEzlD9LK}sSX;SwGY9WGTyTeswwO4nhVS<vEfSwhGE}Ry%hxpou^<xN&-"
            "eNs5#7d%8;n6cZn~w=PFe~;gK%0Qh#I%Z-B^vXdVkTw0eE{zQI6z&-"
            "h?$2m4>{%o#ys7aGZ(9^gSv(dFGj<xwwPxYGrwY%^e*b^r;h4cB+ToHnKm)^C1#_<%-"
            "fhj3@;(T^f#Dl9dl!2VsK2;jft}{l{F@p#^lSG4jB^^W6EGm;)`i@G0`n1g2hCsn7R~Gdt&NKJQ{`v(J"
            "(h7CTzqkf|yzmv(I5lI?T3*Dflo;8>Vi<v|pHy3X@b}z9vlKg!zmx$r0xJ!6ZPK4+oRvV6GTUB7+$}Fb"
            "&8AMVK)H(@0=O1x&MmiM=o#3g!X8<Nzhu6V?Geqk8mHO7XD+91rw4P%9CnNyU~b!JD0c<^f^m`$vJ!R}"
            "E9BMuUw&{o!|Csm53a&sRjy0C)kzBk)`V&y_%{RGzcv;kg><1)%jn?*P3E^qvfQ>HC-"
            "?3}_S3W*Kz04}m@cDuGJv4b&H?zZYDSHyX3B08Im$0W=F}j%Vh`VS?y3_HnN&=tk>=8N4LHTM}lhH-wc"
            "USZxS@69?~d3D(o39-lEJTOPq1K=1|{!pkRkIPUxRYGbA(L-"
            "k3M6yhA?4Gi!K4arwX@Nho!1_jwqmKnlpLGXr?_8VacuO-"
            "17Oz?&n!fQq6XIWdH`%5!;tqESL)*g@@4B_oZ@K%LcH4W8e8-"
            "n!`k?nIscx?$D+HYQQ&~_^g;k6@pRiS)wyrUcMR>J!jzlPzZ6`tnBo2oEL1YTiPrKWMb;03R*z?AuzQX"
            "UhaV}fu@=!z*;(Z;}}N!{Oo4=Y4)$p;$2&&l9olM|JZzd{C=jP+DydQyRfseqDdT*9#)jgfpc4x{zA9q"
            "(I3UBff<SRkNYKz(pd2O0o09cU)dY@oSba1jT3BlF?^7Rumy1#~n%0NSAXET#ruDg)=EA3Wy*Ex=nFfo"
            "?+k1n5meV{m8EF6+pc@rI~PF}QXwdF@TvsBQ2J!COJ_o@T_Ob12%6-"
            "kJdK1Vi<C5W#yY#FMuevq`>B@XoH4&j{AR1gmweeNcPN6Jxtk+u(Q&%cNcRIq@??td|(&qT?>kpMGW&L"
            "+y14!5TvP+E60fU`E-"
            "fJurgc4I_BN8S$vSgMOcX%ebMs>_V{m7{)r3V9g6}h=5<smuBz|BY2M+mhEtY^{8R2BM27808EaJT?rQ"
            "AQlFO_>qvrCNc<*xO>GOten$PKfuvuT5xfD6c+?NYSdB>?If`KQH>@K^6RfWc%XJLFLjOpg(^8D>Mg62"
            "@wSILCR(D1$>QiIPj{0QWby!5>A#!)Q+DksUsBe3cVLR?vg7rvvo2?<N;|SKG8hdz?57);K=J5n`CGl<"
            "FByIOBqfS!a_Kn){vBoZ5XUKnAQ3uvDhJ2^KHEp*g1CR5<?%^WyT5f6^bEl`H2_j>L?eNnGRxiVHjU;?"
            "eG>mmR;d`24tWi|&rCF?U!uPnEu{cI!Q?joi>@x`8o`&o6Ov1OFVXV=F?~{hx?<~SM$FN*u2;aD2tg{K"
            "<gkh|62;U^Zs=2C*(e^o)U=`H*Gc{O+hJ2Y^!*w{8@O{j%&W|H}^9{>2p76~xj5UGq?PeIOg77_o*x;c"
            "a7BlK0jT0AXz96?;^n!(BEn>~Dja}8$;XKB1gT}4;)Yzw+Gw>EMwi)#+%IdJa2O5fjd|<fEstDf=hOw#"
            "%UyR>|aeWh5lL+5ob+p$A#`dDI=%t!Z%`Mk?gzwNg<Ql>#7mex9CH>iiTvN#V1zIeQ8*3_!S;^gXo^$i"
            "+48r%#+IU1wd#yASi@<$mw7t0f+L;7vyJ7og7UBDmH0!U=Ay{7+#+pm8zBF8i^9bKnhUJ=1u%0t4*G~x"
            "F=MBrXfMBgQjJ1$py<iyYe1i3kVXO-X*1LwWenzm~GmLd1wWADUT|}_f8^*eZU~M#vbuqzu-"
            "!RrC)W$Z9bt%ExWEkt`1Z%TltX~kUErzjvNw7XNjP)xzS9xZ!eoe5XXLhc<jPUgg%XK-yiW!#c3c@#TS"
            "gu6`E61>0R}#J@hUL17VD&OA*VTk?Z^Lr^hQ^5u%k^8rx36KjuBE=7VY#j&eES=g>w1DUz_4655Wdq4%"
            "XK5cnr>LGn+V?-hUNMl!J27UuA2$pS%&4hg<#D#EZ41s?;OK&-"
            "9}@2hUNMX!uJ8ga{ZoQJ!n|2+X>%48<y)1g7uJLx$Y!<|6*9KKM<^k4a;>G;k(4JTz3<!rH19Yhwxo!I"
            "L<ba+8c(kCKJ9r4P#9sd~Y(0HJ$Lq^WP@dIB0zS4A0)#=+U0}eYxS<$?q)6b)iM9PYjPy_Y$n_hR3M;2"
            ";Uus<@zJR+G$v>#e{Fim_6NSVHk_*MoSILq;9k_EEm;{)`sPxy3xm?TzxId)z6|_{VmEhz@l6OEy^|7F"
            "c!^WFxz4s&aqgBzq2UU%@*al#iCrdT9oS!i}UiRxV<_ow}^E{++KT~X%TCz#X1~k5o^4~I-"
            "Fn;>pY8fIK?8?WQ%n;)gsnqhU@T81nY8(SXWxay4rAiQLO7NVm+*3NrPBREMhISi1oBZJ$%L@)(VSQ&s"
            "x;^2Q6Z)vlzE|*`n|8mPM?0En>ZA5o?o0tdA^WZMBH?iAAg(7O{3(#QL{ItivqY^M_lsv5PFqb*x3Xer"
            "Qpy9v0;~J;$D0qby=gu!vP*5o?A;teF<Eer<8=z04xk<rcB7u!yzDBG#1_v97X+b#<0voo{j6xZfhyV-"
            "~UgW)bTti&!fyVy&`>wbmlms}`|pUeZqi;=lYi{||`edEW"
        ),
    },
    {
        "sample": "6p",
        "player_id": 5,
        "size": 180863,
        "raw_sha256": "c188593e9c477b86de12d461a8e8224c5fb980677127fd452b732ddfb8a5ccc4",
        "research_sha256": "e9f6376b4ec219b916a2fc5b1288f12b71e7c1930b70a287b00e3dc2f289e83d",
        "history_rows": 1,
        "next_section": "saved_ai",
        "next16_hex": "100a11000000dd250000de250000df25",
        "configuration_relative": 115691,
        "after_configuration_relative": 180851,
        "history_relative": 115097,
        "history_end_relative": 115280,
        "research_end_relative": 115093,
        "data": (
            "c-"
            "rk<37nM0vG4w7c4qeCkV6nd67g7#tFjsiVUaU4$U+1}RuPqBmtEw(L(q8T(qJ_4h>7M!b7(@MF+worJz"
            "tFP<tc(9f*LjEKm`R95s0_Es_*M>x2D-ucDK6uX13?|tNmtnXY1e9UEN((-"
            "CbQA69@GQzqYl2eiA}XE)pUnv420({{0{A*MGua_V1V3Jn`G%&sOmA|Iz={c3$H|xk$W~VJX)*Q7Mvpv"
            "Umy6YF=rP+RIh03X$5!Cu8d0jOBW}nfekf<276K6sdF5eC2wFOU5#hdY7^8-"
            "{a6PPYehBl9N<@eNdPd#VIbvWkO!iz_^T&aaSQPY+&5AdB!bNo$=7z@r#;K9ntdUPQK4ouC$0v;VD-WL"
            "uRXo^6>(O^J!_8VUBZJ@VmzcS#>X4TP_?<64TRs?O2!QlkvlhscE#;?a0Z?pOQb~n_`l)GLbVo+9|JA>"
            "qI%UW61)ZF{fM%5hV-"
            "L=5?YqWAx&5<aD(b=CqQfY1fBxybsl*dvYmHAF4+?hl$rlQ6ma2<KZ<P%H?fmG~M@Sm}IOF@=C7y0@M8"
            "}MteexU?~@;u5JWl-"
            "}@#<eZ|BGueXrjQoK4PdkZg~3B8EkqBM~)C4JtFM!vRuhfnho*D?kYz8gKOc%!Hih1c<Ta2uh%3a-"
            "yESwOu-"
            "@ioz_uR0thZ{Qgv>!9xCjX7bpL}J9{j1V;8)wiJ?VMhNEmrm3Oc`FyMe!{zri&t8BKW5a`Em?g#Cir-"
            "@x?I>FW4EW7c$JIT9bCLBMeL`1b6Rq4PDC3b(YFnkD>^c+Oq(i~85vt)o5b%<^VQcq>B!k8eZe+K+?$S"
            "^epO?H^S*TCJh*DnM<iDBM9^o8D@F0|xp>_!iq~-"
            "Q`fpKuf0}Qu&5beI@pA1b_HW6ww{k_o{>mZ!;`CwMnB#akUTz+8GDbwkjiR?GEXqXF-"
            ")5`(8mFs{mrY)rJN()guc)@8TWiYY`7x@zqPiB~csX89SKZp2A)Ub8Tvc>8R~6mORi*Fda=j}*ETFuL;"
            "^xpO*`__OsXaNi^4-"
            "EiX(ghMND4LPT#+CjBDIC8w@7@zwN<H)NNnZeRVEVKcsBV~cs+$I&4kkeeCW_HE%X#69WzWQ6%?g{qEz"
            "T8?ZND6b=#L<+aH;U+@x45#)#ynqqp>geI@ys3{$`BCz7A#;Wb-SiDaKlB=xK0sOYt02_9}do@boEtv{"
            "&~xO5^dl4TiFE=?Oo+!{LK*3c2RhG|?^qtWT^m}o>cG~}HrTn{5|;Yk@LUX>zI&U4J&my@aP>%|a}I?>"
            "n&5|N{@Gel|tPdno1o#-"
            "FELpZq6H8s559g2&Db%4j*ONT~rQ61h4%jB^ukCrT0#p(Q(u^v<1oEb&03#{UEc*dN*;E^P%`Npqews9"
            "3ar3vn^vExPkj<iUO&oK3&l_Ghz(=W%%@yah7Ge}|K)npn|Sj1{c3X2X&p6E6%trC<fic-"
            "})N{bIom5J2FIkCCFJsjS3eb{Zr%azrp_OPNBiCCWN+m4szn14jZLK)HVUbaVjqSf_<iC9XnYsRk@Esv"
            "Rb-"
            "!ZnX5s3sIn9eb_f+r5qSKKU;H*jUaFA^o+=kYr>;#RHixiwzLD<}Q5n2Y5(op8Rp<K^_;)xG284$~jXB"
            "+!Y+`4TrLo?ztlBp0u8k$9f5T+i~Qq)$A>cbimV6Bn;4k$9T1zMkRY)lVe;%BT|?7-"
            "ihd!>b%)9nW!HQvkfy@?CjQ{J%UhV!4X{!c||rMTbYY$^|;{7~@(d(>#RzvG`H0cI+);|JUx~CT%!NP$"
            "3Fm&x!hS`-2=W$LmnuJo_&fk9NFre7&~CSENeO;nj9`Qre{=asAQpa=hAIys#Ey9lLq%07u`7q+6-"
            "b)2*~Y;PU7iiC*;XXY`$1IfCinN`)wXjVmR>5K+2|>ws>#DBi)d`J`S{iIO+DcvXtxoqR#y)J<Fm)BA|"
            "h*a&Czw50A6Bl6mS!n?Lh3!*2ZzhDs`;f&Xo+_3r%&xT4|#7a)eL{KNnL@JrzI^oy-"
            "&5ZYB|A3EI@*zfE-)7`>HP5`=UT%m^{EcUvXb+o+{Q7#q1%Vx}=<});V?=5m*SOkSB>&84Pdv;x-"
            "v1BR;RWEej<H<p8SAT_k=G19Uo<(Bt6ZR8vlz=Yo3S0|Fxp=?GL~zyn}-gS4UjByzUU#dzs`-"
            "OFPglNah$j)iZYgq#Ce(g_qQi8w&Mki^Y%2xa!q9{*F?s0o$uzfgI|ZaRHQ1Sw=u(TeaY6x6p9$@{&qc"
            "i8|UrGk<c$y9>>e^a=aX`mhfs@+}G8;<7J3fdq}V(L`UJZKVHsPuo(v!7}5B|84)elkcgJ+OBOD)5QjL"
            "PGm<erQN<WH8O2zx(TwW~UuG=VS&Zcx!&t7dJiMI!<>p7n%kgr&RAP(4(X(@^p<EpX<@W*q646tXj?0N"
            "8{p}%fa2pbo^b|$Yqj$+%4kfV9Lw`Fh5}9c3c}R?iV!4Kh#Qcc*+Y1=|p@oe8&>}{^b}=8X)DlJ+zrtA"
            "eOBs1BV>}!9)#&Mct*8-"
            "&%iX>XXXoVPeiO&b@ydH%E{=KV#%R1)Jb7Q*l<(di{KvdY!s6^4$II!xn}>39ZO#i~R+lNC@1;2T5VZi"
            "-<q-"
            "{FT@ld$)|FhriasKF6=QJc>x==JZ*T>$Dn#m=jOF?kV}1Rdv0VRPEZ09>pvduZyd19_HD0&0yYVX$x2s"
            "0?kY+zoxP`}_C=p#n@yfKRLx*kaL%G2#FBdHKGs?Jsi?hERuN=1lL_6Ts_CS&2<#@G6UM_I^Nin`u)RJ"
            "3yLAeT5xvof%4-5hykj<+|6ts?4kw_JfU<w{qiew3&jHyzWvCQ#uyc{nV@N=ux&bT<BT%7g<+q_-LHg7"
            "j+=d{{3Dc9|sR`<tRkWuXB2|D!^D@0*kz6Y>mM0vS6El*F>xzl-"
            "$m(wrTj_%4_$17iWxt+ky=ga$YMcNm2<vJw#)faEj_*%yG$3wCi4D{<#x538oa=hGHfUEn+@@jt@W23s"
            "s*70(@n&%~2o+XiW1HC&`kq7aK%I5tJkstnJiKr2Y@otQEysV8A(Xl78dAY-"
            "C?c4_N59ODRV6uJT&4M%^uZ29k%0*XEIyA$^tN0q8{<sn5w33&2%C!;NQRCHya+Qk?FLUv#(0Os{MBeQ"
            ";aeFA;9?FB*Uub6EW3={AI$tzD>@VTU6#>6PI6K;{E3`vi!u27?%kgr&952Vqw9i)|5>If&YAYCJbi5p"
            "|T;UbXzTH<;iR6Untr?cUm{TZoEN&tq6%%#k%E6eZvrSr&n3^qCTahcV+B|H>1Nx9#cXw+PjJH+`(Q8="
            "r?402uE#xGgwcp_|7Rn2_cy$%>!e;g<2)EYcc)9(nZqI`|Cw*wo8Ky<@)A_yM*N;6q-"
            "^%fFyc{pb%iYZFcpaKpS}QI$jABf|#cB_&e(~i^=hM}88eeT&xyD<#a7pCH+8pn>CeAUstoi)DZcku-"
            "?5k~iJIdDEh0?__9WTer6tAexk0Nhnbi6E{-%h?dIl;EC<F#gZwIW|f$#%YSmG0o-#a;K!`U+0(&D-"
            "~p)cZ0<y|0X@-"
            "uE`C_m0=c)_s~$?>|OYWy{OeY#(yt{lWNrZP)|eulYUTg3%Wh5%sq@>po8|OTHvkCJHxa^`SQK>c_}y2"
            "pccX`pTrBZ$HCRt_;){7q3r}u}D-;S@4<6lv%TCm$gjV<g;AT4q@ZP-"
            "J+?#^0lbOE2<WCMCyKwD16?6PRN#yKII~@v6*tUm>2Y+r=q9#ob{D~`YL&vr@naGu~MWq8S9Un){}^Wl"
            "~OAvio(ActFKnKV+nY;#V_*cSBW@B&+01jZCuTv$PTA<?sz#~xx%YGL~ZlV&Y3MLg!gxzd1$uiBVzyH;"
            "?+^a|7py|Y+ox3Ev|bZynpdTN3k7aTljdzU*fXKC1VygqrBR*GhjdC?JmvoY7gUTwCut*_>V$#*vb_Lk"
            "al=Q)drAmRiG(*BK8W;3KsH;Z{y<CQ<S{S#jA{sR}QV*x}8mqS9|2;;sB19i|4p;!tsjkZt$q`5)rL0*"
            "(M+6@-"
            "t{0pw+xOW1Oku2o_#Vl&cM=rDP;e_8C5T)oQ<Xg4ajLBc>#T>H2b6U7J|@m7?RPc<Mf?ysD8`@BHRfi@"
            "ZLaW4v0ti?}P}4({HJyROUJiJe1s6L*;?%uF#~U+xA}*B>L*AIscHqP#ejWT_9yNcADN_Um{#UU{(p3r"
            "{bW^qRu5hL2-T>5)_1T-"
            "$=|yoDojB5o21y`NJkMU0VGlBvF`@f7`;Q*vQHfLpJ1>wK>6^OIK_VzojfPUp$ih_|vuk(aw!I#Rq^y{"
            "8%13}pwN?3Rj$yP4t;WQgU>Qd;hAWy?=qZP;7TQN%jsw@ySgQ+YM^$9WkyPB>nX=M~jkgrnNGF>gWP3t"
            "Vdy?uJUoD_6z|KE2014+j0(w#~I8Gp-"
            "N0_^RXOcsX8<m*eGlIbM#J<K=icUJ<%2F3IFS`g>PS;Nq1QrMof_j9DEJ<8%7u)<s2vGgf<K#*}_VH74"
            "r%kh?KfBtGI==j+3`7EobF?^`o|g)e?y?woW^>OJR;*L`y3#%ni5ThrA(?eP}$NQ|rgdfHsR{Hs>>W4b"
            "-yj+f)r8eYXAvr3@uaiI++ZFm(5bFa?|arvK+iktg}Cu2r`A8#RU%U{I@{Y9yCqNW*oeEs@?```<Efn-"
            "fh8=wy66+fm(?p~yd<Q3yNjdGw0pfu2Mpb?(%^R-"
            "vN6KDAe@azHg7B7VlBZ1DwHiln%wWyWC=F2ZNQeidxtOI%kXdC=`JUp>Hi-"
            "FDpx*{P&3F^UF@M8=RZu7qY=pp!WFW_-GyiWpE0qug%m%u-Cm<}H{0j-"
            "h&=V3q{fcgQARpNJtzop>$G|*!}>%GQu*{K0kVlPz>KgR*h2H?K%+z50l&~~7gK;XgK;YS&KI1~Q`{^v"
            "~i-{au@5%BB`|8zVG0nd}*c`VR-A`q+x{QXj_omilJyMW$@?{x$^9RAh^Xb-&a3D2JJw?Xi|)$n-"
            "$JYU8C2kM3gfPkjMcaDO;jfVGA;qSZQeJwm^0L=oL3-"
            "kc|?GNz1*WmpwpnX8^0PO^N3ur9JF&StY&~%^~K(m0>0<8zy0Q3~lR-lOmLM#Q~uL7k}KQ;qBsx<szr2"
            "?k_y$jR{Xq2kON+`e}pd~;L0NoFCiK?(t)ibsM4Tax*pekt%Jf9UorJN4W-"
            "@|hSJl6pY0eS;IzX!Bl25t5PJU0M63G@=s%RsLHZIyuzzlxOrv>j*%&`zM&m1=oFaiA^mxe}gd01XBj3"
            "N#UD4$wTH1we~{?gsiT(C>g&VZ#BNx8S+gYt$h-"
            "+KQdfi|>G+JAt~wuRa9u5l6#^pTma&5eRyx3<}x_=uM!J@cDV5{_wsZP*<Qj`23t|px*HL8K7f<dco(T"
            ";W-Mm8t7!80suJ?o}U9M2RaO>8+H}cc%Tn~P665n)CK4StWfx$HSin=&+hR2Bk-+(_jN!sf#v|s2U-"
            "BM0m{7to^J!ahnfxa2GCxhsUUMLP(9F0pmjh`0Br=?3{(Yt=fLwSplv{tpb~b$a~Wvua-"
            "d6r2E70PYk>x<F7-"
            "J4(?EEhriS3P@cCqT4p80gK~<S?)%9?2D^XKDb}#J8Xo%ogajF{km!j6ILGU%8tw0@t#sICBLAPBD&t<"
            "6XKrh1QJ@9-VCo8C+7*;e^7|<Y~Awa``<^s(JS_rfl=pLYZf$sByp<+4w{}7-"
            "7K(_!*_JRR=k7^M4F_SpIhGH#wUbUJ*N=B+-"
            "BAgkftBUAHG;p`lQq+VP&Hy+LOjIS8++~!pf&w99@wnf>e^ZU;Nt~j(ma6GEoalO~y2K$Khjbjaafn78"
            "!6EhMq@#6Jono+3UR3xv4uPl`*ziMyA(6azstAUKRG}{tn!Od_+^*n;x1a?-"
            "=|$$|gn~;GC}}{cG`Qiuj-ia>eebw~npaAU6+ueur0^rGU^MJ-"
            "7U`#qm^EtZG6V1VZRv>yc>fL{A#vy`tXF*vt;gx2(VnVPGjk79#frtT!{UzywF_z`_L!QuU$odDekbk`"
            "69lqHj8E&ycS1-s<~@0q5au;Mgsk@4-"
            "M7VYN;*zWX9>|b_v1W|R^VG|{=|9FLu(4>pm0nm5u7#S6+mI|2bSRmrFx#k$x(FNBpS{C(CiNl$<ScL4"
            "joR>Rcgu{EzGzApfWH4_&>0?J(YLjg}#8A5K3F%LA7A`s#WHxCl@yirk+{7c~Fg$FkYaa7Dwx~v$EVfk"
            "|GS})d>%!^nwn0qZ*<-"
            "QHm}jI#1{%9i>cDG)vJ8Mbi^aL3BvwC<g@1Id7G69t^2(0$RpP6f~&sVqbl4&1#@+k`GdwK_66ZwkNk|"
            "K~C_D4PTc5)%!4B=$#gYUR&s~p@;T?>J6biyGEMvcrXlrgIX%E%AQi=f+t2(ryHGZ>S(7#wo|P;)6|iE"
            "<`dkRk8@?H8-tEFx-qrNm6@U3nOVxEnXB9ybij8gCw#YZ#NSrVIJ!9KgilqDc&&2A>y<-"
            "3Q#s`8lvDnMa?Cd>=N#Q0bj+72=N#P}^h$Oqcj&B6YF@x*(%qbob8(t-"
            "Z$cM^I^gI&g${UYop7lf@tAVP3y4ELP&ws;lw&?bIp@Qab3Ru&=<}76zEC;pi<Pr}k8;@WRZjbT%5g`9"
            "K*xQLa^Ckf;XWBs?+ng+@B^#-"
            "Y87engfTcezWk?ZNlz4E7z^z|G*vNZaHn$q(eV$R{;_c~9oDgqv?7k>QLfibD$WK_r8J_1k)ok03baD`"
            ">?bQf8~y8L%EvV|4iz+xLpQ51U|1V5Rm{Z)!76qTwbF!dv)!Kvb~LbvsmWnQ3*wnAG%9xx3F9j0Ifx%F"
            "lyIj8hwZzAsX|3I++Y<X^Msi&h$h|jB8bOXg8QOcOrVZ_v07*_q@5TG2b*E5inW>QgVJ}W0^9L^FIa#8"
            "*h^G6&yZgreP|KD;_BA(32SYcz*Un}7>BYJC(77|tW8?0)Hk6GKPa@dn&iLGZS=|w)n-"
            "F*1MAUKPqZsMQ;{#fk5@H;iq@nz+Yo9&Q*!!NNwuNQkFhh^Lqq+6a+Dj|lN)upF6U}x0yVTJH=-"
            "}%beWA>tyXgVHE0v4=!?mtylm9<A_%V=tKF|5-)>qBzbS&%YHz$D)Lwd<-"
            "l2ReW4e1J@=a){)6_zSv9ah=P4&^LP<KO<WaL3|^A2__3ZsI5SHq!iGNVz_*N`>h^Sx8+F+UZ-ZUAqbA"
            "yo8-"
            "<ndaM!R;?+nnXnpOP;KumdGIZVhk076B0u*6!nWD2opApN!+NPN4_JqcHN<3>J5FB8x?(8`MieukO)Fs"
            "#%dTBspN@TyOzpeMb_9{^9AI)+dFWS=p2qqp%-{ooNtuqkEmT0>QQ8rINoH>L3Nd%(`4-"
            "+gHWY0R1D?GXEfB`${;vu3>EiJ%5n|0qYCL8>#rEbl)bc`bEgQF<r`)>Zqze;8$y${liIXqtcEf8A`jD"
            "0lQIb18Jp=aSR#+rP^YW?YhJw})FHYZ@nf|fVGMDojyPT|BN%H>T>6xKwVLfLgM|xYsJNadPts5ilfhD"
            "nF;v_NB0tnnj}XDunXFNN4CAPer#NJ%CPw|kP4*ZJw8`F@tQU%4A<9?{qX{Ta(NGg=>B|@@TJmzAhKlc"
            "dnv~TKJ#^7fyQt+oW2m?-L7t$YVjLN_ei@r<eAi~MW(WUC2CG)aWc@PoU8Bi*oeUOEjiKU-"
            "h8(EL`ezv|)fz*^Z6&h1CTlktghjk+k-"
            "aX#H8%ONrJb_z<U%+$braf%*vsQX^`jquln0K830>ACqpW@`0(TrC>QsV?c0@yDAg01xT&R9jt4_)K7l"
            "L|Jc(NiyeMs`5`cbV16zWF=b+piAt>TV?Jf~1M5L8^w_4+C<_^p#$5>@_$*L>Y(`i%%Szc%PEH{t>WT&"
            "4BZV^nasL4UbX7wU4JBZ6HES%^KDM+YDAb<&o1O06xoGuleNHFUJ9*~tWTm8Z4m&l!8mg7Ax9k&TF*bi"
            "|H~BVZ=1*}X)@k&=uEaTR3ZLiA%w8x-"
            "nJg8IC!LB}y_(CML^&lAM{o+f86MmYzDUo0eT+0P@R9wI&`c}G3}iz$NGRo9-"
            "*jM~#btkr*$TCJ0sjMEuq>=7c~O=NsdM;y&Pm-JI3!E;2;2lQTY6l2Zy4CVX{krTbBtP$^U#+n@wBJLt"
            "GJ`-"
            "BiA>z}FG7bn4?<F!GtIODfQAR&{Gb%hZLr{C^ZF#KV9SLNAg}RYiBf6}2GRoRF{NjFsI7&x6*5j>R|BH"
            "i3%^t67P#I&*R)iWfgCL%)Bc92Kcxs4vF+nVdX^62HAL3~tVkK$E6LlGnVAPy`A>uqD<L7k5;~8u9iy`"
            "7{f>^F2p2Ub)86wUnh==KjDMrLWA!0p2?55Ao?=d2t5h5-"
            "kh<$Y#iy0Azg@_9Y;z>H<E=I)RA>v$u_@R#YKI15t4iS5i{&<Rx*oUz{o*5#}Au{gM5%)04I5I@^h>Tr"
            "y#GZ^YR)vT&iHs*4fXJvhqe8@41aWXo>yLvNNAl4j;zI;+jV|MA#&-"
            "O2i1=NCI8dLh1~AHaR*3j8LF}%}_$p&NjtLPL5X3*~QI~Fvh+hj4`;gu-"
            ")np_Xj|9pZEfTy*<qF8E*{O_eIX0AYGpX6#bT<V4au=h%`nw_CRF?AP1hv*=?fQJ{wAy`E21l2&YPXiL"
            "cE^Ra`&T08ER%BLc2qe>lk;sE9LdU(a~7kVXNPjWL*$%cQci!@;!I7>f6CwpT9%wM808!v%K0xM=UkI="
            "V%SyA*W~<A21o0%<ebYW=Q*LA9}+n+D@9fWhVym6UW6hqi0Wr~>?4_DltJvyYn1U#I`SdnZsw8CXM7*2"
            ")dz&ZU3QE0TE#f?A55-"
            "Oe@RDNsd6wGL!5wocW6BX^Dpesd&p~yJ!C>C=cz<{cA1pZ*OA?toTqugq1tTUi&4(%P|nX2Iro{A^IYW"
            "nwkGH4UT|nQOU`|aa-JK?*^kKij!8MsL%#26a(=-J4n=3l`3|F;=Y?|iCvxsIxtn7m@_j>-"
            "bG#R%2FkMEcQVR3F_iNhA}3}7$y)K}d@Vu1y_%euxnOUI8t$jS_ir5p{K4!+UJ`z>n#hUUh>e{l@%I&X"
            "*4CpZdBHX|W2pYVwvHO=1?rHtv3+gl>$BPUUXZZB*r+fG`A&^%dr!R}MMBo7Fqv^Bd{QW99nqp`CgsFk"
            "FS1sXv)&6*KxD}|jZw}ELOEv;Ij5VH6E{K1dQHxYy&%O!mYmZW<-D*V(njQ*VN%YEe1A-"
            "nbCwsR@W}SZ80EYulyf$bvx?fc+<wX;eMG<yn5M_re*ek7N3UvjiAt7%=yNEl@6j{X?Br0+rKD#43|e&"
            "eMuIWoc4UZn9YI`cQfH?i-*uYK{=y5=&1C89TE?2463Tfek#oICIdS`;d_t4+E-"
            "y%@lO^YRMmeX3a{iLYxxu8Ic+^vF)a3k?7o-"
            "cyl5+#2oYO)%R}wj&GASo+ot2w4Ie+a1>5#JIe2P)dno!Q)5IHgbh4)h2jGX@1wylZ&xh+Hu<=o0BXKh"
            "pc6BDo*8{simrNs1ZRL;jdmGX_oza|#&$vHiga~+Lf#0}1!2gHUjD;1{iGS*WtX_Lg{U=;NYFGv`c)l-"
            "%x_-eK;lyeuU*{>RxbGarb#xj@da(>l>oV$sfn3~4BB4Nf0^yR#?2{|tfQA0T|F)ioM5Ded#=qYu2Pr-"
            "%%Ur<CN8g!RdvqgY%SBM(c>@Q5zY;mlyW`Aj1&Xt;+C4jP0m-Ck<<SZp}{#r-"
            "m+*{g!co;#vTSq)v7(nbo5FZH<g@M-"
            "ry~OtztRp^d9dUzo#3!vIK4l$olXb+Wts_2T9r0P~h|gI^e8D>6KddAE%R1sm))Daps9i*99WiDdF=ZX"
            "G$U0)Nb;MHZh+V8BcC(K7`4s%lD&pxW+cJK^x{Up;%Q(QgjFr}9Ji|KTAnS-"
            "#))7ZpM;vV(@ypf`&$5m<#ya9y>xkp5Bc5#?alCcJbF3pyu#Q-"
            "59dV*{#Ph8qPO^?zV;!;9I^uNeh;`Nx7g)DfZ?^7R-"
            "C`Z_N7fN<vyS*<>xe(Gj(EFu#GhJ6yvsV`udE}kw2pX>b;NtEBi?5nagBAvKUzopFYAc2ts~C0jyTUc;"
            "zH|)i>xCqv5vUZI^yNl5wEn4c$Ia;?gh3H|6OPs@yH_Ei0@dJ@jdH^p7mOdTSrV-"
            "M@(5qEVPbTY#p(Sb;NGg5xZMQ>|q`82<wO|tRr4)9q~Hrh}T<3{9cjm`0Dqq%Xp)8#G9-"
            "m{=hooE!Gjww2p`uO!;@%7GvroOyPh@cQFYjrrsO@U&B9Es2jB>sN1$vc*QSfk;Lp@nA;I^A7c6xOx69"
            "_FztGG!GGnZ{;CbjpQ=_O;ziEeWRS26|B8u_Fl}KsKRdbzG67(UMog7~i7W8Nk;_GJ2MFdL$6SJV00i@"
            "z<GBpH`T!FSV&V%-LxG8uFzq@XiSC3)={5naf-"
            "iJY=$Iz;aG(w%NVYpxRaSR(XBs9bc^c?3Vd%nX(Rhfjdssh)u;?w;(?hHzY84(m!?XFApaZjF-wL!H=s"
            "ZlTh*_dB?<r<d#@h$*E`TG{WsI1481s;0K48q#jX86%+IpyK*zjUB%xa5yW-"
            ";?CW=Zd(u72vNu0_JUo|tJ9b6;XMO3b{C8N~1s0!)8{sn#(!HYNtgG~Jju8&g?ha%oJyjOmauK{2Kb#w"
            "5O&Ru>c9Vj@^fl!~cKF|{YAzQm(pcn}S9Gh)I<%p!=X1u^>^rliAcdzgX`v$SFAHcb14`KT~S73OQgBu"
            "<#m2$LLPz8_2ig!ynVNe<?U!6Y)6@dML<OjCpzBQT8wW>mm53z*mo)1hD<089>0i9KO6(4(qHKdclVJH"
            "RPG?*eraL7G%-sY<-"
            "r31|rrX1>24=n~a1rD`<T1~e3Y_kn7RHSl~^1Py=}F#H~#E8w{fXuZmF_5?gP06ht`1?VN9mw{f9K`(t"
            "3bA$nH2ihTn&h|Rc8$gv%sb>HU1{&%G*W^vaEG$5CfaU=$09xdkIdYgFx{ZC@s|&i(W?=>|N$^&M8S4#"
            "Ur3h9R!r#QfyF!BX2&u<M4artS@P-"
            "k*;fC;v2_BC7{=M3mDalZM(j<jA$9Tg7yi!B*l@dIh&%6;q_LDV+@H!B@v84UR8N%yG@J156QHJn3(fL"
            "_6*5~2U3|?n~muj>JWDi4lhY`H>VOC8;b=ierJxyeL*AQM;f`|5-"
            "R}r+`IzxEf2wq(%UmWk~#=Dj9KE@AWc<F?vdGV$yOcH@tSk<X%94~mm>nkv2KBkn%1n8I`922@?idD2R"
            "Flkc17vRHM5nS?tM)2b@xY*=0W#q4w!6jn@RGA)BU|}ktq#BoStVd&{SdGJI{q4c~R#DgR3_TVIXduua"
            "oYR4Z0nG)P53~?yu@_v#f!@ec_`l^cxLyGrjn{y-"
            "sy>UU!B@+``4|Gv#X!sO)<&RP&^`fr(a;#&o3zVjGG@FW8dD5zI!ImzQ#NWFJWBA^61+zk@#q|i_M^8k"
            "z&q7YeSVtYJsjf6TaDQypCNb`G|FcL>$3!_bEAFGc+C@IyHVTV6b;LyUH2~WGefMW8ReqmF3z8RW)nm0"
            "briuGMf%!kBHKtt*{D4*j^K?Ucw-sysJ(-"
            "JpMT4^p}Ootum%~%I+|cD32%siUoDkp@QxvP4;Ys1Sb}xGVXWf_7RCTfj*Vpm3vsE>%Z+tB!73$w6TPO"
            "k17km<e$#N$ud4{&Fh)G;hhnV8q>h|Gu!b7ek<SsV4-Ct7BEdrcNT1VEjO|7Jq&1CxbpuvEMl9-"
            "6W6X~FWZZRFPU9i+K)Je0KDnrGd%9se?j(Zs`|vhfLs%yhtQ8IR@OB?=kRi-"
            "d2<AHC+rCKJ?lDH4q`vJ7jpJj3UA)<l|FpIVtVa#`PJ<iTZf6!A=Y`#4MfSDa)Hdc$Pe&6(#thrxXA`V"
            "}hUFSh_?~7M>m0)OY{OU+sNPGnSk;8@$qi$1jK-"
            "$qU_;pF621cr*XenLZ#TnO6A9l34Y%L<gl~aixh4_5al=>_5WWe+SQiq$NrKgIRTrb}a}mKRY4m3ruu2"
            "X2GKGfga5CZh2g5o)h43vlEZ0=Rx5zNoG{U#9VXPX$_f%qohk97SsE0I8T(0?o+;Y(i7EZE=wX`vI)li"
            "2^7{?77w;I%7pYF)QTfx|7)UT*&!uB3+C<gMH;Wn!ye773LswaFgejCR1O<>I+e8)7=UgH?si^if?Yd$"
            "r%To)6*qnnUx6r)@;roWi<XA^SGBJY=Ju{dt5*)(P)57c?i&8zbW-xnL>5e@CN&QL4@_nFc5;`VFj6Rb"
            "Uk?VAOJ?;FyrzrKiIy=NF}F~NG@a2+loeAgS6Ybn8c+^}3<A$*@OEY~uEwZSmfa)R}wVXR9C)=P%5E+t"
            "qm8^-z?!Ft6o)@9U=GK_UO!P;UN>w1E<%`ny#1nX79SXWXT+c4Hu1Z%rttgjQS9fq;KL9lij#`-"
            "3~dfhPAx9D8unZ^1x!IGZYx$<hl*E1~FH3TbWSg!97zH!5HtsqzhhUL1J@U1i~*LMllK*MrfNBEv$Sg!"
            "BUIFVtwzEAiLHZ0c-"
            ")YmgC*NuelP{VTFM6iY#mg{E1caCAXen7D18kXx8!growxqe8n<{OslM}+SJ!*bn9uofDY>o&r7kzu)h"
            "Ok;Y6<@yi8_in>-"
            "{e)oMV_2@+3E$rumg^3Jb+2K$eoFZM&ahlRBUtwtmh0z)?<&J`{eobvHZ0ejgzs|0aklBy-"
            "Y|?clkgp27;6sUdy8SLxr8sC|2DbCLF4o1diKsnPxQ?1%MI5~erQpy%PeBOWq6Fbi(u_BJVyPJ@ZD=zu"
            "3r(XeTL;)N%;1R+0%^<hOww_bkwj+>P9ESa#7vrY*;R;8-"
            "py$HQ1tDLoCWQ)S_I&EXp<9qFgf#W6>N23oX{+B8zqSLyL0#$f8`gT9oTHi*nszabBJfw^xVN7O~Ea+i"
            "S1$EMiTzScg+AVokMJhtn)#U2L%qXIaFWX|WDxTg1BBa2@`dU|nMo>spIg*BNdviglAktot-"
            "9X%K6bMXc2pu^zFghmTssT5A#OF^f8Xk43D_7UMS0So9tKVG-"
            "+Pi&(E%#M*8V>kW%oyDVb8Wf5zyMXY@mvHool>llmn{IM2o>~f28on%q2FIbeTzeTyuDX=Hk1dCYHEMn"
            "DI#F}RjYraLSZ(AIDueOMFjYX{QSj1Xk5$jruSl_jXbzPofU1D+E_>D!ZKUl>2vqh|jEn=;+h_&7#)+U"
            "Qsf3=9EK#KA6{{wB3eX{"
        ),
    },
]


@pytest.mark.parametrize("index", range(3), ids=["gaia-prefix", "human-prefix", "ai-prefix"])
def test_derived_native_boundaries_and_all_research_values_match_snapshots(index: int) -> None:
    case = _PREFIX_CASES[index]
    raw = _raw(case)
    base = _raw(_CASES[index])
    following = bytes.fromhex(case["next16_hex"])
    reader = SaveReader(base + raw + following)
    header = read_player_header(reader, _CASES[index]["num_players"])
    prefix = read_player_prefix(reader, header, _CASES[index]["num_players"])
    assert len(raw) == case["size"]
    assert hashlib.sha256(raw).hexdigest() == case["raw_sha256"]
    assert prefix.offset == len(base)
    assert prefix.end_offset == reader.pos == len(base) + len(raw)
    assert reader.take(16) == following
    assert prefix.next_section == case["next_section"]
    assert prefix.saved_type == header.factory_type
    assert prefix.raw == b"".join(prefix.sections.values()) == raw
    assert len(prefix.research) == 1510
    assert [tech.research_id for tech in prefix.research] == list(range(1510))
    # This expected digest is generated from the independent native spectator
    # snapshot, not by deserializing this native replay slice.
    values = b"".join(
        struct.pack(
            "<fh3hhB",
            tech.research_done,
            tech.state,
            *tech.cost_adjustments,
            tech.times_researched,
            tech.allow_multiple_research,
        )
        for tech in prefix.research
    )
    assert hashlib.sha256(values).hexdigest() == case["research_sha256"]
    assert prefix.configuration.counts == (4, 37, 266, 241)
    assert prefix.configuration.extra_word == 116
    assert len(prefix.configuration.raw) == 65160
    assert tuple(map(len, prefix.configuration.groups)) == prefix.configuration.counts
    assert len(prefix.history.rows) == case["history_rows"]
    assert prefix.history.player_slots == 9
    assert prefix.history.death_records == ()
    assert [len(a) for a in prefix.history.player_arrays] == [9, 9]


@pytest.mark.parametrize("index", range(3))
@pytest.mark.parametrize("cut", [0, 1, 49, 65, 115000, 180000])
def test_incomplete_derived_section_cannot_advance_outer_loader(index: int, cut: int) -> None:
    case = _PREFIX_CASES[index]
    raw = _raw(case)[:cut]
    base = _raw(_CASES[index])
    reader = SaveReader(base + raw)
    header = read_player_header(reader, _CASES[index]["num_players"])
    start = reader.pos
    with pytest.raises(SaveDecodeError):
        read_player_prefix(reader, header, _CASES[index]["num_players"])
    assert reader.pos == start


@pytest.mark.parametrize("case_index,what", [(0, "generation"), (1, "scout")])
def test_unverified_optional_payload_is_explicit_without_losing_cursor(
    case_index: int, what: str
) -> None:
    case = _PREFIX_CASES[case_index]
    raw = bytearray(_raw(case))
    at = len(raw) - 13 if what == "generation" else case["after_configuration_relative"]
    struct.pack_into("<i", raw, at, 1)
    base = _raw(_CASES[case_index])
    reader = SaveReader(base + bytes(raw))
    header = read_player_header(reader, _CASES[case_index]["num_players"])
    with pytest.raises(SaveDecodeError, match="unsupported"):
        read_player_prefix(reader, header, _CASES[case_index]["num_players"])
    assert reader.pos == len(base)


@pytest.mark.parametrize("what", ["type", "research-count", "history-marker", "config-count"])
def test_derived_invalid_structure_is_reported_at_its_boundary(what: str) -> None:
    case = _PREFIX_CASES[0]
    raw = bytearray(_raw(case))
    if what == "type":
        raw[1] = 3
    elif what == "research-count":
        struct.pack_into("<h", raw, 48, -1)
    elif what == "history-marker":
        raw[case["history_end_relative"] - 1] = 99
    else:
        struct.pack_into("<H", raw, case["configuration_relative"] + 2, 65535)
    base = _raw(_CASES[0])
    reader = SaveReader(base + bytes(raw))
    header = read_player_header(reader, 4)
    with pytest.raises(SaveDecodeError):
        read_player_prefix(reader, header, 4)
    assert reader.pos == len(base)


def test_prefix_requires_the_same_structural_header_and_world_count() -> None:
    case = _PREFIX_CASES[0]
    base = _raw(_CASES[0])
    reader = SaveReader(base + _raw(case))
    header = read_player_header(reader, 4)
    with pytest.raises(SaveDecodeError, match="player count differs"):
        read_player_prefix(reader, header, 7)
    assert reader.pos == len(base)
    reader.skip(1)
    with pytest.raises(SaveDecodeError, match="does not follow"):
        read_player_prefix(reader, header, 4)
    assert reader.pos == len(base) + 1


# Original452-byte Gaia extensions; provenance: player-base/gaia-fixture-sources.json.
_GAIA_CASES = [
    {
        "sample": "3p",
        "raw_sha256": "46063a73fcae2d7a86d979a5f0b8d159c34a3cefbf5881f132a4f7ed972affb9",
        "first_words": [0, 59],
        "following_hex": "0bbe0a0000",
        "data": ("c-muNU|_Ijpd7qlW?;~mFA8KSI599Z?57SU9{dLahG7Iq@ecqnUm(i"),
    },
    {
        "sample": "6p",
        "raw_sha256": "8e3fedcb7fd83a3eb5e67699c444739f46ce759d9e1705c1905d3a295e078e6f",
        "first_words": [0, 59],
        "following_hex": "0bbe0a0000",
        "data": ("c-muNU|_Ijpd7qlW?%@|AOU14I599Z?57SU9{dLahG7Iq@ecrqXdwp"),
    },
]


@pytest.mark.parametrize("case", _GAIA_CASES, ids=["gaia-3p", "gaia-6p"])
def test_gaia_native_extension_leaves_master_marker_and_count_unread(case: dict) -> None:
    raw = _raw(case)
    following = bytes.fromhex(case["following_hex"])
    assert len(raw) == 452
    assert hashlib.sha256(raw).hexdigest() == case["raw_sha256"]
    reader = SaveReader(b"prefix" + raw + following, pos=6)
    gaia = read_gaia_extension(reader)
    assert gaia.offset == 6
    assert gaia.end_offset == reader.pos == 458
    assert gaia.raw == b"".join(gaia.sections.values()) == raw
    assert [gaia.fields[0x13F0], gaia.fields[0x13F4]] == case["first_words"]
    for member, count in ((0x1484, 9), (0x14A8, 9), (0x14D0, 10), (0x1500, 50), (0x1694, 10)):
        assert len(gaia.fields[member]) == count
    # No implicit marker consumption: this belongs to the master-list reader.
    reader.marker(11)
    assert reader.i32() == 2750
    assert reader.remaining == 0


@pytest.mark.parametrize("case", _GAIA_CASES)
@pytest.mark.parametrize("cut", [0, 7, 8, 67, 155, 156, 451])
def test_truncated_gaia_extension_restores_the_outer_cursor(case: dict, cut: int) -> None:
    reader = SaveReader(b"prefix" + _raw(case)[:cut], pos=6)
    with pytest.raises(SaveDecodeError):
        read_gaia_extension(reader)
    assert reader.pos == 6


def test_gaia_extension_does_not_assume_other_save_gates_are_equivalent() -> None:
    reader = SaveReader(_raw(_GAIA_CASES[0]), version=0x44CCCC)
    with pytest.raises(SaveDecodeError, match="unsupported Gaia save version"):
        read_gaia_extension(reader)
    assert reader.pos == 0


@pytest.mark.parametrize("relic", [0, 0x3F800000, 0x80000000, 0x7FC01234])
def test_ai_continuation_preserves_relic_bits_and_leaves_master_marker_unread(relic: int) -> None:
    raw = bytes(9) + b"\x0b" + struct.pack("<I", relic)
    following = b"\x0b" + struct.pack("<i", 2750)
    reader = SaveReader(b"prefix" + raw + following, len(b"prefix"))
    saved = read_player_ai_continuation(reader)
    assert saved.offset == len(b"prefix")
    assert saved.end_offset == reader.pos == len(b"prefix") + 14
    assert saved.raw == b"".join(saved.sections.values()) == raw
    assert saved.xs_flag == saved.task_accumulator_count == saved.task_group_count == 0
    assert saved.saved_relic_time_modifier_bits == relic
    assert reader.data[reader.pos :] == following


def test_every_truncated_empty_ai_continuation_rolls_back() -> None:
    raw = bytes(9) + b"\x0b" + struct.pack("<I", 0x3F800000)
    for end in range(len(raw)):
        reader = SaveReader(b"prefix" + raw[:end], len(b"prefix"))
        with pytest.raises(SaveDecodeError):
            read_player_ai_continuation(reader)
        assert reader.pos == len(b"prefix")


@pytest.mark.parametrize("at,value", [(0, 1), (1, 1), (5, 1), (1, -1), (5, -1)])
def test_unverified_continuation_bodies_fail_explicitly(at: int, value: int) -> None:
    raw = bytearray(bytes(9) + b"\x0b" + bytes(4))
    if at == 0:
        raw[0] = value
    else:
        struct.pack_into("<i", raw, at, value)
    reader = SaveReader(b"prefix" + bytes(raw), len(b"prefix"))
    with pytest.raises(SaveDecodeError, match="unsupported"):
        read_player_ai_continuation(reader)
    assert reader.pos == len(b"prefix")


def test_continuation_rejects_bad_marker_and_unverified_version() -> None:
    reader = SaveReader(bytes(9) + b"\x0c" + bytes(4))
    with pytest.raises(SaveDecodeError, match="expected marker"):
        read_player_ai_continuation(reader)
    assert reader.pos == 0
    reader = SaveReader(bytes(14), version=0x44CCCC)
    with pytest.raises(SaveDecodeError, match="continuation save version"):
        read_player_ai_continuation(reader)
    assert reader.pos == 0


def test_all_seven_native_ai_continuations_reach_their_master_tables() -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "native_saved_xs_54800.json.gz"
    fixture = json.loads(gzip.decompress(fixture_path.read_bytes()))
    xs_raw = bytes.fromhex(fixture["xs_raw_hex"])
    xs_count = total = 0
    for case in fixture["samples"]:
        raw = bytes([case["xs_flag"]]) + (xs_raw if case["xs_flag"] else b"")
        raw += bytes.fromhex(case["common_tail_hex"])
        following = bytes.fromhex(case["following_hex"])
        assert hashlib.sha256(raw).hexdigest() == case["raw_sha256"]
        reader = SaveReader(b"prefix" + raw + following, len(b"prefix"))
        saved = read_player_ai_continuation(reader)
        assert saved.raw == raw == b"".join(saved.sections.values())
        assert saved.end_offset - saved.offset == case["master_marker"] - case["ai_end"]
        assert len(raw) == case["raw_bytes"]
        assert reader.data[reader.pos :] == following
        assert saved.saved_relic_time_modifier_bits == case["relic_modifier_bits"]
        assert saved.task_accumulator_count == saved.task_group_count == 0
        if case["xs_flag"]:
            assert saved.xs is not None and saved.xs.raw == xs_raw
            assert len(saved.raw) == 262609
            xs_count += 1
        else:
            assert saved.xs is None and len(saved.raw) == 14
        total += 1
    assert (total, xs_count) == (7, 4)


def test_outer_xs_flag_preserves_nonzero_values_and_later_errors_roll_back() -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "native_saved_xs_54800.json.gz"
    fixture = json.loads(gzip.decompress(fixture_path.read_bytes()))
    raw = b"\x02" + bytes.fromhex(fixture["xs_raw_hex"]) + bytes(8) + b"\x0b" + bytes(4)
    saved = read_player_ai_continuation(SaveReader(raw))
    assert saved.xs_flag == 2 and saved.xs is not None
    damaged = bytearray(raw)
    damaged[-5] = 12
    reader = SaveReader(bytes(damaged))
    with pytest.raises(SaveDecodeError, match="expected marker"):
        read_player_ai_continuation(reader)
    assert reader.pos == 0
