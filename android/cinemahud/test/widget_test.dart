// This is a basic Flutter widget test.
//
// To perform an interaction with a widget in your test, use the WidgetTester
// utility in the flutter_test package. For example, you can send tap and scroll
// gestures. You can also use WidgetTester to find child widgets in the widget
// tree, read text, and verify that the values of widget properties are correct.

import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:cinemahud_android/main.dart';
import 'package:cinemahud_android/sony_ptp.dart';

void main() {
  test('Sony descriptors preserve enum order and reject truncations', () {
    final bytes = ByteData(39);
    var at = 0;
    void put(int value, int size) {
      if (size == 4) {
        bytes.setUint32(at, value, Endian.little);
      } else if (size == 2) {
        bytes.setUint16(at, value, Endian.little);
      } else {
        bytes.setUint8(at, value);
      }
      at += size;
    }

    put(1, 4);
    put(0, 4);
    put(0xd21e, 2);
    put(6, 2);
    put(0, 1);
    put(1, 1);
    put(100, 4);
    put(0xffffff, 4);
    put(2, 1);
    put(3, 2);
    put(0xffffff, 4);
    put(100, 4);
    put(800, 4);
    final wire = Uint8List.sublistView(bytes.buffer.asUint8List(), 0, at);
    final p = parseSonyProperties(wire)[0xd21e]!;
    expect(p.current, 0xffffff);
    expect(p.values, [0xffffff, 100, 800]);
    for (var i = 0; i < wire.length; i++) {
      expect(
        () => parseSonyProperties(Uint8List.sublistView(wire, 0, i)),
        throwsFormatException,
      );
    }
  });
  testWidgets(
    'Landscape monitor has exposure controls and an accessible menu',
    (tester) async {
      tester.view.physicalSize = const Size(1000, 450);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(
            UsbPtp.channel,
            (call) async =>
                call.method == 'launchOptions' ? <String, dynamic>{} : null,
          );
      await tester.pumpWidget(const CinemaApp());
      await tester.pump();
      expect(find.text('SHUTTER'), findsOneWidget);
      expect(find.text('IRIS'), findsOneWidget);
      expect(find.text('OFFLINE'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.tap(find.text('MENU'));
      await tester.pumpAndSettle();
      expect(find.text('CINEMA HUD / MONITOR'), findsOneWidget);
      expect(find.text('CONNECT'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.tap(find.text('CLOSE'));
      await tester.pumpAndSettle();
      await tester.pumpWidget(const SizedBox());
      await tester.pumpAndSettle();
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(UsbPtp.channel, null);
    },
  );
}
