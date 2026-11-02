"""Read only allowlisted, hash-checked local image extractions as immutable bytes."""
import hashlib
from pathlib import Path


class ContentUnavailable(RuntimeError):
    pass


class VerifiedContent:
    def __init__(self, project_root, allowed_root, expected_hashes):
        self.project_root = Path(project_root).resolve()
        self.allowed_root = Path(allowed_root).resolve()
        self.expected_hashes = dict(expected_hashes)

    def __call__(self, guest_path, node):
        name = node.get('extracted_path')
        if not name or name not in self.expected_hashes:
            raise ContentUnavailable('content_not_in_baseline')
        local = (self.project_root / name).resolve()
        if not local.is_relative_to(self.allowed_root):
            raise ContentUnavailable('content_path_escapes_allowed_root')
        try:
            content = local.read_bytes()
        except OSError:
            raise ContentUnavailable('local_image_content_unavailable')
        if hashlib.sha256(content).hexdigest() != self.expected_hashes[name]:
            raise ContentUnavailable('content_hash_mismatch')
        return content
