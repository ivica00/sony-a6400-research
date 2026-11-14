"""Contract checks for the multi-device BIONZ X target registry.

These tests are offline and standard-library only. They enforce the evidence rules that
make a profile trustworthy: every populated claim has a source, an unverified stub
carries no claims, and known values match the evidence record they cite.
"""
import json
import unittest
from pathlib import Path

from src.a6400.execution.zve10_uvc_enablement import ZVE10_UVC_COMPONENTS
from src.a6400.targets import (
    DEFAULT_REGISTRY,
    PID_TIER_OBSERVED,
    PID_TIER_PROJECT_AUTHORED,
    PID_TIER_STOCK,
    SOC_BIONZ_X,
    STATUS_REFERENCE,
    STATUS_UNVERIFIED,
    STATUS_VERIFIED,
    EvidenceRef,
    ModuleComponent,
    TargetProfile,
    TargetRegistry,
    UsbIdentity,
    UsbPid,
    get_profile,
    list_profiles,
    profile_ids,
    registry_dict,
)

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_A6400_KALLSYMS = (
    "usb_gadgetcore_ioctl",
    "osal_snd_msg",
    "osal_rcv_msg_tmo",
    "setup_req",
)


def _fixture_profile(**overrides):
    """A minimal well-formed verified profile; overrides drive the failure cases."""
    base = dict(
        target_id="fixture_body",
        model_name="Fixture Body",
        status=STATUS_VERIFIED,
        soc_verified=True,
        kallsyms={"usb_gadgetcore_ioctl": 0x602B8844},
        sources={"kallsyms.usb_gadgetcore_ioctl": (EvidenceRef("README.md", "fixture source"),)},
    )
    base.update(overrides)
    return TargetProfile(**base)


class TestRegistryContents(unittest.TestCase):
    def test_registered_targets(self):
        self.assertEqual(
            profile_ids(),
            ("ilce_6100", "ilce_6400", "ilce_6400a", "ilce_6600", "ilce_7c", "ilce_7m3", "zv_e10"),
        )

    def test_every_profile_is_a_bionz_x_cxd90045_body(self):
        for profile in list_profiles():
            self.assertEqual(profile.soc, SOC_BIONZ_X, profile.target_id)

    def test_primary_target_is_verified_and_reference_is_not(self):
        self.assertEqual(get_profile("ilce_6400").status, STATUS_VERIFIED)
        self.assertTrue(get_profile("ilce_6400").soc_verified)
        self.assertEqual(get_profile("zv_e10").status, STATUS_REFERENCE)

    def test_unknown_target_raises_with_known_ids(self):
        with self.assertRaises(KeyError) as caught:
            get_profile("ilce_9999")
        message = str(caught.exception)
        self.assertIn("ilce_6400", message)
        self.assertIn("registered targets", message)

    def test_registry_rejects_duplicate_target_ids(self):
        profile = _fixture_profile()
        with self.assertRaises(ValueError):
            TargetRegistry((profile, profile))

    def test_by_status_partitions_the_registry(self):
        # E0436 sourced the three ILCE bodies from their own packaged updaters, so the registry
        # no longer carries an unverified stub.  A stub would reappear here if a body were
        # declared without any evidence behind it.
        stubs = DEFAULT_REGISTRY.by_status(STATUS_UNVERIFIED)
        self.assertEqual(tuple(p.target_id for p in stubs), ())
        self.assertEqual(
            tuple(p.target_id for p in DEFAULT_REGISTRY.by_status(STATUS_REFERENCE)),
            ("ilce_6100", "ilce_6400a", "ilce_6600", "ilce_7c", "ilce_7m3", "zv_e10"),
        )
        self.assertEqual(
            sum(len(DEFAULT_REGISTRY.by_status(status))
                for status in (STATUS_VERIFIED, STATUS_REFERENCE, STATUS_UNVERIFIED)),
            len(list_profiles()),
        )
        with self.assertRaises(ValueError):
            DEFAULT_REGISTRY.by_status("supported")


