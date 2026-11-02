"""Compatibility entry point; implementation moved to tools/research/backup_camera.py."""
if __name__ == "__main__":
    import runpy
    runpy.run_module("tools.research.backup_camera", run_name="__main__")
else:
    from importlib import import_module as _import_module
    _implementation = _import_module("tools.research.backup_camera")
    globals().update({k: v for k, v in vars(_implementation).items() if not k.startswith("__")})
