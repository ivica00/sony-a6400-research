import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/services.dart';

class PtpProperty {
  final int code, type, access, enabled, current;
  final List<int> values;
  PtpProperty(
    this.code,
    this.type,
    this.access,
    this.enabled,
    this.current,
    this.values,
  );
}

class WireReader {
  final ByteData data;
  int pos = 0;
  WireReader(Uint8List bytes) : data = ByteData.sublistView(bytes);
  int number(int size, {bool signed = false}) {
    if (pos + size > data.lengthInBytes) {
      throw const FormatException('Truncated Sony descriptor');
    }
    final at = pos;
    pos += size;
    return switch (size) {
      1 => signed ? data.getInt8(at) : data.getUint8(at),
      2 =>
        signed
            ? data.getInt16(at, Endian.little)
            : data.getUint16(at, Endian.little),
      4 =>
        signed
            ? data.getInt32(at, Endian.little)
            : data.getUint32(at, Endian.little),
      8 =>
        signed
            ? data.getInt64(at, Endian.little)
            : data.getUint64(at, Endian.little),
      _ => throw const FormatException('Unsupported size'),
    };
  }

  dynamic value(int type) {
    if (type >= 1 && type <= 8) {
      return number(1 << ((type - 1) ~/ 2), signed: type.isOdd);
    }
    if (type == 0xffff) {
      final count = number(1);
      return List.generate(count, (_) => number(2));
    }
    if (type == 9 || type == 10) {
      number(8);
      number(8);
      return 0;
    }
    if ((type & 0x4000) != 0) {
      final count = number(4);
      if (count > 65536) {
        throw const FormatException('Oversized property array');
      }
      return List.generate(count, (_) => value(type & ~0x4000));
    }
    throw FormatException('Unsupported datatype $type');
  }
}

Map<int, PtpProperty> parseSonyProperties(Uint8List bytes) {
  final r = WireReader(bytes), properties = <int, PtpProperty>{};
  final count = r.number(4);
  if (count > 4096 || r.number(4) != 0) {
    throw const FormatException('Invalid property header');
  }
  for (var i = 0; i < count; i++) {
    final code = r.number(2),
        type = r.number(2),
        access = r.number(1),
        enabled = r.number(1);
    r.value(type);
    final current = r.value(type), form = r.number(1);
    final values = <int>[];
    if (form == 1) {
      for (var j = 0; j < 3; j++) {
        r.value(type);
      }
    } else if (form == 2) {
      final n = r.number(2);
      for (var j = 0; j < n; j++) {
        final value = r.value(type);
        if (value is int) values.add(value);
      }
    } else if (form != 0) {
      throw FormatException('Unknown property form $form');
    }
    if (properties.containsKey(code)) {
      throw const FormatException('Duplicate property');
    }
    if (current is int) {
      properties[code] = PtpProperty(
        code,
        type,
        access,
        enabled,
        current,
        values,
      );
    }
  }
  if (r.pos != bytes.length) {
    throw const FormatException('Trailing property data');
  }
  return properties;
}

const propertyCodes = {
  'shutter': 0xd20d,
  'aperture': 0x5007,
  'iso': 0xd21e,
  'ev': 0x5010,
};
const apertures = [
  100,
  110,
  120,
  140,
  160,
  180,
  200,
  220,
  250,
  280,
  320,
  350,
  400,
  450,
  500,
  560,
  630,
  710,
  800,
  900,
  1000,
  1100,
  1300,
  1400,
  1600,
  1800,
  2000,
  2200,
];
final shutters = [
  for (final d in [
    3,
    4,
    5,
    6,
    8,
    10,
    13,
    15,
    20,
    25,
    30,
    40,
    45,
    50,
    60,
    80,
    90,
    100,
    125,
    160,
    180,
    200,
    250,
    320,
    350,
    400,
    500,
    640,
    725,
    800,
    1000,
    1250,
    1500,
    1600,
    2000,
    2500,
    3000,
    3200,
    4000,
  ])
    (1 << 16) | d,
  for (final n in [1, 2, 4, 5, 6, 8, 10, 13, 15, 20, 25, 30]) (n << 16) | 1,
];

