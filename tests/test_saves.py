"""Core tests. Real saves found on this machine are copied to a temp dir; originals are never touched."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sunless_editor import paths, saves
from sunless_editor.catalog import Catalog, QualityDef

SEA_SAMPLE = {
    "Name": "Test", "QualitiesPossessedList": [
        {"Name": None, "EquippedPossession": None, "Relationships": [], "XP": 0, "EffectiveLevelModifier": 0,
         "TargetQuality": None, "TargetLevel": None, "CompletionMessage": None, "Level": 60, "AssociatedQuality": None,
         "AssociatedQualityId": 102028, "QualityName": None, "QualityDescription": None, "QualityImage": None,
         "QualityNature": None, "QualityCategory": None, "QualityAllowedOn": None, "Id": 0},
    ],
}

SKIES_SAMPLE = {
    "Slots": [{"Type": 1, "Category": 70010, "Active": True}],
    "QualitiesPossessedList": [
        {"EffectiveLevel": 66, "Level": 66, "AssociatedQuality": {"Tag": "", "Id": 131137}},
        {"EffectiveLevel": 6, "EffectiveLevelModifier": -3, "Level": 9, "AssociatedQuality": {"Tag": "", "Id": 132086}},
        {"EffectiveLevel": 30, "EffectiveLevelModifier": 30, "AssociatedQuality": {"Tag": "", "Id": 132352}},
    ],
}

EMPTY = Catalog({}, "test")


def real_saves():
    return [s for s in paths.find_saves()]


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        patcher = mock.patch.object(paths, "backup_dir", return_value=self.tmp / "backups")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def write_json(self, name, data):
        p = self.tmp / name
        p.write_text(saves.dumps(data), encoding="utf-8")
        return p


class RoundTrip(TempDirTest):
    def test_unmodified_real_saves_are_byte_identical(self):
        found = [s for s in real_saves() if s.path.name != "saveSnippet.json"]
        if not found:
            self.skipTest("no real saves on this machine")
        for entry in found:
            with self.subTest(save=str(entry.path)):
                copy = self.tmp / entry.path.name
                shutil.copy2(entry.path, copy)
                s = saves.load_save(copy, EMPTY)
                self.assertEqual(s.game, entry.game)
                s.write()
                self.assertEqual(copy.read_bytes(), entry.path.read_bytes())

    def test_write_makes_backup_outside_save_folder(self):
        p = self.write_json("Autosave.json", SEA_SAMPLE)
        original = p.read_bytes()
        s = saves.load_save(p, EMPTY)
        s.set_quality(102028, 5000)
        backup = s.write()
        self.assertEqual(backup.read_bytes(), original)
        self.assertTrue(str(backup).startswith(str(self.tmp / "backups")))
        self.assertEqual(saves.load_save(p, EMPTY).level_of(102028), 5000)
        self.assertEqual(list(self.tmp.glob("*.editing")), [])


class Sea(TempDirTest):
    def load(self):
        return saves.load_save(self.write_json("s.json", SEA_SAMPLE), EMPTY)

    def test_add_uses_game_key_order(self):
        s = self.load()
        e = s.add(102027, 10)
        self.assertEqual(list(e), list(SEA_SAMPLE["QualitiesPossessedList"][0]))
        self.assertEqual((e["AssociatedQualityId"], e["Level"]), (102027, 10))

    def test_equip_ship_keeps_name_and_removes_old_ship(self):
        s = self.load()
        old = s.add(104361, 1)
        old["Name"] = "Matilda Briggs"
        slot = s.add(102889, 1)
        slot["EquippedPossession"] = s._possessed_copy(old)
        s.equip(102889, 104362)
        self.assertIsNone(s.find(104361))
        self.assertEqual(s.find(102889)["EquippedPossession"]["AssociatedQualityId"], 104362)
        self.assertEqual(s.ship_name(), "Matilda Briggs")
        s.set_ship_name("Nautilus")
        self.assertEqual(s.find(104362)["Name"], "Nautilus")
        self.assertEqual(s.ship_name(), "Nautilus")

    def test_remove_unequips(self):
        s = self.load()
        s.add(102904, 1)
        s.equip(102904, 109343)
        s.remove(109343)
        self.assertIsNone(s.find(102904)["EquippedPossession"])


class Skies(TempDirTest):
    def load(self):
        return saves.load_save(self.write_json("autosave.json", SKIES_SAMPLE), EMPTY)

    def test_detected(self):
        self.assertEqual(self.load().game, paths.SKIES)

    def test_level_keeps_effective_level_in_sync(self):
        s = self.load()
        e = s.find(132086)
        s.set_level(e, 20)
        self.assertEqual(e, {"EffectiveLevel": 17, "EffectiveLevelModifier": -3, "Level": 20,
                             "AssociatedQuality": {"Tag": "", "Id": 132086}})

    def test_zero_values_are_omitted_like_the_game(self):
        s = self.load()
        e = s.find(131137)
        s.set_level(e, 0)
        self.assertEqual(e, {"AssociatedQuality": {"Tag": "", "Id": 131137}})
        e = s.find(132352)
        s.set_level(e, 5)
        self.assertEqual(list(e), ["EffectiveLevel", "EffectiveLevelModifier", "Level", "AssociatedQuality"])

    def test_add_entry_shape(self):
        s = self.load()
        e = s.add(132096, 3)
        self.assertEqual(saves.dumps(e), '{"EffectiveLevel":3,"Level":3,"AssociatedQuality":{"Tag":"","Id":132096}}')

    def test_equip_slot_and_possess_item(self):
        s = self.load()
        s.equip(("slot", 0), 140436)
        self.assertEqual(saves.dumps(s.data["Slots"][0]),
                         '{"Type":1,"Category":70010,"EquipmentQualityId":140436,"Active":true}')
        self.assertEqual(s.level_of(140436), 1)
        s.equip(("slot", 0), None)
        self.assertNotIn("EquipmentQualityId", s.data["Slots"][0])

    def test_officer_assignment_matches_game(self):
        # Exact bytes the game wrote for an Incautious Driver assigned as Chief Engineer (Sept 2026 save).
        s = self.load()
        s.add(131169, 1)
        s.equip(("copy", 131169), 132923)
        self.assertEqual(saves.dumps(s.find(131169)),
                         '{"EquippedPossession":{"EffectiveLevel":1,"Level":1,"AssociatedQuality":{"Tag":"","Id":132923}},'
                         '"EffectiveLevel":1,"Level":1,"AssociatedQuality":{"Tag":"","Id":131169}}')

    def test_locomotive_copy_uses_skies_shape(self):
        s = self.load()
        loco = s.add(132785, 1)
        s._set_name(loco, "Orphean")
        s.add(132796, 1)
        s.equip(("copy", 132796), 132785)
        self.assertEqual(saves.dumps(s.find(132796)),
                         '{"EquippedPossession":{"Name":"Orphean","EffectiveLevel":1,"Level":1,'
                         '"AssociatedQuality":{"Tag":"","Id":132785}},"EffectiveLevel":1,"Level":1,'
                         '"AssociatedQuality":{"Tag":"","Id":132796}}')

    def test_cargo_excludes_non_items(self):
        s = self.load()
        hold = lambda qid, nature: QualityDef(qid, "x", "Hold item / passenger", nature, 150, None, True)
        self.assertTrue(s.is_cargo(hold(137000, "Thing")))       # Fastidious Inspector (charter)
        self.assertFalse(s.is_cargo(hold(138302, "Thing")))      # Minimum Safe Manning Number
        self.assertFalse(s.is_cargo(hold(139194, "Other")))      # Guests Aboard


class Catalogs(unittest.TestCase):
    def test_skies_catalog_names_every_quality_in_real_saves(self):
        found = [s for s in real_saves() if s.game == paths.SKIES]
        if not found or not paths.skies_qualities_files():
            self.skipTest("no Skies saves/data on this machine")
        cat = saves.get_catalog(paths.SKIES)
        self.assertGreater(len(cat), 2000)
        for entry in found:
            s = saves.load_save(entry.path, cat)
            missing = [s.entry_id(e) for e in s.entries() if not cat.get(s.entry_id(e)).known]
            self.assertEqual(missing, [], entry.path)
        self.assertEqual(cat.get(131137).name, "Sovereign")

    def test_sea_catalog(self):
        if not paths.sea_qualities_file():
            self.skipTest("no Sea data on this machine")
        cat = saves.get_catalog(paths.SEA)
        self.assertEqual(cat.get(102028).name, "Echo")
        self.assertEqual(cat.get(109343).slot_id, 102904)


if __name__ == "__main__":
    unittest.main()
