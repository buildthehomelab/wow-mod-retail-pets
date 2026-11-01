#!/usr/bin/env python3
"""Retail gear for the client: the pieces in data/gear.tsv, with their retail looks converted to
3.3.5, and the module's world SQL for their items.

    python3 build_gear.py --patch <live z80>.MPQ --client /path/to/client --cache <download dir> \\
        --out <new z80>.MPQ --sql ../data/sql/db-world/mod_retail_pets_gear.sql

A row of data/gear.tsv is one item: our item id, the retail item whose look it takes, the mount
item it comes with (the coin shop of wow-mod-boss-coins mails the pieces with that mount) and
its name. The item's ItemDisplayInfo id is its item id.

--patch is the realm's spell patch, the one that carries Item.dbc and ItemDisplayInfo.dbc. A
patch MPQ replaces whole files, so the new rows go into its copies, appended after every old
row, and every other file in it is copied unchanged. It gains:

- Item.dbc and ItemDisplayInfo.dbc: a row per item. The display starts as a copy of a stock one
  of its kind (a cloth helm, shoulders, cloak, staff), so it keeps that kind's sounds.
- The models, converted from retail by wow-mod-retail-creatures' converter (clone it next to
  this repo or set RETAIL_CREATURES), under Item\\ObjectComponents: a helm has one model per
  race and sex (Head\\<name>_HuM.m2 and so on, the client picks the one it needs), shoulders a
  left and a right one (Shoulder), a staff one (Weapon). A cloak is only a texture (Cape) on
  the character's own cape mesh. Several items can share a model and differ only in texture.
- Their textures next to them, and the retail icons Blizzard's own client doesn't have.

Retail's helmet geoset rules (which hair and ears a helm hides) are mapped to the client's own
HelmetGeosetVisData rows by RETAIL_HELMET_VIS; a retail rule the table doesn't know stops the
build.

Running it again on its own output changes nothing. Needs Python 3 and StormLib (`STORMLIB`,
default /usr/local/lib/libstorm.dylib).
"""

import argparse
import csv
import ctypes
import glob
import importlib.util
import os
import struct
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GEAR = os.path.join(ROOT, "data", "gear.tsv")
FIRST, LAST = 90690, 90699     # our gear items and their displays
PREFIX = "Evermore_"           # our model and texture names, apart from any the client has
UNSET = 0xFFFFFFFF

# Retail InventoryType -> (kind, folder under Item\ObjectComponents, 3.3.5 class, subclass, the
# stock ItemDisplayInfo a row starts as). Cosmetic armour (retail subclass 5) is Miscellaneous
# here: anyone can wear it, and transmog takes it for any armour type.
SLOTS = {
    1:  ("head", "Head", 4, 0, 1123),           # Helm_Leather_D_01
    3:  ("shoulder", "Shoulder", 4, 0, 1057),   # Shoulder_Leather_A_01
    16: ("cape", "Cape", 4, 1, 13963),          # Cape_Mage_A_01Black
    17: ("staff", "Weapon", 2, 10, None),       # the first stock staff (Stave_*)
}

# Retail HelmetGeosetVisDataID -> the client's HelmetGeosetVisData row that hides the same. 246
# hides the hair of every race but Tauren (whose horns are hair here), and the ears of every race
# but the Night Elves, Trolls and Blood Elves: retail's hood rule, which also hides Tauren hair,
# because retail's horns are a geoset of their own.
RETAIL_HELMET_VIS = {0: 0, 498: 246, 499: 246}

# Retail race id -> the client's ChrRaces prefix, for a helm's model per race and sex.
RACE_PREFIX = {1: "Hu", 2: "Or", 3: "Dw", 4: "Ni", 5: "Sc", 6: "Ta", 7: "Gn", 8: "Tr", 9: "Go",
               10: "Be", 11: "Dr"}
SEX = {0: "M", 1: "F"}

TABLES = {"Item": 8, "ItemDisplayInfo": 25}
IDI_STRINGS = (1, 2, 3, 4, 5, 6, *range(15, 23))


# --- DBC ---------------------------------------------------------------------------------------

