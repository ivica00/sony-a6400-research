import unittest

from tools.research.pthread_init_profile import select_initializer


class Symbol(dict):
    def __init__(self, section, value=0, kind='STT_FUNC'):
        super().__init__(st_shndx=section, st_value=value, st_size=48, st_info={'type': kind})
        self.name = 'pthread_mutex_init'


class PthreadBindingTests(unittest.TestCase):
    def test_required_version_selects_defined_function_and_preserves_thumb_bit(self):
        result = select_initializer('pthread_mutex_init', [Symbol('SHN_UNDEF')], {0: 'GLIBC_2.4'},
                                    [Symbol(1, 0x101), Symbol(1, 0x201)], {0: 'GLIBC_2.0', 1: 'GLIBC_2.4'})
        self.assertEqual(result['value'], 0x201)
        self.assertEqual(result['version'], 'GLIBC_2.4')

    def test_wrong_version_undefined_or_nonfunction_provider_cannot_bind(self):
        for symbol, version in ((Symbol(1, 0x101), 'GLIBC_2.0'),
                                (Symbol('SHN_UNDEF'), 'GLIBC_2.4'),
                                (Symbol(1, 0x101, 'STT_OBJECT'), 'GLIBC_2.4')):
            with self.subTest(symbol=symbol, version=version):
                with self.assertRaises(ValueError):
                    select_initializer('pthread_mutex_init', [Symbol('SHN_UNDEF')], {0: 'GLIBC_2.4'}, [symbol], {0: version})

    def test_ambiguous_import_or_export_and_missing_version_stop(self):
        for imports, requested, exports, offered in (
                ([Symbol('SHN_UNDEF')], {}, [Symbol(1, 0x101)], {0: 'GLIBC_2.4'}),
                ([Symbol('SHN_UNDEF')] * 2, {0: 'GLIBC_2.4', 1: 'GLIBC_2.4'}, [Symbol(1, 0x101)], {0: 'GLIBC_2.4'}),
                ([Symbol('SHN_UNDEF')], {0: 'GLIBC_2.4'}, [Symbol(1, 0x101)] * 2, {0: 'GLIBC_2.4', 1: 'GLIBC_2.4'})):
            with self.assertRaises(ValueError):
                select_initializer('pthread_mutex_init', imports, requested, exports, offered)
