"""Check the selected original pthread provider/versioned initializer bindings."""
import io

from elftools.elf.elffile import ELFFile

PTHREAD = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha7_unpacked/lib/libpthread-2.11.2.so'


def versions(elf):
    names = {}
    needs = elf.get_section_by_name('.gnu.version_r')
    if needs:
        for version, auxiliaries in needs.iter_versions():
            for auxiliary in auxiliaries:
                names[auxiliary['vna_other'] & 0x7fff] = auxiliary.name
    definitions = elf.get_section_by_name('.gnu.version_d')
    if definitions:
        for version, auxiliaries in definitions.iter_versions():
            names[version['vd_ndx'] & 0x7fff] = next(auxiliaries).name
    result = {}
    table = elf.get_section_by_name('.gnu.version')
    if table:
        for index, entry in enumerate(table.iter_symbols()):
            ndx = entry['ndx']
            if isinstance(ndx, int):
                result[index] = names.get(ndx & 0x7fff)
    return result


def select_initializer(name, client_symbols, requested, provider_symbols, offered):
    imports = [(i, s) for i, s in enumerate(client_symbols) if s.name == name and s['st_shndx'] == 'SHN_UNDEF']
    if len(imports) != 1 or not requested.get(imports[0][0]):
        raise ValueError('Ambiguous/unversioned pthread import')
    version = requested[imports[0][0]]
    exports = [s for i, s in enumerate(provider_symbols) if s.name == name and s['st_shndx'] != 'SHN_UNDEF'
               and s['st_info']['type'] == 'STT_FUNC' and offered.get(i) == version]
    if len(exports) != 1:
        raise ValueError('Pthread initializer version/definition mismatch')
    function = exports[0]
    return {'value': function['st_value'], 'size': function['st_size'],
            'version': version, 'client_symbol_index': imports[0][0]}


def profile(client, provider_raw, application_needed):
    if ('libpthread.so.0' not in application_needed or 'libc.so.6' not in application_needed
            or application_needed.index('libpthread.so.0') >= application_needed.index('libc.so.6')):
        raise ValueError('Selected application does not declare pthread before libc')
    provider = ELFFile(io.BytesIO(provider_raw))
    if (provider.elfclass, provider.little_endian, provider['e_machine'], provider['e_type']) != (32, True, 'EM_ARM', 'ET_DYN'):
        raise ValueError('Expected original ARM32 pthread library')
    sonames = [tag.soname for tag in provider.get_section_by_name('.dynamic').iter_tags() if tag.entry.d_tag == 'DT_SONAME']
    if sonames != ['libpthread.so.0']:
        raise ValueError('Selected pthread provider SONAME mismatch')
    requested, offered = versions(client), versions(provider)
    client_symbols = list(client.get_section_by_name('.dynsym').iter_symbols())
    provider_symbols = list(provider.get_section_by_name('.dynsym').iter_symbols())
    functions = {}
    for name in ('pthread_mutex_init', 'pthread_cond_init'):
        functions[name] = select_initializer(name, client_symbols, requested, provider_symbols, offered)
    return provider, {'soname': sonames[0], 'application_needed': application_needed, 'functions': functions,
        'limitation': 'Explicit isolated matching provider; complete runtime symbol-scope search is not executed.'}
