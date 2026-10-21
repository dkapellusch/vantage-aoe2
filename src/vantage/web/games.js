// Per-game rules: Age of Empires II and Return of Rome (the game's "Pompeii"
// mode) share the engine and many ids but differ in ages, technologies and
// age-up requirements. `applyGame` rewrites the shared tables in place so every
// module that imported them follows the game being watched.

export const AGE_NAMES = [];
export const STATIC_TECHS = [];
export const ECO_TECHS = new Set();
export const MIL_TECHS = new Set();
export const AGE_REQ = [];
export const AGE_TECHS = [101, 102, 103]; // same ids in both games
export const TOWN_CENTERS = [];
export const GOTO_BUILDINGS = {};

const AOE2 = {
  ages: ['Dark', 'Feudal', 'Castle', 'Imperial', 'Post-Imp'],
  staticTechs: [
    [101, 102, 103],
    [22, 213, 249, 8, 280],
    [202, 203, 221, 14, 13, 12, 55, 182, 278, 279],
    [67, 68, 75, 74, 76, 77, 81, 82, 80, 199, 200, 201, 211, 212, 219],
    [93, 47, 437, 436, 39, 435, 215, 602, 315, 875],
    [50, 51, 322, 54, 377],
    [316, 319, 439, 45, 231, 252, 233, 230, 438],
  ],
  // Tech categories (timeline eco/military overlays). Eco is the economy
  // upgrades; military is the blacksmith/university/stable lines, the generic
  // unit upgrades and the newer naval/DLC techs. Named unique techs are in
  // neither set.
  eco: [12, 13, 14, 15, 17, 23, 48, 54, 55, 65, 182, 202, 203, 213, 221, 249, 278, 279, 490, 506, 1012, 1013, 1014],
  mil: [
    67, 68, 75, 74, 76, 77, 81, 82, 80, 199, 200, 201, 211, 212, 219, 93, 47, 437, 436, 39, 435, 215, 602, 315, 875, 716, 377,
    222, 207, 217, 264, 197, 429, 384, 434, 100, 237, 98, 218, 655, 254, 428, 209, 265, 236, 521, 786, 526, 631, 715, 885,
    96, 255, 257, 320, 239, 787, 246, 244, 376, 373, 374, 375, 529, 605,
    // naval and DLC techs
    1404, 34, 35, 903, 904, 905, 906, 907, 908, 909, 910, 911, 913, 528, 1350, 1402, 1351, 1352, 1378, 1376, 1401, 1364,
    1390, 1389, 1450, 1451, 1453, 1454, 1462, 1472, 1482, 272, 372, 1452, 1496,
  ],
  // Next-age cost and the buildings that qualify (two needed; a castle alone
  // qualifies for Imperial).
  ageReq: [
    { food: 500, gold: 0, buildings: [12, 68, 562, 584, 45], need: 2 },
    { food: 800, gold: 200, buildings: [87, 101, 103, 84], need: 2 },
    { food: 1000, gold: 800, buildings: [209, 104, 49, 82], need: 2, castleCounts: 82 },
  ],
  townCenters: [109, 71, 141, 142, 618, 619, 620, 444],
  goto: {
    gotoBarracks: [12, 498], gotoArcheryRange: [87, 10, 14], gotoStable: [101, 86, 153],
    gotoSiegeWorkshop: [49, 150], gotoCastle: [82, 1251], gotoMonastery: [104, 30, 31, 32],
    gotoMarket: [84, 116, 137], gotoBlacksmith: [103, 18, 19], gotoUniversity: [209, 210],
    gotoDock: [45, 47, 51, 133], gotoMill: [68, 129, 130, 131], gotoLumberCamp: [562, 563, 564, 565],
  },
};

