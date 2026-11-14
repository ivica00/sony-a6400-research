"""Re-exported CXD90045 boot contract helpers under ``src.a6400.machine``."""
from src.a6400.execution.machine_contract import (
    BOOT_PARAMS,
    INITRD_LOAD,
    MACHINE_NAME,
    UPDATER_LOADADDR,
    MachineContractError,
    MachineDescriptor,
    UpdaterBootContract,
    recover_machine_descriptor,
)

__all__ = [
    "BOOT_PARAMS",
    "INITRD_LOAD",
    "MACHINE_NAME",
    "MachineContractError",
    "MachineDescriptor",
    "UPDATER_LOADADDR",
    "UpdaterBootContract",
    "recover_machine_descriptor",
]
