"""Verify multi-device TargetProfile wiring into UnicornMachine, InterpreterProbe, and scaffold_target."""
import unittest

from src.a6400.execution.interpreter_probe import InterpreterProbe
from src.a6400.execution.unicorn_machine import UnicornMachine
from src.a6400.targets import (
    ILCE_6400,
    STATUS_REFERENCE,
    BootLayoutSpec,
    EvidenceRef,
    TargetProfile,
    get_profile,
)
from tools.research.scaffold_target import scaffold_profile_source


class TestMultiDeviceArchitecture(unittest.TestCase):
    def test_unicorn_machine_from_target_uses_profile_boot_layout_and_kallsyms(self):
        fake_kernel = int(0xE321F0D3).to_bytes(4, "little") + b"\x00" * 4096
        custom = TargetProfile(
            target_id="ilce_custom_test",
            model_name="Sony Test Body",
            status=STATUS_REFERENCE,
            soc_verified=True,
            kallsyms={
                "usb_gadgetcore_ioctl": 0x602BC864,
                "ret_to_user": 0x6010DF34,
            },
            boot_layout=BootLayoutSpec(
                machine_id=0x0DAA,
                kernel_load=0x00108000,
                initrd_load=0x00700000,
                boot_params=0x00103000,
                uart_base=0xF2001000,
            ),
            sources={
                "kallsyms.usb_gadgetcore_ioctl": (EvidenceRef("docs/ARCHITECTURE.md", "synthetic test"),),
                "kallsyms.ret_to_user": (EvidenceRef("docs/ARCHITECTURE.md", "synthetic test"),),
                "boot_layout": (EvidenceRef("docs/ARCHITECTURE.md", "synthetic test"),),
            },
            boundaries=("Synthetic test profile only.",),
        )
        machine = UnicornMachine.from_target(
            custom,
            fake_kernel,
            b"",
            b"",
            instruction_limit=100,
        )
        self.assertEqual(machine.target_id, "ilce_custom_test")
        self.assertEqual(machine.machine_id, 0x0DAA)
        self.assertEqual(machine.uart_base, 0xF2001000)
        self.assertEqual(machine.symbols["ret_to_user"], 0x6010DF34)

    def test_unicorn_machine_from_ilce_6400_profile(self):
        fake_kernel = int(0xE321F0D3).to_bytes(4, "little") + b"\x00" * 4096
        machine = UnicornMachine.from_target(
            get_profile("ilce_6400"),
            fake_kernel,
            b"",
            b"",
            instruction_limit=100,
        )
        self.assertEqual(machine.target_id, "ilce_6400")
        self.assertEqual(machine.machine_id, 0x0DA9)
        self.assertEqual(machine.uart_base, 0xF2000000)

    def test_interpreter_probe_accepts_target_profile(self):
        probe = InterpreterProbe(syscall_policy="stop", target_profile=ILCE_6400)
        self.assertEqual(probe.target_id, "ilce_6400")
        self.assertIs(probe.target_profile, ILCE_6400)

    def test_scaffold_target_generates_valid_profile_skeleton(self):
        code = scaffold_profile_source(
            target_id="ilce_6500",
            model_name="Sony ILCE-6500 (a6500)",
            firmware_version="1.06",
            kernel_version="3.0.27_nl-rt106+ SMP preempt mod_unload ARMv7",
            kallsyms={"usb_gadgetcore_ioctl": 0x602BC000},
            evidence_path="docs/ARCHITECTURE.md",
            kernel_sha256="a" * 64,
        )
        ns = {}
        exec(compile(code, "<scaffold>", "exec"), ns)
        profile = ns["ILCE_6500"]
        self.assertEqual(profile.target_id, "ilce_6500")
        self.assertEqual(profile.kallsyms["usb_gadgetcore_ioctl"], 0x602BC000)


if __name__ == "__main__":
    unittest.main()