// Return of Rome: Stone, Tool, Bronze and Iron Ages. Ids from the game's own
// modes/Pompeii tech trees (served by /api/techtree in Return of Rome).
const ROR = {
  ages: ['Stone', 'Tool', 'Bronze', 'Iron', 'Iron'],
  staticTechs: [
    [101, 102, 103],
    [107, 32, 110, 108, 30, 109, 111, 81, 31, 80, 28], // storage pit, market, granary
    [46, 51, 52, 40, 41, 42, 43, 44, 45, 48, 49, 50, 47, 117, 122], // storage pit armour
    [34, 19, 112, 121, 113, 106, 37, 35], // government center
    [22, 21, 24, 18, 114, 20, 23, 119, 120], // temple
  ],
  eco: [107, 32, 110, 108, 30, 109, 111, 81, 31, 80, 28],
  mil: [46, 51, 52, 40, 41, 42, 43, 44, 45, 48, 49, 50, 47, 117, 122, 106, 37, 121],
  ageReq: [
    { food: 500, gold: 0, buildings: [12, 68, 562, 45], need: 2 }, // barracks, granary, storage pit, dock
    { food: 800, gold: 0, buildings: [84, 87, 101], need: 2 }, // market, archery range, stable
    { food: 1000, gold: 800, buildings: [104, 103, 49, 209], need: 2 }, // temple, academy, siege workshop, government center
  ],
  townCenters: [109, 621],
  goto: {
    gotoBarracks: [12], gotoArcheryRange: [87], gotoStable: [101], gotoSiegeWorkshop: [49],
    gotoCastle: [], gotoMonastery: [104], gotoMarket: [84], gotoBlacksmith: [103],
    gotoUniversity: [209], gotoDock: [45], gotoMill: [68], gotoLumberCamp: [562],
  },
};

export const GAMES = { aoe2: AOE2, ror: ROR };

// In Return of Rome some hotkeys name the AoE2 building whose role the RoR one
// plays (monastery -> temple, blacksmith -> academy, university -> government
// center, mill -> granary, lumber camp -> storage pit).
export const ROR_BUILDING_LABELS = {
  gotoMonastery: 'Next temple', gotoBlacksmith: 'Next academy', gotoUniversity: 'Next government center',
  gotoMill: 'Next granary', gotoLumberCamp: 'Next storage pit',
};

let current = null;

export function applyGame(game) {
  const g = GAMES[game] || AOE2;
  if (g === current) return false;
  current = g;
  AGE_NAMES.splice(0, AGE_NAMES.length, ...g.ages);
  STATIC_TECHS.splice(0, STATIC_TECHS.length, ...g.staticTechs);
  ECO_TECHS.clear(); g.eco.forEach((x) => ECO_TECHS.add(x));
  MIL_TECHS.clear(); g.mil.forEach((x) => MIL_TECHS.add(x));
  AGE_REQ.splice(0, AGE_REQ.length, ...g.ageReq);
  TOWN_CENTERS.splice(0, TOWN_CENTERS.length, ...g.townCenters);
  for (const k of Object.keys(GOTO_BUILDINGS)) delete GOTO_BUILDINGS[k];
  Object.assign(GOTO_BUILDINGS, { gotoTownCenter: g.townCenters, ...g.goto });
  return true;
}

applyGame('aoe2');