String settingLabel(String name, int value) => switch (name) {
  'iso' =>
    (value & 0xffffff) == 0xffffff
        ? 'Auto'
        : '${value & 0xffffff}${value >> 24 == 0 ? '' : ' NR${value >> 24}'}',
  'aperture' => 'f/${(value / 100).toStringAsFixed(value % 100 == 0 ? 0 : 1)}',
  'ev' => '${value > 0 ? '+' : ''}${(value / 1000).toStringAsFixed(1)}',
  'shutter' =>
    value == 0
        ? 'BULB'
        : (value & 0xffff) == 1
        ? '${value >> 16}″'
        : '${value >> 16}/${value & 0xffff}',
  _ => '$value',
};

class UsbPtp {
  static const channel = MethodChannel('com.cinemahud/usb');
  Map<int, PtpProperty> properties = {};
  Future<Map<dynamic, dynamic>> transaction(
    int code, [
    List<int> args = const [],
    Uint8List? data,
  ]) async {
    final result = await channel.invokeMapMethod<dynamic, dynamic>(
      'transaction',
      {'code': code, 'args': args, 'data': data},
    );
    if (result == null) throw StateError('Empty USB response');
    return result;
  }

  Future<void> checked(int code, List<int> args) async {
    final reply = await transaction(code, args);
    if (reply['rc'] != 0x2001) {
      throw StateError('PTP 0x${code.toRadixString(16)}: ${reply['rc']}');
    }
  }

  Future<void> connect() async {
    await channel.invokeMethod('connect');
    final session = await transaction(0x1002, [1]);
    if (session['rc'] != 0x2001 && session['rc'] != 0x201e) {
      throw StateError('PTP session rejected');
    }
    await checked(0x9201, [1, 0, 0]);
    await checked(0x9201, [2, 0, 0]);
    await checked(0x9202, [0xc8]);
    await checked(0x9201, [3, 0, 0]);
    await refresh();
  }

  Future<void> disconnect() async {
    await channel.invokeMethod('disconnect');
    properties = {};
  }

  Future<void> refresh() async {
    final reply = await transaction(0x9209);
    if (reply['rc'] != 0x2001) {
      throw StateError('Camera settings unavailable: ${reply['rc']}');
    }
    properties = parseSonyProperties(reply['data'] as Uint8List);
  }

  Future<Uint8List?> frame() async {
    final reply = await transaction(0x1009, [0xffffc002]);
    if (reply['rc'] != 0x2001) return null;
    final data = reply['data'] as Uint8List;
    var start = -1;
    for (var i = 0; i + 1 < data.length; i++) {
      if (data[i] == 255 && data[i + 1] == 216) {
        start = i;
        break;
      }
    }
    if (start < 0) return null;
    for (var i = data.length - 2; i > start; i--) {
      if (data[i] == 255 && data[i + 1] == 217) {
        return Uint8List.sublistView(data, start, i + 2);
      }
    }
    return null;
  }

