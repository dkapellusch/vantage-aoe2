"""Tests for the BC7 block decoder (expected pixels derived from an independent decoder)."""

from __future__ import annotations

import pytest

from vantage.bc7 import decode_bc7

# (name, 16-byte block hex, expected 4x4 RGBA hex). Blocks cover every mode,
# all rotations (modes 4/5) and both index-select values (mode 4).
CASES = (
    (
        "mode0",
        "39b4e652e44da7f2370d9e260e271365",
        "4f216eff3fa1d1ff3678beff8e6a80ff102152ff3163b5ff52f7f7ff8e6a80ff4f216eff49cde4ff3678beff8e6a80ff102152ff3a8dc8ff3fa1d1ff809d95ff",
    ),
    (
        "mode1",
        "52a4a3a6d07f5c0c332f8b1224083fd2",
        "7a7732ff934232ffaa27b8ffaa27b8ff865d32ff934232ff865d32ffaa27b8ff934232ff865d32ff60af32ff3aff32ff6d9232ff60af32ff60af32ff47e432ff",
    ),
    (
        "mode2",
        "2c902f8911e81818f8c99d5d5d983195",
        "7d7e83ff7d7e83ff3443d9ff2963deff42847bfff77394ff2963deff4a00ceff42847bffbc798cff4d5186ff378d9affbc798cffbc798cff631873ff4d5186ff",
    ),
    (
        "mode3",
        "7804d90e945de2e8f54ee781cc75f636",
        "9fab6cff9fab6cffbc665dffd9254fffbc665dffbc665dffd9254fff1c1cceffd9254fffbc665dff507a06ff2d3b8cffd9254fff3f5b48ff2d3b8cff1c1cceff",
    ),
    (
        "mode4",
        "d05099095aa300165a67036f9b540d6b",
        "7d340f408434003167343e6f52346b9c59285c8d592c5c8d59345c8d67343e6f67303e6f76281e4f602c4d7e592c5c8d8428003159345c8d76281e4f6f2c2d5e",
    ),
    (
        "mode5",
        "a00be21124179c3dd9f73817ce6e118d",
        "165fe58f894f044063674e5a894f044089570440634f4e5a895704403c5f9b75165fe58f896704403c5f9b7563674e5a895f0440634f4e5a1667e58f1657e58f",
    ),
    (
        "mode6",
        "404aad6cb6dd210faf94acd3cf92c190",
        "47cba92055ccc41f3acb8f2050ccba1f5dccd41f55ccc41f36cb872062cddd1f6bcdef1f5dccd41f31ca7e2050ccba1f2cca74205dccd41f28ca6c2050ccba1f",
    ),
    (
        "mode7",
        "807cb11f5d108cf25930263938b370a1",
        "28ba5161b200f361557d8661853dbe61be158ead7e234dc8be158eadbe158ead28ba5161853dbe61413010e37e234dc828ba516128ba5161be158eadbe158ead",
    ),
    (
        "mode0_b",
        "b5769fa0f1483f95a90d9df2f130d60f",
        "7cb39bff8ba79eff6ebf99ffa790a3ffff4a4affb573c6ffd46292ffd46292ff42a5d6ff2acba9ff20d998ff18e689ff10f27aff08ff6bff3ab2c7ff42a5d6ff",
    ),
    (
        "mode1_b",
        "ce04bd93f50ae69514da8c659ce2b10c",
        "61c44fff10d554ff61c44fff2bcf52ff61c44fffb8bbb6ff61c44fff46ca51ffe08f91ffb8bbb6ff91e5d9ff10d554ff61c44fffe08f91ff61c44fff10d554ff",
    ),
    (
        "mode3_b",
        "c8daebf990d19838b0d7ec0b3e97818e",
        "eb8cd7ff430f2fffb911a1ffec8cd8ff430f2fffeb8cd7ffeb8cd7ff7c1066ffb911a1ffec8cd8ffec8cd8ff7c1066ffeb8cd7ff430f2ffff212d8ffeb8cd7ff",
    ),
    (
        "mode7_b",
        "8096c4dbadbe172296d5234a42b24c6b",
        "965d45ae965d45aeb4bc2c5f965d45aea58c3987b4bc2c5fa58c3987a58c3987dbdbb210c3eb2038965d45aea58c3987755d652c96867e23b4bc2c5fa58c3987",
    ),
    (
        "mode4_rot0_sel0",
        "10e6ed24ec636a8ac0a1271e58662792",
        "31de106449ad46727b4ab53c31de109a49ad464949ad463c31de108d49ad465631de108d31de1072637b7f807b4ab56431de105631de107249ad46727b4ab572",
    ),
    (
        "mode4_rot0_sel1",
        "90aaf84e58056d8f2fa8edd094ba97ae",
        "46f5344e35f1504e41f43d4152f7214835f150414cf62a4e35f150553af2474146f5344129ef634e2ff05a4e41f43d554cf62a5535f1504e41f43d4e35f15041",
    ),
    (
        "mode4_rot1_sel0",
        "3015442ee2db611a91bfe39469733a92",
        "b48c10ad948c10ad9fe78c00a98c10adb4aa39749fe78c00a98c10ad9fc963399f8c10ad7fc96339b48c10ad8ae78c009fe78c0094e78c0094aa397494e78c00",
    ),
    (
        "mode4_rot1_sel1",
        "b0d58fa3c55018300372555fd235f118",
        "0c219ec214219ec20c3048e20c3910f70c3048e2112b64d80f2b64d811342ced0f3048e20c342ced0c2b64d80c18d6ad0f3910f7111dbab714342ced1118d6ad",
    ),
    (
        "mode4_rot2_sel0",
        "50fb388c22e44cb637f01210c3707a90",
        "a8405a8ea83e5a8e6f4174abde41427339408cc66f3974aba8415a8e39398cc639418cc66f3974aba8405a8ede3b4273de3842736f4174ab393c8cc6a83c5a8e",
    ),
    (
        "mode4_rot2_sel1",
        "d005420fb169779edfb5b9342405157f",
        "29af848484c6c6f743db97a4439a97a44fdba0b529db8484369a8d9436db8d946adbb3d729db84845ec6aac643db97a436c68d9477c6bde784afc6f74fdba0b5",
    ),
    (
        "mode4_rot3_sel0",
        "70b12eae62d11e887eb0766d1877f8c6",
        "97885865ade79f8c8c5a88528c5a9f528c5a9f52978814658c5a9f5297881465ade7b68cade79f8cade72b8c8c5a72528c5ab652a2b9887997882b6597889f65",
    ),
    (
        "mode4_rot3_sel1",
        "f0f26b5010af3177d161e79587a766ec",
        "c17cf334d25a9637ff00c642b29a9630a3b8692dff009642a3b8692dd25a9637ff00f342d25a9637b29a9630c17c6934f01ef33e94d6f329c17c6934ff009642",
    ),
    (
        "mode5_rot0",
        "20e4037458a9905cad87bd4c77e2983f",
        "8c982a358c982a358c982a570e872a350e872a46c9a12a24c9a12a460e872a574b902a240e872a468c982a358c982a464b902a578c982a574b902a574b902a24",
    ),
    (
        "mode5_rot1",
        "60745ccb9a31052e944cf1b220eaa2c7",
        "81753bc181924398325a32e981753bc13292439832753bc1329243980b924398325a32e98192439832ad4c7032753bc10b753bc15a92439881753bc10b753bc1",
    ),
    (
        "mode5_rot2",
        "a01b7d3e3f73f414af6e0d935520dd4c",
        "753d4ef3756a4ef3756a4ef3756a4ef3f53d1cf3753d4ef3f5981cf3b63d34f3b66a34f375c54ef3366a66f3b6c534f3753d4ef3b6c534f3363d66f3f56a1cf3",
    ),
    (
        "mode5_rot3",
        "e047738606f2bf7ec70209e0cd05ee57",
        "a344af7e8f32df40b956afbfa344df7ea344bf7e8f32bf408f32af40b956afbf8f32cf40a344df7e8f32cf408f32df408f32df408f32bf40cd68bffdcd68bffd",
    ),
)


