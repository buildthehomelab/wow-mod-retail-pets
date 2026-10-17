# Retail Pets

Companion (non-combat) pets and mounts from later expansions for an
[AzerothCore](https://www.azerothcore.org/) (WotLK 3.3.5a) server, with their retail models
converted for the 3.3.5a client. Most are red pandas, sold by one of their own: **Nari
Rustpaw**, a red panda breeder on the Booty Bay boardwalk.

| Companions (1 gold each) | Looks like |
|---|---|
| **Red Panda**, **Sunfur Panda**, **Snowy Panda**, **Mountain Panda**, **Moonfur Panda** | The four-legged red panda of Pandaria, in its red, orange, pale, tan and blue coats |
| **Red Panda Backpacker**, **Azure**, **Ashen**, **Crimson** and **Violet Panda Backpacker** | The upright red panda with a scarf and a backpack, in five colours |

| Mounts (10 gold each) | Looks like |
|---|---|
| **Great Red Panda**, **Great Azure**, **Ashen**, **Crimson** and **Violet Panda** | A red panda big enough to ride, carrying a chair and a tea set, in five colours |

| Not sold by Nari | Looks like |
|---|---|
| **Whoofle Bramblewing** | A plump little owl with a warm glow, retail's shop mount. A mount that flies, a druid's Flight Form look, and the achievement **Owl Be Seeing You** |
| **Armadillo Pup**, **Dark Phoenix Hatchling**, **Lil' Tarecgosa** (companions) | Cataclysm's guild reward pets |
| **Golden King**, **Kor'kron Annihilator** (mounts), **Dark Phoenix** (a mount that flies) | Cataclysm's guild reward mounts: a golden lion, a scorpion, a shadowy phoenix |

These items have no vendor: hand them out some other way, such as a shop (the launcher shop of
[mod-boss-coins](https://github.com/buildthehomelab/wow-mod-boss-coins) has Whoofle Bramblewing
for free), a reward or a GM's `.additem 90215`. The guild vendors of
[mod-guild-levels](https://github.com/buildthehomelab/wow-mod-guild-levels) sell the six guild
reward pets and mounts (90216-90221). Those six wear looks from
[mod-retail-library](https://github.com/buildthehomelab/wow-mod-retail-library) (displays 236220,
237136, 238614, 236213, 237138, 237145) and have no model in this module's patch, so they need
that module and its patches.

Each is learned from an item and shows up on the Pets or the Mounts tab of the character window,
like any stock companion or mount. They keep their retail animations: the Backpacker has 149 of
them, including sitting, sleeping, eating and dancing.

The mounts are ground mounts that ask for Apprentice Riding and no level. Their spell is a copy of
a stock 100% mount, so they are epic-speed mounts unless the server scales mount speed itself
(such as [mod-mount-scaling](https://github.com/buildthehomelab/wow-mod-mount-scaling), which
treats them like every other ground mount).

Whoofle Bramblewing is a **flyer**, like retail's mounts: the same ground mount, and once its
rider has Expert Riding (225) it also flies, at +150%, or +280% with Artisan Riding (300), wherever
a stock flying mount can (Outland, and Northrend with Cold Weather Flying). The module's script
(`src/RetailPetsFlyer.cpp`) gives the rider one of two server-only flight auras, 90230 or 90231,
while the mount is up and the place allows it; the core turns flying on and off from them. A
server that scales flying speed (mod-mount-scaling) scales those too.

**Mount and form.** With [mod-transmog-plus](https://github.com/buildthehomelab/wow-mod-transmog-plus)
(1.12.0 or later), the owl is also a Flight Form look in its Forms tab: a druid who knows the
mount has the look, and gets a chat line when they learn it. Druids who don't see it locked,
with what it comes with. The form is the owl without its saddle: a model of its own (display
97016), so the mount keeps the saddle.

**Achievement.** Learning the owl earns **Owl Be Seeing You** (Feats of Strength, no points). With
mod-accountwide-mounts, the account's other characters learn the mount, and earn it, as they
log in. It is an Achievement.dbc row in the spell patch, the same row in `achievement_dbc`, and
one "learn spell" criterion; the core awards it by itself.

## Progression

With [mod-individual-progression](https://github.com/ZhengPeiRu21/mod-individual-progression)
on the server, Nari only shows and sells what a player's own progression has unlocked:

| Sold once the player has cleared | Phase | Companions | Mount |
|---|---|---|---|
| nothing: from the start | 0 | Red Panda, Red Panda Backpacker | |
| Molten Core | 1 | Sunfur Panda, Crimson Panda Backpacker | Great Red Panda |
| Onyxia's Lair | 2 | Mountain Panda | |
| Blackwing Lair | 3 | Ashen Panda Backpacker | Great Crimson Panda |
| the Temple of Ahn'Qiraj | 6 | Moonfur Panda, Azure Panda Backpacker | Great Ashen Panda |
| Naxxramas (level 60) | 7 | Snowy Panda, Violet Panda Backpacker | Great Azure Panda |
| the Into the Breach quest (Outland opens) | 8 | | Great Violet Panda |

She says so before she opens her window: one greeting while some of her pandas are still locked
for the player, another once none is.

The phase is the `tier` column of `data/pets.tsv`. It becomes a vendor condition on that module's
hidden quest 66000 + phase, so the server refuses the purchase too, not just the listing. Set
every `tier` to 0 to sell everything to everyone. Without mod-individual-progression the server
has no such quests: it logs each condition as skipped at startup and Nari sells everything.

Everything is listed in [`data/pets.tsv`](data/pets.tsv), one row per pet or mount. Another
retail creature becomes one by adding a row and running the two tools below.

Not converted: particle effects, so the steam over the mounts' teapot is missing.

## Patch Notes: Red Panda Companions

Category: Collections

- A red panda breeder, **Nari Rustpaw**, has set up on the Booty Bay boardwalk. She sells red panda
  companions, among them the **Red Panda** and the **Red Panda Backpacker**, and the rideable
  **Great Red Panda**.
- Companions appear on the Pets tab and mounts on the Mounts tab once learned, like any other.
- Nari starts you off with two companions. The other coats and the mounts join her stock as you
  clear raids: Molten Core brings the first mount, and the last arrives when the Dark Portal opens.

> Red pandas arrived in Azeroth with Mists of Pandaria. Booty Bay never asks where anything came
> from, so that is where Nari opened shop.

## Requirements

- AzerothCore wotlk (master) with the WotLK 3.3.5a (12340) client.
- **Two client patches for every player.** Each pet or mount is a new model, a new spell and a new
  item, none of which the 3.3.5a client knows:
  - the model patch (`patch-Z.MPQ` in the examples below): the models, their textures, and
    `CreatureDisplayInfo.dbc` / `CreatureModelData.dbc` with their rows;
  - the spell patch (`patch-W.MPQ` in the examples; if another patch already ships your
    `Spell.dbc`, use that one): `Spell.dbc`, `SkillLineAbility.dbc`, `Item.dbc`,
    `ItemDisplayInfo.dbc` and `SpellIcon.dbc` with their rows, and the icons; `Achievement.dbc`
    and `Achievement_Criteria.dbc` for the achievements.

  A player without the model patch sees nothing where a pet stands, and a rider floating without
  a mount. A player without the spell patch can't learn or summon one.
- Works with [mod-accountwide-pets](https://github.com/buildthehomelab/wow-mod-accountwide-pets)
  and [mod-accountwide-mounts](https://github.com/buildthehomelab/wow-mod-accountwide-mounts):
  the pets are on the Companions skill line and the mounts on the Mounts one, so they are shared
  like the stock ones.

No Blizzard file is kept in this repository. The tools download the retail files they convert.

## Install

```bash
cd azerothcore-wotlk/modules
git clone https://github.com/buildthehomelab/wow-mod-retail-pets.git mod-retail-pets
```

The folder must be named `mod-retail-pets`, because AzerothCore derives the loader name from it.
Re-run CMake and rebuild: the flyer mounts have a script. The world database rows in
`data/sql/db-world` are applied when the server starts. There is no config file.

Put both client patches in every player's `Data` folder before the server runs with the module.

## Building the client patches

Both tools need Python 3 and StormLib (`STORMLIB`, default `/usr/local/lib/libstorm.dylib`), and
download retail files from wago.tools into a cache folder.

**1. The model patch.** This repo is a pack for
[wow-mod-retail-creatures](https://github.com/buildthehomelab/wow-mod-retail-creatures), which
converts the models (`pack.json` tells it where the ids start):

```bash
python3 wow-mod-retail-creatures/tools/build_patch.py --pack mod-retail-pets \
    --dbc dbc/ --cache ~/creatures-cache --work ~/pets-work --out patch-Z.MPQ
```

`dbc/` holds the `CreatureDisplayInfo.dbc` and `CreatureModelData.dbc` your players already have,
plus the client's `AnimationData.dbc`. A patch replaces whole files, so if another patch ships
those two DBCs, build on the copies from the last one to load and give this patch a later letter.
For example, if you also run the wow-mod-retail-druid-forms and wow-mod-retail-shaman-totems
packs, their patches ship those DBCs: build on the one that loads last, and **rebuild the model
patch whenever one of them changes**.

Leave out the builder's `--sql`: that file is for mod-transmog-plus. The next tool writes this
module's SQL.

**2. The spell patch and the SQL.**

```bash
python3 tools/build_pets.py --patch-w patch-W.MPQ --patch-z patch-Z.MPQ --client /path/to/client \
    --cache ~/creatures-cache --out patch-W-new.MPQ --sql data/sql/db-world/mod_retail_pets.sql
```

It copies `patch-W.MPQ`, adds the pets' and mounts' rows and icons to it and writes
`data/sql/db-world/mod_retail_pets.sql` from `data/pets.tsv` and the built model patch. If your
spell patch has no `SpellIcon.dbc`, `Achievement.dbc` or `Achievement_Criteria.dbc`, the
client's own copy is the base. Running it again on its
own output changes nothing.

## What it adds to the database

All in the world database, all from `data/pets.tsv`:

| Table | Rows |
|---|---|
| `creature_template`, `creature_template_model` | 9502000-9502009 the pets, 9502010-9502015 the mounts, 9502016 the owl flight form's preview, 9502017-9502022 the guild reward pets and mounts |
| `spell_dbc`, `skilllineability_dbc` | 90200-90221: the summon spells |
| `spell_script_names` | 90215 and 90221: the flyer script on Whoofle Bramblewing's and the Dark Phoenix's spells |
| `spell_dbc` | 90230-90231: the flyers' flight auras (server only) |
| `item_template`, `npc_vendor` | 90200-90221: the items; Nari Rustpaw sells 90200-90214 |
| `achievement_dbc`, `achievement_criteria_dbc` | 9215 and criterion 19215: Owl Be Seeing You (the module keeps 9200-9229 and 19200-19229) |
| `mod_transmog_plus_forms`, `mod_transmog_plus_form_spells` | 97016: Whoofle Bramblewing (no saddle) as a flight form look, unlocked by spell 90215 |
| `conditions` | vendor conditions (source type 23) on those items: the progression phase each one waits for |
| `creature_template`, `creature_template_model`, `creature` | 9502090: Nari Rustpaw and her spawn (guid 9502090) in Booty Bay |
| `gossip_menu`, `gossip_menu_option`, `npc_text` | menu 9502090 and texts 9502090-9502091: her two greetings and the option that opens her window |
| `conditions` | gossip conditions (source type 14) on menu 9502090: which greeting a player gets |
| `creaturedisplayinfo_dbc`, `creature_model_info` | 97000-97016: the model patch's displays |
| `creaturemodeldata_dbc` | 97000-97004: the model patch's five models |

A pet or mount has the same last digits everywhere: row 5 of the list is creature 9502005,
spell and item 90205 and display 97005 (from the guild rewards on, the creature is one ahead:
9502016 went to the owl's flight form). A row wearing a mod-retail-library look keeps that
library's display id (200000 + the retail display) and leaves `retail_display` empty, so the
model patch skips it and the SQL leaves its display rows to the library. Reserved for more: creatures 9502000-9502099 (vendors
from 9502090, and their gossip menus and texts), spells and items 90200-90229, displays and models 97000-97099. In the client patches the spell icon and the skill line row use the spell's
id, and the item display uses the item's.

## Columns of data/pets.tsv

The first eight are what wow-mod-retail-creatures reads; the rest are this module's.

| Column | Meaning |
|---|---|
| `display` | CreatureDisplayInfo id of the pet or mount |
| `retail_display` | the retail CreatureDisplayInfo id it is converted from |
| `form` | `pet`, `mount`, `flyer` (a mount that also flies) or `look` (only a druid form look): which stock display the builder clones for sounds and size (`template` in `pack.json`), and what `build_pets.py` makes of the row |
| `tier` | the mod-individual-progression phase (0-18) a player has to have cleared before the vendor sells it; `0` = from the start |
| `model` | name of the model's folder and files, in snake_case |
| `name` | name of the pet or mount, its spell and its item |
| `variant`, `textures` | empty (builder options the pets don't use) |
| `creature`, `spell`, `item` | its ids |
| `icon_fdid`, `icon` | retail file data id of the icon, and its file name in `Interface\Icons` |
| `scale` | the creature's `DisplayScale`, on top of the retail display's own scale (a mount is drawn at its display's scale whatever this says) |
| `quality` | item quality: 3 rare, 4 epic |
| `price` | buy price in copper |
| `vendor` | `creature_template` entry of the NPC that sells the item: one of `data/vendors.tsv`, or a creature the server already has; `0` for none |
| `summon_text` | description of the summon spell |
| `druid_form` | empty, or the druid form (`flight`, `travel`, ...) the model is also a mod-transmog-plus look for, unlocked by knowing the spell |
| `hide` | empty, or retail texture file ids (comma-separated) whose meshes the builder leaves out, giving the row a model of its own: the owl flight form leaves out the saddle (7768244) |
| `achievement`, `achievement_name`, `achievement_text` | empty, or an achievement for learning the spell: its id (9200-9229; the criterion is id + 10000), title and description |

## Columns of data/vendors.tsv

The module's own vendors. The SQL makes each one (level `level`, friendly to both factions, can't
be attacked) and spawns it. The last six columns are optional: leave `gossip_menu` empty and a
click opens the vendor window straight away.

| Column | Meaning |
|---|---|
| `creature`, `guid` | `creature_template` entry and spawn guid |
| `name`, `subname` | the NPC's name and the title under it |
| `display`, `scale` | the display it wears, which has to be one from `data/pets.tsv`, and its `DisplayScale` |
| `map`, `x`, `y`, `z`, `o` | where it stands and which way it faces (in game: `.gps`) |
| `gossip_menu` | id of its gossip menu; with one, a click shows a greeting first |
| `text`, `greeting` | `npc_text` id and words of the greeting for a player who can't buy everything yet (`$c` class, `$n` name, `$B` line break) |
| `text_all`, `greeting_all` | the same for a player who can buy everything, and for everyone if no item of the vendor has a `tier` |
| `browse` | the gossip option that opens the vendor window |

## Uninstalling

Remove the module folder, rebuild (the module has a script), and delete its rows:

```sql
DELETE FROM `mod_transmog_plus_form_spells` WHERE `DisplayId` BETWEEN 97000 AND 97099;
DELETE FROM `mod_transmog_plus_forms` WHERE `DisplayId` BETWEEN 97000 AND 97099;
DELETE FROM `achievement_criteria_dbc` WHERE `ID` BETWEEN 19200 AND 19229;
DELETE FROM `achievement_dbc` WHERE `ID` BETWEEN 9200 AND 9229;
DELETE FROM `spell_script_names` WHERE `spell_id` BETWEEN 90200 AND 90229;
DELETE FROM `conditions` WHERE `SourceTypeOrReferenceId` = 23 AND `SourceEntry` BETWEEN 90200 AND 90229;
DELETE FROM `conditions` WHERE `SourceTypeOrReferenceId` = 14 AND `SourceGroup` = 9502090;
DELETE FROM `gossip_menu_option` WHERE `MenuID` = 9502090;
DELETE FROM `gossip_menu` WHERE `MenuID` = 9502090;
DELETE FROM `npc_text` WHERE `ID` BETWEEN 9502090 AND 9502091;
DELETE FROM `npc_vendor` WHERE `item` BETWEEN 90200 AND 90229;
DELETE FROM `item_template` WHERE `entry` BETWEEN 90200 AND 90229;
DELETE FROM `skilllineability_dbc` WHERE `ID` BETWEEN 90200 AND 90229;
DELETE FROM `spell_dbc` WHERE `ID` BETWEEN 90200 AND 90231;
DELETE FROM `creature` WHERE `guid` = 9502090;
DELETE FROM `creature_template_model` WHERE `CreatureID` BETWEEN 9502000 AND 9502090;
DELETE FROM `creature_template` WHERE `entry` BETWEEN 9502000 AND 9502090;
DELETE FROM `creature_model_info` WHERE `DisplayID` BETWEEN 97000 AND 97099;
DELETE FROM `creaturemodeldata_dbc` WHERE `ID` BETWEEN 97000 AND 97099;
DELETE FROM `creaturedisplayinfo_dbc` WHERE `ID` BETWEEN 97000 AND 97099;
```

Characters that learned a pet or mount keep an unknown spell, which the server drops at their
next login.

## Credits

The models, textures and icons are Blizzard Entertainment's, from World of Warcraft. The converter
is [wow-mod-retail-creatures](https://github.com/buildthehomelab/wow-mod-retail-creatures).

## License

MIT, see [LICENSE](LICENSE). It covers this repository's code and data, not Blizzard's assets.
