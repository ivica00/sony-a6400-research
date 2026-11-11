import 'dart:async';
import 'dart:convert';

import 'package:flutter/scheduler.dart';

import 'cube_lut.dart';
import 'motion_frames.dart';
import 'render_stats.dart';

import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import 'camera_controller.dart';
import 'sony_ptp.dart';

const gold = Color(0xfff3bc62), muted = Color(0xff858b83);
Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  LicenseRegistry.addLicense(() async* {
    yield LicenseEntryWithLineBreaks([
      'Qualcomm Snapdragon GSR1',
    ], await rootBundle.loadString('third_party/sgsr1/LICENSE'));
  });
  await SystemChrome.setPreferredOrientations([
    DeviceOrientation.landscapeLeft,
    DeviceOrientation.landscapeRight,
  ]);
  await SystemChrome.setEnabledSystemUIMode(SystemUiMode.immersiveSticky);
  runApp(const CinemaApp());
}

class CinemaApp extends StatelessWidget {
  const CinemaApp({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
    debugShowCheckedModeBanner: false,
    title: 'CinemaHUD',
    theme: ThemeData.dark(useMaterial3: true).copyWith(
      scaffoldBackgroundColor: const Color(0xff050606),
      colorScheme: const ColorScheme.dark(
        primary: gold,
        surface: Color(0xff171a16),
      ),
    ),
    home: const Monitor(),
  );
}

class Monitor extends StatefulWidget {
  const Monitor({super.key});
  @override
  State<Monitor> createState() => _MonitorState();
}

class _MonitorState extends State<Monitor>
    with WidgetsBindingObserver, SingleTickerProviderStateMixin {
  final camera = CameraController();
  bool frame = true,
      guide = true,
      crop = false,
      zoom = false,
      enhance = true,
      peaking = false,
      crosshair = true,
      flipV = false,
      flipH = false;
  double sharpness = .5, zebraLevel = .95, lutStrength = 1;
  bool zebra = false, view709 = false, pickingLut = false;
  CubeLut? lut;
  String selectedLut = phantomLuts.first;
  final motion = MotionFrames();
  ui.Image? lastAccepted;
  late Ticker displayTicker;
  final renderStats = RenderStats();
  Duration lastProfile = Duration.zero;
  final profileClock = Stopwatch()..start();
  int get generatedFrames => renderStats.generated;
  bool lowLatency = true;
  bool get motionEnabled => motion.enabled;
  void toggleMotion() => setLowLatency(motion.enabled);
  void setLowLatency(bool value) {
    lowLatency = value;
    motion.setEnabled(!value);
    if (motion.enabled) {
      displayTicker.start();
    } else {
      displayTicker.stop();
    }
    if (mounted) setState(() {});
  }

  String latencySummary() {
    final values = camera.latency.snapshot();
    String ms(String key) => values[key] == null
        ? '—'
        : (values[key]['p50_ms'] as double).toStringAsFixed(1);
    return 'Fetch ${ms(camera.bridge == null ? 'camera_to_phone_fetch' : 'camera_to_pc_fetch')} ms · Decode ${ms('phone_decode')} ms\nPC frame age ${ms('pc_age_at_send')} ms';
  }

  Future<void> loadLut(String name) async {
    final next = await CubeLut.asset(name);
    if (!mounted) {
      next.atlas.dispose();
      return;
    }
    final old = lut;
    lut = next;
    selectedLut = name;
    if (mounted) setState(() {});
    if (old != null) {
      Future<void>.delayed(
        const Duration(milliseconds: 200),
        old.atlas.dispose,
      );
    }
  }

  Future<void> importLut() async {
    pickingLut = true;
    try {
      final picked = await UsbPtp.channel.invokeMapMethod<String, dynamic>(
        'pickLut',
      );
      if (picked == null) return;
      final next = await CubeLut.fromText(
        utf8.decode(picked['bytes'] as Uint8List),
        picked['name'] as String,
      );
      final old = lut;
      lut = next;
      selectedLut = next.name;
      view709 = true;
      if (mounted) setState(() {});
      if (old != null) {
        Future<void>.delayed(
          const Duration(milliseconds: 200),
          old.atlas.dispose,
        );
      }
    } catch (e) {
      if (mounted) notice('LUT: $e');
    } finally {
      pickingLut = false;
    }
  }

  ui.FragmentProgram? program;
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    camera.addListener(_changed);
    motion.addListener(_changed);
    displayTicker = createTicker((elapsed) {
      if (motion.enabled && motion.pair != null && mounted) {
        _profileMetrics();
        setState(() {});
      }
    });
    _init();
  }

