import 'dart:convert';
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:cinemahud_android/main.dart' as app;
import 'package:cinemahud_android/cube_lut.dart';
import 'package:cinemahud_android/motion_frames.dart';

Future<ui.Image> solid(Color color) async {
  final r = ui.PictureRecorder();
  final c = Canvas(r);
  c.drawColor(color, BlendMode.src);
  final p = r.endRecording();
  final image = await p.toImage(64, 64);
  p.dispose();
  return image;
}

Future<ui.Image> render(
  app.VideoPainter painter, {
  int w = 64,
  int h = 64,
}) async {
  final r = ui.PictureRecorder();
  final c = Canvas(r);
  painter.paint(c, Size(w.toDouble(), h.toDouble()));
  final p = r.endRecording();
  final image = await p.toImage(w, h);
  p.dispose();
  return image;
}

Future<List<int>> pixel(ui.Image image, int x, int y) async {
  final bytes = (await image.toByteData(format: ui.ImageByteFormat.rawRgba))!;
  final at = (y * image.width + x) * 4;
  return [for (var i = 0; i < 3; i++) bytes.getUint8(at + i)];
}

String cube(bool swap) =>
    'LUT_3D_SIZE 2\n${[for (var b = 0; b < 2; b++)
      for (var g = 0; g < 2; g++)
        for (var r = 0; r < 2; r++) swap ? '$b $g $r' : '$r $g $b'].join('\n')}';
Future<ui.Image> scene(double dx) async {
  final r = ui.PictureRecorder(), c = Canvas(r);
  c.drawColor(const Color(0xff141414), BlendMode.src);
  for (var y = 0; y < 12; y++) {
    for (var x = 0; x < 18; x++) {
      final v = 40 + ((x * 71 + y * 53 + x * y * 11) % 200);
      c.drawRect(
        Rect.fromLTWH(30 + dx + x * 10, 15 + y * 10, 9, 9),
        Paint()..color = Color.fromARGB(255, v, (v * 3) % 256, (v * 7) % 256),
      );
    }
  }
  final p = r.endRecording();
  final image = await p.toImage(256, 144);
  p.dispose();
  return image;
}

