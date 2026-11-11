"""Sony SDIO settings, independent of WPD/COM and the CinemaHUD HTTP threads.

Wire layout references: gphoto/libgphoto2 camlibs/ptp2/{ptp.h,ptp-pack.c,ptp.c}.
No firmware patches, priority changes, or synthetic camera state.

Tested configurations (offline): the 0x9209 parser is exercised with little-endian
scalar descriptors (INT8/UINT8/INT16/UINT16/INT32/UINT32), form=1 ranges and
form=2 enumerations. Physical evidence referenced but not re-run here:
``docs/CINEMAHUD_STOCK_PTP.md`` (1730-byte 0x9209 payload; shutter 1/100,
aperture f/2.8, ISO Auto; 0x9205 no-readback and 0x9207 stepped confirmation)
and the PTP/libgphoto2 wire facts named above.

Unknown handling: ``decode_property_value`` never invents a label or a success
for an unknown code, an unlisted enum value, an unavailable sentinel, or a value
outside a documented reference range. ``validate_property_value`` and
``encode_property_value`` raise instead of silently coercing. Interface/model
labels in ``PROPERTY_SPECS`` are offline PTP mappings where noted; camera
descriptor values, access flags and current mode remain authoritative.

Known unknowns: the complete Sony enum sets for white balance, focus mode and
exposure mode are not physically validated; EV and battery reference ranges are
PTP reference bounds, not a measurement of every a6400 mode/lens; 0xD25A
(priority mode) is a known code with undecoded value semantics; INT128/STRING
parsing exists but has no retained camera fixture.
"""
import struct
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple

FORMATS = {1: 'b', 2: 'B', 3: 'h', 4: 'H', 5: 'i', 6: 'I', 7: 'q', 8: 'Q'}
APERTURES = [100, 110, 120, 140, 160, 180, 200, 220, 250, 280, 320, 350, 400, 450, 500, 560, 630, 710, 800, 900, 1000, 1100, 1300, 1400, 1600, 1800, 2000, 2200]
SHUTTERS = [(1 << 16) | d for d in [3,4,5,6,8,10,13,15,20,25,30,40,45,50,60,80,90,100,125,160,180,200,250,320,350,400,500,640,725,800,1000,1250,1500,1600,2000,2500,3000,3200,4000]] + [(n << 16) | 1 for n in [1,2,4,5,6,8,10,13,15,20,25,30]]

def choices(name, p):
    if p['values']:
        return p['values']
    candidates = APERTURES if name == 'aperture' else SHUTTERS if name == 'shutter' else []
    if p['limits']:
        lo, hi, step = p['limits']
        candidates = [v for v in candidates if lo <= v <= hi]
    return candidates


PROPERTIES = {'shutter': 0xD20D, 'aperture': 0x5007,
              'iso': 0xD21E, 'ev': 0x5010}


class Reader:
    def __init__(self, data):
        self.data, self.pos = data, 0

    def take(self, n):
        if n < 0 or self.pos + n > len(self.data):
            raise ValueError('Truncated Sony property data')
        result = self.data[self.pos:self.pos + n]
        self.pos += n
        return result

    def number(self, fmt):
        return struct.unpack('<' + fmt, self.take(struct.calcsize(fmt)))[0]

    def value(self, dtype):
        if dtype in FORMATS:
            return self.number(FORMATS[dtype])
        if dtype in (9, 10):
            return int.from_bytes(self.take(16), 'little', signed=dtype == 9)
        if dtype == 0xFFFF:
            return self.take(self.number('B') * 2).decode('utf-16-le').rstrip('\0')
        if dtype & 0x4000 and (dtype & ~0x4000) in FORMATS:
            count = self.number('I')
            if count > 65536:
                raise ValueError('Oversized Sony property array')
            return [self.value(dtype & ~0x4000) for _ in range(count)]
        raise ValueError(f'Unsupported PTP datatype 0x{dtype:04x}')


