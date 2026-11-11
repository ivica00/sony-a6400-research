import 'dart:ui' as ui;

import 'package:flutter/foundation.dart';

class MotionPair {
  final ui.Image previous, current, flow, generated;
  final DateTime arrived;
  final double intervalMs;
  MotionPair(
    this.previous,
    this.current,
    this.flow,
    this.generated,
    this.arrived,
    this.intervalMs,
  );
  void dispose() {
    previous.dispose();
    current.dispose();
    flow.dispose();
    generated.dispose();
  }
}

/// GPU optical-flow interpolation. One real input interval of display delay.
/// This is app-owned GPU flow, not a claim of Qualcomm AFME/ANF acceleration.
class MotionFrames extends ChangeNotifier {
  ui.FragmentProgram? program;
  ui.FragmentProgram? interpolationProgram;
  MotionPair? pair;
  ui.Image? _last;
  DateTime? _lastTime;
  bool enabled = false, _working = false, _disposed = false;
  int generation = 0, pairs = 0;
  double flowMs = 0;
  String? error;
  Future<void> init() async {
    program = await ui.FragmentProgram.fromAsset('shaders/flow.frag');
    interpolationProgram = await ui.FragmentProgram.fromAsset(
      'shaders/interpolate.frag',
    );
  }

  void clear() {
    generation++;
    final old = pair;
    pair = null;
    _last?.dispose();
    _last = null;
    _lastTime = null;
    if (old != null) {
      Future<void>.delayed(const Duration(milliseconds: 100), old.dispose);
    }
  }

  void setEnabled(bool value) {
    enabled = value;
    error = null;
    clear();
    notifyListeners();
  }

  Future<void> accept(ui.Image image) async {
    if (!enabled || program == null || _working || _disposed) return;
    final previous = _last, at = DateTime.now(), before = _lastTime;
    _last = image.clone();
    _lastTime = at;
    if (previous == null) return;
    if (previous.width != image.width ||
        previous.height != image.height ||
        before == null ||
        at.difference(before).inMilliseconds > 200) {
      previous.dispose();
      return;
    }
    _working = true;
    final epoch = generation;
    final current = image.clone(), clock = Stopwatch()..start();
    const w = 160;
    final h = (160 * image.height / image.width).round().clamp(32, 160);
    ui.Image? flow, generated;
    try {
      final shader = program!.fragmentShader();
      shader.setFloat(0, w.toDouble());
      shader.setFloat(1, h.toDouble());
      shader.setFloat(2, image.width.toDouble());
      shader.setFloat(3, image.height.toDouble());
      shader.setImageSampler(0, previous);
      shader.setImageSampler(1, current);
      final recorder = ui.PictureRecorder(), canvas = ui.Canvas(recorder);
      canvas.drawRect(
        ui.Rect.fromLTWH(0, 0, w.toDouble(), h.toDouble()),
        ui.Paint()..shader = shader,
      );
      final picture = recorder.endRecording();
      flow = await picture.toImage(w, h);
      picture.dispose();
      shader.dispose();
      final interpolation = interpolationProgram!.fragmentShader();
      interpolation.setFloat(0, image.width.toDouble());
      interpolation.setFloat(1, image.height.toDouble());
      interpolation.setImageSampler(0, previous);
      interpolation.setImageSampler(1, current);
      interpolation.setImageSampler(2, flow);
      final generatedRecorder = ui.PictureRecorder(),
          generatedCanvas = ui.Canvas(generatedRecorder);
      generatedCanvas.drawRect(
        ui.Rect.fromLTWH(0, 0, image.width.toDouble(), image.height.toDouble()),
        ui.Paint()..shader = interpolation,
      );
      final generatedPicture = generatedRecorder.endRecording();
      generated = await generatedPicture.toImage(image.width, image.height);
      generatedPicture.dispose();
      interpolation.dispose();
      flowMs = clock.elapsedMicroseconds / 1000;
      if (_disposed || epoch != generation || !enabled) {
        previous.dispose();
        current.dispose();
        flow.dispose();
        generated.dispose();
        return;
      }
      final old = pair;
      pair = MotionPair(
        previous,
        current,
        flow,
        generated,
        DateTime.now(),
        (at.difference(before).inMicroseconds / 1000).clamp(16.0, 100.0),
      );
      pairs++;
      if (old != null) {
        Future<void>.delayed(const Duration(milliseconds: 100), old.dispose);
      }
      notifyListeners();
    } catch (e) {
      previous.dispose();
      current.dispose();
      flow?.dispose();
      generated?.dispose();
      enabled = false;
      error = e.toString();
      notifyListeners();
    } finally {
      _working = false;
    }
  }

  double get phase {
    final p = pair;
    if (p == null) return 1;
    final elapsed = DateTime.now().difference(p.arrived).inMicroseconds / 1000;
    // Only two distinct presentation stages per input interval. Vsync repeats
    // are not counted as newly generated frames.
    return elapsed < p.intervalMs * 0.5 ? 0.5 : 1.0;
  }

  @override
  void dispose() {
    _disposed = true;
    clear();
    super.dispose();
  }
}