class Dbc:
    def __init__(self, path, table):
        data = open(path, "rb").read()
        magic, count, fields, size, strsize = struct.unpack_from("<4s4I", data, 0)
        if magic != b"WDBC" or size != fields * 4 or fields != TABLES[table]:
            sys.exit("%s.dbc isn't a plain WDBC file with %d fields" % (table, TABLES[table]))
        self.table, self.fields = table, fields
        self.order, self.rows = [], {}
        for i in range(count):
            row = list(struct.unpack_from("<%dI" % fields, data, 20 + i * size))
            if row[0] in self.rows:
                sys.exit("%s.dbc has row %d twice" % (table, row[0]))
            self.order.append(row[0])
            self.rows[row[0]] = row
        self.strings = bytearray(data[20 + count * size:20 + count * size + strsize])

    def write(self, path):
        # Old rows keep their order and new ones go after them: the client's own files are not
        # all in id order, and some of its lookups depend on the order they have.
        with open(path, "wb") as f:
            f.write(struct.pack("<4s4I", b"WDBC", len(self.order), self.fields, self.fields * 4, len(self.strings)))
            for key in self.order:
                f.write(struct.pack("<%dI" % self.fields, *self.rows[key]))
            f.write(self.strings)

    def string(self, at):
        return self.strings[at:self.strings.index(b"\0", at)].decode("utf-8")

    def add_string(self, text):
        if not text:
            return 0
        raw = text.encode("utf-8") + b"\0"
        at = self.strings.find(b"\0" + raw)
        if at >= 0:
            return at + 1
        at = len(self.strings)
        self.strings.extend(raw)
        return at

    def put(self, row):
        """Adds one of our rows, or replaces it in its place on a rebuild."""
        if row[0] not in self.rows:
            self.order.append(row[0])
        self.rows[row[0]] = row


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
    """Extracts every file; returns {archive name: local path}, in the archive's order."""
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
    os.makedirs(folder, exist_ok=True)
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


class Client:
    """The base client's archives, newest first, without the realm patch being rebuilt. stock:
    Blizzard's own archives only (an icon a custom patch has isn't on every player's client)."""

    def __init__(self, folder, locale, skip):
        data = os.path.join(folder, "Data") if os.path.isdir(os.path.join(folder, "Data")) else folder
        loc = os.path.join(data, locale)
        if not os.path.isdir(loc):
            sys.exit("no %s folder in %s: --client is the WoW folder or its Data folder" % (locale, data))
        blizzard = {"patch.mpq", "patch-2.mpq", "patch-3.mpq"}
        extra = sorted((p for p in glob.glob(os.path.join(data, "patch-*.[mM][pP][qQ]"))
                        if os.path.basename(p).lower() not in blizzard | skip), key=lambda p: os.path.basename(p).lower())
        stem = len("patch-" + locale)
        locale_patches = sorted(glob.glob(os.path.join(loc, "patch-%s*.[mM][pP][qQ]" % locale)),
                                key=lambda p: os.path.basename(p).lower()[stem:-4])
        stock_locale = {("patch-%s%s.mpq" % (locale, n)).lower() for n in ("", "-2", "-3")}
        order = extra[::-1] + locale_patches[::-1]
        order += [os.path.join(data, n) for n in ("patch-3.MPQ", "patch-2.MPQ", "patch.MPQ")]
        order += [os.path.join(loc, n % locale) for n in ("lichking-locale-%s.MPQ", "expansion-locale-%s.MPQ",
                                                           "locale-%s.MPQ")]
        order += [os.path.join(data, n) for n in ("lichking.MPQ", "expansion.MPQ", "common-2.MPQ", "common.MPQ")]
        extra_names = {os.path.basename(p).lower() for p in extra}
        self.lib, H = stormlib()
        self.archives, self.stock = [], []
        for path in order:
            if os.path.exists(path):
                self.archives.append((path, open_mpq(self.lib, H, path)))
                name = os.path.basename(path).lower()
                if name not in extra_names and (not name.startswith("patch-%s" % locale.lower()) or name in stock_locale):
                    self.stock.append(self.archives[-1])

    def has_stock(self, name):
        return any(self.lib.SFileHasFile(h, name.encode("latin-1")) for _p, h in self.stock)

    def extract(self, name, dst):
        for path, h in self.archives:
            if self.lib.SFileHasFile(h, name.encode("latin-1")):
                if not self.lib.SFileExtractFile(h, name.encode("latin-1"), dst.encode(), 0):
                    sys.exit("can't extract %s from %s" % (name, path))
                return os.path.basename(path)
        sys.exit("the client has no " + name)


# --- inputs ------------------------------------------------------------------------------------