def parse_properties(data):
    """Parse the 0x9209 count/reserved header and Sony extended descriptors."""
    r = Reader(data)
    count, reserved = r.number('I'), r.number('I')
    if count > 4096 or reserved != 0:
        raise ValueError('Invalid Sony property header')
    result = {}
    for _ in range(count):
        code, dtype = r.number('H'), r.number('H')
        access, enabled = r.number('B'), r.number('B')
        default, current = r.value(dtype), r.value(dtype)
        form = r.number('B')
        values, limits = [], None
        if form == 1:
            limits = [r.value(dtype) for _ in range(3)]
        elif form == 2:
            n = r.number('H')
            values = [r.value(dtype) for _ in range(n)]
        elif form != 0:
            raise ValueError(f'Unknown Sony property form {form}')
        if code in result:
            raise ValueError('Duplicate Sony property')
        result[code] = dict(code=code, datatype=dtype, access=access,
                            enabled=enabled, default=default, current=current,
                            form=form, values=values, limits=limits)
    if r.pos != len(data):
        raise ValueError('Trailing Sony property data')
    return result


def label(name, value):
    if name == 'aperture':
        return f'f/{value / 100:g}'
    if name == 'ev':
        return f'{value / 1000:+.1f}'
    if name == 'iso':
        return 'Auto' if value == 0xFFFFFF else str(value)
    if name == 'shutter':
        numerator, denominator = value >> 16, value & 0xFFFF
        return f'{numerator}/{denominator}' if denominator else 'Bulb'
    return str(value)


FORMAT_NAMES = {1: 'INT8', 2: 'UINT8', 3: 'INT16', 4: 'UINT16',
                5: 'INT32', 6: 'UINT32', 7: 'INT64', 8: 'UINT64',
                9: 'INT128', 10: 'UINT128', 0xFFFF: 'STRING'}

# PTP/libgphoto2 property names.  These are reference names; Sony extends some
# enum value sets (0x8000+).  Absence here is not a claim that a camera does not
# expose the property.  Evidence prefixes: "ptp:" = PTP/libgphoto2 reference
# (URLs above), "physical:" = docs/CINEMAHUD_STOCK_PTP.md physical receipt,
# "tool:" = existing CinemaHUD mapping in this repository.
@dataclass(frozen=True)
class PropertySpec:
    code: int
    name: str
    ptp_name: str
    datatype: int
    unit: Optional[str] = None
    reference_range: Optional[Tuple[int, int]] = None
    enum: Mapping[int, str] = field(default_factory=dict)
    auto_value: Optional[int] = None
    unavailable_values: Tuple[int, ...] = ()
    evidence: str = ''

    def datatype_name(self) -> str:
        return FORMAT_NAMES.get(self.datatype, f'0x{self.datatype:04x}')


PROPERTY_SPECS: Dict[int, PropertySpec] = {
    0x5001: PropertySpec(
        0x5001, 'battery', 'BatteryLevel', 2, 'percent', (0, 100),
        unavailable_values=(),
        evidence='ptp:PTP_DPC_BatteryLevel UINT8 0..100; tool:publish_settings reads 0x5001 as a label only'),
    0x5005: PropertySpec(
        0x5005, 'white_balance', 'WhiteBalance', 4, 'enum',
        enum={1: 'Manual', 2: 'Auto', 3: 'One-push', 4: 'Daylight',
              5: 'Fluorescent', 6: 'Tungsten', 7: 'Flash',
              0x8010: 'Cloudy', 0x8011: 'Shade', 0x8012: 'Color temperature',
              0x8013: 'Custom'},
        evidence='ptp:WhiteBalance enum 1..7; tool:Sony 0x8010..0x8013 labels; camera enum set and 0x8012/0x8013 semantics not physically validated'),
    0x5007: PropertySpec(
        0x5007, 'aperture', 'FNumber', 4, 'f-number x100', (100, 2200),
        unavailable_values=(0, 0xFFFF),
        evidence='physical:0x5007 descriptor in 0x9209; f/2.8 (280) roundtrip; ptp:FNumber UINT16; descriptor limits/candidates are authoritative'),
    0x500A: PropertySpec(
        0x500A, 'focus_mode', 'FocusMode', 4, 'enum',
        enum={1: 'MF', 2: 'AF-S', 3: 'AF-C', 0x8004: 'AF-A', 0x8005: 'DMF'},
        evidence='ptp:FocusMode 1..3; tool:Sony 0x8004/0x8005 labels; PTP calls 2/3 Automatic/AutomaticMacro, so the camera-specific labels are not physically validated'),
    0x500E: PropertySpec(
        0x500E, 'exposure_mode', 'ExposureProgramMode', 4, 'enum',
        enum={1: 'M', 2: 'P', 3: 'A', 4: 'S', 5: 'Program creative',
              6: 'Program action', 7: 'Portrait', 0x8050: 'Movie M'},
        evidence='ptp:ExposureProgramMode 1..7; tool:Sony 0x8050 label; not physically validated'),
    0x5010: PropertySpec(
        0x5010, 'ev', 'ExposureBiasCompensation', 3, 'millistop (EV x1000)',
        (-3000, 3000),
        evidence='physical:EV 0 -> +0.3 -> 0 (values 0/300) roundtrip; ptp:INT16 millistops; descriptor form=1 limits are authoritative, the -3000..3000 reference is not a camera measurement'),
    0xD20D: PropertySpec(
        0xD20D, 'shutter', 'ShutterSpeed (Sony SDIO)', 6,
        'numerator<<16 | denominator', (1, 0x7FFFFFFF),
        unavailable_values=(0, 0xFFFFFFFF),
        evidence='physical:0xD20D descriptor; shutter 1/100 (0x00010064) roundtrip; ptp:Sony property namespace; encoding numerator/denominator'),
    0xD21E: PropertySpec(
        0xD21E, 'iso', 'ISO (Sony SDIO)', 6, 'ISO',
        auto_value=0xFFFFFF,
        evidence='physical:0xD21E descriptor; ISO Auto=0xFFFFFF and 0x9207 enumeration-order stepping confirmed; absolute 0x9205 did not confirm'),
    0xD25A: PropertySpec(
        0xD25A, 'priority_mode', 'SONY_PROP_PRIORITY_MODE', 4,
        evidence='tool:liveview handshake constant; value semantics/known enum not decoded, so no label is claimed'),
}

