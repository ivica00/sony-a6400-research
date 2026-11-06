"""Bounded read-only guest file contracts over an explicit image namespace."""
import hashlib

import unicorn
from src.a6400.images.guest_paths import resolve_guest
from src.a6400.execution.guest_memory import accessible
from src.a6400.images.verified_content import ContentUnavailable

UNKNOWN_ROOTS = ('/dev', '/proc', '/sys', '/tmp', '/setting', '/log', '/cert', '/lens',
                 '/run', '/initrd', '/usr/upgrade', '/system', '/rootfs', '/wbi', '/android',
                 '/PMBP', '/MP3', '/BGM', '/mnt', '/media', '/devel')


class UnsupportedFilesystem(RuntimeError):
    def __init__(self, reason, **details):
        super().__init__(reason)
        self.details = {'reason': reason, **details}


class PathError(Exception):
    def __init__(self, errno, reason):
        self.errno, self.reason = errno, reason


AUTHENTIC_PROC_MODULES = (
    b"devno 2161 23 usbg_stillimage,usbg_storage,cec,hdmi,usb_buspwr,usb_darwin,usbg_buspower,dma330,mmc_drv,ms_drv,mcmn_drv,grm_gles,kikilog,usb_extcmd,usbg_sen,usb_portMonitor,stream2,stream,backup,osal_uipc,emmc,ldec,dmac, Live 0x5f000000 (P)\n"
    b"dmac 12460 3 liro,emmc,ldec, Live 0x5f004000 (P)\n"
    b"ldec 10134 1 emmc, Live 0x5f00b000 (P)\n"
    b"emmc 171059 11 - Live 0x5f011000 (P)\n"
    b"osal_utm 2139 16 cec,hdmi,liro,codec_drv,ms_drv,mcmn_drv,accel,nfc,upm,dmm,kikilog,usb_portMonitor,i2c,osal_ulogio,utimer,osal_uipc, Live 0x5f042000 (P)\n"
    b"osal_uipc 37181 34 usbg_stillimage,usbg_storage,cec,hdmi,usb_buspwr,usb_darwin,usbg_buspower,liro,codec_drv,dma330,mmc_drv,ms_drv,mcmn_drv,compass,mag,accel,grm_gles,grm_ma,nfc,upm,dmm,kikilog,usbg_sen,usb_portMonitor,sircs,i2c,indctr,udate,input,osal_ulogio,backup,utimer, Live 0x5f046000 (P)\n"
    b"utimer 21490 0 - Live 0x5f054000 (P)\n"
    b"backup 61073 17 hdmi,usb_buspwr,usb_darwin,liro,mcmn_drv,mag,accel,nfc,upm,dmm,usbg_sen,usb_portMonitor,i2c,indctr,udate,input,osal_ulogio, Live 0x5f05d000 (P)\n"
    b"osal_ulogio 29859 0 - Live 0x5f070000 (P)\n"
    b"input 22826 0 - Live 0x5f07c000 (P)\n"
    b"udate 9116 0 - Live 0x5f086000 (P)\n"
    b"indctr 7911 0 - Live 0x5f08c000 (P)\n"
    b"i2c 10265 0 - Live 0x5f091000 (P)\n"
    b"sircs 15346 0 - Live 0x5f097000 (P)\n"
    b"stream 1077 9 - Live 0x5f09f000 (P)\n"
    b"stream2 1629 3 - Live 0x5f0a3000 (P)\n"
    b"usb_portMonitor 11648 0 - Live 0x5f0a7000 (P)\n"
    b"usbg_sen 30337 0 - Live 0x5f0ad000 (P)\n"
    b"usb_extcmd 9511 0 - Live 0x5f0b9000 (P)\n"
    b"kikilog 25020 1 - Live 0x5f0bf000 (P)\n"
    b"dmm 3148818 2 liro,upm, Live 0x5f0ca000 (P)\n"
    b"upm 110055 0 - Live 0x5f3d0000 (P)\n"
    b"nfc 10006 0 - Live 0x5f3f1000 (P)\n"
    b"grm_ma 19680 0 - Live 0x5f3f7000 (P)\n"
    b"grm_gles 9348 2 - Live 0x5f3ff000 (P)\n"
    b"accel 9024 0 - Live 0x5f405000 (P)\n"
    b"mag 6757 0 - Live 0x5f40b000 (P)\n"
    b"compass 2734 0 - Live 0x5f410000 (P)\n"
    b"mcmn_drv 91324 2 mmc_drv,ms_drv, Live 0x5f414000 (P)\n"
    b"ms_drv 162876 0 - Live 0x5f430000 (P)\n"
    b"usbg_stillimage 19213 0 - Live 0x5f459000 (P)\n"
    b"mmc_drv 185090 4 - Live 0x5f461000 (P)\n"
    b"dma330 248111 1 liro, Live 0x5f499000 (P)\n"
    b"codec_drv 12644 0 - Live 0x5f4d9000 (P)\n"
    b"liro 51420 0 - Live 0x5f4e0000 (P)\n"
    b"usbg_buspower 9293 0 - Live 0x5f4f3000 (P)\n"
    b"usb_darwin 21440 1 usb_buspwr, Live 0x5f4f9000 (P)\n"
    b"usb_buspwr 8195 1 - Live 0x5f502000 (P)\n"
    b"hdmi 154375 4 cec, Live 0x5f508000 (P)\n"
    b"cec 53250 3 - Live 0x5f53c000 (P)\n"
    b"wlanMemoryAllocator 3569 0 - Live 0x5f552000 (P)\n"
    b"usbg_storage 53865 1 - Live 0x5f554000 (P)\n"
)