  List<int> options(String name, PtpProperty p) => p.values.isNotEmpty
      ? p.values
      : name == 'shutter'
      ? shutters
      : name == 'aperture'
      ? apertures
      : [];
  Map<String, dynamic> snapshot() {
    final controls = <String, dynamic>{};
    for (final entry in propertyCodes.entries) {
      final p = properties[entry.value];
      if (p == null) continue;
      final values = options(entry.key, p);
      controls[entry.key] = {
        'value': p.current,
        'label': settingLabel(entry.key, p.current),
        'writable':
            p.enabled == 1 &&
            values.isNotEmpty &&
            p.access < 128 &&
            !(entry.key == 'aperture' &&
                (p.current == 0 || p.current == 65535)) &&
            !(entry.key == 'shutter' &&
                (p.current == 0 || p.current == 0xffffffff)),
        'options': [
          for (final v in values)
            {'value': v, 'label': settingLabel(entry.key, v)},
        ],
      };
    }
    return {
      'controls': controls,
      'battery': properties[0x5001]?.current,
      'white_balance': {
        2: 'AUTO',
        4: 'DAY',
        6: 'TUNG',
        0x8010: 'CLOUD',
        0x8011: 'SHADE',
      }[properties[0x5005]?.current],
      'focus_mode': {
        1: 'MF',
        2: 'AF-S',
        3: 'AF-C',
        0x8004: 'AF-A',
        0x8005: 'DMF',
      }[properties[0x500a]?.current],
      'exposure_mode': {
        1: 'M',
        2: 'P',
        3: 'A',
        4: 'S',
      }[properties[0x500e]?.current],
    };
  }

  Future<void> apply(String name, int target) async {
    final code = propertyCodes[name];
    if (code == null) throw ArgumentError('Unsupported camera setting');
    await refresh();
    var p = properties[code];
    if (p == null ||
        p.enabled != 1 ||
        p.access >= 128 ||
        !options(name, p).contains(target)) {
      throw StateError('Setting is unavailable in this mode');
    }
    if (p.current == target) return;
    if (p.access != 0) {
      final size = 1 << ((p.type - 1) ~/ 2), wire = ByteData(8);
      wire.setInt64(0, target, Endian.little);
      final reply = await transaction(0x9205, [
        code,
      ], Uint8List.sublistView(wire.buffer.asUint8List(), 0, size));
      if (reply['rc'] != 0x2001) throw StateError('Camera rejected setting');
      await Future<void>.delayed(const Duration(milliseconds: 200));
      await refresh();
      if (properties[code]?.current == target) return;
      throw StateError('Camera did not confirm requested value');
    }
    double metric(int value, PtpProperty prop) {
      if (name == 'iso') {
        final index = prop.values.indexOf(value);
        if (index < 0) throw StateError('ISO is not in camera enumeration');
        return index.toDouble();
      }
      if (name == 'shutter') {
        if (value == 0 || value == 0xffffffff || (value & 0xffff) == 0) {
          throw StateError('Shutter unavailable');
        }
        return -(value >> 16) / (value & 0xffff);
      }
      return value.toDouble();
    }

    final deadline = DateTime.now().add(const Duration(seconds: 10));
    for (var step = 0; step < 64; step++) {
      p = properties[code]!;
      if (p.current == target) return;
      if (p.enabled != 1 || !options(name, p).contains(target)) {
        throw StateError('Camera mode changed');
      }
      final before = p.current,
          old = metric(before, p),
          goal = metric(target, p);
      final direction = goal > old ? 1 : -1;
      final reply = await transaction(0x9207, [
        code,
      ], Uint8List.fromList([direction & 255]));
      if (reply['rc'] != 0x2001) throw StateError('Camera rejected step');
      var changed = false;
      for (var poll = 0; poll < 12; poll++) {
        await Future<void>.delayed(const Duration(milliseconds: 100));
        await refresh();
        if (properties[code]!.current != before) {
          changed = true;
          break;
        }
      }
      if (!changed) throw StateError('Mode/lens limit: camera did not change');
      await Future<void>.delayed(const Duration(milliseconds: 120));
      await refresh();
      p = properties[code]!;
      if (p.current == target) return;
      final now = metric(p.current, p);
      if ((now - goal) * direction > 0 || (now - old) * direction <= 0) {
        throw StateError('Exact value unavailable; current value read back');
      }
      if (DateTime.now().isAfter(deadline)) {
        throw StateError('Confirmation timed out; check current value');
      }
    }
    throw StateError('Camera step limit reached');
  }
}
