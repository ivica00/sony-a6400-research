/// Counts distinct compositor stages actually painted, not vsync repetitions.
class RenderStats {
  final _clock = Stopwatch()..start();
  String? _last;
  int stages = 0, generated = 0, _windowStages = 0, _windowStart = 0;
  double fps = 0;
  void record(String stamp, bool interpolated) {
    if (stamp == _last) return;
    _last = stamp;
    stages++;
    _windowStages++;
    if (interpolated) generated++;
    final now = _clock.elapsedMilliseconds;
    if (now - _windowStart >= 1000) {
      fps = _windowStages * 1000 / (now - _windowStart);
      _windowStart = now;
      _windowStages = 0;
    }
  }
}
