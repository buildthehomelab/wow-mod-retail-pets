#!/usr/bin/env python3
"""The spell and item side of the pets in data/pets.tsv: rows for the realm's spell patch and the
module's world database SQL.

    python3 build_pets.py --patch-w patch-W.MPQ --patch-z patch-Z.MPQ --client /path/to/client \\
        --cache <download dir> --out patch-W-new.MPQ --sql ../data/sql/db-world/mod_retail_pets.sql

The pet models are a separate patch (patch-Z.MPQ), built first from this repo's pack.json by
wow-mod-retail-creatures' tools/build_patch.py. This tool does the rest.

--patch-w is the patch that carries the realm's Spell.dbc, Item.dbc, SkillLineAbility.dbc and
ItemDisplayInfo.dbc (ours is patch-W.MPQ). A patch MPQ replaces whole files, so the pets' rows go
into its copies; every other file in it is copied unchanged. Per pet it gains:

- Spell.dbc: the summon spell, a copy of Bombay Cat (10673) with the pet's creature, name and icon.
- SkillLineAbility.dbc: that spell on the Companions skill line, which puts it on the Pets tab.
- Item.dbc and ItemDisplayInfo.dbc: the item that teaches it, with the pet's icon.
- SpellIcon.dbc: the icon. If the patch has no SpellIcon.dbc yet, the client's own copy (--client,
  newest locale patch) is the base.
- Interface\\Icons\\<icon>.blp, downloaded from wago.tools into --cache.

The spell icon and the SkillLineAbility row use the spell's id, the item display uses the item's.

--patch-z is the built model patch: its CreatureDisplayInfo and CreatureModelData rows are
mirrored into the SQL, because the server checks creature displays against its own DBC stores.

Running it again on its own output changes nothing. Needs Python 3 and StormLib (`STORMLIB`,
default /usr/local/lib/libstorm.dylib).
"""

import argparse
import ctypes
import os
import struct
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))

TEMPLATE_SPELL = 10673          # Bombay Cat: summon companion, instant, no cost
TEMPLATE_ITEM_DISPLAY = 20629   # Cat Carrier (Bombay)'s display: an icon and nothing else
SKILL_COMPANIONS = 778
SPELL_LEARNING = 55884          # item spell 1 of every companion item; teaches item spell 2
ITEM_SPELLTRIGGER_LEARN = 6
ITEM_CLASS_MISC, ITEM_SUBCLASS_PET = 15, 2
UNSET = 0xFFFFFFFF

SPELL_FIELDS = 234
F_EFFECT_MISC, F_ICON, F_ACTIVE_ICON, F_NAME, F_DESCRIPTION = 110, 133, 134, 136, 170
STRING_FIELDS = set(range(136, 152)) | set(range(153, 169)) | set(range(170, 186)) | set(range(187, 203))
FLOAT_FIELDS = {47, 77, 78, 79, 101, 102, 103, 119, 120, 121, 216, 217, 218, 229, 230, 231}
# Plain `int` columns of AC's spell_dbc; every other integer column is unsigned.
SIGNED_FIELDS = {0, 13, 15, 41, *range(52, 71), 74, 75, 76, 80, 81, 82, *range(110, 116), 224, 228}

LOCALE_MPQS = ["patch-{0}-3.MPQ", "patch-{0}-2.MPQ", "patch-{0}.MPQ", "locale-{0}.MPQ"]
CASC = "https://wago.tools/api/casc/{}"


# --- DBC ---------------------------------------------------------------------------------------

def read_dbc(path):
    data = open(path, "rb").read()
    magic, count, fields, size, strsize = struct.unpack_from("<4s4I", data, 0)
    if magic != b"WDBC" or size != fields * 4:
        sys.exit("%s isn't a plain WDBC file" % path)
    rows = [list(struct.unpack_from("<%dI" % fields, data, 20 + i * size)) for i in range(count)]
    strings = bytearray(data[20 + count * size:20 + count * size + strsize])
    return rows, strings, fields


def write_dbc(path, rows, strings, fields):
    rows = sorted(rows, key=lambda r: r[0])
    with open(path, "wb") as f:
        f.write(struct.pack("<4s4I", b"WDBC", len(rows), fields, fields * 4, len(strings)))
        for r in rows:
            f.write(struct.pack("<%dI" % fields, *r))
        f.write(strings)


