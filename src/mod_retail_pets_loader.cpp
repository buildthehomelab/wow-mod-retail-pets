/*
 * mod-retail-pets loader.
 *
 * The module is data only: the pets are world database rows (data/sql/db-world) and client patch
 * files. AzerothCore still calls a loader for every module folder, so this one is empty.
 *
 * AzerothCore looks up a loader symbol derived from the module's folder name: for folder
 * "mod-retail-pets" that symbol is exactly "Addmod_retail_petsScripts". If you clone the repo under
 * a different folder name, rename this function to match.
 *
 * Released under the MIT License.
 */

void Addmod_retail_petsScripts()
{
}