def load_retail():
    """wow-mod-retail-creatures' build_patch (the converter, the checks and the downloads)."""
    here = os.path.dirname(ROOT)
    for path in (os.environ.get("RETAIL_CREATURES"), os.path.join(here, "mod-retail-creatures"),
                 os.path.join(here, "wow-mod-retail-creatures")):
        if path and os.path.exists(os.path.join(path, "tools", "m2creature.py")):
            tools = os.path.join(path, "tools")
            sys.path.insert(1, tools)
            spec = importlib.util.spec_from_file_location("retail_build_patch", os.path.join(tools, "build_patch.py"))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    sys.exit("wow-mod-retail-creatures not found: clone it next to this repo or set RETAIL_CREATURES")


def load_gear():
    rows = []
    with open(GEAR, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            row = {"item": int(r["item"]), "retail_item": int(r["retail_item"]),
                   "comes_with": int(r["comes_with"]), "name": r["name"].strip()}
            if not FIRST <= row["item"] <= LAST:
                sys.exit("gear item %d is outside %d-%d" % (row["item"], FIRST, LAST))
            rows.append(row)
    if len({r["item"] for r in rows}) != len(rows):
        sys.exit("%s lists an item twice" % GEAR)
    return rows


class RetailItems:
    """What a retail item looks like: its display, models (with the race and sex or side each is
    for) and textures, from wago.tools' DB2 tables."""

    def __init__(self, retail, cache):
        db2, rows = retail.fetch.db2, retail.fetch.db2_rows
        self.items = db2(cache, "Item")
        self.sparse = db2(cache, "ItemSparse")
        self.appearances = db2(cache, "ItemAppearance")
        self.displays = db2(cache, "ItemDisplayInfo")
        self.modified = {}
        for r in rows(cache, "ItemModifiedAppearance"):
            if r["ItemAppearanceModifierID"] == "0":
                self.modified[int(r["ItemID"])] = int(r["ItemAppearanceID"])
        self.models, self.textures = {}, {}
        for r in rows(cache, "ModelFileData"):
            self.models.setdefault(int(r["ModelResourcesID"]), []).append(int(r["FileDataID"]))
        for r in rows(cache, "TextureFileData"):
            self.textures.setdefault(int(r["MaterialResourcesID"]), []).append((int(r["UsageType"]), int(r["FileDataID"])))
        self.components = {int(r["ID"]): r for r in rows(cache, "ComponentModelFileData")}

    def look(self, item):
        if item not in self.modified or str(item) not in self.items or str(item) not in self.sparse:
            sys.exit("retail item %d has no appearance" % item)
        appearance = self.appearances[str(self.modified[item])]
        display = self.displays[appearance["ItemDisplayInfoID"]]
        return self.items[str(item)], self.sparse[str(item)], appearance, display

    def texture(self, material, what):
        found = sorted(self.textures.get(int(material), []))
        if not found:
            sys.exit("%s: material %s has no texture" % (what, material))
        return found[0][1]


# --- building ----------------------------------------------------------------------------------

def client_animations(client, work):
    local = os.path.join(work, "AnimationData.dbc")
    client.extract("DBFilesClient\\AnimationData.dbc", local)
    data = open(local, "rb").read()
    count, fields = struct.unpack_from("<II", data, 4)
    return {struct.unpack_from("<I", data, 20 + i * fields * 4)[0] for i in range(count)}


def stem_of(path):
    return os.path.splitext(os.path.basename(path))[0]


class Builder:
    def __init__(self, retail, cache, client, files, work, max_texture):
        self.retail, self.cache, self.client = retail, cache, client
        self.files, self.work, self.max_texture = files, work, max_texture
        self.valid = client_animations(client, work)
        self.names = {}
        self.textures = {}   # archive name: (file data id, blend modes drawing it)
        self.models = set()  # archive names of models already converted
        self.warnings = []

    def name(self, fdid):
        if fdid not in self.names:
            self.names.update(self.retail.listfile(self.cache, [fdid]))
        if fdid not in self.names:
            sys.exit("file %d isn't in the listfile" % fdid)
        return self.names[fdid]

    def want_names(self, fdids):
        missing = set(fdids) - set(self.names)
        if missing:
            self.names.update(self.retail.listfile(self.cache, missing))

    def texture(self, folder, fdid, use=()):
        """A texture shipped under Item\\ObjectComponents\\<folder>; returns its name without the
        folder and extension, as ItemDisplayInfo names it."""
        name = PREFIX + stem_of(self.name(fdid))
        archive = "Item\\ObjectComponents\\%s\\%s.blp" % (folder, name)
        self.textures.setdefault(archive, (fdid, set()))[1].update(use)
        return name

    def model(self, folder, fdid, stem, skin_fdid):
        """Converts one retail item model to Item\\ObjectComponents\\<folder>\\<stem>.m2. Its own
        textures go next to it; the item's skin (texture type 2) is the display's ModelTexture."""
        archive = "Item\\ObjectComponents\\%s\\%s.m2" % (folder, stem)
        if archive in self.models:
            return
        retail = self.retail
        raw, model, skins, anims = retail.load_model(self.cache, fdid, stem, self.warnings)
        conv = retail.Converter(raw, skins(0), anims, self.valid, stem)
        drawn = conv.batch_textures()
        textures, own = [], {}
        for i, (ttype, tflags, _n, _o) in enumerate(model.arr("textures", "<IIII")):
            fd = model.txid[i] if i < len(model.txid) else 0
            if i not in drawn:
                textures.append((None, tflags, None))
            elif ttype == 0 and fd:
                own[i] = fd
                name = "Item\\ObjectComponents\\%s\\%s.blp" % (folder, PREFIX + stem_of(self.name(fd)))
                textures.append((0, tflags, name))
            elif ttype == 2:
                own[i] = skin_fdid
                textures.append((2, tflags, None))
            else:
                self.warnings.append("%s: texture %d is of type %d (the character's own), not drawn" % (stem, i, ttype))
                textures.append((None, tflags, None))
        m2, skin_out = conv.convert(textures)
        errors, info = retail.check(m2, skin_out)
        if errors:
            sys.exit("%s fails the 3.3.5 checks: %s" % (stem, errors[:5]))
        for i, use in conv.texture_use.items():
            if i in own:
                self.texture(folder, own[i], use)
        for ext, blob in (".m2", m2), ("00.skin", skin_out):
            path = os.path.join(self.work, stem + ext)
            with open(path, "wb") as f:
                f.write(blob)
            self.files["Item\\ObjectComponents\\%s\\%s%s" % (folder, stem, ext)] = path
        self.models.add(archive)
        print("  %s\\%s: %d vertices, %d batches" % (folder, stem, info["vertices"], info["batches"]))

    def icon(self, fdid):
        path = self.name(fdid).replace("/", "\\")
        if not path.lower().startswith("interface\\icons\\") or not path.lower().endswith(".blp"):
            sys.exit("icon %d is %s, not an icon" % (fdid, path))
        icon = stem_of(path.replace("\\", "/"))
        archive = "Interface\\Icons\\%s.blp" % icon
        if archive not in self.files and not self.client.has_stock(archive):
            blp = self.retail.fetch.casc_path(self.cache, fdid)
            if open(blp, "rb").read(4) != b"BLP2":
                sys.exit("icon %d isn't a BLP2 file" % fdid)
            self.files[archive] = blp
        return icon

    def ship_textures(self):
        """A texture drawn only alpha-keyed gets its alpha stretched (retail keeps a texel from
        alpha 128, the 3.3.5 client only from 224): feathers and fringes would come out ragged."""
        for archive, (fdid, use) in sorted(self.textures.items()):
            blp = self.retail.shrink_blp(self.retail.casc(self.cache, fdid), self.max_texture)
            if 1 in use and max(use) < 2:
                blp = self.retail.key_alpha_blp(blp)
            elif 1 in use:
                self.warnings.append("%s is drawn alpha-keyed and blended: not keyed" % archive)
            path = os.path.join(self.work, os.path.basename(archive))
            with open(path, "wb") as f:
                f.write(blp)
            self.files[archive] = path


def staff_template(displays):
    for key in displays.order:
        row = displays.rows[key]
        if row[1] and displays.string(row[1]).lower().startswith("stave_"):
            return key
    sys.exit("ItemDisplayInfo.dbc has no stock staff (Stave_*) to copy")


def add_gear(dbc, gear, builder, looks):
    items, displays = dbc["Item"], dbc["ItemDisplayInfo"]
    out = []
    for g in gear:
        item, sparse, appearance, display = looks.look(g["retail_item"])
        inventory = int(item["InventoryType"])
        if inventory not in SLOTS:
            sys.exit("retail item %d: inventory type %d isn't one this tool builds" % (g["retail_item"], inventory))
        kind, folder, item_class, subclass, template = SLOTS[inventory]
        if kind == "staff" and (int(item["ClassID"]), int(item["SubclassID"])) != (2, 10):
            sys.exit("retail item %d isn't a staff" % g["retail_item"])
        template = template or staff_template(displays)
        if template not in displays.rows:
            sys.exit("ItemDisplayInfo.dbc has no row %d to copy" % template)
        what = "%s (retail %d)" % (g["name"], g["retail_item"])
        print("%d %s, retail display %s" % (g["item"], g["name"], display["ID"]))

        row = list(displays.rows[template])
        for field in IDI_STRINGS:
            row[field] = 0
        row[0] = g["item"]
        row[7:10] = [0, 0, 0]
        row[13:15] = [0, 0]
        row[23] = row[24] = 0
        material = [int(display["ModelMaterialResourcesID_%d" % i]) for i in (0, 1)]
        resources = [int(display["ModelResourcesID_%d" % i]) for i in (0, 1)]

        if kind == "cape":
            if any(resources):
                sys.exit("%s: a cloak with a model (retail's 3D capes can't be drawn here)" % what)
            row[3] = displays.add_string(builder.texture(folder, looks.texture(material[0], what)))
            row[7] = int(display["GeosetGroup_0"])
        else:
            fdids = looks.models.get(resources[0], [])
            if not fdids:
                sys.exit("%s: model resource %d has no files" % (what, resources[0]))
            builder.want_names(fdids)
            skin = looks.texture(material[0], what)
            base = PREFIX + stem_of(builder.name(fdids[0]))
            if kind == "head":
                # One model per race and sex: <base>_<prefix><M|F>, retail's file names end in _<race>_<sex>.
                base = base.rsplit("_", 2)[0]
                done = set()
                for fdid in fdids:
                    c = looks.components.get(fdid)
                    if not c or int(c["RaceID"]) not in RACE_PREFIX or int(c["GenderIndex"]) not in SEX:
                        continue
                    suffix = RACE_PREFIX[int(c["RaceID"])] + SEX[int(c["GenderIndex"])]
                    builder.model(folder, fdid, "%s_%s" % (base, suffix), skin)
                    done.add(suffix)
                missing = [p + s for p in RACE_PREFIX.values() for s in SEX.values() if p + s not in done]
                if missing:
                    builder.warnings.append("%s: no helm model for %s (they show no helm)" % (what, ", ".join(missing)))
                row[1] = displays.add_string(base + ".mdx")
                vis = [int(display["HelmetGeosetVis_%d" % i]) for i in (0, 1)]
                for v in vis:
                    if v not in RETAIL_HELMET_VIS:
                        sys.exit("%s: retail helmet geoset rule %d isn't in RETAIL_HELMET_VIS" % (what, v))
                row[13:15] = [RETAIL_HELMET_VIS[v] for v in vis]
            elif kind == "shoulder":
                # Retail's PositionIndex 0 is the left shoulder, 1 the right; 3.3.5 names them in that order.
                sides = {}
                for fdid in fdids:
                    c = looks.components.get(fdid)
                    if c and c["PositionIndex"] in ("0", "1"):
                        sides[int(c["PositionIndex"])] = fdid
                if sorted(sides) != [0, 1]:
                    sys.exit("%s: shoulders without a left and a right model" % what)
                for side in (0, 1):
                    stem = PREFIX + stem_of(builder.name(sides[side]))
                    builder.model(folder, sides[side], stem, skin)
                    row[1 + side] = displays.add_string(stem + ".mdx")
                    row[3 + side] = displays.add_string(builder.texture(folder, skin))
            else:
                if len(fdids) != 1:
                    sys.exit("%s: %d model files, not one" % (what, len(fdids)))
                builder.model(folder, fdids[0], base, skin)
                row[1] = displays.add_string(base + ".mdx")
            if kind != "shoulder":
                row[3] = displays.add_string(builder.texture(folder, skin))

        row[5] = displays.add_string(builder.icon(int(appearance["DefaultIconFileDataID"])))
        displays.put(row)
        sheath = int(item["SheatheType"]) if kind == "staff" else 0
        items.put([g["item"], item_class, subclass, UNSET, int(item["Material"]) & 0xFFFFFFFF, g["item"],
                   inventory, sheath])
        out.append(dict(g, item_class=item_class, subclass=subclass, inventory=inventory, sheath=sheath,
                        material=int(item["Material"]), quality=int(sparse["OverallQualityID"]),
                        delay=int(sparse["ItemDelay"]), kind=kind))
    return out


# --- SQL ---------------------------------------------------------------------------------------

def sql_str(s):
    return "'" + s.replace("\\", "\\\\").replace("'", "''") + "'"


def write_sql(path, rows):
    ids = ", ".join(str(r["item"]) for r in rows)
    cols = ("`entry`, `class`, `subclass`, `SoundOverrideSubclass`, `name`, `displayid`, `Quality`, `Flags`, "
            "`BuyPrice`, `SellPrice`, `InventoryType`, `AllowableClass`, `AllowableRace`, `ItemLevel`, "
            "`RequiredLevel`, `maxcount`, `stackable`, `dmg_min1`, `dmg_max1`, `dmg_type1`, `delay`, "
            "`bonding`, `description`, `Material`, `sheath`, `MaxDurability`")
    values = []
    for r in rows:
        staff = r["kind"] == "staff"
        # A look to wear, nothing more: no stats, no armour, no durability; the staff hits for 1-2.
        values.append("(%d, %d, %d, -1, %s, %d, %d, 0, 0, 0, %d, -1, -1, 1, 0, 0, 1, %d, %d, 0, %d, 1, '', %d, %d, 0)"
                      % (r["item"], r["item_class"], r["subclass"], sql_str(r["name"]), r["item"], r["quality"],
                         r["inventory"], 1 if staff else 0, 2 if staff else 0, r["delay"] if staff else 0,
                         r["material"], r["sheath"]))
    text = ["-- mod-retail-pets: retail gear (data/gear.tsv), the looks that come with some mounts.",
            "-- Generated by tools/build_gear.py: run it again, don't edit this file.",
            "-- The client draws them from the realm's spell patch (Item.dbc + ItemDisplayInfo.dbc rows",
            "-- %d-%d and their models), which the same tool builds." % (FIRST, LAST),
            "",
            "DELETE FROM `item_template` WHERE `entry` IN (%s);" % ids,
            "INSERT INTO `item_template` (%s) VALUES\n%s;" % (cols, ",\n".join(values)),
            ""]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(text))
    print("wrote", os.path.relpath(path))