double mse(ByteData a, ByteData b) {
  double total = 0;
  var n = 0;
  for (var y = 20; y < 130; y++) {
    for (var x = 40; x < 205; x++) {
      for (var c = 0; c < 3; c++) {
        final i = (y * 256 + x) * 4 + c;
        final d = a.getUint8(i) - b.getUint8(i);
        total += d * d;
        n++;
      }
    }
  }
  return total / n;
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets('Adreno SGSR, float LUT, zebra and GPU optical-flow validation', (
    tester,
  ) async {
    await tester.pumpWidget(const MaterialApp(home: SizedBox()));
    await tester.pump();
    final report = <String, dynamic>{};
    final program = await ui.FragmentProgram.fromAsset('shaders/monitor.frag');
    final input = await solid(const Color.fromRGBO(51, 102, 179, 1));
    final identity = await CubeLut.fromText(cube(false), 'identity');
    final swap = await CubeLut.fromText(cube(true), 'swap');
    for (final enhance in [false, true]) {
      final out = await render(
        app.VideoPainter(input, program, enhance, false, .5, lut: identity),
      );
      final got = await pixel(out, 24, 24);
      report[enhance ? 'sgsr_identity' : 'lut_identity'] = got;
      for (var i = 0; i < 3; i++) {
        expect((got[i] - [51, 102, 179][i]).abs(), lessThanOrEqualTo(3));
      }
      out.dispose();
    }
    final swapped = await render(
      app.VideoPainter(input, program, false, false, 0, lut: swap),
    );
    final got = await pixel(swapped, 24, 24);
    report['swap_rb'] = got;
    for (var i = 0; i < 3; i++) {
      expect((got[i] - [179, 102, 51][i]).abs(), lessThanOrEqualTo(3));
    }
    swapped.dispose();
    final white = await solid(Colors.white);
    final zebra = await render(
      app.VideoPainter(
        white,
        program,
        false,
        false,
        0,
        zebra: true,
        zebraLevel: .95,
      ),
    );
    final a = await pixel(zebra, 3, 3), b = await pixel(zebra, 0, 0);
    report['zebra'] = [a, b];
    expect((a[0] - b[0]).abs(), greaterThan(100));
    zebra.dispose();
    white.dispose();
    final loaded = <String>[];
    for (final name in phantomLuts) {
      final lut = await CubeLut.asset(name);
      expect(lut.data.size, 33);
      final output = await render(
        app.VideoPainter(input, program, true, false, .5, lut: lut),
      );
      final actual = await pixel(output, 24, 24);
      final rgb = [51 / 255, 102 / 255, 179 / 255];
      final n = lut.data.size;
      final pos = [
        for (var c = 0; c < 3; c++)
          ((rgb[c] - lut.data.min[c]) / (lut.data.max[c] - lut.data.min[c]))
                  .clamp(0.0, 1.0) *
              (n - 1),
      ];
      final low = pos.map((v) => v.floor()).toList(),
          f = [for (var c = 0; c < 3; c++) pos[c] - pos[c].floor()];
      final expected = [0.0, 0.0, 0.0];
      for (var z = 0; z < 2; z++) {
        for (var y = 0; y < 2; y++) {
          for (var x = 0; x < 2; x++) {
            final r = (low[0] + x).clamp(0, n - 1),
                g = (low[1] + y).clamp(0, n - 1),
                b = (low[2] + z).clamp(0, n - 1);
            final weight =
                (x == 0 ? 1 - f[0] : f[0]) *
                (y == 0 ? 1 - f[1] : f[1]) *
                (z == 0 ? 1 - f[2] : f[2]);
            for (var c = 0; c < 3; c++) {
              expected[c] +=
                  lut.data.rgb[((b * n + g) * n + r) * 3 + c] * weight;
            }
          }
        }
      }
      for (var c = 0; c < 3; c++) {
        expect(
          (actual[c] - expected[c].clamp(0.0, 1.0) * 255).abs(),
          lessThanOrEqualTo(3),
          reason: name,
        );
      }
      loaded.add(name);
      output.dispose();
      lut.atlas.dispose();
    }
    report['phantom_luts'] = loaded;
    final prev = await scene(0),
        current = await scene(4),
        truth = await scene(2);
    final motion = MotionFrames();
    await motion.init();
    motion.setEnabled(true);
    await motion.accept(prev);
    await Future<void>.delayed(const Duration(milliseconds: 25));
    await motion.accept(current);
    expect(motion.pair, isNotNull);
    report['flow_ms'] = motion.flowMs;
    final interpolated = await render(
      app.VideoPainter(
        current,
        program,
        false,
        false,
        0,
        pair: motion.pair,
        phase: .5,
      ),
      w: 256,
      h: 144,
    );
    final truthBytes = (await truth.toByteData(
      format: ui.ImageByteFormat.rawRgba,
    ))!;
    final generatedBytes = (await interpolated.toByteData(
      format: ui.ImageByteFormat.rawRgba,
    ))!;
    final previousBytes = (await prev.toByteData(
      format: ui.ImageByteFormat.rawRgba,
    ))!;
    final currentBytes = (await current.toByteData(
      format: ui.ImageByteFormat.rawRgba,
    ))!;
    final blend = ByteData(previousBytes.lengthInBytes);
    for (var i = 0; i < blend.lengthInBytes; i++) {
      blend.setUint8(
        i,
        ((previousBytes.getUint8(i) + currentBytes.getUint8(i)) / 2).round(),
      );
    }
    report['flow_mse'] = mse(generatedBytes, truthBytes);
    report['blend_mse'] = mse(blend, truthBytes);
    report['repeat_mse'] = mse(currentBytes, truthBytes);
    expect(
      report['flow_mse'] as double,
      lessThan(report['repeat_mse'] as double),
    );
    expect(
      report['flow_mse'] as double,
      lessThan(report['blend_mse'] as double),
    );
    // Renderer feature test on the real camera stream, without setting changes.
    motion.dispose();
    prev.dispose();
    current.dispose();
    truth.dispose();
    interpolated.dispose();
    identity.atlas.dispose();
    swap.atlas.dispose();
    input.dispose();
    await app.main();
    dynamic state;
    for (var i = 0; i < 200; i++) {
      await tester.pump(const Duration(milliseconds: 100));
      final monitor = find.byType(app.Monitor);
      if (monitor.evaluate().isNotEmpty) {
        state = tester.state(monitor);
        if (state.camera.connected &&
            state.camera.image != null &&
            state.lut != null) {
          break;
        }
      }
    }
    expect(state.camera.connected, true);
    expect(state.lut, isNotNull);
    await tester.tap(find.text('709'));
    await tester.pump(const Duration(milliseconds: 300));
    await tester.tap(find.text('ZEBRA'));
    await tester.pump(const Duration(milliseconds: 300));
    await tester.tap(find.text('MOTION'));
    await tester.pump(const Duration(milliseconds: 300));
    for (var i = 0; i < 50; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
    report['live_flow_ms'] = state.motion.flowMs;
    report['live_pairs'] = state.motion.pairs;
    report['live_generated_stages'] = state.generatedFrames;
    report['input_fps'] = state.camera.fps;
    report['output_fps'] = state.renderStats.fps;
    expect(state.motion.pairs, greaterThan(0));
    expect(state.generatedFrames, greaterThan(0));
    expect(tester.takeException(), isNull);
    // ignore: avoid_print
    print('CINEMAHUD_GPU_RECEIPT:${jsonEncode(report)}');
  });
}
