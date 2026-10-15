/*
 * mod-retail-pets loader.
 *
 * Most of the module is data: the pets are world database rows (data/sql/db-world) and client
 * patch files. The one script is RetailPetsFlyer.cpp, which lets the "flyer" mounts fly.
 *
 * AzerothCore looks up a loader symbol derived from the module's folder name: for folder
 * "mod-retail-pets" that symbol is exactly "Addmod_retail_petsScripts". If you clone the repo under
 * a different folder name, rename this function to match.
 *
 * Released under the MIT License.
 */

void AddRetailPetsFlyerScripts();

void Addmod_retail_petsScripts()
{
    AddRetailPetsFlyerScripts();
}
