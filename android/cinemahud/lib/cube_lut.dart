import 'dart:async';
import 'dart:convert';
import 'dart:ui' as ui;

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

/// CUBE red-fastest order. Preserve float values and DOMAIN_MIN/MAX until display.
class CubeData {
  final String title;
  final int size;
  final List<double> min, max;
  final Float32List rgb;
  CubeData(this.title, this.size, this.min, this.max, this.rgb);
}

CubeData parseCube(String text) {
  if (utf8.encode(text).length > 8 * 1024 * 1024) {
    throw const FormatException('LUT exceeds 8 MB');
  }
  var size = 0, title = 'Imported LUT';
  var min = <double>[0, 0, 0], max = <double>[1, 1, 1];
  final values = <double>[];
  for (final original in const LineSplitter().convert(text)) {
    final line = original.split('#').first.trim();
    if (line.isEmpty) continue;
    final parts = line.split(RegExp(r'\s+'));
    if (parts.first == 'TITLE') {
      title = line.substring(5).trim().replaceAll('"', '');
      continue;
    }
    if (parts.first == 'LUT_1D_SIZE') {
      throw const FormatException('Use a 3D .cube LUT');
    }
    if (parts.first == 'LUT_3D_SIZE') {
      if (size != 0) throw const FormatException('Duplicate LUT size');
      size = int.parse(parts[1]);
      if (size < 2 || size > 65) {
        throw const FormatException('LUT size must be 2–65');
      }
      continue;
    }
    if (parts.first == 'DOMAIN_MIN' || parts.first == 'DOMAIN_MAX') {
      if (parts.length != 4) throw const FormatException('Invalid LUT domain');
      final domain = parts.skip(1).map(double.parse).toList();
      if (parts.first == 'DOMAIN_MIN') {
        min = domain;
      } else {
        max = domain;
      }
      continue;
    }
    if (parts.length != 3) throw const FormatException('Invalid LUT row');
    for (final part in parts) {
      final value = double.parse(part);
      if (!value.isFinite) throw const FormatException('Non-finite LUT value');
      values.add(value);
    }
    if (values.length > 65 * 65 * 65 * 3) {
      throw const FormatException('Oversized LUT');
    }
  }
  if (size == 0 || values.length != size * size * size * 3) {
    throw const FormatException('LUT row count does not match LUT_3D_SIZE');
  }
  for (var i = 0; i < 3; i++) {
    if (!min[i].isFinite || !max[i].isFinite || max[i] <= min[i]) {
      throw const FormatException('Invalid LUT domain');
    }
  }
  return CubeData(title, size, min, max, Float32List.fromList(values));
}

class CubeLut {
  final CubeData data;
  final ui.Image atlas;
  final String name;
  CubeLut(this.data, this.atlas, this.name);
  static Future<CubeLut> fromText(String text, String name) async {
    final data = await compute(parseCube, text);
    final n = data.size,
        rgba = Float32List(data.size * data.size * data.size * 4);
    // Image x = blue*N + red, image y = green. Sample texel centers in shader.
    for (var b = 0; b < n; b++) {
      for (var g = 0; g < n; g++) {
        for (var r = 0; r < n; r++) {
          final src = ((b * n + g) * n + r) * 3,
              dst = (g * n * n + b * n + r) * 4;
          rgba[dst] = data.rgb[src];
          rgba[dst + 1] = data.rgb[src + 1];
          rgba[dst + 2] = data.rgb[src + 2];
          rgba[dst + 3] = 1;
        }
      }
    }
    final done = Completer<ui.Image>();
    ui.decodeImageFromPixels(
      rgba.buffer.asUint8List(),
      n * n,
      n,
      ui.PixelFormat.rgbaFloat32,
      done.complete,
      rowBytes: n * n * 16,
    );
    return CubeLut(data, await done.future, name);
  }

  static Future<CubeLut> asset(String name) async => fromText(
    await rootBundle.loadString('assets/user_luts/$name'),
    name.replaceAll('.cube', ''),
  );
}

const phantomLuts = [
  'Neutral_A7s3_G4_to_SLog2_SGamut.cube',
  'Neutral_A7s3_G4_to_SLog2_SGamut3Cine.cube',
  'IceBlue_A7s3_G4_to_SLog2_SGamut.cube',
  'IceBlue_A7s3_G4_to_SLog2_SGamut3Cine.cube',
  'Jamaica_A7s3_G4_to_SLog2_SGamut.cube',
  'Jamaica_A7s3_G4_to_SLog2_SGamut3Cine.cube',
  'Tungsten_A7s3_G4_to_SLog2_SGamut.cube',
  'Tungsten_A7s3_G4_to_SLog2_SGamut3Cine.cube',
  'Utopia_A7s3_G4_to_SLog2_SGamut.cube',
  'Utopia_A7s3_G4_to_SLog2_SGamut3Cine.cube',
];
