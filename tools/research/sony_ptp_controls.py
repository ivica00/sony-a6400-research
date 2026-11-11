"""Sony SDIO settings, independent of WPD/COM and the CinemaHUD HTTP threads.

Wire layout references: gphoto/libgphoto2 camlibs/ptp2/{ptp.h,ptp-pack.c,ptp.c}.
No firmware patches, priority changes, or synthetic camera state.
"""
import struct
import time

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