  Future<void> _init() async {
    try {
      program = await ui.FragmentProgram.fromAsset('shaders/monitor.frag');
      await motion.init();
      await loadLut(phantomLuts.first);
      if (mounted) setState(() {});
    } catch (e) {
      if (mounted) notice('GPU/LUT setup: $e');
    }
    if (!mounted) return;
    final options = await UsbPtp.channel.invokeMapMethod<String, dynamic>(
      'launchOptions',
    );
    if (options?['effects'] == true) {
      view709 = true;
      zebra = true;
      toggleMotion();
    }
    final bridge = options?['bridge'] as String?;
    if (bridge != null && mounted) await camera.connect(bridgeUrl: bridge);
  }

  void _profileMetrics() {
    if (!const bool.fromEnvironment('CINEMAHUD_PROFILE')) return;
    final elapsed = profileClock.elapsed;
    if (elapsed - lastProfile < const Duration(seconds: 5)) return;
    lastProfile = elapsed;
    debugPrint(
      'CINEMAHUD_RENDER_STATS:${jsonEncode({'input_fps': camera.fps, 'output_fps': renderStats.fps, 'generated': renderStats.generated, 'pairs': motion.pairs, 'flow_ms': motion.flowMs, 'latency': camera.latency.snapshot(), 'low_latency': lowLatency})}',
    );
  }

  void _changed() {
    _profileMetrics();
    final image = camera.image;
    if (image != null && !identical(image, lastAccepted)) {
      lastAccepted = image;
      unawaited(motion.accept(image));
    }
    if (!camera.connected && motion.pair != null) motion.clear();
    if (mounted) setState(() {});
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.paused && !pickingLut) {
      motion.clear();
      unawaited(camera.disconnect());
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    camera.removeListener(_changed);
    displayTicker.dispose();
    motion.removeListener(_changed);
    motion.dispose();
    lut?.atlas.dispose();
    unawaited(camera.disconnect());
    super.dispose();
  }