// -- hover tech tree: nine categories ---------------------------------------------------
// The game's tech-tree data groups nodes by building; the hover tree groups them
// by role. Buildings map to a category; the blacksmith, university, castle and
// town center split by technology.
// Row order and headers (nine headed rows).
export const TREE_CATEGORIES = ['Economy', 'Infantry', 'Archery', 'Cavalry', 'Siege', 'Naval', 'Monastery', 'Defensive', 'Misc'];
export const TREE_CATEGORY_LABEL = { Misc: 'Miscellaneous' };
// Server layout row keys (/api/techtree layout.rows[].key) -> category.
export const TREE_ROW_KEYS = {
  economy: 'Economy', infantry: 'Infantry', archery: 'Archery', cavalry: 'Cavalry', siege: 'Siege',
  naval: 'Naval', monastery: 'Monastery', defensive: 'Defensive', misc: 'Misc',
};
const CAT_BY_BUILDING = {
  87: 'Archery', 12: 'Infantry', 101: 'Cavalry', 49: 'Siege', 45: 'Naval', 104: 'Monastery',
  109: 'Economy', 621: 'Economy', 68: 'Economy', 562: 'Economy', 584: 'Economy', 84: 'Economy', 70: 'Economy', 50: 'Economy', 1889: 'Economy',
  598: 'Defensive', 79: 'Defensive', 234: 'Defensive', 235: 'Defensive', 236: 'Defensive', 72: 'Defensive',
  792: 'Defensive', 487: 'Defensive', 117: 'Defensive', 155: 'Defensive',
  82: 'Misc', 103: 'Misc', 209: 'Misc', 276: 'Misc',
};
const CAT_BY_NODE = {
  103: { 211: 'Archery', 212: 'Archery', 219: 'Archery', 199: 'Archery', 200: 'Archery', 201: 'Archery',
    81: 'Cavalry', 82: 'Cavalry', 80: 'Cavalry', 74: 'Infantry', 76: 'Infantry', 77: 'Infantry' },
  209: { 50: 'Defensive', 51: 'Defensive', 194: 'Defensive', 64: 'Defensive', 140: 'Defensive', 63: 'Defensive', 380: 'Defensive',
    608: 'Defensive', 322: 'Defensive', 54: 'Economy', 377: 'Siege', 374: 'Naval', 375: 'Naval', 908: 'Naval', 907: 'Naval',
    909: 'Naval', 910: 'Naval', 373: 'Naval' },
  82: { 440: 'Siege', 331: 'Siege', 379: 'Defensive', 321: 'Infantry' },
  109: { 8: 'Defensive', 280: 'Defensive' },
};
export function treeCategory(node) {
  const byNode = CAT_BY_NODE[node.building];
  return (byNode && byNode[node.id]) || CAT_BY_BUILDING[node.building] || 'Misc';
}

// Armour classes (the game's attack/armour class ids) for the unit-panel tooltip.
export const ARMOR_CLASSES = {
  1: 'Infantry', 2: 'Turtle Ships', 3: 'Base Pierce', 4: 'Base Melee', 5: 'War Elephants', 8: 'Cavalry',
  11: 'All Buildings', 13: 'Stone Defense', 14: 'Predator Animals', 15: 'Archers', 16: 'Ships, Camels, Saboteurs',
  17: 'Rams', 18: 'Trees', 19: 'Unique Units', 20: 'Siege Weapons', 21: 'Standard Buildings', 22: 'Walls & Gates',
  23: 'Gunpowder Units', 24: 'Boars', 25: 'Monks', 26: 'Castles', 27: 'Spearmen', 28: 'Cavalry Archers',
  29: 'Eagle Warriors', 30: 'Camels', 32: 'Condottieri', 34: 'Fishing Ships', 35: 'Mamelukes', 36: 'Heroes & Kings',
};

// Settlement masters (antiquity): one built satisfies every building
// requirement of the next age (catalog building_groups.settlement when sent).
export const SETTLEMENT_MASTERS = [2556, 2558, 2560];

// Static techs: the farm cell swaps to pasture for pasture civs.
export const FARM_TECHS = [14, 13, 12];
export const PASTURE_TECHS = [1014, 1013, 1012];

// "Power Techs" (community FFA layout): final unit upgrades and age techs; the
// catalog's power_techs (with the civs' unique techs and elite unique units)
// replaces this fallback when the server sends it.
export const POWER_TECHS = [101, 102, 103, 265, 264, 237, 218, 320, 255, 239, 787, 244, 35, 246, 64, 429, 428, 236, 521, 434, 631, 715, 376, 98, 655];

// Castle-researched technologies every civ shares (the rest at the castle are
// unique techs), for the fallback when the tech tree lacks unique_techs.
export const SHARED_CASTLE_TECHS = [379, 321, 315, 408];

// The King (regicide) master id, for the scoreboard fallback when view.kings is absent.
export const KING_MASTER = 434;
