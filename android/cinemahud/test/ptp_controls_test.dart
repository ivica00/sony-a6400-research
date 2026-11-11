import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:cinemahud_android/sony_ptp.dart';

Uint8List descriptor(
  int code,
  int type,
  List<int> values,
  int current, {
  bool range = false,
}) {
  final builder = BytesBuilder();
  void put(int value, int size) {
    final b = ByteData(size);
    if (size == 4) {
      b.setUint32(0, value, Endian.little);
    } else if (size == 2) {
      b.setUint16(0, value, Endian.little);
    } else {
      b.setUint8(0, value);
    }
    builder.add(b.buffer.asUint8List());
  }

  final size = 1 << ((type - 1) ~/ 2);
  put(1, 4);
  put(0, 4);
  put(code, 2);
  put(type, 2);
  put(0, 1);
  put(1, 1);
  put(values.first, size);
  put(current, size);
  put(range ? 1 : 2, 1);
  if (range) {
    put(0, size);
    put((1 << (size * 8)) - 1, size);
    put(1, size);
  } else {
    put(values.length, 2);
    for (final value in values) {
      put(value, size);
    }
  }
  return builder.toBytes();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test(
    'Legacy notches confirm shutter, iris, ISO and non-monotonic EV enum',
    () async {
      for (final name in ['shutter', 'aperture', 'iso', 'ev']) {
        final code = propertyCodes[name]!;
        final type = name == 'aperture'
            ? 4
            : name == 'ev'
            ? 3
            : 6;
        final dial = switch (name) {
          'shutter' => [65636, 65661],
          'aperture' => [280, 320],
          'iso' => [0xffffff, 100, 800],
          _ => [0, 300],
        };
        var pos = 0, writes = 0;
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
            .setMockMethodCallHandler(UsbPtp.channel, (call) async {
              final args = Map<String, dynamic>.from(call.arguments as Map);
              if (args['code'] == 0x9209) {
                return {
                  'rc': 0x2001,
                  'data': descriptor(
                    code,
                    type,
                    name == 'ev' ? [300, 0] : dial,
                    dial[pos],
                    range: name == 'shutter' || name == 'aperture',
                  ),
                };
              }
              expect(args['code'], 0x9207);
              expect(args['args'], [code]);
              final data = args['data'] as Uint8List;
              pos += data[0] == 1 ? 1 : -1;
              writes++;
              return {'rc': 0x2001, 'data': Uint8List(0)};
            });
        final usb = UsbPtp();
        await usb.apply(name, dial.last);
        expect(usb.properties[code]!.current, dial.last);
        await usb.apply(name, dial.first);
        expect(pos, 0);
        expect(writes, 2 * (dial.length - 1));
      }
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(UsbPtp.channel, null);
    },
  );
  test('An acknowledged but unchanged ISO step never succeeds', () async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(UsbPtp.channel, (call) async {
          final args = Map<String, dynamic>.from(call.arguments as Map);
          return {
            'rc': 0x2001,
            'data': args['code'] == 0x9209
                ? descriptor(0xd21e, 6, [100, 800], 100)
                : Uint8List(0),
          };
        });
    await expectLater(UsbPtp().apply('iso', 800), throwsStateError);
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(UsbPtp.channel, null);
  });
}
