"""Offline, fail-closed host enumeration for the byte-verified UVC+PTP descriptor.

The 173-byte configuration descriptor is the E0154/E0317 ZV-E10 UVC+PTP
composite (SHA-256 ``cc99cbd9...``).  This module is deliberately host-side and
emulator-independent: it loads the descriptor from the existing read-only
artifacts manifests, verifies the pinned hash, parses USB descriptors, selects
the UVC+PTP configuration, and describes the SET_CONFIGURATION request that the
already-decoded UsbControl path maps to FSM event 0x13 (E0323/E0335).

Unknown layouts, bad hashes, and unsupported configuration values fail closed;
no descriptor bytes or SET_CONFIG results are fabricated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Pinned evidence (E0154/E0317/E0321)
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[3]

EXPECTED_DESCRIPTOR_SHA256 = (
    'cc99cbd9ca3ed62b009de00e69095cf04fdc6986b337719dbda8e7c2d197231f')
EXPECTED_DESCRIPTOR_LENGTH = 173

# Existing read-only manifests used for provenance.  The enablement manifest
# (E0322) points at its E0321 companion; the descriptor bytes themselves are in
# the E0154 native-descriptor manifest.
DEFAULT_ENABLEMENT_MANIFEST = (
    PROJECT_ROOT / 'artifacts' / 'analysis' / 'e0322-uvc-overlay-plan.json')
DEFAULT_DESCRIPTOR_MANIFEST = (
    PROJECT_ROOT / 'artifacts' / 'native' / 'uvc-ptp-descriptors-e0154'
    / 'manifest.json')

# USB descriptor types / values used by the verified descriptor.
USB_DT_DEVICE = 0x01
USB_DT_CONFIG = 0x02
USB_DT_INTERFACE = 0x04
USB_DT_ENDPOINT = 0x05
USB_DT_INTERFACE_ASSOCIATION = 0x0B
USB_DT_CS_INTERFACE = 0x24
USB_DT_CS_ENDPOINT = 0x25

USB_CLASS_STILL_IMAGE = 0x06
USB_SUBCLASS_STILL_IMAGE = 0x01
USB_PROTOCOL_STILL_IMAGE = 0x01
USB_CLASS_VIDEO = 0x0E
USB_SC_VIDEOCONTROL = 0x01
USB_SC_VIDEOSTREAMING = 0x02
USB_IAD_FUNCTION_VIDEO = 0x03

USB_ENDPOINT_XFER_CONTROL = 0
USB_ENDPOINT_XFER_ISOC = 1
USB_ENDPOINT_XFER_BULK = 2
USB_ENDPOINT_XFER_INT = 3

# Inbound SET_CONFIG decoded by E0323/E0335.
SET_CONFIG_CATEGORY = 0x6103
SET_CONFIG_MESSAGE_ID = 0x0A4001
SET_CONFIG_PARAM_ID = 0x1006
SET_CONFIG_PARAM_VALUE = 0
SET_CONFIG_PARAM_TYPE = 'int32'
SET_CONFIG_FSM_EVENT = 0x13
SET_CONFIG_CONFIGURATION_VALUE = 1

# Expected E0154 layout facts (evidence, not inferred).
EXPECTED_INTERFACE_COUNT = 3
EXPECTED_PTP_ENDPOINTS = ('0x81', '0x02', '0x83')
EXPECTED_VIDEO_STREAMING_ENDPOINTS = ('0x82',)
EXPECTED_VIDEO_CONTROL_ENDPOINTS = ()
EXPECTED_PTP_BULK_IN = '0x81'
EXPECTED_PTP_BULK_OUT = '0x02'
EXPECTED_PTP_INTERRUPT_IN = '0x83'
EXPECTED_VIDEO_STREAMING_ENDPOINT = '0x82'
EXPECTED_VIDEO_CONTROL_INTERFACE = 1
EXPECTED_VIDEO_STREAMING_INTERFACE = 2
EXPECTED_PTP_INTERFACE = 0


class UsbHostEnumError(ValueError):
    """Base class for fail-closed host-enumeration errors."""


class DescriptorHashMismatch(UsbHostEnumError):
    """The descriptor bytes do not match the pinned SHA-256 evidence."""


class UnsupportedDescriptorLayout(UsbHostEnumError):
    """The descriptor is structurally valid USB but not the known UVC+PTP layout."""


class UnsupportedConfiguration(UsbHostEnumError):
    """The requested configuration value is not the verified UVC+PTP one."""


# ---------------------------------------------------------------------------
# Descriptor model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UsbEndpoint:
    address: int
    attributes: int
    max_packet_size: int
    interval: int
    raw: bytes = field(repr=False)

    @property
    def direction(self) -> str:
        return 'in' if self.address & 0x80 else 'out'

    @property
    def number(self) -> int:
        return self.address & 0x0F

    @property
    def transfer_type(self) -> str:
        return {
            USB_ENDPOINT_XFER_CONTROL: 'control',
            USB_ENDPOINT_XFER_ISOC: 'isochronous',
            USB_ENDPOINT_XFER_BULK: 'bulk',
            USB_ENDPOINT_XFER_INT: 'interrupt',
        }.get(self.attributes & 0x03, 'unknown')

    def to_dict(self) -> dict[str, Any]:
        return {
            'address': f'0x{self.address:02x}',
            'number': self.number,
            'direction': self.direction,
            'transfer_type': self.transfer_type,
            'attributes': self.attributes,
            'max_packet_size': self.max_packet_size,
            'interval': self.interval,
        }


@dataclass(frozen=True)
class UsbInterface:
    number: int
    alternate_setting: int
    interface_class: int
    interface_subclass: int
    interface_protocol: int
    i_interface: int
    endpoints: tuple[UsbEndpoint, ...]
    class_specific: tuple[bytes, ...] = ()
    raw: bytes = field(repr=False, default=b'')

    @property
    def kind(self) -> str:
        if (self.interface_class == USB_CLASS_STILL_IMAGE
                and self.interface_subclass == USB_SUBCLASS_STILL_IMAGE):
            return 'ptp'
        if self.interface_class == USB_CLASS_VIDEO:
            if self.interface_subclass == USB_SC_VIDEOCONTROL:
                return 'video_control'
            if self.interface_subclass == USB_SC_VIDEOSTREAMING:
                return 'video_streaming'
        return 'other'

    def to_dict(self) -> dict[str, Any]:
        return {
            'number': self.number,
            'alternate_setting': self.alternate_setting,
            'kind': self.kind,
            'class': self.interface_class,
            'subclass': self.interface_subclass,
            'protocol': self.interface_protocol,
            'i_interface': self.i_interface,
            'endpoint_count': len(self.endpoints),
            'endpoints': [endpoint.to_dict() for endpoint in self.endpoints],
            'class_specific_lengths': [len(blob) for blob in self.class_specific],
        }


@dataclass(frozen=True)
class UsbInterfaceAssociation:
    first_interface: int
    interface_count: int
    function_class: int
    function_subclass: int
    function_protocol: int
    i_function: int
    raw: bytes = field(repr=False, default=b'')

    def to_dict(self) -> dict[str, Any]:
        return {
            'first_interface': self.first_interface,
            'interface_count': self.interface_count,
            'function_class': self.function_class,
            'function_subclass': self.function_subclass,
            'function_protocol': self.function_protocol,
            'i_function': self.i_function,
        }


@dataclass(frozen=True)
class UsbConfiguration:
    value: int
    total_length: int
    num_interfaces: int
    attributes: int
    max_power: int
    interfaces: tuple[UsbInterface, ...]
    associations: tuple[UsbInterfaceAssociation, ...]
    raw: bytes = field(repr=False, default=b'')

    def interfaces_by_kind(self, kind: str) -> tuple[UsbInterface, ...]:
        return tuple(item for item in self.interfaces if item.kind == kind)

    def to_dict(self) -> dict[str, Any]:
        return {
            'value': self.value,
            'total_length': self.total_length,
            'num_interfaces': self.num_interfaces,
            'attributes': self.attributes,
            'max_power': self.max_power,
            'interfaces': [item.to_dict() for item in self.interfaces],
            'associations': [item.to_dict() for item in self.associations],
        }


# ---------------------------------------------------------------------------
# Manifest loading (fail-closed)
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open('r', encoding='utf-8') as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:
        raise UsbHostEnumError(f'manifest not found: {path}') from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise UsbHostEnumError(f'unreadable manifest: {path}: {exc}') from exc
    if not isinstance(data, dict):
        raise UsbHostEnumError(f'manifest root is not an object: {path}')
    return data


def _resolve_manifest_path(raw: str | Path, base: Path) -> Path:
    path = Path(raw)
    if path.is_absolute():
        return path
    candidate = base / path
    if candidate.exists():
        return candidate
    return PROJECT_ROOT / path


def _read_enablement_provenance(manifest_path: Path | None) -> dict[str, Any]:
    """Read the E0322 (or E0321) read-only manifest for provenance checks."""
    path = Path(manifest_path) if manifest_path else DEFAULT_ENABLEMENT_MANIFEST
    data = _load_json(path)
    kind = data.get('e')
    if kind not in ('E0321', 'E0322'):
        raise UsbHostEnumError(
            f'enablement manifest {path} has unsupported e={kind!r}')
    provenance: dict[str, Any] = {
        'manifest': str(path),
        'e': kind,
        'objective': data.get('objective'),
    }
    if kind == 'E0322':
        linked = data.get('manifest')
        if not linked:
            raise UsbHostEnumError(
                f'E0322 manifest {path} has no linked E0321 manifest')
        linked_path = _resolve_manifest_path(linked, path.parent)
        linked_data = _load_json(linked_path)
        if linked_data.get('e') != 'E0321':
            raise UsbHostEnumError(
                f'linked manifest {linked_path} is not E0321')
        provenance['linked_manifest'] = str(linked_path)
        provenance['linked_e'] = 'E0321'
        provenance['enablement_verdict'] = linked_data.get('verdict')
    else:
        provenance['enablement_verdict'] = data.get('verdict')
    return provenance


def load_descriptor_bytes(
        descriptor_manifest_path: Path | str | None = None,
        enablement_manifest_path: Path | str | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """Load and hash-verify the pinned UVC+PTP configuration descriptor.

    ``descriptor_manifest_path`` must be a read-only JSON manifest containing
    ``configuration.raw_hex`` (E0154 format).  ``enablement_manifest_path`` is
    the E0322/E0321 manifest chain used only for provenance and structural
    checks.  The descriptor SHA-256 and length are compared to the pinned
    evidence; any mismatch raises ``DescriptorHashMismatch`` before parsing.
    """
    provenance = _read_enablement_provenance(enablement_manifest_path)
    path = (Path(descriptor_manifest_path) if descriptor_manifest_path
            else DEFAULT_DESCRIPTOR_MANIFEST)
    data = _load_json(path)
    configuration = data.get('configuration')
    if not isinstance(configuration, dict) or not isinstance(
            configuration.get('raw_hex'), str):
        raise UsbHostEnumError(
            f'descriptor manifest {path} lacks configuration.raw_hex')
    try:
        raw = bytes.fromhex(configuration['raw_hex'])
    except ValueError as exc:
        raise UsbHostEnumError(
            f'descriptor manifest {path} has invalid raw_hex') from exc
    actual_sha = hashlib.sha256(raw).hexdigest()
    if actual_sha != EXPECTED_DESCRIPTOR_SHA256:
        raise DescriptorHashMismatch(
            'UVC+PTP descriptor hash mismatch: '
            f'expected {EXPECTED_DESCRIPTOR_SHA256}, got {actual_sha}')
    if len(raw) != EXPECTED_DESCRIPTOR_LENGTH:
        raise DescriptorHashMismatch(
            'UVC+PTP descriptor length mismatch: '
            f'expected {EXPECTED_DESCRIPTOR_LENGTH}, got {len(raw)}')
    provenance.update({
        'descriptor_manifest': str(path),
        'descriptor_sha256': actual_sha,
        'descriptor_length': len(raw),
    })
    return raw, provenance


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _iter_descriptors(raw: bytes,
                      start: int = 0) -> Iterable[tuple[int, int, bytes]]:
    offset = start
    while offset < len(raw):
        if offset + 2 > len(raw):
            raise UnsupportedDescriptorLayout(
                f'truncated descriptor header at offset {offset}')
        length = raw[offset]
        descriptor_type = raw[offset + 1]
        if length < 2:
            raise UnsupportedDescriptorLayout(
                f'invalid descriptor length {length} at offset {offset}')
        end = offset + length
        if end > len(raw):
            raise UnsupportedDescriptorLayout(
                f'truncated descriptor at offset {offset} (need {end})')
        yield descriptor_type, offset, raw[offset:end]
        offset = end


def _parse_endpoint(blob: bytes) -> UsbEndpoint:
    if len(blob) != 7:
        raise UnsupportedDescriptorLayout(
            f'endpoint descriptor must be 7 bytes, got {len(blob)}')
    return UsbEndpoint(
        address=blob[2],
        attributes=blob[3],
        max_packet_size=blob[4] | (blob[5] << 8),
        interval=blob[6],
        raw=blob,
    )


def parse_configuration_descriptor(raw: bytes) -> UsbConfiguration:
    """Parse a single USB configuration descriptor blob (no hash dependency)."""
    if not isinstance(raw, (bytes, bytearray)) or len(raw) < 9:
        raise UnsupportedDescriptorLayout('configuration descriptor too short')
    prefix = bytes(raw)
    descriptors = list(_iter_descriptors(prefix))
    if not descriptors or descriptors[0][0] != USB_DT_CONFIG:
        raise UnsupportedDescriptorLayout(
            'first descriptor is not a configuration descriptor')
    config_type, _, config_blob = descriptors[0]
    if len(config_blob) < 9:
        raise UnsupportedDescriptorLayout('configuration header too short')
    total_length = config_blob[2] | (config_blob[3] << 8)
    num_interfaces = config_blob[4]
    value = config_blob[5]
    attributes = config_blob[7]
    max_power = config_blob[8]
    if total_length != len(prefix):
        raise UnsupportedDescriptorLayout(
            f'wTotalLength {total_length} != blob length {len(prefix)}')

    interfaces: list[UsbInterface] = []
    associations: list[UsbInterfaceAssociation] = []
    current: dict[str, Any] | None = None
    interface_endpoints: list[UsbEndpoint] = []
    class_specific: list[bytes] = []

    def flush_current() -> None:
        nonlocal current, interface_endpoints, class_specific
        if current is None:
            return
        interfaces.append(UsbInterface(
            number=current['number'],
            alternate_setting=current['alternate_setting'],
            interface_class=current['interface_class'],
            interface_subclass=current['interface_subclass'],
            interface_protocol=current['interface_protocol'],
            i_interface=current['i_interface'],
            endpoints=tuple(interface_endpoints),
            class_specific=tuple(class_specific),
            raw=current['raw'],
        ))
        current = None
        interface_endpoints = []
        class_specific = []

    for descriptor_type, offset, blob in descriptors[1:]:
        if descriptor_type == USB_DT_INTERFACE:
            flush_current()
            if len(blob) < 9:
                raise UnsupportedDescriptorLayout(
                    f'interface descriptor at {offset} is too short')
            declared_endpoints = blob[4]
            current = {
                'number': blob[2],
                'alternate_setting': blob[3],
                'declared_endpoints': declared_endpoints,
                'interface_class': blob[5],
                'interface_subclass': blob[6],
                'interface_protocol': blob[7],
                'i_interface': blob[8],
                'raw': blob,
            }
            if declared_endpoints != 0:
                # Endpoints follow immediately; checked when the next
                # interface/association flushes this one.
                pass
        elif descriptor_type == USB_DT_ENDPOINT:
            if current is None:
                raise UnsupportedDescriptorLayout(
                    f'endpoint descriptor at {offset} outside an interface')
            interface_endpoints.append(_parse_endpoint(blob))
        elif descriptor_type == USB_DT_INTERFACE_ASSOCIATION:
            flush_current()
            if len(blob) < 8:
                raise UnsupportedDescriptorLayout(
                    f'IAD descriptor at {offset} is too short')
            associations.append(UsbInterfaceAssociation(
                first_interface=blob[2],
                interface_count=blob[3],
                function_class=blob[4],
                function_subclass=blob[5],
                function_protocol=blob[6],
                i_function=blob[7],
                raw=blob,
            ))
        elif descriptor_type in (USB_DT_CS_INTERFACE, USB_DT_CS_ENDPOINT):
            if current is not None:
                class_specific.append(blob)
        # Other standard descriptors (strings/devices) are not part of a
        # configuration blob and are ignored only if they appear here, which
        # the verified descriptor does not do.
    flush_current()

    for interface in interfaces:
        declared = None
        for _, _, blob in descriptors[1:]:
            if (blob[1] == USB_DT_INTERFACE and blob[2] == interface.number
                    and blob[3] == interface.alternate_setting):
                declared = blob[4]
                break
        if declared is not None and declared != len(interface.endpoints):
            raise UnsupportedDescriptorLayout(
                f'interface {interface.number} declares {declared} endpoints '
                f'but has {len(interface.endpoints)} descriptors')
    if len(interfaces) != num_interfaces:
        raise UnsupportedDescriptorLayout(
            f'bNumInterfaces {num_interfaces} != parsed {len(interfaces)}')
    return UsbConfiguration(
        value=value,
        total_length=total_length,
        num_interfaces=num_interfaces,
        attributes=attributes,
        max_power=max_power,
        interfaces=tuple(interfaces),
        associations=tuple(associations),
        raw=prefix,
    )


# ---------------------------------------------------------------------------
# Selection / validation of the known UVC+PTP layout
# ---------------------------------------------------------------------------


def _endpoint_addresses(interface: UsbInterface) -> tuple[str, ...]:
    return tuple(f'0x{endpoint.address:02x}' for endpoint in interface.endpoints)


def _validate_class_specific(interface: UsbInterface) -> None:
    if not interface.class_specific:
        raise UnsupportedDescriptorLayout(
            f'interface {interface.number} lacks class-specific descriptors')
    if interface.kind == 'video_control':
        header = interface.class_specific[0]
        if len(header) < 13 or header[2] != 0x01:
            raise UnsupportedDescriptorLayout(
                'video control class-specific header is not VC header')
        # E0317: VC header baInterfaceNr byte 12 must reference interface 2.
        if header[12] != EXPECTED_VIDEO_STREAMING_INTERFACE:
            raise UnsupportedDescriptorLayout(
                'video control baInterfaceNr != video streaming interface 2')
    if interface.kind == 'video_streaming':
        header = interface.class_specific[0]
        if len(header) < 14 or header[2] != 0x01:
            raise UnsupportedDescriptorLayout(
                'video streaming class-specific header is not VS header')
        # bEndpointAddress is byte 6 in the VS header (E0317).
        if header[6] != int(EXPECTED_VIDEO_STREAMING_ENDPOINT, 16):
            raise UnsupportedDescriptorLayout(
                'video streaming header endpoint address is not 0x82')


def select_uvc_ptp_configuration(
        configuration: UsbConfiguration) -> UsbConfiguration:
    """Validate and return the known UVC+PTP configuration, else fail closed."""
    if configuration.value != SET_CONFIG_CONFIGURATION_VALUE:
        raise UnsupportedConfiguration(
            f'configuration value {configuration.value} is not the verified '
            f'value {SET_CONFIG_CONFIGURATION_VALUE}')
    if configuration.num_interfaces != EXPECTED_INTERFACE_COUNT:
        raise UnsupportedDescriptorLayout(
            f'expected {EXPECTED_INTERFACE_COUNT} interfaces, got '
            f'{configuration.num_interfaces}')

    ptp = tuple(item for item in configuration.interfaces
                if item.kind == 'ptp' and item.alternate_setting == 0)
    video_control = tuple(item for item in configuration.interfaces
                          if item.kind == 'video_control'
                          and item.alternate_setting == 0)
    video_streaming = tuple(item for item in configuration.interfaces
                            if item.kind == 'video_streaming'
                            and item.alternate_setting == 0)
    if (len(ptp), len(video_control), len(video_streaming)) != (1, 1, 1):
        raise UnsupportedDescriptorLayout(
            'expected exactly one PTP, one video-control and one '
            'video-streaming interface')
    ptp_interface = ptp[0]
    vc_interface = video_control[0]
    vs_interface = video_streaming[0]
    if (ptp_interface.number, vc_interface.number, vs_interface.number) != (
            EXPECTED_PTP_INTERFACE, EXPECTED_VIDEO_CONTROL_INTERFACE,
            EXPECTED_VIDEO_STREAMING_INTERFACE):
        raise UnsupportedDescriptorLayout(
            'interface numbers do not match the verified PTP/VC/VS layout')
    for interface in (ptp_interface, vc_interface, vs_interface):
        if (interface.interface_class, interface.interface_subclass,
                interface.interface_protocol) not in (
                    (USB_CLASS_STILL_IMAGE, USB_SUBCLASS_STILL_IMAGE,
                     USB_PROTOCOL_STILL_IMAGE),
                    (USB_CLASS_VIDEO, USB_SC_VIDEOCONTROL, 0),
                    (USB_CLASS_VIDEO, USB_SC_VIDEOSTREAMING, 0)):
            raise UnsupportedDescriptorLayout(
                f'interface {interface.number} class/subclass/protocol is '
                'not the verified UVC/PTP values')
    if len(ptp_interface.endpoints) != 3:
        raise UnsupportedDescriptorLayout(
            f'PTP interface must have 3 endpoints, got '
            f'{len(ptp_interface.endpoints)}')
    if tuple(_endpoint_addresses(ptp_interface)) != EXPECTED_PTP_ENDPOINTS:
        raise UnsupportedDescriptorLayout(
            'PTP endpoint addresses do not match 0x81/0x02/0x83')
    if vc_interface.endpoints:
        raise UnsupportedDescriptorLayout(
            'video control interface must have zero endpoints')
    if len(vs_interface.endpoints) != 1:
        raise UnsupportedDescriptorLayout(
            'video streaming interface must have one endpoint')
    if _endpoint_addresses(vs_interface) != EXPECTED_VIDEO_STREAMING_ENDPOINTS:
        raise UnsupportedDescriptorLayout(
            'video streaming endpoint address is not 0x82')

    iad = tuple(item for item in configuration.associations
                if item.function_class == USB_CLASS_VIDEO)
    if len(iad) != 1:
        raise UnsupportedDescriptorLayout(
            'expected exactly one video function IAD')
    association = iad[0]
    if (association.first_interface, association.interface_count,
            association.function_class, association.function_subclass) != (
                EXPECTED_VIDEO_CONTROL_INTERFACE, 2, USB_CLASS_VIDEO,
                USB_IAD_FUNCTION_VIDEO):
        raise UnsupportedDescriptorLayout(
            'video IAD range/class/subclass do not match interfaces 1-2 '
            'class 0x0E/3')

    _validate_class_specific(vc_interface)
    _validate_class_specific(vs_interface)

    endpoint_addresses = [
        endpoint.address for interface in (ptp_interface, vc_interface,
                                           vs_interface)
        for endpoint in interface.endpoints
    ]
    if len(set(endpoint_addresses)) != len(endpoint_addresses):
        raise UnsupportedDescriptorLayout('duplicate endpoint address')
    return configuration


def load_configuration(
        descriptor_manifest_path: Path | str | None = None,
        enablement_manifest_path: Path | str | None = None,
) -> tuple[UsbConfiguration, dict[str, Any]]:
    """Load + hash-verify + parse + validate the known UVC+PTP descriptor."""
    raw, provenance = load_descriptor_bytes(
        descriptor_manifest_path, enablement_manifest_path)
    configuration = select_uvc_ptp_configuration(
        parse_configuration_descriptor(raw))
    return configuration, provenance


# ---------------------------------------------------------------------------
# SET_CONFIGURATION planning
# ---------------------------------------------------------------------------


def plan_set_configuration(
        config_value: int) -> dict[str, Any]:
    """Plan the host SET_CONFIGURATION request/event for the verified descriptor.

    Returns a pure description (no emulator dependency): the UsbControl
    category/messageId/param 0x1006=0 is the inbound SET_CONFIG message decoded
    by E0323/E0335 and mapped to FSM event 0x13.  Unknown config values refuse.
    """
    if not isinstance(config_value, int) or isinstance(config_value, bool):
        raise UnsupportedConfiguration(
            f'config_value must be an int, got {type(config_value).__name__}')
    if config_value != SET_CONFIG_CONFIGURATION_VALUE:
        raise UnsupportedConfiguration(
            f'config_value {config_value} is not the verified UVC+PTP '
            f'configuration {SET_CONFIG_CONFIGURATION_VALUE}')
    configuration, provenance = load_configuration()
    ptp_interface = next(item for item in configuration.interfaces
                         if item.kind == 'ptp')
    vc_interface = next(item for item in configuration.interfaces
                        if item.kind == 'video_control')
    vs_interface = next(item for item in configuration.interfaces
                       if item.kind == 'video_streaming')
    return {
        'request': {
            'name': 'SET_CONFIGURATION',
            'configuration_value': config_value,
            'category': SET_CONFIG_CATEGORY,
            'message_id': SET_CONFIG_MESSAGE_ID,
            'params': [{
                'id': SET_CONFIG_PARAM_ID,
                'type': SET_CONFIG_PARAM_TYPE,
                'value': SET_CONFIG_PARAM_VALUE,
            }],
        },
        'event': {
            'category': SET_CONFIG_CATEGORY,
            'message_id': SET_CONFIG_MESSAGE_ID,
            'param_0x1006': SET_CONFIG_PARAM_VALUE,
            'fsm_event': SET_CONFIG_FSM_EVENT,
        },
        'configuration': {
            'value': configuration.value,
            'total_length': configuration.total_length,
            'num_interfaces': configuration.num_interfaces,
            'ptp': {
                'interface': ptp_interface.number,
                'endpoints': [item.to_dict()
                              for item in ptp_interface.endpoints],
            },
            'video_control': {
                'interface': vc_interface.number,
                'endpoints': [item.to_dict()
                              for item in vc_interface.endpoints],
            },
            'video_streaming': {
                'interface': vs_interface.number,
                'endpoints': [item.to_dict()
                              for item in vs_interface.endpoints],
            },
            'endpoint_counts': {
                'ptp': len(ptp_interface.endpoints),
                'video_control': len(vc_interface.endpoints),
                'video_streaming': len(vs_interface.endpoints),
            },
        },
        'provenance': provenance,
    }


__all__ = [
    'EXPECTED_DESCRIPTOR_SHA256',
    'EXPECTED_DESCRIPTOR_LENGTH',
    'EXPECTED_PTP_ENDPOINTS',
    'EXPECTED_VIDEO_STREAMING_ENDPOINTS',
    'SET_CONFIG_CATEGORY',
    'SET_CONFIG_MESSAGE_ID',
    'SET_CONFIG_PARAM_ID',
    'SET_CONFIG_PARAM_VALUE',
    'SET_CONFIG_PARAM_TYPE',
    'SET_CONFIG_FSM_EVENT',
    'SET_CONFIG_CONFIGURATION_VALUE',
    'UsbHostEnumError',
    'DescriptorHashMismatch',
    'UnsupportedDescriptorLayout',
    'UnsupportedConfiguration',
    'UsbEndpoint',
    'UsbInterface',
    'UsbInterfaceAssociation',
    'UsbConfiguration',
    'load_descriptor_bytes',
    'parse_configuration_descriptor',
    'select_uvc_ptp_configuration',
    'load_configuration',
    'plan_set_configuration',
]