PTP_PROPERTY_NAMES = {code: spec.ptp_name for code, spec in PROPERTY_SPECS.items()}


@dataclass(frozen=True)
class ValueDecoding:
    """Offline decode result; ``known_value`` is False when no label is proven."""

    code: int
    value: Any
    known_code: bool
    known_value: bool
    label: Optional[str]
    unit: Optional[str]
    spec_name: Optional[str]
    reason: Optional[str] = None


def property_spec(code: int) -> Optional[PropertySpec]:
    return PROPERTY_SPECS.get(code)


def decode_property_value(code: int, value: Any) -> ValueDecoding:
    """Decode one property value without guessing unknown enum/sentinel values."""
    spec = PROPERTY_SPECS.get(code)
    if spec is None:
        return ValueDecoding(code, value, False, False, None, None, None,
                             'unknown_property_code')
    if not isinstance(value, int) or isinstance(value, bool):
        return ValueDecoding(code, value, True, False, None, spec.unit,
                             spec.name, 'unsupported_value_type')
    if value in spec.unavailable_values:
        return ValueDecoding(code, value, True, False, None, spec.unit,
                             spec.name, 'unavailable_in_current_state')
    base = dict(code=code, value=value, known_code=True, unit=spec.unit,
                spec_name=spec.name)
    if spec.enum:
        if value in spec.enum:
            return ValueDecoding(label=spec.enum[value], known_value=True,
                                 reason=None, **base)
        if spec.auto_value is not None and value == spec.auto_value:
            return ValueDecoding(label='Auto', known_value=True, reason=None,
                                 **base)
        return ValueDecoding(label=None, known_value=False,
                             reason='unlisted_enum_value', **base)
    if code == 0x5001:
        if 0 <= value <= 100:
            return ValueDecoding(label=f'{value}%', known_value=True,
                                 reason=None, **base)
        return ValueDecoding(label=None, known_value=False,
                             reason='outside_reference_range', **base)
    if code == 0x5007:
        note = None
        if spec.reference_range and not (spec.reference_range[0] <= value <= spec.reference_range[1]):
            note = 'outside_reference_range'
        return ValueDecoding(label=f'f/{value / 100:g}', known_value=True,
                             reason=note, **base)
    if code == 0x5010:
        note = None
        if spec.reference_range and not (spec.reference_range[0] <= value <= spec.reference_range[1]):
            note = 'outside_reference_range'
        return ValueDecoding(label=f'{value / 1000:+.1f} EV', known_value=True,
                             reason=note, **base)
    if code == 0xD20D:
        numerator, denominator = value >> 16, value & 0xFFFF
        if denominator == 0:
            # Existing CinemaHUD label() maps denominator 0 to Bulb; keep that
            # offline convention while marking the encoding in the reason.
            return ValueDecoding(label='Bulb', known_value=True,
                                 reason='bulb_encoding', **base)
        if numerator:
            return ValueDecoding(label=f'{numerator}/{denominator}',
                                 known_value=True, reason=None, **base)
        return ValueDecoding(label=None, known_value=False,
                             reason='invalid_shutter_encoding', **base)
    if code == 0xD21E:
        if value == spec.auto_value:
            return ValueDecoding(label='Auto', known_value=True, reason=None,
                                 **base)
        if value > 0:
            return ValueDecoding(label=str(value), known_value=True,
                                 reason=None, **base)
        return ValueDecoding(label=None, known_value=False,
                             reason='invalid_iso_value', **base)
    # Known code with no offline label rule: keep the numeric value, claim no label.
    return ValueDecoding(label=None, known_value=True,
                         reason='label_not_mapped', **base)