@pytest.mark.parametrize(("name", "block", "expected"), CASES, ids=[c[0] for c in CASES])
def test_block(name: str, block: str, expected: str) -> None:
    assert decode_bc7(bytes.fromhex(block), 4, 4).hex() == expected


def test_modes_all_covered() -> None:
    firsts = {bytes.fromhex(b)[0] & -bytes.fromhex(b)[0] for _, b, _ in CASES}
    assert firsts >= {1, 2, 4, 8, 16, 32, 64, 128}


def test_invalid_mode_is_transparent_black() -> None:
    assert decode_bc7(bytes(16), 4, 4) == bytes(64)


def test_block_layout_and_cropping() -> None:
    # Two blocks side by side (8x4), then cropped to 6x3.
    a, b = CASES[0], CASES[1]
    data = bytes.fromhex(a[1] + b[1])
    full = decode_bc7(data, 8, 4)
    left, right = bytes.fromhex(a[2]), bytes.fromhex(b[2])
    for y in range(4):
        assert full[y * 32 : y * 32 + 16] == left[y * 16 : y * 16 + 16]
        assert full[y * 32 + 16 : y * 32 + 32] == right[y * 16 : y * 16 + 16]
    crop = decode_bc7(data, 6, 3)
    assert len(crop) == 6 * 3 * 4
    assert crop[:24] == full[:24]
    assert crop[24:48] == full[32:56]


def test_truncated_raises() -> None:
    with pytest.raises(ValueError, match="truncated"):
        decode_bc7(bytes(16), 8, 4)