  void toggle(VoidCallback change) => setState(change);
  TextStyle get small => const TextStyle(
    fontSize: 8,
    fontWeight: FontWeight.w700,
    letterSpacing: 1.2,
    color: muted,
  );
  Widget keyValue(String key, String value) => Row(
    mainAxisSize: MainAxisSize.min,
    children: [
      Text(key, style: small),
      const SizedBox(width: 5),
      Text(
        value,
        style: const TextStyle(
          fontSize: 15,
          fontWeight: FontWeight.w600,
          color: Color(0xffdedfd7),
        ),
      ),
    ],
  );
  Widget readout(String name, String title) {
    final control = camera.controls[name] as Map?;
    return InkWell(
      onTap: control?['writable'] == true && !camera.busy
          ? () => pick(name, title, control!)
          : null,
      borderRadius: BorderRadius.circular(3),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 8),
        child: keyValue(title, control?['label']?.toString() ?? '—'),
      ),
    );
  }

  Future<void> pick(String name, String title, Map control) async {
    final options = (control['options'] as List? ?? []).cast<Map>();
    final value = await showDialog<int>(
      context: context,
      builder: (context) => Dialog(
        child: SizedBox(
          width: 300,
          height: 300,
          child: Column(
            children: [
              Padding(
                padding: const EdgeInsets.all(16),
                child: Text(
                  title,
                  style: const TextStyle(letterSpacing: 3, color: gold),
                ),
              ),
              Expanded(
                child: ListView.builder(
                  itemCount: options.length,
                  itemBuilder: (context, i) {
                    final item = options[i];
                    return ListTile(
                      dense: true,
                      title: Text(item['label'].toString()),
                      selected: item['value'] == control['value'],
                      selectedColor: gold,
                      trailing: item['value'] == control['value']
                          ? const Icon(Icons.check, size: 16)
                          : null,
                      onTap: () => Navigator.pop(context, item['value'] as int),
                    );
                  },
                ),
              ),
            ],
          ),
        ),
      ),
    );
    if (value == null || !mounted) return;
    try {
      await camera.apply(name, value);
      if (mounted) notice(camera.message);
    } catch (e) {
      if (mounted) notice(e.toString());
    }
  }

  void notice(String message) => ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(
      content: Text(message),
      duration: const Duration(seconds: 3),
      backgroundColor: const Color(0xff292e25),
    ),
  );
  Widget button(
    String label, {
    VoidCallback? onTap,
    bool active = false,
    String? hint,
  }) => Tooltip(
    message: hint ?? label,
    child: SizedBox(
      width: 48,
      height: 27,
      child: TextButton(
        onPressed: onTap,
        style: TextButton.styleFrom(
          padding: EdgeInsets.zero,
          minimumSize: Size.zero,
          backgroundColor: active ? gold : const Color(0xff262925),
          foregroundColor: active
              ? const Color(0xff231c10)
              : const Color(0xffd2d5cd),
          disabledBackgroundColor: const Color(0xff101310),
          disabledForegroundColor: const Color(0xff434940),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(3)),
        ),
        child: Text(
          label,
          style: const TextStyle(
            fontSize: 8,
            fontWeight: FontWeight.w800,
            letterSpacing: 1.1,
          ),
        ),
      ),
    ),
  );
  Widget rail(bool left) => SizedBox(
    width: 65,
    child: Column(
      children: [
        if (left) ...[
          button(
            'STD',
            active: !enhance,
            onTap: () => toggle(() => enhance = false),
          ),
          const SizedBox(height: 5),
          button(
            '709',
            active: view709,
            onTap: lut == null ? null : () => toggle(() => view709 = !view709),
            hint: 'Selected S-Log2 to 709 LUT',
          ),
          const SizedBox(height: 5),
          button('EXP'),
          const SizedBox(height: 5),
          button(
            'PEAK',
            active: peaking,
            onTap: program == null
                ? null
                : () => toggle(() => peaking = !peaking),
          ),
          const SizedBox(height: 5),
          button(
            'ZEBRA',
            active: zebra,
            onTap: () => toggle(() => zebra = !zebra),
          ),
          const SizedBox(height: 5),
          button(
            '2.00×',
            active: zoom,
            onTap: () => toggle(() => zoom = !zoom),
          ),
          const SizedBox(height: 10),
          button(
            'FRAME',
            active: frame,
            onTap: () => toggle(() => frame = !frame),
          ),
          const SizedBox(height: 5),
          button(
            'GUIDE',
            active: guide,
            onTap: () => toggle(() => guide = !guide),
          ),
          const SizedBox(height: 5),
          button('CROP', active: crop, onTap: () => toggle(() => crop = !crop)),
          const Spacer(),
          button('MENU', onTap: menu),
        ] else ...[
          button('SCOPE'),
          const SizedBox(height: 5),
          button(
            'ENH',
            active: enhance,
            onTap: () => toggle(() => enhance = !enhance),
          ),
          const SizedBox(height: 5),
          button(
            'MOTION',
            active: motionEnabled,
            onTap: motion.program == null ? null : toggleMotion,
            hint: 'GPU optical-flow ×2',
          ),
          const SizedBox(height: 5),
          button('NR1'),
          const SizedBox(height: 12),
          button('AF'),
          const SizedBox(height: 5),
          button('AEL'),
          const SizedBox(height: 5),
          button('◂ NEAR'),
          const SizedBox(height: 5),
          button('FAR ▸'),
          const SizedBox(height: 5),
          button('STILL'),
          const Spacer(),
          button('● REC'),
        ],
      ],
    ),
  );
  Future<void> connectDialog() async {
    final controller = TextEditingController(text: 'http://127.0.0.1:8080');
    await showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text(
          'CONNECT CAMERA',
          style: TextStyle(fontSize: 14, letterSpacing: 2),
        ),
        content: SizedBox(
          width: 360,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'USB: connect the Sony camera directly to this phone with an OTG cable. Camera USB mode: PC Remote.',
                style: TextStyle(fontSize: 12, color: muted),
              ),
              const SizedBox(height: 18),
              TextField(
                controller: controller,
                style: const TextStyle(fontSize: 13),
                decoration: const InputDecoration(
                  labelText: 'PC bridge address',
                  hintText: 'http://PC-address:8080',
                ),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('CANCEL'),
          ),
          TextButton(
            onPressed: () {
              Navigator.pop(context);
              unawaited(camera.connect(bridgeUrl: controller.text.trim()));
            },
            child: const Text('PC BRIDGE'),
          ),
          FilledButton(
            onPressed: () {
              Navigator.pop(context);
              unawaited(camera.connect());
            },
            child: const Text('USB CAMERA'),
          ),
        ],
      ),
    );
    // The dialog owns the controller until its closing animation has completed.
    Future<void>.delayed(const Duration(seconds: 1), controller.dispose);
  }

  Future<void> menu() async {
    await showDialog<void>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setLocal) => AlertDialog(
          title: const Text(
            'CINEMA HUD / MONITOR',
            style: TextStyle(fontSize: 13, letterSpacing: 2),
          ),
          content: SizedBox(
            width: 360,
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    camera.message,
                    style: const TextStyle(fontSize: 12, color: muted),
                  ),
                  const SizedBox(height: 15),
                  Wrap(
                    spacing: 7,
                    runSpacing: 7,
                    children: [
                      button(
                        camera.connected ? 'UNLINK' : 'CONNECT',
                        onTap: () {
                          Navigator.pop(context);
                          if (camera.connected) {
                            unawaited(camera.disconnect());
                          } else {
                            unawaited(connectDialog());
                          }
                        },
                      ),
                      button(
                        'FLIP V',
                        active: flipV,
                        onTap: () {
                          toggle(() => flipV = !flipV);
                          setLocal(() {});
                        },
                      ),
                      button(
                        'MIRROR',
                        active: flipH,
                        onTap: () {
                          toggle(() => flipH = !flipH);
                          setLocal(() {});
                        },
                      ),
                      button(
                        'CENTER',
                        active: crosshair,
                        onTap: () {
                          toggle(() => crosshair = !crosshair);
                          setLocal(() {});
                        },
                      ),
                    ],
                  ),
                  const SizedBox(height: 18),
                  SwitchListTile(
                    contentPadding: EdgeInsets.zero,
                    title: const Text(
                      'LOW LATENCY',
                      style: TextStyle(fontSize: 12, letterSpacing: 1),
                    ),
                    subtitle: const Text(
                      'Newest real frame · Motion disabled',
                      style: TextStyle(fontSize: 10),
                    ),
                    value: lowLatency,
                    onChanged: (value) {
                      setLowLatency(value);
                      setLocal(() {});
                    },
                  ),
                  Text(
                    latencySummary(),
                    style: const TextStyle(fontSize: 11, color: muted),
                  ),
                  const SizedBox(height: 14),
                  Text('SGSR1 · Adreno GPU', style: small),
                  if (motion.error != null)
                    Text(
                      'Motion disabled: ${motion.error}',
                      style: const TextStyle(fontSize: 10, color: gold),
                    ),
                  const SizedBox(height: 14),
                  Text('709 / LUT', style: small),
                  const SizedBox(height: 8),
                  DropdownButton<String>(
                    isExpanded: true,
                    value: phantomLuts.contains(selectedLut)
                        ? selectedLut
                        : null,
                    hint: Text(lut?.data.title ?? 'Select LUT'),
                    items: [
                      for (final name in phantomLuts)
                        DropdownMenuItem(
                          value: name,
                          child: Text(
                            name
                                .replaceAll('_A7s3_G4_to_', ' · ')
                                .replaceAll('.cube', ''),
                            style: const TextStyle(fontSize: 10),
                          ),
                        ),
                    ],
                    onChanged: (value) async {
                      if (value == null) return;
                      try {
                        await loadLut(value);
                        view709 = true;
                        if (mounted) {
                          setState(() {});
                          setLocal(() {});
                        }
                      } catch (e) {
                        notice('$e');
                      }
                    },
                  ),
                  Text(
                    lut?.data.title ?? 'Loading LUT…',
                    style: const TextStyle(fontSize: 10, color: muted),
                  ),
                  TextButton(
                    onPressed: () async {
                      Navigator.pop(context);
                      await importLut();
                    },
                    child: const Text('LOAD .CUBE FROM PHONE'),
                  ),
                  Text(
                    'LUT strength ${(lutStrength * 100).round()}%',
                    style: small,
                  ),
                  Slider(
                    value: lutStrength,
                    onChanged: (v) {
                      toggle(() => lutStrength = v);
                      setLocal(() {});
                    },
                  ),
                  Text(
                    'ZEBRA · INPUT SIGNAL ${(zebraLevel * 100).round()}%',
                    style: small,
                  ),
                  Slider(
                    value: zebraLevel,
                    min: .5,
                    max: 1,
                    divisions: 50,
                    onChanged: (v) {
                      toggle(() => zebraLevel = v);
                      setLocal(() {});
                    },
                  ),
                  Text(
                    'MOTION ×2 · GPU optical flow\n${motion.pairs} pairs · ${motion.flowMs.toStringAsFixed(1)} ms flow\n$generatedFrames generated stages · IN ${camera.fps.toStringAsFixed(1)} / OUT ${renderStats.fps.toStringAsFixed(1)} fps',
                    style: const TextStyle(fontSize: 11, color: muted),
                  ),
                  const Text(
                    'LUT input must match the camera Picture Profile. No camera profile is changed. Zebras meter the input before LUT.',
                    style: TextStyle(fontSize: 10, color: muted, height: 1.5),
                  ),
                  const SizedBox(height: 18),
                  const Text(
                    'ENHANCEMENT',
                    style: TextStyle(
                      fontSize: 10,
                      letterSpacing: 2,
                      color: muted,
                    ),
                  ),
                  Slider(
                    value: sharpness,
                    onChanged: (v) {
                      toggle(() => sharpness = v);
                      setLocal(() {});
                    },
                  ),
                  TextButton(
                    onPressed: () => showLicensePage(
                      context: context,
                      applicationName: 'CinemaHUD',
                      applicationVersion: '1.2.0',
                    ),
                    child: const Text('LICENSES'),
                  ),
                  const Text(
                    'Sony ILCE-6400 · USB PTP\nExposure changes require camera readback.\nGrey controls are not connected.',
                    style: TextStyle(fontSize: 11, color: muted, height: 1.7),
                  ),
                ],
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('CLOSE'),
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    body: SafeArea(
      child: LayoutBuilder(
        builder: (context, bounds) {
          final narrow = bounds.maxWidth < 820;
          return Padding(
            padding: const EdgeInsets.fromLTRB(4, 1, 4, 2),
            child: Column(
              children: [
                SizedBox(
                  height: 37,
                  child: Row(
                    children: [
                      const SizedBox(width: 10),
                      keyValue(
                        'FPS',
                        camera.fps == 0 ? '—' : camera.fps.toStringAsFixed(2),
                      ),
                      const SizedBox(width: 9),
                      readout('shutter', 'SHUTTER'),
                      readout('aperture', 'IRIS'),
                      readout('iso', 'EI'),
                      readout('ev', 'EV'),
                      if (!narrow) ...[
                        const SizedBox(width: 5),
                        keyValue(
                          'WB',
                          camera.state['white_balance']?.toString() ?? '—',
                        ),
                        const SizedBox(width: 14),
                        keyValue(
                          'FOCUS',
                          camera.state['focus_mode']?.toString() ?? '—',
                        ),
                      ],
                      const Spacer(),
                      Text(
                        camera.state['exposure_mode']?.toString() ?? '—',
                        style: small,
                      ),
                      const SizedBox(width: 9),
                      Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 6,
                          vertical: 3,
                        ),
                        color: const Color(0xffdedfd7),
                        child: const Text(
                          'A',
                          style: TextStyle(
                            fontSize: 12,
                            color: Colors.black,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                      ),
                      const SizedBox(width: 9),
                    ],
                  ),
                ),
                Expanded(
                  child: Row(
                    children: [
                      rail(true),
                      Expanded(
                        child: Center(
                          child: AspectRatio(
                            aspectRatio: 16 / 9,
                            child: ClipRect(
                              child: Stack(
                                fit: StackFit.expand,
                                children: [
                                  const ColoredBox(color: Colors.black),
                                  if (camera.image != null)
                                    Transform(
                                      alignment: Alignment.center,
                                      transform: Matrix4.diagonal3Values(
                                        (flipH ? -1.0 : 1.0) * (zoom ? 2 : 1),
                                        (flipV ? -1.0 : 1.0) * (zoom ? 2 : 1),
                                        1,
                                      ),
                                      child: CustomPaint(
                                        painter: VideoPainter(
                                          motion.enabled && motion.pair != null
                                              ? motion.pair!.current
                                              : camera.image!,
                                          program,
                                          enhance,
                                          peaking,
                                          sharpness,
                                          zebra: zebra,
                                          zebraLevel: zebraLevel,
                                          lut: view709 ? lut : null,
                                          lutStrength: lutStrength,
                                          pair: motion.enabled
                                              ? motion.pair
                                              : null,
                                          phase: motion.phase,
                                          stats: renderStats,
                                        ),
                                      ),
                                    ),
                                  CustomPaint(
                                    painter: GuidesPainter(
                                      frame,
                                      guide,
                                      crosshair,
                                      crop,
                                    ),
                                  ),
                                  if (camera.image == null)
                                    Center(
                                      child: Column(
                                        mainAxisSize: MainAxisSize.min,
                                        children: [
                                          const Text(
                                            'CINEMA HUD',
                                            style: TextStyle(
                                              fontSize: 24,
                                              fontWeight: FontWeight.w300,
                                              letterSpacing: 9,
                                              color: Color(0xffb9c0b1),
                                            ),
                                          ),
                                          const SizedBox(height: 14),
                                          Text(
                                            camera.message,
                                            style: const TextStyle(
                                              fontSize: 11,
                                              color: muted,
                                            ),
                                          ),
                                          const SizedBox(height: 22),
                                          OutlinedButton(
                                            onPressed: camera.connecting
                                                ? null
                                                : connectDialog,
                                            child: Text(
                                              camera.connecting
                                                  ? 'CONNECTING…'
                                                  : 'CONNECT CAMERA',
                                            ),
                                          ),
                                        ],
                                      ),
                                    ),
                                  if (camera.busy)
                                    const Align(
                                      alignment: Alignment.topCenter,
                                      child: LinearProgressIndicator(
                                        minHeight: 2,
                                        color: gold,
                                      ),
                                    ),
                                ],
                              ),
                            ),
                          ),
                        ),
                      ),
                      rail(false),
                    ],
                  ),
                ),
                SizedBox(
                  height: 25,
                  child: Row(
                    children: [
                      const SizedBox(width: 10),
                      keyValue(
                        'PWR',
                        camera.state['battery'] == null
                            ? '—'
                            : '${camera.state['battery']}%',
                      ),
                      const SizedBox(width: 18),
                      Text('A · ILCE-6400', style: small),
                      const Spacer(),
                      Container(
                        width: 6,
                        height: 6,
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          color: camera.connected
                              ? const Color(0xff73c49a)
                              : muted,
                        ),
                      ),
                      const SizedBox(width: 6),
                      Text(
                        camera.connected
                            ? (camera.bridge == null ? 'USB PTP' : 'PC BRIDGE')
                            : 'OFFLINE',
                        style: const TextStyle(
                          fontSize: 10,
                          letterSpacing: 1.4,
                          color: Color(0xff91b9a2),
                        ),
                      ),
                      const Spacer(),
                      Text(
                        'sRGB  ${camera.image?.width ?? '—'} × ${camera.image?.height ?? '—'}',
                        style: small,
                      ),
                      const SizedBox(width: 10),
                    ],
                  ),
                ),
              ],
            ),
          );
        },
      ),
    ),
  );
}