def decode_properties(properties: Mapping[int, Mapping[str, Any]]) -> Dict[int, ValueDecoding]:
    """Decode all parsed descriptors (known and unknown codes) without mutation."""
    return {code: decode_property_value(code, descriptor.get('current'))
            for code, descriptor in properties.items()}


def validate_property_value(code: int, value: Any) -> int:
    """Validate a scalar write target; raise instead of coercing/guessing."""
    spec = PROPERTY_SPECS.get(code)
    if spec is None:
        raise ValueError(f'Unknown PTP property code 0x{code:04x}')
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError('PTP property value must be an integer')
    if value in spec.unavailable_values:
        raise ValueError('PTP property value is an unavailable sentinel')
    if spec.enum:
        if value not in spec.enum and value != spec.auto_value:
            raise ValueError('PTP property value is not in the declared enum')
    if code == 0x5001 and not 0 <= value <= 100:
        raise ValueError('Battery level outside 0..100 reference range')
    if code == 0x5007:
        low, high = spec.reference_range
        if not low <= value <= high:
            raise ValueError('Aperture outside the offline reference range')
    if code == 0x5010:
        low, high = spec.reference_range
        if not low <= value <= high:
            raise ValueError('EV outside the offline reference range')
    if code == 0xD20D:
        numerator, denominator = value >> 16, value & 0xFFFF
        if not numerator or not denominator:
            raise ValueError('Shutter must encode positive numerator/denominator')
    if code == 0xD21E and value != spec.auto_value and value <= 0:
        raise ValueError('ISO must be positive or the Auto sentinel')
    if spec.datatype in FORMATS:
        fmt = FORMATS[spec.datatype]
        size = struct.calcsize(fmt)
        try:
            struct.pack('<' + fmt, value)
        except struct.error as exc:
            raise ValueError(f'Value does not fit {spec.datatype_name()} ({size} bytes)') from exc
    return value


def encode_property_value(code: int, value: Any) -> bytes:
    """Encode a validated scalar using the offline spec datatype."""
    validate_property_value(code, value)
    spec = PROPERTY_SPECS[code]
    if spec.datatype not in FORMATS:
        raise ValueError('Datatype has no offline scalar encoding')
    return struct.pack('<' + FORMATS[spec.datatype], value)


def validate_setting_value(name: str, value: Any) -> int:
    if name not in PROPERTIES:
        raise ValueError('Unknown setting')
    return validate_property_value(PROPERTIES[name], value)


