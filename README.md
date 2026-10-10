# Retail Pets

Companion (non-combat) pets from later expansions for an [AzerothCore](https://www.azerothcore.org/)
(WotLK 3.3.5a) server, with their retail models converted for the 3.3.5a client.

| Pet | Looks like | Sold by |
|---|---|---|
| **Red Panda** | The four-legged red panda of Pandaria, in its red coat | Narkk, Booty Bay |
| **Red Panda Backpacker** | The upright red panda with a scarf and a backpack | Narkk, Booty Bay |

Both are learned from an item (1 gold each), show up on the Pets tab of the character window and
are summoned and dismissed like any other companion. They keep their retail animations: the
Backpacker has 149 of them, including sitting, sleeping, eating and dancing.

The pets are listed in [`data/pets.tsv`](data/pets.tsv), one row each. Another retail creature
becomes a pet by adding a row and running the two tools below.

## Patch Notes: Red Panda Companions

Category: Collections

- **Narkk** in Booty Bay now sells two new companions: the **Red Panda** and the
  **Red Panda Backpacker**.
- Both pets appear on the Pets tab once learned, like any other companion.

> Red pandas arrived in Azeroth with Mists of Pandaria. Narkk already deals in exotic animals, so
> he was the obvious smuggler.

## Requirements

- AzerothCore wotlk (master) with the WotLK 3.3.5a (12340) client.
- **Two client patches for every player.** The pets are new models, a new spell and a new item,
  none of which the 3.3.5a client knows:
  - the model patch (ours is `patch-Z.MPQ`): the models, their textures, and
    `CreatureDisplayInfo.dbc` / `CreatureModelData.dbc` with the pets' rows;
  - the spell patch (ours is `patch-W.MPQ`, which other modules share): `Spell.dbc`,
    `SkillLineAbility.dbc`, `Item.dbc`, `ItemDisplayInfo.dbc` and `SpellIcon.dbc` with the pets'
    rows, and the two icons.

  A player without the model patch sees nothing where the pet stands. A player without the spell
  patch can't learn or summon one.
- Works with [mod-accountwide-pets](https://github.com/buildthehomelab/wow-mod-accountwide-pets):
  the pets are on the Companions skill line, so they are shared like the stock ones.

No Blizzard file is kept in this repository. The tools download the retail files they convert.

## Install

```bash
cd azerothcore-wotlk/modules
git clone https://github.com/buildthehomelab/wow-mod-retail-pets.git mod-retail-pets
```

The folder must be named `mod-retail-pets`, because AzerothCore derives the loader name from it.
Re-run CMake and rebuild. The world database rows in `data/sql/db-world` are applied when the
server starts. There is no config file.

Put both client patches in every player's `Data` folder before the server runs with the module.

## Building the client patches

Both tools need Python 3 and StormLib (`STORMLIB`, default `/usr/local/lib/libstorm.dylib`), and
download retail files from wago.tools into a cache folder.

**1. The model patch.** This repo is a pack for
[wow-mod-retail-creatures](https://github.com/buildthehomelab/wow-mod-retail-creatures), which
converts the models (`pack.json` tells it where the pets' ids start):

```bash
python3 wow-mod-retail-creatures/tools/build_patch.py --pack mod-retail-pets \
    --dbc dbc/ --cache ~/creatures-cache --work ~/pets-work --out patch-Z.MPQ
```

`dbc/` holds the `CreatureDisplayInfo.dbc` and `CreatureModelData.dbc` your players already have,
plus the client's `AnimationData.dbc`. A patch replaces whole files, so if another patch ships
those two DBCs, build on the copies from the last one to load and give this patch a later letter.
On our realm that is `patch-V.MPQ` (the shaman totems): **rebuild patch-Z whenever patch-R or
patch-V changes**.

Leave out the builder's `--sql`: that file is for mod-transmog-plus. The next tool writes this
module's SQL.

**2. The spell patch and the SQL.**

```bash
python3 tools/build_pets.py --patch-w patch-W.MPQ --patch-z patch-Z.MPQ --client /path/to/client \
    --cache ~/creatures-cache --out patch-W-new.MPQ --sql data/sql/db-world/mod_retail_pets.sql
```

It copies `patch-W.MPQ`, adds the pets' rows and icons to it and writes
`data/sql/db-world/mod_retail_pets.sql` from `data/pets.tsv` and the built model patch. If your
spell patch has no `SpellIcon.dbc`, the client's own copy is the base. Running it again on its
own output changes nothing.

## What it adds to the database

All in the world database, all from `data/pets.tsv`:

| Table | Rows |
|---|---|
| `creature_template`, `creature_template_model` | 9502000 Red Panda, 9502001 Red Panda Backpacker |
| `spell_dbc`, `skilllineability_dbc` | 90200, 90201: the summon spells |
| `item_template`, `npc_vendor` | 90200, 90201: the items, sold by Narkk (2663) |
| `creaturedisplayinfo_dbc`, `creaturemodeldata_dbc`, `creature_model_info` | 97000, 97001: the model patch's rows |

Reserved for more pets: creatures 9502000-9502099, spells and items 90200-90229, displays and
models 97000-97099. In the client patches the spell icon and the skill line row use the spell's
id, and the item display uses the item's.

## Columns of data/pets.tsv

The first eight are what wow-mod-retail-creatures reads; the rest are this module's.

| Column | Meaning |
|---|---|
| `display` | CreatureDisplayInfo id of the pet |
| `retail_display` | the retail CreatureDisplayInfo id it is converted from |
| `form`, `tier` | always `pet` and `0` (the builder's kind of look and unlock tier) |
| `model` | name of the model's folder and files, in snake_case |
| `name` | name of the pet, its spell and its item |
| `variant`, `textures` | empty (builder options the pets don't use) |
| `creature`, `spell`, `item` | the pet's ids |
| `icon_fdid`, `icon` | retail file data id of the icon, and its file name in `Interface\Icons` |
| `scale` | the creature's `DisplayScale`, on top of the retail display's own scale |
| `price` | buy price in copper |
| `vendor` | `creature_template` entry of the NPC that sells the item |
| `summon_text` | description of the summon spell |

## Uninstalling

Remove the module folder, rebuild, and delete its rows:

```sql
DELETE FROM `npc_vendor` WHERE `item` IN (90200, 90201);
DELETE FROM `item_template` WHERE `entry` IN (90200, 90201);
DELETE FROM `skilllineability_dbc` WHERE `ID` IN (90200, 90201);
DELETE FROM `spell_dbc` WHERE `ID` IN (90200, 90201);
DELETE FROM `creature_template_model` WHERE `CreatureID` IN (9502000, 9502001);
DELETE FROM `creature_template` WHERE `entry` IN (9502000, 9502001);
DELETE FROM `creature_model_info` WHERE `DisplayID` IN (97000, 97001);
DELETE FROM `creaturemodeldata_dbc` WHERE `ID` IN (97000, 97001);
DELETE FROM `creaturedisplayinfo_dbc` WHERE `ID` IN (97000, 97001);
```

Characters that learned a pet keep an unknown spell, which the server drops at their next login.

## Credits

The models, textures and icons are Blizzard Entertainment's, from World of Warcraft. The converter
is [wow-mod-retail-creatures](https://github.com/buildthehomelab/wow-mod-retail-creatures).

## License

MIT, see [LICENSE](LICENSE). It covers this repository's code and data, not Blizzard's assets.
