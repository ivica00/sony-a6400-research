"""Fail-closed ZV-E10/a6400 UVC video device contract (E0319/E0320).

Evidence:
- ZV-E10 2.03 `devno.ko` (SHA-256 273db657...) registers `/dev/usb/video`
  (major 248, minor 0x21 = 33) and `/dev/usb/audio` (248, 32); the a6400
  `devno.ko` (3b36fcea...) has neither entry.
- ZV-E10 `usbg_video.ko` (d385a051...) is the char driver; its ioctl commands
  are decoded in ``usb_video_contract`` (0x4038e000, 0x4008f000, 0xe001).

This device model intentionally does NOT invent driver behaviour: open/close
are served and recorded, every ioctl/write/read stops with an explicit
boundary until the decoded contract is complete.  No fabricated success.
"""

from src.a6400.execution.usb_video_contract import (
    ZVE10_USBG_VIDEO_IOCTL_COMMANDS,
    decode_usb_video_ioctl,
)


class UnsupportedUsbVideo(Exception):
    """The usbg_video contract is not modelled for this operation."""

    def __init__(self, reason, **details):
        super().__init__(reason)
        self.reason = reason
        self.details = details


# Device identity from the ZV-E10 devno table (see module docstring).
ZVE10_USB_VIDEO_DEVICE = {
    'path': '/dev/usb/video',
    'major': 248,
    'minor': 0x21,
    'devno_flags_word': 0x10021,
    'module_sha256': 'd385a051bf01b0e5ea37412623ae85cfe3cda76ab0d11e61d111994ca9fbf4fb',
    'devno_sha256': '273db657a8e2c9c8752b0ace56817357ddea38285a52b5cb7007a3fcf9df33c1',
}
ZVE10_USB_AUDIO_DEVICE = {
    'path': '/dev/usb/audio',
    'major': 248,
    'minor': 0x20,
    'devno_flags_word': 0x10020,
    'devno_sha256': '273db657a8e2c9c8752b0ace56817357ddea38285a52b5cb7007a3fcf9df33c1',
}
A6400_DEVNO_SHA256 = (
    '3b36fcea8687d7f29112a7008ce61fde9229679ebc24c65ec2d21cf3af632f56')
A6400_MISSING_USB_NODES = ('/dev/usb/audio', '/dev/usb/video')


class GuestUsbVideo:
    """Minimal /dev/usb/video char-device model (fail-closed)."""

    def __init__(self, address_limit=0x5f000000):
        self.address_limit = address_limit
        self.major = ZVE10_USB_VIDEO_DEVICE['major']
        self.minor = ZVE10_USB_VIDEO_DEVICE['minor']
        self.path = ZVE10_USB_VIDEO_DEVICE['path']
        self.owners = {}
        self.transactions = []
        self.stopped = None

    def open(self, flags, caller_pid=0, caller_tgid=0):
        owner_id = len(self.owners) + 1
        self.owners[owner_id] = {
            'owner_id': owner_id,
            'flags': flags,
            'caller_pid': caller_pid,
            'caller_tgid': caller_tgid,
        }
        self.transactions.append({'operation': 'open', 'flags': flags,
                                  'owner_id': owner_id})
        return owner_id

    def close(self, owner_id):
        if owner_id not in self.owners:
            raise UnsupportedUsbVideo('usb_video_owner_unknown',
                                      owner_id=owner_id)
        del self.owners[owner_id]
        self.transactions.append({'operation': 'close', 'owner_id': owner_id})
        return 0

    def _stop(self, reason, **details):
        self.stopped = reason
        entry = {'operation': 'stop', 'reason': reason}
        entry.update(details)
        self.transactions.append(entry)
        raise UnsupportedUsbVideo(reason, **details)

    def ioctl(self, owner_id, command, argument=0):
        if owner_id not in self.owners:
            raise UnsupportedUsbVideo('usb_video_owner_unknown',
                                      owner_id=owner_id)
        description = decode_usb_video_ioctl(command)
        self.transactions.append({
            'operation': 'ioctl',
            'command': command,
            'name': description.get('name'),
            'known': description.get('known'),
            'argument': argument,
        })
        # The kernel driver's per-command behaviour (buffer/format updates) is
        # not decoded yet; returning success would be fabrication.
        self._stop('usb_video_ioctl_contract_unresolved',
                   command=command,
                   name=description.get('name'),
                   known=description.get('known'))

    def write(self, owner_id, buffer_size):
        if owner_id not in self.owners:
            raise UnsupportedUsbVideo('usb_video_owner_unknown',
                                      owner_id=owner_id)
        self.transactions.append({'operation': 'write',
                                  'size': buffer_size})
        self._stop('usb_video_write_buffer_contract_unresolved',
                   size=buffer_size)

    def read(self, owner_id, size):
        if owner_id not in self.owners:
            raise UnsupportedUsbVideo('usb_video_owner_unknown',
                                      owner_id=owner_id)
        self.transactions.append({'operation': 'read', 'size': size})
        self._stop('usb_video_read_completion_contract_unresolved', size=size)


def devno_usb_video_evidence():
    """Return the device-node evidence rows (a6400 vs ZV-E10 devno.ko)."""
    return {
        'zve10': {
            'devno_sha256': ZVE10_USB_VIDEO_DEVICE['devno_sha256'],
            'nodes': [dict(ZVE10_USB_AUDIO_DEVICE), dict(ZVE10_USB_VIDEO_DEVICE)],
        },
        'a6400': {
            'devno_sha256': A6400_DEVNO_SHA256,
            'missing_nodes': list(A6400_MISSING_USB_NODES),
        },
        'command_table': sorted(ZVE10_USBG_VIDEO_IOCTL_COMMANDS),
    }
