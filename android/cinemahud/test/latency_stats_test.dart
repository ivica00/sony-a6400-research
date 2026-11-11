import 'package:flutter_test/flutter_test.dart';
import 'package:cinemahud_android/latency_stats.dart';

void main() {
  test(
    'Latency window excludes invalid samples and retains recent measurements',
    () {
      final stats = LatencyStats();
      stats.add('decode', double.nan);
      stats.add('decode', -1);
      expect(stats.snapshot(), isEmpty);
      for (var i = 0; i < 240; i++) {
        stats.add('decode', i.toDouble());
      }
      final result = stats.snapshot()['decode'];
      expect(result['p50_ms'], 180.0);
      expect(result['p95_ms'], greaterThan(230));
    },
  );
}