class GuidesPainter extends CustomPainter {
  final bool frame, grid, center, crop;
  GuidesPainter(this.frame, this.grid, this.center, this.crop);
  @override
  void paint(Canvas canvas, Size s) {
    if (crop) {
      final h = (s.height - s.width / 2.39) / 2;
      final p = Paint()..color = Colors.black.withValues(alpha: .9);
      canvas.drawRect(Rect.fromLTWH(0, 0, s.width, h.clamp(0, s.height)), p);
      canvas.drawRect(
        Rect.fromLTWH(0, s.height - h, s.width, h.clamp(0, s.height)),
        p,
      );
    }
    if (grid) {
      final p = Paint()
        ..color = Colors.white.withValues(alpha: .12)
        ..strokeWidth = .5;
      for (var i = 1; i < 3; i++) {
        canvas.drawLine(
          Offset(s.width * i / 3, 0),
          Offset(s.width * i / 3, s.height),
          p,
        );
        canvas.drawLine(
          Offset(0, s.height * i / 3),
          Offset(s.width, s.height * i / 3),
          p,
        );
      }
    }
    if (frame) {
      final p = Paint()
        ..color = const Color(0xffb85348).withValues(alpha: .8)
        ..style = PaintingStyle.stroke
        ..strokeWidth = .7;
      final r = Rect.fromLTWH(
        s.width * .04,
        s.height * .04,
        s.width * .92,
        s.height * .92,
      );
      canvas.drawRect(r, p);
      canvas.drawLine(
        Offset(r.left, s.height / 2),
        Offset(r.left + 9, s.height / 2),
        p,
      );
      canvas.drawLine(
        Offset(r.right - 9, s.height / 2),
        Offset(r.right, s.height / 2),
        p,
      );
    }
    if (center) {
      final p = Paint()
        ..color = Colors.white.withValues(alpha: .5)
        ..strokeWidth = .6;
      canvas.drawLine(
        Offset(s.width / 2 - 6, s.height / 2),
        Offset(s.width / 2 + 6, s.height / 2),
        p,
      );
      canvas.drawLine(
        Offset(s.width / 2, s.height / 2 - 6),
        Offset(s.width / 2, s.height / 2 + 6),
        p,
      );
    }
  }

