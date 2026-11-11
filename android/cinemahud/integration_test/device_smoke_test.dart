import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:cinemahud_android/main.dart' as app;
import 'package:cinemahud_android/camera_controller.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets('Xiaomi PC bridge liveview and exposure UI roundtrips', (
    tester,
  ) async {
    await app.main();
    CameraController? camera;
    for (var i = 0; i < 120; i++) {
      await tester.pump(const Duration(milliseconds: 100));
      final monitor = find.byType(app.Monitor);
      if (monitor.evaluate().isNotEmpty) {
        final dynamic state = tester.state(monitor);
        camera = state.camera as CameraController;
      }
      if (camera?.connected == true && camera?.image != null) break;
    }
    expect(camera?.connected, true);
    expect(camera?.image, isNotNull);
    final controller = camera!;
    final reports = <String, dynamic>{
      'width': controller.image!.width,
      'height': controller.image!.height,
      'fps': controller.fps,
      'transport': controller.bridge,
    };
    for (final entry in {
      'shutter': 65661,
      'aperture': 320,
      'ev': 300,
      'iso': 800,
    }.entries) {
      final control = controller.controls[entry.key] as Map?;
      if (control == null || control['writable'] != true) {
        reports[entry.key] = {'skipped': 'camera reports this setting is not writable'};
        continue;
      }
      final original = control['value'] as int;
      final label = control['label'].toString();
      final report = <String, dynamic>{
        'original': original,
        'target': entry.value,
      };
      try {
        await tester.tap(find.text(label).first);
        await tester.pump(const Duration(milliseconds: 300));
        final options = (controller.controls[entry.key]['options'] as List)
            .cast<Map>();
        final targetLabel = options
            .firstWhere((e) => e['value'] == entry.value)['label']
            .toString();
        final target = find.text(targetLabel);
        await tester.scrollUntilVisible(
          target,
          120,
          scrollable: find.byType(Scrollable).last,
          maxScrolls: 60,
        );
        await tester.tap(target);
        await tester.pump(const Duration(milliseconds: 300));
        for (var i = 0; i < 160; i++) {
          await tester.pump(const Duration(milliseconds: 100));
          if (!controller.busy &&
              controller.controls[entry.key]['value'] == entry.value) {
            break;
          }
        }
        expect(
          controller.controls[entry.key]['value'],
          entry.value,
          reason: controller.message,
        );
        report['confirmed'] = controller.controls[entry.key]['value'];
      } finally {
        if (controller.controls[entry.key]['value'] != original) {
          await controller.apply(entry.key, original);
        }
        report['restored'] = controller.controls[entry.key]['value'];
        reports[entry.key] = report;
      }
    }
    expect(reports.values.whereType<Map>().any((r) => r.containsKey('confirmed')), isTrue);
    ScaffoldMessenger.of(tester.element(find.byType(app.Monitor))).clearSnackBars();
    await tester.pump(const Duration(milliseconds: 500));
    await tester.tap(find.text('MENU'));
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.text('CINEMA HUD / MONITOR'), findsOneWidget);
    await tester.tap(find.text('CLOSE'));
    await tester.pump(const Duration(milliseconds: 300));
    expect(tester.takeException(), isNull);
    reports['latency'] = controller.latency.snapshot();
    reports['low_latency'] = stateLowLatency(tester);
    // A local test receipt, read from logcat after this test APK is launched.
    // ignore: avoid_print
    print('CINEMAHUD_DEVICE_RECEIPT:${jsonEncode(reports)}');
  });
}

bool stateLowLatency(WidgetTester tester) {
  final dynamic state = tester.state(find.byType(app.Monitor));
  return state.lowLatency as bool;
}
