/// Local stage durations only; clocks on PC and phone are never subtracted.
class LatencyStats {
  final Map<String, List<double>> _samples = {};
  void add(String stage, double ms) {
    if (!ms.isFinite || ms < 0) return;
    final samples = _samples.putIfAbsent(stage, () => []);
    samples.add(ms);
    if (samples.length > 120) samples.removeAt(0);
  }

  Map<String, dynamic> snapshot() => {
    for (final entry in _samples.entries) entry.key: _summary(entry.value),
  };
  Map<String, double> _summary(List<double> values) {
    final sorted = [...values]..sort();
    return {
      'p50_ms': sorted[sorted.length ~/ 2],
      'p95_ms': sorted[((sorted.length - 1) * .95).round()],
    };
  }
}
