"""Compatibility entry point; implementation moved to legacy/cxd90045_gui_runner.py."""
if __name__ == "__main__":
    import runpy
    runpy.run_module("legacy.cxd90045_gui_runner", run_name="__main__")
else:
    from importlib import import_module as _import_module
    _implementation = _import_module("legacy.cxd90045_gui_runner")
    globals().update({k: v for k, v in vars(_implementation).items() if not k.startswith("__")})
