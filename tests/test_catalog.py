import copy
import unittest

import _bootstrap  # noqa: F401

from open_audio_fetch import catalog
from open_audio_fetch.sites import available


def _valid_source():
    return {
        "id": "example",
        "name": "Example Source",
        "url": "https://example.org/",
        "categories": ["music"],
        "license": "public-domain",
        "license_url": "https://example.org/license",
        "terms_url": None,
        "personal_use": True,
        "redistributable": "yes",
        "robots_ok": True,
        "access": "api",
        "formats": ["mp3"],
        "adapter_status": "planned",
        "tags": [],
        "added_by": "tester",
        "verified": "2026-07-26",
    }


def _valid_catalog():
    return {"version": 2, "_about": {}, "sources": [_valid_source()]}


class TestRealCatalog(unittest.TestCase):
    def test_ships_valid(self):
        errors = catalog.validate()
        self.assertEqual(errors, [], f"catalog.json is invalid: {errors}")

    def test_registered_adapters_have_entry(self):
        ids = {s["id"] for s in catalog.load_catalog()["sources"]}
        for name in available():
            self.assertIn(name, ids, f"adapter {name!r} missing catalog entry")

    def test_active_entries_are_registered(self):
        registered = set(available())
        for s in catalog.load_catalog()["sources"]:
            if s["adapter_status"] in ("implemented", "experimental"):
                self.assertIn(s["id"], registered, s["id"])

    def test_every_source_declares_rights(self):
        # The legality gate, spelled out as an explicit expectation.
        for s in catalog.load_catalog()["sources"]:
            self.assertTrue(s["personal_use"])
            self.assertTrue(s["license_url"].startswith("http"), s["id"])
            self.assertIn(s["redistributable"], ("yes", "conditional", "no", "mixed"))


class TestValidator(unittest.TestCase):
    def setUp(self):
        self.schema = catalog.load_schema()

    def _errs(self, cat):
        return catalog.validate(cat, self.schema)

    def test_minimal_valid(self):
        self.assertEqual(self._errs(_valid_catalog()), [])

    def test_missing_license_url_rejected(self):
        cat = _valid_catalog()
        del cat["sources"][0]["license_url"]
        errs = self._errs(cat)
        self.assertTrue(any("license_url" in e for e in errs), errs)

    def test_personal_use_must_be_true(self):
        cat = _valid_catalog()
        cat["sources"][0]["personal_use"] = False
        self.assertTrue(any("personal_use" in e for e in self._errs(cat)))

    def test_bad_license_enum(self):
        cat = _valid_catalog()
        cat["sources"][0]["license"] = "all-rights-reserved"
        self.assertTrue(any("license" in e for e in self._errs(cat)))

    def test_url_without_scheme(self):
        cat = _valid_catalog()
        cat["sources"][0]["url"] = "example.org"
        self.assertTrue(any(".url" in e for e in self._errs(cat)))

    def test_unexpected_field(self):
        cat = _valid_catalog()
        cat["sources"][0]["sneaky"] = "x"
        self.assertTrue(any("sneaky" in e for e in self._errs(cat)))

    def test_uppercase_id_rejected(self):
        cat = _valid_catalog()
        cat["sources"][0]["id"] = "BadID"
        self.assertTrue(any(".id" in e for e in self._errs(cat)))

    def test_empty_categories(self):
        cat = _valid_catalog()
        cat["sources"][0]["categories"] = []
        self.assertTrue(any("categories" in e for e in self._errs(cat)))

    def test_bad_verified_date(self):
        cat = _valid_catalog()
        cat["sources"][0]["verified"] = "yesterday"
        self.assertTrue(any("verified" in e for e in self._errs(cat)))

    def test_duplicate_ids(self):
        cat = _valid_catalog()
        cat["sources"].append(copy.deepcopy(cat["sources"][0]))
        self.assertTrue(any("duplicate id" in e for e in self._errs(cat)))

    def test_redistributable_enum(self):
        cat = _valid_catalog()
        cat["sources"][0]["redistributable"] = "sure"
        self.assertTrue(any("redistributable" in e for e in self._errs(cat)))


class TestDiagnose(unittest.TestCase):
    def _src(self, status, robots_ok):
        return {"adapter_status": status, "robots_ok": robots_ok}

    def test_healthy_active_source(self):
        level, _ = catalog.diagnose(self._src("implemented", True), True, True)
        self.assertEqual(level, catalog.OK)

    def test_active_source_now_blocked_is_fail(self):
        level, note = catalog.diagnose(self._src("implemented", True), False, False)
        self.assertEqual(level, catalog.FAIL)
        self.assertIn("DENIES", note)

    def test_active_source_unreachable_is_fail(self):
        level, _ = catalog.diagnose(self._src("implemented", True), True, False)
        self.assertEqual(level, catalog.FAIL)

    def test_planned_blocked_is_only_warn(self):
        level, _ = catalog.diagnose(self._src("planned", False), False, False)
        self.assertEqual(level, catalog.WARN)

    def test_robots_drift_warns(self):
        # catalog claims robots_ok=False but robots now allows -> drift WARN.
        level, note = catalog.diagnose(self._src("planned", False), True, True)
        self.assertEqual(level, catalog.WARN)
        self.assertIn("ALLOWS", note)


if __name__ == "__main__":
    unittest.main()
