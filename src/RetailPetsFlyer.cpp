/*
 * mod-retail-pets: mounts that fly where flying mounts can (the "flyer" rows of data/pets.tsv).
 *
 * A flyer's summon spell is a ground mount like the pandas': a mounted aura and +100% mounted
 * speed, usable with Apprentice Riding. While it is up, the rider also gets one of two
 * server-only auras, picked by riding skill, each a single "mounted flight speed" effect like
 * the one every flying mount spell carries:
 *   90230  +150% flight speed   riding skill 225 (Expert)
 *   90231  +280% flight speed   riding skill 300 (Artisan)
 * The core does the rest from that effect: it switches flying on and off for the client and sets
 * the flight speed. The client doesn't know these two spells, so they show no buff; the mount's
 * own buff is the one players see and cancel. This is how retail's mounts work: one mount, on
 * the ground or in the air depending on the rider and the place.
 *
 * Where it flies is the core's rule, not ours. Both auras carry the same "only in flying areas"
 * attribute as stock flying mounts, so SpellInfo::CheckLocation allows them only where a Swift
 * Blue Gryphon could be summoned (Outland, and Northrend with Cold Weather Flying). Once on, the
 * aura is kept the way the core keeps a stock flying mount's: only the lenient check, so riding
 * into Dalaran or a Wintergrasp battle gets the core's warning and parachute (its area spells
 * look for exactly this kind of aura) instead of a drop out of the sky. Where even that check
 * fails, the core removes the aura itself and the mount carries on on the ground.
 *
 * The auras are passive, so they are not saved at logout. After a login or an area change the
 * area-update hook puts the right one back if the rider is still on a flyer.
 *
 * Released under the MIT License.
 */

#include "Battlefield.h"
#include "BattlefieldMgr.h"
#include "Player.h"
#include "ScriptMgr.h"
#include "SpellAuraEffects.h"
#include "SpellAuras.h"
#include "SpellInfo.h"
#include "SpellMgr.h"
#include "SpellScript.h"
#include "SpellScriptLoader.h"

#include <array>

namespace
{
    constexpr char const* FLYER_SCRIPT = "spell_retail_pets_flyer";

    constexpr uint32 SPELL_FLYER_FLIGHT = 90230;       // +150% mounted flight speed
    constexpr uint32 SPELL_FLYER_FLIGHT_FAST = 90231;  // +280% mounted flight speed

    constexpr uint16 RIDING_SKILL_EXPERT = 225;
    constexpr uint16 RIDING_SKILL_ARTISAN = 300;

    constexpr std::array<uint32, 2> flightSpells = { SPELL_FLYER_FLIGHT, SPELL_FLYER_FLIGHT_FAST };

    // The rider is on one of the module's flyers (any spell with this script on its mounted aura).
    bool IsOnFlyer(Player* player)
    {
        for (AuraEffect* effect : player->GetAuraEffectsByType(SPELL_AURA_MOUNTED))
            if (effect->GetBase()->GetScriptByName(FLYER_SCRIPT))
                return true;
        return false;
    }

    // The flight aura this rider should have right now, or 0 for none. areaId is passed in because
    // during an area update the player's own area id is still the old one.
    uint32 WantedFlightSpell(Player* player, uint32 areaId)
    {
        // not in world: the mount aura is being loaded at login, before the player has a zone
        if (!player->IsInWorld() || !player->IsAlive() || !IsOnFlyer(player))
            return 0;

        uint16 riding = player->GetPureSkillValue(SKILL_RIDING);
        if (riding < RIDING_SKILL_EXPERT)
            return 0;

        uint32 spellId = riding >= RIDING_SKILL_ARTISAN ? SPELL_FLYER_FLIGHT_FAST : SPELL_FLYER_FLIGHT;
        SpellInfo const* spellInfo = sSpellMgr->GetSpellInfo(spellId);
        if (!spellInfo)
            return 0;

        // Flying already: keep it as the core keeps a stock flying mount's aura (lenient check);
        // the core's own area spells take the rider down where flying ends.
        if (player->HasAura(SPELL_FLYER_FLIGHT) || player->HasAura(SPELL_FLYER_FLIGHT_FAST))
            return spellInfo->CheckLocation(player->GetMapId(), player->GetZoneId(), areaId, player, false) == SPELL_CAST_OK
                ? spellId : 0;

        // Taking off: the same two checks the core makes when a flying mount is cast.
        if (spellInfo->CheckLocation(player->GetMapId(), player->GetZoneId(), areaId, player) != SPELL_CAST_OK)
            return 0;

        Battlefield* battlefield = sBattlefieldMgr->GetBattlefieldToZoneId(player->GetZoneId());
        if (battlefield && !battlefield->CanFlyIn())
            return 0;

        return spellId;
    }

    void UpdateFlight(Player* player, uint32 areaId)
    {
        uint32 wanted = WantedFlightSpell(player, areaId);

        // The new aura first: between a removal and an add the core would switch flying off.
        if (wanted && !player->HasAura(wanted))
            player->AddAura(wanted, player);

        for (uint32 spellId : flightSpells)
            if (spellId != wanted)
                player->RemoveAurasDueToSpell(spellId);
    }
}

// The summon spell of every flyer in data/pets.tsv (spell_script_names, written by build_pets.py).
class spell_retail_pets_flyer : public AuraScript
{
    PrepareAuraScript(spell_retail_pets_flyer);

    bool Validate(SpellInfo const* /*spellInfo*/) override
    {
        return ValidateSpellInfo({ SPELL_FLYER_FLIGHT, SPELL_FLYER_FLIGHT_FAST });
    }

    void HandleApply(AuraEffect const* /*aurEff*/, AuraEffectHandleModes /*mode*/)
    {
        if (Player* player = GetTarget()->ToPlayer())
            UpdateFlight(player, player->GetAreaId());
    }

    void HandleRemove(AuraEffect const* /*aurEff*/, AuraEffectHandleModes /*mode*/)
    {
        for (uint32 spellId : flightSpells)
            GetTarget()->RemoveAurasDueToSpell(spellId);
    }

    void Register() override
    {
        AfterEffectApply += AuraEffectApplyFn(spell_retail_pets_flyer::HandleApply, EFFECT_0, SPELL_AURA_MOUNTED, AURA_EFFECT_HANDLE_REAL);
        AfterEffectRemove += AuraEffectRemoveFn(spell_retail_pets_flyer::HandleRemove, EFFECT_0, SPELL_AURA_MOUNTED, AURA_EFFECT_HANDLE_REAL);
    }
};

class RetailPetsFlyerPlayerScript : public PlayerScript
{
public:
    RetailPetsFlyerPlayerScript() : PlayerScript("RetailPetsFlyerPlayerScript", { PLAYERHOOK_ON_UPDATE_AREA, PLAYERHOOK_ON_LEARN_SPELL }) { }

    // Runs before the core drops area-bound auras for the new area. Covers riding into a place
    // where flying is allowed, and the first area update after logging in mounted.
    void OnPlayerUpdateArea(Player* player, uint32 /*oldArea*/, uint32 newArea) override
    {
        if (player->IsMounted())
            UpdateFlight(player, newArea);
    }

    // A riding skill or Cold Weather Flying learned in the saddle counts at once.
    void OnPlayerLearnSpell(Player* player, uint32 /*spellId*/) override
    {
        if (player->IsMounted())
            UpdateFlight(player, player->GetAreaId());
    }
};

void AddRetailPetsFlyerScripts()
{
    RegisterSpellScript(spell_retail_pets_flyer);
    new RetailPetsFlyerPlayerScript();
}