class TestVerifiedContract(unittest.TestCase):
    def setUp(self):
        self.profile = get_profile("ilce_6400")

    def test_required_kallsyms_symbols_are_resolved(self):
        for symbol in REQUIRED_A6400_KALLSYMS:
            self.assertIn(symbol, self.profile.kallsyms)
            address = self.profile.kallsyms[symbol]
            self.assertIsNotNone(address, f"{symbol} must be resolved for the verified target")
            self.assertGreater(address, 0)
            self.assertLessEqual(address, 0xFFFFFFFF)

    def test_known_kallsyms_values_match_the_evidence_record(self):
        self.assertEqual(self.profile.kallsyms["usb_gadgetcore_ioctl"], 0x602B8844)
        self.assertEqual(self.profile.kallsyms["osal_snd_msg"], 0x5F04916C)
        self.assertEqual(self.profile.kallsyms["osal_rcv_msg_tmo"], 0x5F0494F0)
        self.assertEqual(self.profile.kallsyms["setup_req"], 0x602B94A4)

    def test_uipc_queues_are_resolved_32_bit_ids(self):
        self.assertEqual(self.profile.uipc_queues["usb_control"], 0x00CA8192)
        for name, queue_id in self.profile.uipc_queues.items():
            self.assertIsNotNone(queue_id, name)
            self.assertTrue(0 < queue_id <= 0xFFFFFFFF, name)

    def test_usb_identity_is_complete(self):
        usb = self.profile.usb
        self.assertIsNotNone(usb)
        self.assertEqual(usb.vid, 0x054C)
        self.assertEqual(usb.pids["mass_storage"].value, 0x0CA8)
        self.assertEqual(usb.pids["pc_remote"].value, 0x0CAA)
        self.assertEqual(usb.pids["uvc_composite"].value, 0x0322)
        self.assertEqual(usb.pids["mass_storage"].tier, PID_TIER_STOCK)
        self.assertEqual(usb.pids["pc_remote"].tier, PID_TIER_OBSERVED)
        self.assertEqual(usb.pids["uvc_composite"].tier, PID_TIER_PROJECT_AUTHORED)
        self.assertEqual(usb.bcd_device, 0x0200)

    def test_firmware_and_kernel_versions_are_stated(self):
        self.assertEqual(self.profile.firmware_version, "8.2.5.7")
        self.assertEqual(self.profile.live_build_version, "8.2.6.0")
        self.assertIn("3.0.27", self.profile.kernel_version)

    def test_image_and_live_build_are_not_conflated(self):
        boundary = " ".join(self.profile.boundaries)
        self.assertIn("8.2.5.7", boundary)
        self.assertIn("8.2.6.0", boundary)

    def test_boundaries_are_explicit(self):
        self.assertTrue(self.profile.boundaries)
        joined = " ".join(self.profile.boundaries).lower()
        self.assertIn("per-boot", joined)