# --- main --------------------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--patch", required=True, help="the realm's spell patch (has Item.dbc and ItemDisplayInfo.dbc)")
    ap.add_argument("--client", required=True, help="the WoW folder (or its Data folder) the patch goes on")
    ap.add_argument("--locale", default="enUS")
    ap.add_argument("--cache", required=True, help="download folder, shared with wow-mod-retail-creatures")
    ap.add_argument("--out", help="the new spell patch")
    ap.add_argument("--sql", help="write the module's gear SQL here")
    ap.add_argument("--max-texture", type=int, default=512, help="largest texture side (default 512)")
    args = ap.parse_args()
    if not args.out and not args.sql:
        sys.exit("nothing to do: give --out, --sql or both")
    if args.out and os.path.abspath(args.out) == os.path.abspath(args.patch):
        sys.exit("--out would overwrite --patch")

    retail = load_retail()
    gear = load_gear()
    client = Client(args.client, args.locale, {os.path.basename(args.patch).lower()})
    looks = RetailItems(retail, args.cache)
    with tempfile.TemporaryDirectory() as tmp:
        files = unpack(args.patch, os.path.join(tmp, "patch"))
        work = os.path.join(tmp, "work")
        os.makedirs(work)
        dbc = {}
        for table in TABLES:
            name = "DBFilesClient\\%s.dbc" % table
            if name not in files:
                sys.exit("%s has no %s" % (args.patch, name))
            dbc[table] = Dbc(files[name], table)
        for table, (first, last) in (("Item", (FIRST, LAST)), ("ItemDisplayInfo", (FIRST, LAST))):
            for key in dbc[table].rows:
                if first <= key <= last and key not in {g["item"] for g in gear}:
                    sys.exit("%s.dbc has row %d in our block that data/gear.tsv doesn't" % (table, key))

        builder = Builder(retail, args.cache, client, files, work, args.max_texture)
        rows = add_gear(dbc, gear, builder, looks)
        builder.ship_textures()
        for table in TABLES:
            dbc[table].write(files["DBFilesClient\\%s.dbc" % table])
        if args.out:
            pack(args.out, [(local, name) for name, local in files.items()])
            print("%s: %d files, %.1f MB" % (args.out, len(files), os.path.getsize(args.out) / 1e6))
        if args.sql:
            write_sql(args.sql, rows)
    for warning in builder.warnings:
        print("warning:", warning)


if __name__ == "__main__":
    main()