  @override
  bool shouldRepaint(GuidesPainter old) =>
      frame != old.frame ||
      grid != old.grid ||
      center != old.center ||
      crop != old.crop;
}

class VideoPainter extends CustomPainter {
  final ui.Image image;
  final ui.FragmentProgram? program;
  final bool enhance, peaking, zebra;
  final double sharpness, zebraLevel, lutStrength, phase;
  final CubeLut? lut;
  final MotionPair? pair;
  final RenderStats? stats;
  VideoPainter(
    this.image,
    this.program,
    this.enhance,
    this.peaking,
    this.sharpness, {
    this.zebra = false,
    this.zebraLevel = .95,
    this.lut,
    this.lutStrength = 1,
    this.pair,
    this.phase = 1,
    this.stats,
  });
  @override
  void paint(Canvas canvas, Size size) {
    stats?.record(
      '${identityHashCode(image)}:${pair == null ? 1 : phase}',
      pair != null && phase < 1,
    );
    final display = pair != null && phase < 1 ? pair!.generated : image;
    if (program != null) {
      final shader = program!.fragmentShader();
      final values = <double>[
        size.width,
        size.height,
        display.width.toDouble(),
        display.height.toDouble(),
        sharpness,
        peaking ? 1 : 0,
        enhance ? 1 : 0,
        zebra ? 1 : 0,
        zebraLevel,
        lut == null ? 0 : 1,
        lut?.data.size.toDouble() ?? 2,
        lutStrength,
        ...(lut?.data.min ?? [0.0, 0.0, 0.0]),
        ...(lut?.data.max ?? [1.0, 1.0, 1.0]),
      ];
      for (var i = 0; i < values.length; i++) {
        shader.setFloat(i, values[i]);
      }
      shader.setImageSampler(0, display);
      shader.setImageSampler(1, image);
      shader.setImageSampler(2, lut?.atlas ?? image);
      canvas.drawRect(Offset.zero & size, Paint()..shader = shader);
      shader.dispose();
    } else {
      canvas.drawImageRect(
        image,
        Rect.fromLTWH(0, 0, image.width.toDouble(), image.height.toDouble()),
        Offset.zero & size,
        Paint()..filterQuality = FilterQuality.high,
      );
    }
  }

  @override
  bool shouldRepaint(VideoPainter old) => true;
}