class SonySettings:
    """Run only on the thread owning the WPD driver, shared with frame reads."""
    def __init__(self, driver):
        self.driver = driver
        self.properties = {}
        self.on_progress = None

    def _wait(self, seconds):
        # The WPD owner thread can fetch preview frames between property polls.
        # No second COM owner or concurrent USB transaction is introduced.
        if self.on_progress is None:
            time.sleep(seconds)
            return
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.on_progress()
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(0.002, remaining))

    def refresh(self):
        rc, data = self.driver.sendReadCommand(0x9209, [])
        if rc != 0x2001:
            raise RuntimeError(f'Sony settings read failed: 0x{rc:04x}')
        self.properties = parse_properties(data)
        return self.snapshot()

    def snapshot(self):
        controls = {}
        for name, code in PROPERTIES.items():
            p = self.properties.get(code)
            if not p or p['datatype'] not in FORMATS:
                continue
            # Mode-2 descriptors may have access=0 while enabled=1. Only
            # offer absolute values explicitly enumerated by the camera.
            values = choices(name, p)
            writable = p['enabled'] == 1 and bool(values) and not (p['access'] & 0x80)
            if name == 'aperture' and p['current'] in (0, 65535): writable = False
            if name == 'shutter' and p['current'] in (0, 0xFFFFFFFF): writable = False
            controls[name] = dict(value=p['current'], label=label(name, p['current']),
                                  writable=writable, code=code,
                                  options=[dict(value=v, label=label(name, v)) for v in values], candidates_only=not bool(p['values']))
        return controls

    def decoded_properties(self):
        """All parsed descriptors decoded offline (unknowns keep known_code=False)."""
        return decode_properties(self.properties)

    def describe_control(self, name):
        """Return the UI-facing control plus offline datatype/known-value fields."""
        if name not in PROPERTIES:
            raise ValueError('Unknown setting')
        control = self.snapshot().get(name)
        if not control:
            return None
        code = PROPERTIES[name]
        descriptor = self.properties[code]
        decoded = decode_property_value(code, descriptor['current'])
        control = dict(control)
        control.update(datatype=descriptor['datatype'],
                       datatype_name=FORMAT_NAMES.get(descriptor['datatype'], 'UNKNOWN'),
                       unit=decoded.unit, known_value=decoded.known_value,
                       decode_reason=decoded.reason)
        return control

    def apply(self, name, value, timeout=2.0):
        if name not in PROPERTIES or type(value) is not int:
            raise ValueError('Unknown setting or invalid value')
        self.refresh()  # recheck current mode/lens restrictions before writing
        control = self.snapshot().get(name)
        if not control or not control['writable']:
            raise ValueError('Camera does not currently allow this setting')
        p = self.properties[PROPERTIES[name]]
        if value not in choices(name, p):
            raise ValueError('Value is not advertised by the camera')
        if p['access'] == 0:
            return self._step_value(name, value)
        rc = self.driver.sendWriteCommand(0x9205, [p['code']],
                                          struct.pack('<' + FORMATS[p['datatype']], value))
        if rc != 0x2001:
            raise RuntimeError(f'Camera rejected setting: 0x{rc:04x}')
        deadline = time.monotonic() + timeout
        while True:
            self.refresh()
            if self.properties.get(p['code'], {}).get('current') == value:
                return self.snapshot()
            if time.monotonic() >= deadline:
                raise RuntimeError('Camera did not confirm the requested value')
            self._wait(0.05)

    def _step_value(self, name, target):
        """Bounded legacy Sony notches with exact readback, including range props.

        Range picker values are candidates; only readback proves lens/mode support.
        Direction follows enum order for ISO, exposure time for shutter, numeric
        f-number/EV for the other controls. Never report nearest as exact success.
        """
        code = PROPERTIES[name]
        def metric(value, p):
            if name == 'iso':
                return p['values'].index(value)
            if name == 'shutter':
                n, d = value >> 16, value & 0xFFFF
                if not n or not d or value == 0xFFFFFFFF:
                    raise ValueError('Shutter is unavailable in this camera mode')
                return -n / d
            return value
        deadline = time.monotonic() + 8
        for _ in range(64):
            p = self.properties[code]
            current = p['current']
            if current == target:
                return self.snapshot()
            if p['enabled'] != 1 or target not in choices(name, p):
                raise RuntimeError('Setting is unavailable in the current camera state')
            old_metric, target_metric = metric(current, p), metric(target, p)
            direction = 1 if target_metric > old_metric else -1
            rc = self.driver.sendWriteCommand(0x9207, [code], struct.pack('<b', direction))
            if rc != 0x2001:
                raise RuntimeError(f'Camera rejected {name} step: 0x{rc:04x}')
            step_deadline = min(deadline, time.monotonic() + 1.5)
            while True:
                self._wait(0.08)
                self.refresh()
                new = self.properties[code]['current']
                if new != current:
                    break
                if time.monotonic() >= step_deadline:
                    raise RuntimeError(f'Camera did not confirm {name} step (mode/lens limit)')
            # Let a delayed camera response settle before issuing another notch.
            self._wait(0.12)
            self.refresh()
            p = self.properties[code]
            new = p['current']
            if new == target:
                return self.snapshot()
            new_metric = metric(new, p)
            if (new_metric - target_metric) * direction > 0:
                raise RuntimeError('Requested value is skipped by the current lens/mode; current value was read back')
            if (new_metric - old_metric) * direction <= 0:
                raise RuntimeError('Camera value did not progress toward requested setting')
            if time.monotonic() >= deadline:
                raise RuntimeError('Setting deadline reached; read current camera value')
        raise RuntimeError('Camera setting step limit reached')
