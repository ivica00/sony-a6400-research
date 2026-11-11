import 'package:flutter_test/flutter_test.dart';
import 'package:cinemahud_android/cube_lut.dart';

String identityCube() =>
    'TITLE "Identity"\nLUT_3D_SIZE 2\n${[for (var b = 0; b < 2; b++)
      for (var g = 0; g < 2; g++)
        for (var r = 0; r < 2; r++) '$r $g $b'].join('\n')}';
void main() {
  test(
    'CUBE red-fastest order, title, float precision and domain are preserved',
    () {
      final cube = parseCube(
        'DOMAIN_MIN -1 -2 -3\nDOMAIN_MAX 2 3 4\n${identityCube()}',
      );
      expect(cube.size, 2);
      expect(cube.title, 'Identity');
      expect(cube.min, [-1, -2, -3]);
      expect(cube.max, [2, 3, 4]);
      expect(cube.rgb.sublist(3, 6), [1, 0, 0]);
      expect(cube.rgb.sublist(12, 15), [0, 0, 1]);
    },
  );
  test('Malformed and 1D LUTs do not become a partial GPU atlas', () {
    for (final text in [
      'LUT_3D_SIZE 2\n0 0 0',
      'LUT_1D_SIZE 2\n0 0 0',
      'LUT_3D_SIZE 100\n',
      'DOMAIN_MIN 1 1 1\nDOMAIN_MAX 0 0 0\n${identityCube()}',
      '${identityCube()}\n0 0 0',
    ]) {
      expect(() => parseCube(text), throwsFormatException);
    }
  });
}
