#!/usr/bin/env python3
"""The spell and item side of the pets and mounts in data/pets.tsv: rows for the realm's spell
patch and the module's world database SQL.

    python3 build_pets.py --patch-w patch-W.MPQ --patch-z patch-Z.MPQ --client /path/to/client \\
        --cache <download dir> --out patch-W-new.MPQ --sql ../data/sql/db-world/mod_retail_pets.sql

The models are a separate patch (patch-Z.MPQ), built first from this repo's pack.json by
wow-mod-retail-creatures' tools/build_patch.py. This tool does the rest.

--patch-w is the patch that carries the realm's Spell.dbc, Item.dbc, SkillLineAbility.dbc and
ItemDisplayInfo.dbc (ours is patch-W.MPQ). A patch MPQ replaces whole files, so the new rows go
into its copies; every other file in it is copied unchanged. Per pet or mount it gains:

- Spell.dbc: the summon spell, a copy of Bombay Cat (10673) for a pet and of Amani War Bear
  (43688) for a mount, with the row's creature, name and icon.
- SkillLineAbility.dbc: that spell on the Companions or the Mounts skill line, which puts it on
  the Pets or the Mounts tab.
- Item.dbc and ItemDisplayInfo.dbc: the item that teaches it, with the row's icon.
- SpellIcon.dbc: the icon. If the patch has no SpellIcon.dbc yet, the client's own copy (--client,
  newest locale patch) is the base.
- Interface\\Icons\\<icon>.blp, downloaded from wago.tools into --cache.

The spell icon and the SkillLineAbility row use the spell's id, the item display uses the item's.

--patch-z is the built model patch: its CreatureDisplayInfo and CreatureModelData rows are
mirrored into the SQL, because the server checks creature displays against its own DBC stores.

A row's `vendor` is the creature that sells its item. data/vendors.tsv lists the module's own
vendors (the SQL makes and spawns those); any other entry is taken to be a creature the server
already has.

A row's `tier` is the mod-individual-progression phase its item waits for: the vendor shows and
sells it only to a player who has cleared that phase (0 = to everyone). The SQL does that with a
vendor condition on the phase's hidden quest, 66000 + tier.

A vendor with a `gossip_menu` greets the player before it opens its window: with `greeting` while
some item of its is still locked for that player, and with `greeting_all` once none is.

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

TEMPLATE_ITEM_DISPLAY = 20629   # Cat Carrier (Bombay)'s display: an icon and nothing else
SPELL_LEARNING = 55884          # item spell 1 of every companion and mount item; teaches item spell 2
ITEM_SPELLTRIGGER_LEARN = 6
ITEM_CLASS_MISC = 15
SKILL_RIDING, RIDING_APPRENTICE = 762, 75
UNSET = 0xFFFFFFFF

# mod-individual-progression keeps a player's phase as rewarded hidden quests: 66000 + phase, for
# every phase up to theirs. Phases run from 0 (new character) to 18.
PROGRESSION_QUEST = 66000
PROGRESSION_PHASES = range(0, 19)
CONDITION_SOURCE_GOSSIP_MENU = 14
CONDITION_SOURCE_NPC_VENDOR = 23
CONDITION_QUESTREWARDED = 8
NPCFLAG_GOSSIP, NPCFLAG_VENDOR = 1, 128
GOSSIP_OPTION_VENDOR, GOSSIP_ICON_VENDOR = 3, 1

# What a row of each `form` becomes. A mount is a ground mount any rider can use: its item asks
# for Apprentice Riding and no level, like the stock mounts whose speed a server scales.
#   spell     Spell.dbc row the summon spell copies: Bombay Cat (summon companion) and Amani War
#             Bear (mounted aura on the creature, +100% mounted speed, 1.5 s cast, outdoors)
#   skill     its skill line: Companions or Mounts
#   subclass  item subclass: pet or mount
#   item      (Flags, RequiredSkill, RequiredSkillRank, bonding, BagFamily) of the item, from
#             Cat Carrier (Bombay) and Amani War Bear
#   creature  (faction, unit_flags, type, movementId, flags_extra) of the creature, from Bombay
#             Cat and the Amani War Bear mount
#   model     (BoundingRadius, CombatReach) of its display
KINDS = {
    "pet": dict(spell=10673, skill=778, subclass=2, item=(64, 0, 0, 0, 4096),
                creature=(188, 768, 12, 121, 2), model=(0.25, 0.5)),
    "mount": dict(spell=43688, skill=777, subclass=5, item=(0, SKILL_RIDING, RIDING_APPRENTICE, 1, 0),
                  creature=(35, 0, 1, 140, 0), model=(1.45, 1.5)),
}

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
        for k in ("display", "tier", "creature", "spell", "item", "icon_fdid", "quality", "price", "vendor"):
            p[k] = int(p[k])
        if p["tier"] not in PROGRESSION_PHASES:
            sys.exit("%s: %s has tier %d, which is no progression phase" % (path, p["name"], p["tier"]))
        p["scale"] = float(p["scale"])
        if p["form"] not in KINDS:
            sys.exit("%s: %s is a %s, not one of %s" % (path, p["name"], p["form"], ", ".join(KINDS)))
        p["kind"] = KINDS[p["form"]]
    for k in ("display", "creature", "spell", "item"):
        if len({p[k] for p in pets}) != len(pets):
            sys.exit("%s: two pets share a %s id" % (path, k))
    return pets


def load_vendors(path, pets):
    """The module's own vendor NPCs. Each wears the display of one of the pets or mounts, which is
    what gives the server and the client its model."""
    if not os.path.exists(path):
        return []
    lines = open(path, encoding="utf-8").read().splitlines()
    head = lines[0].split("\t")
    vendors = [dict(zip(head, l.split("\t"))) for l in lines[1:] if l.strip()]
    displays = {p["display"] for p in pets}
    taken = {p["creature"] for p in pets}
    for v in vendors:
        for k in ("creature", "guid", "display", "level", "map"):
            v[k] = int(v[k])
        for k in ("scale", "x", "y", "z", "o"):
            v[k] = float(v[k])
        v["gossip_menu"] = int(v.get("gossip_menu") or 0)
        if v["gossip_menu"]:
            for k in ("text", "text_all"):
                v[k] = int(v[k])
            for k in ("greeting", "greeting_all", "browse"):
                if not v[k]:
                    sys.exit("%s: %s has a gossip menu and no %s" % (path, v["name"], k))
            # the last phase any of its items waits for: past it, nothing is locked
            v["last_tier"] = max((p["tier"] for p in pets if p["vendor"] == v["creature"]), default=0)
        if v["display"] not in displays:
            sys.exit("%s: %s wears display %d, which no row of the pet list has" % (path, v["name"], v["display"]))
        if v["creature"] in taken:
            sys.exit("%s: %s shares creature entry %d with a pet or mount" % (path, v["name"], v["creature"]))
        taken.add(v["creature"])
    if len({v["guid"] for v in vendors}) != len(vendors):
        sys.exit("%s: two vendors share a spawn guid" % path)
    texts = [v[k] for v in vendors if v["gossip_menu"] for k in ("text", "text_all")]
    if len(set(texts)) != len(texts):
        sys.exit("%s: two greetings share a text id" % path)
    return vendors


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
        spell = template(spells, p["kind"]["spell"], "Spell.dbc row")
        spell[0] = p["spell"]
        spell[F_EFFECT_MISC] = p["creature"]
        spell[F_ICON] = p["spell"]
        spell[F_ACTIVE_ICON] = 0
        spell[F_NAME] = add_string(spell_str, p["name"])
        spell[F_DESCRIPTION] = add_string(spell_str, p["summon_text"])
        upsert(spells, spell)
        new_spells.append(spell)

        upsert(abilities, [p["spell"], p["kind"]["skill"], p["spell"], 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0])
        upsert(items, [p["item"], ITEM_CLASS_MISC, p["kind"]["subclass"], UNSET, UNSET, p["item"], 0, 0])
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


def write_gossip(f, vendors):
    """The greeting of each vendor that has one, and the option under it that opens its window. A
    vendor with locked items has two texts on its menu, told apart by the last phase's quest."""
    if not vendors:
        return
    menus = id_list(v["gossip_menu"] for v in vendors)
    f.write("-- Their greetings: one while some item is still locked for the player, one once none is.\n")
    f.write("DELETE FROM `conditions` WHERE `SourceTypeOrReferenceId` = %d AND `SourceGroup` IN (%s);\n" % (
        CONDITION_SOURCE_GOSSIP_MENU, menus))
    f.write("DELETE FROM `gossip_menu_option` WHERE `MenuID` IN (%s);\n" % menus)
    f.write("DELETE FROM `gossip_menu` WHERE `MenuID` IN (%s);\n" % menus)
    f.write("DELETE FROM `npc_text` WHERE `ID` IN (%s);\n" % id_list(v[k] for v in vendors for k in ("text", "text_all")))
    texts, menu, conditions = [], [], []
    for v in vendors:
        shown = [("text_all", "greeting_all", 0)]
        if v["last_tier"]:
            shown.insert(0, ("text", "greeting", 1))
        for text, greeting, negative in shown:
            texts.append("(%d, %s, %s, 0, 0, 1)" % (v[text], sql_str(v[greeting]), sql_str(v[greeting])))
            menu.append("(%d, %d)" % (v["gossip_menu"], v[text]))
            if v["last_tier"]:
                conditions.append("(%d, %d, %d, 0, 0, %d, 0, %d, 0, 0, %d, 0, 0, '', %s)" % (
                    CONDITION_SOURCE_GOSSIP_MENU, v["gossip_menu"], v[text], CONDITION_QUESTREWARDED,
                    PROGRESSION_QUEST + v["last_tier"], negative,
                    sql_str("%s greets a player who has %scleared progression phase %d" % (
                        v["name"], "not " if negative else "", v["last_tier"]))))
    f.write("INSERT INTO `npc_text` (`ID`, `text0_0`, `text0_1`, `BroadcastTextID0`, `lang0`, `Probability0`) VALUES\n")
    f.write(",\n".join(texts) + ";\n")
    f.write("INSERT INTO `gossip_menu` (`MenuID`, `TextID`) VALUES\n")
    f.write(",\n".join(menu) + ";\n")
    f.write("INSERT INTO `gossip_menu_option` (`MenuID`, `OptionID`, `OptionIcon`, `OptionText`, `OptionBroadcastTextID`, `OptionType`, `OptionNpcFlag`, `ActionMenuID`, `ActionPoiID`, `BoxCoded`, `BoxMoney`, `BoxText`, `BoxBroadcastTextID`) VALUES\n")
    f.write(",\n".join("(%d, 0, %d, %s, 0, %d, %d, 0, 0, 0, 0, '', 0)" % (
        v["gossip_menu"], GOSSIP_ICON_VENDOR, sql_str(v["browse"]), GOSSIP_OPTION_VENDOR, NPCFLAG_VENDOR)
        for v in vendors) + ";\n")
    if conditions:
        f.write("INSERT INTO `conditions` (`SourceTypeOrReferenceId`, `SourceGroup`, `SourceEntry`, `SourceId`, `ElseGroup`, `ConditionTypeOrReference`, `ConditionTarget`, `ConditionValue1`, `ConditionValue2`, `ConditionValue3`, `NegativeCondition`, `ErrorType`, `ErrorTextId`, `ScriptName`, `Comment`) VALUES\n")
        f.write(",\n".join(conditions) + ";\n")
    f.write("\n")