def string_at(strings, at):
    return strings[at:strings.index(b"\0", at)].decode("utf-8")


def add_string(strings, text):
    """Offset of text in the string block, appended unless it is already there as a whole string."""
    raw = text.encode("utf-8") + b"\0"
    at = strings.find(b"\0" + raw)
    if at >= 0:
        return at + 1
    at = len(strings)
    strings.extend(raw)
    return at


def template(rows, row_id, what):
    for r in rows:
        if r[0] == row_id:
            return list(r)
    sys.exit("%s %d missing" % (what, row_id))


def upsert(rows, row):
    rows[:] = [r for r in rows if r[0] != row[0]]
    rows.append(row)


# --- MPQ ---------------------------------------------------------------------------------------

def stormlib():
    lib = ctypes.CDLL(os.environ.get("STORMLIB", "/usr/local/lib/libstorm.dylib"))
    H = ctypes.c_void_p
    lib.SFileOpenArchive.argtypes = [ctypes.c_char_p, ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(H)]
    lib.SFileExtractFile.argtypes = [H, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    lib.SFileHasFile.argtypes = [H, ctypes.c_char_p]
    lib.SFileFindFirstFile.argtypes = [H, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_char_p]
    lib.SFileFindFirstFile.restype = H
    lib.SFileFindNextFile.argtypes = [H, ctypes.c_void_p]
    lib.SFileFindClose.argtypes = [H]
    lib.SFileCreateArchive.argtypes = [ctypes.c_char_p, ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(H)]
    lib.SFileAddFileEx.argtypes = [H, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint]
    lib.SFileCloseArchive.argtypes = [H]
    for fn in (lib.SFileOpenArchive, lib.SFileExtractFile, lib.SFileHasFile, lib.SFileFindNextFile,
               lib.SFileFindClose, lib.SFileCreateArchive, lib.SFileAddFileEx, lib.SFileCloseArchive):
        fn.restype = ctypes.c_bool
    return lib, H


def open_mpq(lib, H, mpq):
    h = H()
    if not lib.SFileOpenArchive(mpq.encode(), 0, 0x100, ctypes.byref(h)):
        sys.exit("can't open " + mpq)
    return h


def unpack(mpq, folder):
    """Extracts every file; returns {archive name: local path}."""
    lib, H = stormlib()
    h = open_mpq(lib, H, mpq)
    names = []
    found = ctypes.create_string_buffer(2048)  # SFILE_FIND_DATA starts with the name (1024 bytes)
    find = lib.SFileFindFirstFile(h, b"*", found, None)
    while find:
        name = found.value.decode("latin-1")
        if name not in ("(listfile)", "(attributes)", "(signature)"):
            names.append(name)
        if not lib.SFileFindNextFile(find, found):
            lib.SFileFindClose(find)
            break
    files = {}
    for i, name in enumerate(names):
        local = os.path.join(folder, "%05d" % i)
        if not lib.SFileExtractFile(h, name.encode("latin-1"), local.encode(), 0):
            sys.exit("can't extract %s from %s" % (name, mpq))
        files[name] = local
    lib.SFileCloseArchive(h)
    if not files:
        sys.exit("%s has no files (or no listfile)" % mpq)
    return files


def extract(mpq, name, dst):
    lib, H = stormlib()
    h = open_mpq(lib, H, mpq)
    ok = lib.SFileExtractFile(h, name.encode("latin-1"), dst.encode(), 0)
    lib.SFileCloseArchive(h)
    return ok


def client_file(client, locale, name, dst):
    """The client's newest copy of a locale file (the later locale patches load over the earlier)."""
    folder = os.path.join(client, "Data", locale)
    for pattern in LOCALE_MPQS:
        mpq = os.path.join(folder, pattern.format(locale))
        if os.path.exists(mpq) and extract(mpq, name, dst):
            return mpq
    sys.exit("no %s in %s's locale MPQs" % (name, folder))


def pack(out, files):
    """files: [(local path, archive name)]. zlib-compressed, with listfile and attributes."""
    lib, H = stormlib()
    if os.path.exists(out):
        os.remove(out)
    h = H()
    if not lib.SFileCreateArchive(out.encode(), 0x00300000, max(64, len(files) * 2), ctypes.byref(h)):
        sys.exit("can't create " + out)
    for src, name in files:
        if not lib.SFileAddFileEx(h, src.encode(), name.encode("latin-1"), 0x80000200, 0x02, 0x02):
            lib.SFileCloseArchive(h)
            os.remove(out)
            sys.exit("can't add " + name)
    if not lib.SFileCloseArchive(h):
        os.remove(out)
        sys.exit("can't finish " + out)


# --- downloads ---------------------------------------------------------------------------------

def casc_path(cache, fdid, tries=6):
    """A retail file by file data id, from wago.tools (502/504 under load, so retry), kept in cache."""
    path = os.path.join(cache, "casc", str(fdid))
    if os.path.exists(path) and os.path.getsize(path) > 64:
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    request = urllib.request.Request(CASC.format(fdid), headers={"User-Agent": "mod-retail-pets/1.0"})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(request, timeout=120) as r:
                data = r.read()
            if len(data) <= 64:
                raise urllib.error.URLError(data.decode("latin-1"))
            with open(path + ".part", "wb") as f:
                f.write(data)
            os.replace(path + ".part", path)
            return path
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt == tries - 1:
                sys.exit("%s: %s" % (request.full_url, e))
            time.sleep(2 + 3 * attempt)


# --- pets --------------------------------------------------------------------------------------

def load_pets(path):
    lines = open(path, encoding="utf-8").read().splitlines()
    head = lines[0].split("\t")
    pets = [dict(zip(head, l.split("\t"))) for l in lines[1:] if l.strip()]
    for p in pets:
        for k in ("display", "creature", "spell", "item", "icon_fdid", "price", "vendor"):
            p[k] = int(p[k])
        p["scale"] = float(p["scale"])
    for k in ("display", "creature", "spell", "item"):
        if len({p[k] for p in pets}) != len(pets):
            sys.exit("%s: two pets share a %s id" % (path, k))
    return pets


def patch_w(files, pets, args, tmp):
    """Adds the pets' rows and icons to the unpacked spell patch. Returns the new spell rows."""
    def dbc(table):
        return "DBFilesClient\\%s.dbc" % table

    for table in ("Spell", "SkillLineAbility", "Item", "ItemDisplayInfo"):
        if dbc(table) not in files:
            sys.exit("%s has no %s.dbc" % (args.patch_w, table))
    if dbc("SpellIcon") not in files:
        local = os.path.join(tmp, "SpellIcon.dbc")
        source = client_file(args.client, args.locale, dbc("SpellIcon"), local)
        files[dbc("SpellIcon")] = local
        print("SpellIcon.dbc: from %s" % os.path.basename(source))

    spells, spell_str, fields = read_dbc(files[dbc("Spell")])
    if fields != SPELL_FIELDS:
        sys.exit("Spell.dbc has %d fields, not %d" % (fields, SPELL_FIELDS))
    abilities, ability_str, ability_fields = read_dbc(files[dbc("SkillLineAbility")])
    items, item_str, item_fields = read_dbc(files[dbc("Item")])
    displays, display_str, display_fields = read_dbc(files[dbc("ItemDisplayInfo")])
    icons, icon_str, icon_fields = read_dbc(files[dbc("SpellIcon")])

    # An id of ours that the patch already uses for something else is a clash, not an update.
    for p in pets:
        for rows, row_id, col, strings, table in (
                (spells, p["spell"], F_NAME, spell_str, "Spell"),
                (icons, p["spell"], 1, icon_str, "SpellIcon"),
                (displays, p["item"], 5, display_str, "ItemDisplayInfo")):
            old = next((r for r in rows if r[0] == row_id), None)
            if old and string_at(strings, old[col]) not in (p["name"], p["icon"], "Interface\\Icons\\" + p["icon"]):
                sys.exit("%s.dbc row %d is taken: %s" % (table, row_id, string_at(strings, old[col])))
        for rows, row_id, col, table in ((abilities, p["spell"], 2, "SkillLineAbility"), (items, p["item"], 5, "Item")):
            old = next((r for r in rows if r[0] == row_id), None)
            if old and old[col] != (p["spell"] if col == 2 else p["item"]):
                sys.exit("%s.dbc row %d is taken" % (table, row_id))

    new_spells = []
    for p in pets:
        spell = template(spells, TEMPLATE_SPELL, "Spell.dbc row")
        spell[0] = p["spell"]
        spell[F_EFFECT_MISC] = p["creature"]
        spell[F_ICON] = p["spell"]
        spell[F_ACTIVE_ICON] = 0
        spell[F_NAME] = add_string(spell_str, p["name"])
        spell[F_DESCRIPTION] = add_string(spell_str, p["summon_text"])
        upsert(spells, spell)
        new_spells.append(spell)

        upsert(abilities, [p["spell"], SKILL_COMPANIONS, p["spell"], 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0])
        upsert(items, [p["item"], ITEM_CLASS_MISC, ITEM_SUBCLASS_PET, UNSET, UNSET, p["item"], 0, 0])
        display = template(displays, TEMPLATE_ITEM_DISPLAY, "ItemDisplayInfo.dbc row")
        display[0] = p["item"]
        display[5] = add_string(display_str, p["icon"])
        upsert(displays, display)
        upsert(icons, [p["spell"], add_string(icon_str, "Interface\\Icons\\" + p["icon"])])
        files["Interface\\Icons\\%s.blp" % p["icon"]] = casc_path(args.cache, p["icon_fdid"])

    write_dbc(files[dbc("Spell")], spells, spell_str, fields)
    write_dbc(files[dbc("SkillLineAbility")], abilities, ability_str, ability_fields)
    write_dbc(files[dbc("Item")], items, item_str, item_fields)
    write_dbc(files[dbc("ItemDisplayInfo")], displays, display_str, display_fields)
    write_dbc(files[dbc("SpellIcon")], icons, icon_str, icon_fields)
    return new_spells


# --- SQL ---------------------------------------------------------------------------------------

def sql_str(s):
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def si(v):
    """A DBC uint32 as the signed int the server's *_dbc columns hold (-1, not 4294967295)."""
    return struct.unpack("<i", struct.pack("<I", v))[0]


def fl(v):
    return "%g" % struct.unpack("<f", struct.pack("<I", v))[0]


def id_list(values):
    return ", ".join(str(v) for v in values)


def write_sql(path, pets, new_spells, patch_z, tmp):
    def spell_value(i, v):
        if i in STRING_FIELDS:
            return "''"
        if i in FLOAT_FIELDS:
            return fl(v)
        return str(si(v) if i in SIGNED_FIELDS else v)

    cdi_path, cmd_path = os.path.join(tmp, "z-cdi.dbc"), os.path.join(tmp, "z-cmd.dbc")
    for name, local in (("CreatureDisplayInfo", cdi_path), ("CreatureModelData", cmd_path)):
        if not extract(patch_z, "DBFilesClient\\%s.dbc" % name, local):
            sys.exit("%s has no %s.dbc" % (patch_z, name))
    cdi_rows, cdi_str, _ = read_dbc(cdi_path)
    cmd_rows, cmd_str, _ = read_dbc(cmd_path)
    cdi = [template(cdi_rows, p["display"], "%s: CreatureDisplayInfo.dbc row" % patch_z) for p in pets]
    cmd = [template(cmd_rows, model, "%s: CreatureModelData.dbc row" % patch_z)
           for model in sorted({r[1] for r in cdi})]

    creatures, spells, items = ([p[k] for p in pets] for k in ("creature", "spell", "item"))
    displays, models = [r[0] for r in cdi], [r[0] for r in cmd]
    with open(path, "w", encoding="utf-8") as f:
        f.write("-- mod-retail-pets: companion pets with retail models. Generated by tools/build_pets.py from\n")
        f.write("-- data/pets.tsv: change that file and run the tool again, don't edit this one.\n")
        f.write("-- The client needs the module's two patches (see the README), or it shows no pet at all.\n\n")

        f.write("-- The pets.\n")
        f.write("DELETE FROM `creature_template_model` WHERE `CreatureID` IN (%s);\n" % id_list(creatures))
        f.write("DELETE FROM `creature_template` WHERE `entry` IN (%s);\n" % id_list(creatures))
        f.write("INSERT INTO `creature_template` (`entry`, `name`, `minlevel`, `maxlevel`, `faction`, `speed_walk`, `speed_run`, `BaseAttackTime`, `RangeAttackTime`, `unit_class`, `unit_flags`, `unit_flags2`, `type`, `movementId`, `flags_extra`) VALUES\n")
        f.write(",\n".join("(%d, %s, 1, 1, 188, 1, 1.14286, 2000, 2000, 1, 768, 2048, 12, 121, 2)" % (p["creature"], sql_str(p["name"]))
                           for p in pets) + ";\n")
        f.write("INSERT INTO `creature_template_model` (`CreatureID`, `Idx`, `CreatureDisplayID`, `DisplayScale`, `Probability`) VALUES\n")
        f.write(",\n".join("(%d, 0, %d, %g, 1)" % (p["creature"], p["display"], p["scale"]) for p in pets) + ";\n\n")

        f.write("-- Their summon spells (client: Spell.dbc in the spell patch), on the Companions skill line.\n")
        f.write("DELETE FROM `spell_dbc` WHERE `ID` IN (%s);\n" % id_list(spells))
        f.write("INSERT INTO `spell_dbc` VALUES\n")
        lines = []
        for p, row in zip(pets, new_spells):
            values = [spell_value(i, v) for i, v in enumerate(row)]
            values[F_NAME] = sql_str(p["name"])
            values[F_DESCRIPTION] = sql_str(p["summon_text"])
            lines.append("(" + ", ".join(values) + ")")
        f.write(",\n".join(lines) + ";\n")
        f.write("DELETE FROM `skilllineability_dbc` WHERE `ID` IN (%s);\n" % id_list(spells))
        f.write("INSERT INTO `skilllineability_dbc` (`ID`, `SkillLine`, `Spell`, `RaceMask`, `ClassMask`, `ExcludeRace`, `ExcludeClass`, `MinSkillLineRank`, `SupercededBySpell`, `AcquireMethod`, `TrivialSkillLineRankHigh`, `TrivialSkillLineRankLow`, `CharacterPoints_1`, `CharacterPoints_2`) VALUES\n")
        f.write(",\n".join("(%d, %d, %d, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0)" % (p["spell"], SKILL_COMPANIONS, p["spell"])
                           for p in pets) + ";\n\n")

        f.write("-- The items that teach them, and who sells those.\n")
        f.write("DELETE FROM `npc_vendor` WHERE `item` IN (%s);\n" % id_list(items))
        f.write("DELETE FROM `item_template` WHERE `entry` IN (%s);\n" % id_list(items))
        f.write("INSERT INTO `item_template` (`entry`, `class`, `subclass`, `name`, `displayid`, `Quality`, `Flags`, `BuyPrice`, `SellPrice`, `ItemLevel`, `delay`, `spellid_1`, `spellcharges_1`, `spellid_2`, `spelltrigger_2`, `description`, `Material`, `BagFamily`) VALUES\n")
        f.write(",\n".join("(%d, %d, %d, %s, %d, 3, 64, %d, %d, 20, 0, %d, -1, %d, %d, 'Teaches you how to summon this companion.', -1, 4096)" % (
            p["item"], ITEM_CLASS_MISC, ITEM_SUBCLASS_PET, sql_str(p["name"]), p["item"], p["price"], p["price"] // 4,
            SPELL_LEARNING, p["spell"], ITEM_SPELLTRIGGER_LEARN) for p in pets) + ";\n")
        f.write("INSERT INTO `npc_vendor` (`entry`, `slot`, `item`, `maxcount`, `incrtime`, `ExtendedCost`) VALUES\n")
        f.write(",\n".join("(%d, 0, %d, 0, 0, 0)" % (p["vendor"], p["item"]) for p in pets) + ";\n\n")

        f.write("-- The model patch's CreatureDisplayInfo and CreatureModelData rows, for the server's DBC stores.\n")
        f.write("DELETE FROM `creaturedisplayinfo_dbc` WHERE `ID` IN (%s);\n" % id_list(displays))
        f.write("INSERT INTO `creaturedisplayinfo_dbc` (`ID`, `ModelID`, `SoundID`, `ExtendedDisplayInfoID`, `CreatureModelScale`, `CreatureModelAlpha`, `TextureVariation_1`, `TextureVariation_2`, `TextureVariation_3`, `PortraitTextureName`, `BloodLevel`, `BloodID`, `NPCSoundID`, `ParticleColorID`, `CreatureGeosetData`, `ObjectEffectPackageID`) VALUES\n")
        f.write(",\n".join("(%d, %d, %d, %d, %s, %d, %s, %s, %s, '', %d, %d, %d, %d, %d, %d)" % (
            r[0], si(r[1]), si(r[2]), si(r[3]), fl(r[4]), si(r[5]),
            *(sql_str(string_at(cdi_str, r[6 + k]) if r[6 + k] else "") for k in range(3)),
            si(r[10]), si(r[11]), si(r[12]), si(r[13]), si(r[14]), si(r[15])) for r in cdi) + ";\n")
        f.write("DELETE FROM `creaturemodeldata_dbc` WHERE `ID` IN (%s);\n" % id_list(models))
        f.write("INSERT INTO `creaturemodeldata_dbc` (`ID`, `Flags`, `ModelName`, `SizeClass`, `ModelScale`, `BloodID`, `FootprintTextureID`, `FootprintTextureLength`, `FootprintTextureWidth`, `FootprintParticleScale`, `FoleyMaterialID`, `FootstepShakeSize`, `DeathThudShakeSize`, `SoundID`, `CollisionWidth`, `CollisionHeight`, `MountHeight`, `GeoBoxMinX`, `GeoBoxMinY`, `GeoBoxMinZ`, `GeoBoxMaxX`, `GeoBoxMaxY`, `GeoBoxMaxZ`, `WorldEffectScale`, `AttachedEffectScale`, `MissileCollisionRadius`, `MissileCollisionPush`, `MissileCollisionRaise`) VALUES\n")
        f.write(",\n".join("(%d, %d, %s, %d, %s, %d, %d, %s, %s, %s, %d, %d, %d, %d, %s)" % (
            r[0], si(r[1]), sql_str(string_at(cmd_str, r[2])), si(r[3]), fl(r[4]), si(r[5]), si(r[6]), fl(r[7]),
            fl(r[8]), fl(r[9]), si(r[10]), si(r[11]), si(r[12]), si(r[13]), ", ".join(fl(x) for x in r[14:28]))
            for r in cmd) + ";\n")
        f.write("DELETE FROM `creature_model_info` WHERE `DisplayID` IN (%s);\n" % id_list(displays))
        f.write("INSERT INTO `creature_model_info` (`DisplayID`, `BoundingRadius`, `CombatReach`, `Gender`, `DisplayID_Other_Gender`) VALUES\n")
        f.write(",\n".join("(%d, 0.25, 0.5, 2, 0)" % d for d in displays) + ";\n")
    print("wrote", path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--patch-w", required=True, help="the realm's live spell patch (patch-W.MPQ)")
    ap.add_argument("--patch-z", required=True, help="the built model patch (patch-Z.MPQ)")
    ap.add_argument("--client", required=True, help="the base client folder (has Data/<locale>/)")
    ap.add_argument("--locale", default="enUS")
    ap.add_argument("--cache", required=True, help="download folder, shared with wow-mod-retail-creatures")
    ap.add_argument("--pets", default=os.path.join(HERE, "..", "data", "pets.tsv"))
    ap.add_argument("--out", required=True, help="the new spell patch")
    ap.add_argument("--sql", help="write the module's world SQL here")
    args = ap.parse_args()

    pets = load_pets(args.pets)
    with tempfile.TemporaryDirectory() as tmp:
        files = unpack(args.patch_w, tmp)
        new_spells = patch_w(files, pets, args, tmp)
        pack(args.out, [(local, name) for name, local in sorted(files.items())])
        print("%s: %d pets, %d files, %.1f MB" % (args.out, len(pets), len(files), os.path.getsize(args.out) / 1e6))
        if args.sql:
            write_sql(args.sql, pets, new_spells, args.patch_z, tmp)


if __name__ == "__main__":
    main()