class GuestFilesystem:
    # Invented, NOT observed: /dev/nflasha10 (the real /tmp device) is not among the preserved inputs.
    EXPERIMENTAL_TMP_METADATA = {'mode': 0o040777, 'uid': 0, 'gid': 0, 'nlink': 2, 'inode': 1,
                                 'size': 4096, 'block_size': 4096, 'blocks_512': 8}
    EXPERIMENTAL_PROC_METADATA = {'mode': 0o040555, 'uid': 0, 'gid': 0, 'nlink': 2, 'inode': 1,
                                  'size': 0, 'block_size': 1024, 'blocks_512': 0}
    EXPERIMENTAL_PROC_MODULES_METADATA = {'mode': 0o100444, 'uid': 0, 'gid': 0, 'nlink': 1, 'inode': 2,
                                          'size': len(AUTHENTIC_PROC_MODULES), 'block_size': 1024,
                                          'blocks_512': (len(AUTHENTIC_PROC_MODULES) + 511) // 512}
    EXPERIMENTAL_SETTING_METADATA = {'mode': 0o040755, 'uid': 0, 'gid': 0, 'nlink': 2, 'inode': 1,
                                     'size': 4096, 'block_size': 4096, 'blocks_512': 8}

    def __init__(self, mu, nodes, content_loader, before_read=None, after_write=None,
                 uid=0, gid=0, stat_contract=None, unknown_roots=UNKNOWN_ROOTS,
                 urandom_open=False, urandom_entropy_policy='stop', urandom_seed=b'\x12\x34\x56\x78',
                 tmp_overlay='stop', proc_overlay='stop', setting_overlay='stop'):
        if urandom_entropy_policy not in ('stop', 'deterministic'):
            raise ValueError(f'Unknown urandom entropy policy: {urandom_entropy_policy}')
        if tmp_overlay not in ('stop', 'experimental-empty'):
            raise ValueError(f'Unknown tmp overlay policy: {tmp_overlay}')
        if proc_overlay not in ('stop', 'experimental-empty'):
            raise ValueError(f'Unknown proc overlay policy: {proc_overlay}')
        if setting_overlay not in ('stop', 'experimental-empty'):
            raise ValueError(f'Unknown setting overlay policy: {setting_overlay}')
        self.setting_overlay = setting_overlay
        self.tmp_overlay = tmp_overlay
        self.proc_overlay = proc_overlay
        self.mu, self.nodes, self.content_loader = mu, nodes, content_loader
        self.before_read, self.after_write = before_read, after_write
        self.uid, self.gid = uid, gid
        self.stat_contract = stat_contract
        self.unknown_roots = unknown_roots
        self.urandom_open = urandom_open
        self.urandom_entropy_policy = urandom_entropy_policy
        self.urandom_seed = urandom_seed
        self.fds = {}
        self.cache = {}

    def _tmp_overlay_request(self, number, event, path, args):
        """Experimental empty /tmp (read-only metadata queries only). Returns an event or None."""
        if self.tmp_overlay != 'experimental-empty' or not (path == '/tmp' or path.startswith('/tmp/')):
            return None
        note = {'experimental': 'empty /tmp overlay; not camera state (real /tmp is vfat on nflasha10)'}
        if number == 5:
            if path == '/tmp':
                raise UnsupportedFilesystem('tmp_directory_open_not_implemented', path=path)
            return {**event, **note, 'returned': (-2) & 0xffffffff, 'reason': 'ENOENT_experimental_empty_tmp'}
        if path != '/tmp':
            return {**event, **note, 'returned': (-2) & 0xffffffff, 'reason': 'ENOENT_experimental_empty_tmp'}
        if number == 33:
            return {**event, **note, 'returned': 0, 'reason': 'experimental_tmp_access'}
        if self.stat_contract is None:
            raise UnsupportedFilesystem('stat64_success_structure_not_implemented', path=path)
        result = self.stat_contract.request(dict(self.EXPERIMENTAL_TMP_METADATA), args[1])
        return {**event, **note, **result, 'experimental_values': dict(self.EXPERIMENTAL_TMP_METADATA)}

    def _proc_overlay_request(self, number, event, path, args):
        """Experimental /proc virtual mount contract. Returns an event or None."""
        if self.proc_overlay != 'experimental-empty' or not (path == '/proc' or path.startswith('/proc/')):
            return None
        note = {'experimental': 'procfs overlay; virtual /proc namespace'}
        if number == 5:
            if path == '/proc':
                fd = next((candidate for candidate in range(3, 259) if candidate not in self.fds), None)
                if fd is None:
                    raise UnsupportedFilesystem('experimental_descriptor_limit')
                self.fds[fd] = {'path': '/proc', 'device': 'proc_dir', 'flags': args[1]}
                return {**event, **note, 'returned': fd, 'reason': 'opened_experimental_proc_dir'}
            if path == '/proc/modules':
                fd = next((candidate for candidate in range(3, 259) if candidate not in self.fds), None)
                if fd is None:
                    raise UnsupportedFilesystem('experimental_descriptor_limit')
                self.fds[fd] = {'path': '/proc/modules', 'device': 'proc_modules', 'data': AUTHENTIC_PROC_MODULES, 'offset': 0, 'flags': args[1]}
                return {**event, **note, 'returned': fd, 'reason': 'opened_authentic_proc_modules',
                        'size': len(AUTHENTIC_PROC_MODULES), 'sha256': hashlib.sha256(AUTHENTIC_PROC_MODULES).hexdigest()}
            return {**event, **note, 'returned': (-2) & 0xffffffff, 'reason': 'ENOENT_experimental_empty_proc'}
        if path == '/proc/modules':
            if number == 33:
                return {**event, **note, 'returned': 0, 'reason': 'authentic_proc_modules_access'}
            if self.stat_contract is None:
                raise UnsupportedFilesystem('stat64_success_structure_not_implemented', path=path)
            meta = dict(self.EXPERIMENTAL_PROC_MODULES_METADATA)
            result = self.stat_contract.request(meta, args[1])
            return {**event, **note, **result, 'experimental_values': meta}
        if path != '/proc':
            return {**event, **note, 'returned': (-2) & 0xffffffff, 'reason': 'ENOENT_experimental_empty_proc'}
        if number == 33:
            return {**event, **note, 'returned': 0, 'reason': 'experimental_proc_access'}
        if self.stat_contract is None:
            raise UnsupportedFilesystem('stat64_success_structure_not_implemented', path=path)
        result = self.stat_contract.request(dict(self.EXPERIMENTAL_PROC_METADATA), args[1])
        return {**event, **note, **result, 'experimental_values': dict(self.EXPERIMENTAL_PROC_METADATA)}

    def _setting_overlay_request(self, number, event, path, args):
        """Experimental /setting mount contract. Returns an event or None."""
        if self.setting_overlay != 'experimental-empty' or not (path == '/setting' or path.startswith('/setting/')):
            return None
        note = {'experimental': 'setting overlay; empty /setting mountpoint (real partition 2 on nflasha2)'}
        if number == 5:
            if path == '/setting':
                raise UnsupportedFilesystem('setting_directory_open_not_implemented', path=path)
            return {**event, **note, 'returned': (-2) & 0xffffffff, 'reason': 'ENOENT_experimental_empty_setting'}
        if path != '/setting':
            return {**event, **note, 'returned': (-2) & 0xffffffff, 'reason': 'ENOENT_experimental_empty_setting'}
        if number == 33:
            return {**event, **note, 'returned': 0, 'reason': 'experimental_setting_access'}
        if self.stat_contract is None:
            raise UnsupportedFilesystem('stat64_success_structure_not_implemented', path=path)
        result = self.stat_contract.request(dict(self.EXPERIMENTAL_SETTING_METADATA), args[1])
        return {**event, **note, **result, 'experimental_values': dict(self.EXPERIMENTAL_SETTING_METADATA)}

    def _scope(self, path):
        if any(path == root or path.startswith(root + '/') for root in self.unknown_roots):
            raise UnsupportedFilesystem('runtime_namespace_not_supplied', path=path)

    def _permission(self, node, requested):
        shift = 6 if node['uid'] == self.uid else 3 if node['gid'] == self.gid else 0
        allowed = (node['mode'] >> shift) & 7
        if allowed & requested != requested:
            if self.uid == 0:
                raise UnsupportedFilesystem('root_capability_policy_required')
            raise PathError(13, 'EACCES')

    def _path(self, pointer):
        raw = bytearray()
        for index in range(4096):
            address = pointer + index
            if not accessible(self.mu, address, 1, unicorn.UC_PROT_READ):
                raise PathError(14, 'EFAULT_path')
            if self.before_read:
                self.before_read(address, 1)
            byte = bytes(self.mu.mem_read(address, 1))
            if byte == b'\0':
                if not raw:
                    raise PathError(2, 'ENOENT_empty_path')
                try:
                    path = raw.decode('ascii')
                except UnicodeDecodeError:
                    raise UnsupportedFilesystem('non_ascii_guest_path')
                if not path.startswith('/'):
                    raise UnsupportedFilesystem('relative_path_requires_cwd', path=path)
                return path
            raw.extend(byte)
        raise PathError(36, 'ENAMETOOLONG')

    def _resolve(self, path, allow_urandom=False):
        def visit(prefix, node, traversing):
            if not (allow_urandom and prefix in ('/dev', '/dev/urandom')):
                self._scope(prefix)
            if node and node['kind'] == 'directory' and traversing:
                self._permission(node, 1)
        try:
            result = resolve_guest(self.nodes, path, visit=visit)
        except ValueError:
            raise PathError(40, 'ELOOP')
        if result['status'] != 'resolved':
            raise PathError(20 if result['status'] == 'not_directory' else 2,
                            'ENOTDIR' if result['status'] == 'not_directory' else 'ENOENT_image_namespace')
        return result['path'], self.nodes[result['path']]

    def _descriptor(self, fd):
        if fd in (0, 1, 2):
            raise UnsupportedFilesystem('inherited_stdio_not_supplied', fd=fd)
        if fd not in self.fds:
            raise PathError(9, 'EBADF')
        return self.fds[fd]

    def request(self, number, args):
        names = {3: 'read', 5: 'open', 6: 'close', 19: 'lseek', 33: 'access', 195: 'stat64', 197: 'fstat64'}
        if number not in names:
            raise UnsupportedFilesystem('unimplemented_file_syscall', number=number)
        event = {'syscall': names[number], 'arguments': list(args[:3])}
        try:
            if number in (5, 33, 195):
                path = self._path(args[0])
                event['path'] = path
                if number == 33:
                    if args[1] & ~7:
                        raise PathError(22, 'EINVAL_access_mode')
                    if args[1] not in (0, 4):
                        raise UnsupportedFilesystem('write_or_execute_access_not_implemented', path=path)
                elif number == 5 and args[1] & ~(0x80000 | 0x20000):  # O_CLOEXEC / ARM O_LARGEFILE only
                    raise UnsupportedFilesystem('open_flags_not_read_only_subset', path=path, flags=args[1])
                overlay = self._tmp_overlay_request(number, event, path, args)
                if overlay is not None:
                    return overlay
                proc_overlay = self._proc_overlay_request(number, event, path, args)
                if proc_overlay is not None:
                    return proc_overlay
                setting_overlay = self._setting_overlay_request(number, event, path, args)
                if setting_overlay is not None:
                    return setting_overlay
                entropy_open = self.urandom_open and number == 5 and path == '/dev/urandom'
                resolved, node = self._resolve(path, allow_urandom=entropy_open)
                if entropy_open:
                    metadata = node.get('stat_metadata', {})
                    source_hash = metadata.get('image_sha256', '')
                    if (node['kind'] != 'special' or node['mode'] & 0xf000 != 0x2000
                            or metadata.get('mode') != node['mode']
                            or metadata.get('device_number') != {'major': 1, 'minor': 9}
                            or len(source_hash) != 64 or any(c not in '0123456789abcdef' for c in source_hash)):
                        raise UnsupportedFilesystem('urandom_image_identity_not_verified', path=path)
                    self._permission(node, 4)
                    fd = next((candidate for candidate in range(3, 259) if candidate not in self.fds), None)
                    if fd is None:
                        raise UnsupportedFilesystem('experimental_descriptor_limit')
                    self.fds[fd] = {'path': resolved, 'device': 'urandom', 'flags': args[1],
                                    'source_sha256': source_hash}
                    return {**event, 'returned': fd, 'reason': 'opened_image_urandom_contract',
                            'partial_contract': True, 'source_sha256': source_hash,
                            'device_number': metadata['device_number']}

                event['resolved_path'] = resolved
                if number == 195:
                    if self.stat_contract is None:
                        raise UnsupportedFilesystem('stat64_success_structure_not_implemented', path=resolved)
                    return {**event, **self._stat(node, args[1])}
                if number == 33:
                    if args[1]:
                        self._permission(node, 4)
                    return {**event, 'returned': 0, 'reason': 'image_metadata_access'}
                if node['kind'] != 'file':
                    raise UnsupportedFilesystem('non_regular_file_open', path=resolved, kind=node['kind'])
                self._permission(node, 4)
                if resolved not in self.cache:
                    try:
                        content = self.content_loader(resolved, node)
                    except ContentUnavailable as error:
                        raise UnsupportedFilesystem('unverified_image_content', path=resolved, detail=str(error))
                    if len(content) != node['size']:
                        raise UnsupportedFilesystem('image_content_size_mismatch', path=resolved)
                    self.cache[resolved] = bytes(content)
                content = self.cache[resolved]
                fd = next((candidate for candidate in range(3, 259) if candidate not in self.fds), None)
                if fd is None:
                    raise UnsupportedFilesystem('experimental_descriptor_limit')
                self.fds[fd] = {'path': resolved, 'data': content, 'offset': 0, 'flags': args[1]}
                return {**event, 'returned': fd, 'reason': 'opened_verified_snapshot',
                        'size': len(content), 'sha256': hashlib.sha256(content).hexdigest()}
            descriptor = self._descriptor(args[0])
            event['path'] = descriptor['path']
            if descriptor.get('device') == 'proc_dir':
                if number == 6:
                    del self.fds[args[0]]
                    return {**event, 'returned': 0, 'reason': 'closed_guest_descriptor'}
                if number == 197:
                    if self.stat_contract is None:
                        raise UnsupportedFilesystem('stat64_success_structure_not_implemented', path=descriptor['path'])
                    result = self.stat_contract.request(dict(self.EXPERIMENTAL_PROC_METADATA), args[1])
                    return {**event, 'experimental': 'procfs overlay; virtual /proc namespace', **result,
                            'experimental_values': dict(self.EXPERIMENTAL_PROC_METADATA)}
                raise UnsupportedFilesystem('proc_dir_operation_not_implemented',
                                            number=number, path=descriptor['path'])
            if descriptor.get('device') == 'proc_modules':
                if number == 6:
                    del self.fds[args[0]]
                    return {**event, 'returned': 0, 'reason': 'closed_guest_descriptor'}
                if number == 197:
                    if self.stat_contract is None:
                        raise UnsupportedFilesystem('stat64_success_structure_not_implemented', path=descriptor['path'])
                    meta = dict(self.EXPERIMENTAL_PROC_MODULES_METADATA)
                    result = self.stat_contract.request(meta, args[1])
                    return {**event, 'experimental': 'procfs overlay; virtual /proc namespace', **result,
                            'experimental_values': meta}
                if number == 19:
                    signed = args[1] if args[1] < 0x80000000 else args[1] - 0x100000000
                    if args[2] not in (0, 1, 2):
                        raise PathError(22, 'EINVAL_whence')
                    base = (0, descriptor['offset'], len(descriptor['data']))[args[2]]
                    offset = base + signed
                    if offset < 0:
                        raise PathError(22, 'EINVAL_negative_offset')
                    if offset > 0x7fffffff:
                        raise UnsupportedFilesystem('large_file_seek_requires_llseek')
                    descriptor['offset'] = offset
                    return {**event, 'returned': offset, 'reason': 'guest_offset_updated'}
                pointer, count = args[1:3]
                if count > 1024 * 1024:
                    raise UnsupportedFilesystem('experimental_read_limit', count=count)
                amount = min(count, max(0, len(descriptor['data']) - descriptor['offset']))
                if amount and not accessible(self.mu, pointer, amount, unicorn.UC_PROT_WRITE):
                    raise PathError(14, 'EFAULT_read_buffer')
                offset = descriptor['offset']
                if amount:
                    self.mu.mem_write(pointer, descriptor['data'][offset:offset + amount])
                    if self.after_write:
                        self.after_write(pointer, amount)
                descriptor['offset'] += amount
                return {**event, 'returned': amount, 'reason': 'read_snapshot', 'offset_before': offset}
            if descriptor.get('device') == 'urandom':
                if number == 6:
                    del self.fds[args[0]]
                    return {**event, 'returned': 0, 'reason': 'closed_guest_descriptor'}
                if number == 3:
                    if self.urandom_entropy_policy == 'stop':
                        raise UnsupportedFilesystem(
                            'entropy_state_not_supplied',
                            path=descriptor['path'], source_sha256=descriptor['source_sha256'],
                            buffer=args[1], count=args[2], bytes_supplied=0)
                    elif self.urandom_entropy_policy == 'deterministic':
                        pointer, count = args[1:3]
                        if not accessible(self.mu, pointer, count, unicorn.UC_PROT_WRITE):
                            raise PathError(14, 'EFAULT_read_buffer')
                        multiplier = (count // len(self.urandom_seed)) + 1
                        entropy = (self.urandom_seed * multiplier)[:count]
                        self.mu.mem_write(pointer, entropy)
                        if self.after_write:
                            self.after_write(pointer, count)
                        return {**event, 'returned': count, 'reason': 'deterministic_urandom_read',
                                'bytes_supplied': count, 'entropy_hex': entropy.hex()}
                if number == 197 and self.stat_contract is not None:
                    return {**event, **self._stat(self.nodes[descriptor['path']], args[1])}
                raise UnsupportedFilesystem(
                    'urandom_operation_not_implemented',
                    path=descriptor['path'], source_sha256=descriptor['source_sha256'])
            if number == 197:
                return {**event, **self._stat(self.nodes[descriptor['path']], args[1])}
            if number == 6:
                del self.fds[args[0]]
                return {**event, 'returned': 0, 'reason': 'closed_guest_descriptor'}
            if number == 19:
                signed = args[1] if args[1] < 0x80000000 else args[1] - 0x100000000
                if args[2] not in (0, 1, 2):
                    raise PathError(22, 'EINVAL_whence')
                base = (0, descriptor['offset'], len(descriptor['data']))[args[2]]
                offset = base + signed
                if offset < 0:
                    raise PathError(22, 'EINVAL_negative_offset')
                if offset > 0x7fffffff:
                    raise UnsupportedFilesystem('large_file_seek_requires_llseek')
                descriptor['offset'] = offset
                return {**event, 'returned': offset, 'reason': 'guest_offset_updated'}
            pointer, count = args[1:3]
            if count > 1024 * 1024:
                raise UnsupportedFilesystem('experimental_read_limit', count=count)
            amount = min(count, max(0, len(descriptor['data']) - descriptor['offset']))
            if amount and not accessible(self.mu, pointer, amount, unicorn.UC_PROT_WRITE):
                raise PathError(14, 'EFAULT_read_buffer')
            offset = descriptor['offset']
            if amount:
                self.mu.mem_write(pointer, descriptor['data'][offset:offset + amount])
                if self.after_write:
                    self.after_write(pointer, amount)
            descriptor['offset'] += amount
            return {**event, 'returned': amount, 'reason': 'read_snapshot', 'offset_before': offset}
        except PathError as error:
            return {**event, 'returned': (-error.errno) & 0xffffffff, 'reason': error.reason}

    def _stat(self, node, address):
        if self.stat_contract is None:
            raise UnsupportedFilesystem('stat64_success_structure_not_implemented')
        if 'stat_metadata' not in node:
            raise UnsupportedFilesystem('stat64_metadata_source_missing')
        return self.stat_contract.request(node['stat_metadata'], address)