def write_sql(path, pets, vendors, new_spells, patch_z, tmp):
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
    creatures += [v["creature"] for v in vendors]
    displays, models = [r[0] for r in cdi], [r[0] for r in cmd]
    with open(path, "w", encoding="utf-8") as f:
        f.write("-- mod-retail-pets: companion pets and mounts with retail models. Generated by tools/build_pets.py from\n")
        f.write("-- data/pets.tsv: change that file and run the tool again, don't edit this one.\n")
        f.write("-- The client needs the module's two patches (see the README), or it shows nothing at all.\n\n")

        f.write("-- The pets and the mounts' creatures.\n")
        if vendors:
            f.write("DELETE FROM `creature` WHERE `guid` IN (%s);\n" % id_list(v["guid"] for v in vendors))
        f.write("DELETE FROM `creature_template_model` WHERE `CreatureID` IN (%s);\n" % id_list(creatures))
        f.write("DELETE FROM `creature_template` WHERE `entry` IN (%s);\n" % id_list(creatures))
        f.write("INSERT INTO `creature_template` (`entry`, `name`, `minlevel`, `maxlevel`, `faction`, `speed_walk`, `speed_run`, `BaseAttackTime`, `RangeAttackTime`, `unit_class`, `unit_flags`, `unit_flags2`, `type`, `movementId`, `flags_extra`) VALUES\n")
        f.write(",\n".join("(%d, %s, 1, 1, %d, 1, 1.14286, 2000, 2000, 1, %d, 2048, %d, %d, %d)" % (
            p["creature"], sql_str(p["name"]), *p["kind"]["creature"]) for p in pets) + ";\n")
        f.write("INSERT INTO `creature_template_model` (`CreatureID`, `Idx`, `CreatureDisplayID`, `DisplayScale`, `Probability`) VALUES\n")
        f.write(",\n".join("(%d, 0, %d, %g, 1)" % (p["creature"], p["display"], p["scale"]) for p in pets) + ";\n\n")

        if vendors:
            f.write("-- Who sells them: friendly to everyone, can't be attacked, a vendor (with a greeting first, if it has one).\n")
            f.write("INSERT INTO `creature_template` (`entry`, `name`, `subname`, `gossip_menu_id`, `minlevel`, `maxlevel`, `faction`, `npcflag`, `speed_walk`, `speed_run`, `BaseAttackTime`, `RangeAttackTime`, `unit_class`, `unit_flags`, `unit_flags2`, `type`, `flags_extra`) VALUES\n")
            f.write(",\n".join("(%d, %s, %s, %d, %d, %d, 35, %d, 1, 1.14286, 2000, 2000, 1, 768, 2048, 7, 2)" % (
                v["creature"], sql_str(v["name"]), sql_str(v["subname"]), v["gossip_menu"], v["level"], v["level"],
                NPCFLAG_VENDOR | (NPCFLAG_GOSSIP if v["gossip_menu"] else 0)) for v in vendors) + ";\n")
            f.write("INSERT INTO `creature_template_model` (`CreatureID`, `Idx`, `CreatureDisplayID`, `DisplayScale`, `Probability`) VALUES\n")
            f.write(",\n".join("(%d, 0, %d, %g, 1)" % (v["creature"], v["display"], v["scale"]) for v in vendors) + ";\n")
            f.write("INSERT INTO `creature` (`guid`, `id`, `map`, `spawnMask`, `phaseMask`, `position_x`, `position_y`, `position_z`, `orientation`, `spawntimesecs`, `wander_distance`, `MovementType`) VALUES\n")
            f.write(",\n".join("(%d, %d, %d, 1, 1, %g, %g, %g, %g, 300, 0, 0)" % (
                v["guid"], v["creature"], v["map"], v["x"], v["y"], v["z"], v["o"]) for v in vendors) + ";\n\n")
        write_gossip(f, [v for v in vendors if v["gossip_menu"]])

        f.write("-- Their summon spells (client: Spell.dbc in the spell patch), on the Companions and Mounts skill lines.\n")
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
        f.write(",\n".join("(%d, %d, %d, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0)" % (p["spell"], p["kind"]["skill"], p["spell"])
                           for p in pets) + ";\n\n")

        f.write("-- The items that teach them, and who sells those.\n")
        f.write("DELETE FROM `npc_vendor` WHERE `item` IN (%s);\n" % id_list(items))
        f.write("DELETE FROM `item_template` WHERE `entry` IN (%s);\n" % id_list(items))
        f.write("INSERT INTO `item_template` (`entry`, `class`, `subclass`, `name`, `displayid`, `Quality`, `Flags`, `BuyPrice`, `SellPrice`, `ItemLevel`, `RequiredSkill`, `RequiredSkillRank`, `delay`, `spellid_1`, `spellcharges_1`, `spellid_2`, `spelltrigger_2`, `bonding`, `description`, `Material`, `BagFamily`) VALUES\n")
        lines = []
        for p in pets:
            flags, skill, rank, bonding, bag = p["kind"]["item"]
            lines.append("(%d, %d, %d, %s, %d, %d, %d, %d, %d, 20, %d, %d, 0, %d, -1, %d, %d, %d, %s, -1, %d)" % (
                p["item"], ITEM_CLASS_MISC, p["kind"]["subclass"], sql_str(p["name"]), p["item"], p["quality"], flags,
                p["price"], p["price"] // 4, skill, rank, SPELL_LEARNING, p["spell"], ITEM_SPELLTRIGGER_LEARN, bonding,
                sql_str("Teaches you how to summon this %s." % ("mount" if p["form"] == "mount" else "companion")), bag))
        f.write(",\n".join(lines) + ";\n")
        f.write("INSERT INTO `npc_vendor` (`entry`, `slot`, `item`, `maxcount`, `incrtime`, `ExtendedCost`) VALUES\n")
        slots = {}
        lines = []
        for p in pets:  # a vendor lists its items in the order of the pet list
            slots[p["vendor"]] = slots.get(p["vendor"], 0) + 1
            lines.append("(%d, %d, %d, 0, 0, 0)" % (p["vendor"], slots[p["vendor"]], p["item"]))
        f.write(",\n".join(lines) + ";\n")
        f.write("DELETE FROM `conditions` WHERE `SourceTypeOrReferenceId` = %d AND `SourceEntry` IN (%s);\n" % (
            CONDITION_SOURCE_NPC_VENDOR, id_list(items)))
        gated = [p for p in pets if p["tier"]]
        if gated:
            f.write("-- A vendor shows and sells an item only to a player who has cleared its progression phase\n")
            f.write("-- (mod-individual-progression's hidden quest 66000 + phase).\n")
            f.write("INSERT INTO `conditions` (`SourceTypeOrReferenceId`, `SourceGroup`, `SourceEntry`, `SourceId`, `ElseGroup`, `ConditionTypeOrReference`, `ConditionTarget`, `ConditionValue1`, `ConditionValue2`, `ConditionValue3`, `NegativeCondition`, `ErrorType`, `ErrorTextId`, `ScriptName`, `Comment`) VALUES\n")
            f.write(",\n".join("(%d, %d, %d, 0, 0, %d, 0, %d, 0, 0, 0, 0, 0, '', %s)" % (
                CONDITION_SOURCE_NPC_VENDOR, p["vendor"], p["item"], CONDITION_QUESTREWARDED,
                PROGRESSION_QUEST + p["tier"],
                sql_str("%s is sold once the player has cleared progression phase %d" % (p["name"], p["tier"])))
                for p in gated) + ";\n")
        f.write("\n")

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
        f.write(",\n".join("(%d, %g, %g, 2, 0)" % (p["display"], *p["kind"]["model"]) for p in pets) + ";\n")
    print("wrote", path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--patch-w", required=True, help="the realm's live spell patch (patch-W.MPQ)")
    ap.add_argument("--patch-z", required=True, help="the built model patch (patch-Z.MPQ)")
    ap.add_argument("--client", required=True, help="the base client folder (has Data/<locale>/)")
    ap.add_argument("--locale", default="enUS")
    ap.add_argument("--cache", required=True, help="download folder, shared with wow-mod-retail-creatures")
    ap.add_argument("--pets", default=os.path.join(HERE, "..", "data", "pets.tsv"))
    ap.add_argument("--vendors", default=os.path.join(HERE, "..", "data", "vendors.tsv"))
    ap.add_argument("--out", required=True, help="the new spell patch")
    ap.add_argument("--sql", help="write the module's world SQL here")
    args = ap.parse_args()

    pets = load_pets(args.pets)
    vendors = load_vendors(args.vendors, pets)
    with tempfile.TemporaryDirectory() as tmp:
        files = unpack(args.patch_w, tmp)
        new_spells = patch_w(files, pets, args, tmp)
        pack(args.out, [(local, name) for name, local in sorted(files.items())])
        print("%s: %d pets and mounts, %d files, %.1f MB" % (args.out, len(pets), len(files), os.path.getsize(args.out) / 1e6))
        if args.sql:
            write_sql(args.sql, pets, vendors, new_spells, args.patch_z, tmp)


if __name__ == "__main__":
    main()