class TestEvidenceDiscipline(unittest.TestCase):
    def test_every_claim_has_a_source_and_vice_versa(self):
        for profile in list_profiles():
            claims = set(profile.claims())
            self.assertEqual(
                claims,
                set(profile.sources),
                f"{profile.target_id}: claim/source mismatch",
            )

    def test_cited_evidence_paths_exist(self):
        for profile in list_profiles():
            for claim, refs in profile.sources.items():
                for ref in refs:
                    self.assertTrue(
                        (ROOT / ref.path).is_file(),
                        f"{profile.target_id}/{claim}: missing evidence file {ref.path}",
                    )
                    self.assertTrue(ref.detail, f"{profile.target_id}/{claim}: empty detail")

    def test_stub_profiles_carry_no_claims(self):
        for profile in DEFAULT_REGISTRY.by_status(STATUS_UNVERIFIED):
            self.assertEqual(profile.claims(), {}, profile.target_id)
            self.assertFalse(profile.soc_verified, profile.target_id)
            self.assertTrue(profile.boundaries, profile.target_id)
            self.assertIn("ADDING_A_BIONZX_CAMERA", " ".join(profile.boundaries))

    def test_claim_without_source_is_rejected(self):
        with self.assertRaises(ValueError) as caught:
            _fixture_profile(sources={})
        self.assertIn("without an evidence source", str(caught.exception))

    def test_source_without_claim_is_rejected(self):
        with self.assertRaises(ValueError) as caught:
            _fixture_profile(
                sources={
                    "kallsyms.usb_gadgetcore_ioctl": (EvidenceRef("README.md", "fixture source"),),
                    "kallsyms.osal_snd_msg": (EvidenceRef("README.md", "source for an unpopulated field"),),
                }
            )
        self.assertIn("fields that are not populated", str(caught.exception))

    def test_unverified_stub_with_claims_is_rejected(self):
        with self.assertRaises(ValueError) as caught:
            _fixture_profile(status=STATUS_UNVERIFIED, soc_verified=False)
        self.assertIn("must carry no claims", str(caught.exception))

    def test_verified_profile_without_resolved_symbol_is_rejected(self):
        with self.assertRaises(ValueError) as caught:
            _fixture_profile(
                kallsyms={"usb_gadgetcore_ioctl": None},
                sources={"kallsyms.usb_gadgetcore_ioctl": (EvidenceRef("README.md", "fixture"),)},
            )
        self.assertEqual(caught.exception.args[0].split(":")[0], "fixture_body")

    def test_non_bionz_x_soc_is_rejected(self):
        with self.assertRaises(ValueError) as caught:
            _fixture_profile(soc="CXD90042")
        self.assertIn("CXD90045", str(caught.exception))

    def test_invalid_address_is_rejected(self):
        with self.assertRaises(ValueError):
            _fixture_profile(
                kallsyms={"usb_gadgetcore_ioctl": 0x1_0000_0000},
                sources={"kallsyms.usb_gadgetcore_ioctl": (EvidenceRef("README.md", "fixture"),)},
            )

    def test_invalid_usb_identity_is_rejected(self):
        with self.assertRaises(ValueError):
            UsbIdentity(vid=0x1_0000, pids={})
        with self.assertRaises(ValueError):
            UsbPid(0x1_0000, PID_TIER_STOCK)
        with self.assertRaises(ValueError):
            UsbPid(0x0CA8, "invented")
        with self.assertRaises(ValueError):
            ModuleComponent(size=0, sha256="0" * 64, role="fixture")
        with self.assertRaises(ValueError):
            ModuleComponent(size=4, sha256="XYZ", role="fixture")

    def test_project_authored_pid_is_not_claimed_as_stock(self):
        pids = get_profile("ilce_6400").usb.pids
        self.assertEqual(
            [name for name, pid in pids.items() if pid.tier == PID_TIER_PROJECT_AUTHORED],
            ["uvc_composite"],
        )


class TestJsonView(unittest.TestCase):
    def test_registry_is_json_serializable(self):
        payload = json.dumps(registry_dict())
        reloaded = json.loads(payload)
        self.assertEqual(reloaded["ilce_6400"]["kallsyms"]["usb_gadgetcore_ioctl"], 0x602B8844)
        self.assertEqual(reloaded["ilce_6400"]["status"], STATUS_VERIFIED)
        self.assertEqual(reloaded["ilce_6100"]["status"], STATUS_REFERENCE)
        self.assertEqual(reloaded["ilce_6100"]["kallsyms"]["usb_gadgetcore_ioctl"], 0x602BC864)

    def test_as_dict_keeps_unknowns_explicit(self):
        # uipc_queues cannot be recovered offline, so it stays explicitly empty rather than
        # borrowing the a6400's live handles.
        body = get_profile("ilce_6600").as_dict()
        self.assertEqual(body["uipc_queues"], {})
        self.assertEqual(body["firmware_version"], "1.10")
        self.assertIsNotNone(body["usb"])
        self.assertTrue(body["soc_verified"])

    def test_zv_e10_modules_match_the_enablement_table(self):
        modules = get_profile("zv_e10").modules
        for name, expected in ZVE10_UVC_COMPONENTS.items():
            self.assertIn(name, modules)
            self.assertEqual(modules[name].size, expected["size"], name)
            self.assertEqual(modules[name].sha256, expected["sha256"], name)


if __name__ == "__main__":
    unittest.main()
