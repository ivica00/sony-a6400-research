import 'package:flutter_test/flutter_test.dart';
import 'package:cinemahud_android/render_stats.dart';

void main() {
  test('Repeated vsync paints do not inflate frame-generation counters', () {
    final stats = RenderStats();
    for (var i = 0; i < 120; i++) {
      stats.record('pair1:0.5', true);
    }
    for (var i = 0; i < 120; i++) {
      stats.record('pair1:1.0', false);
    }
    expect(stats.stages, 2);
    expect(stats.generated, 1);
  });
}
