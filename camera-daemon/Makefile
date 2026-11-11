# Thin wrapper around build.sh and the host-test runner.
#
# GNU-make compatible. On this Windows host the installed make is
# `mingw32-make` (MinGW), so either run `mingw32-make arm` or use the
# `make.cmd` shim, which lets `.\make arm` work from PowerShell:
#
#   mingw32-make arm
#   mingw32-make host-tests
#   mingw32-make clean
#
# The ARM build always runs inside WSL; the host tests use the best host
# compiler available (see test/run_host_tests.py).

WSL_DISTRO ?= Ubuntu
PYTHON     ?= python

.PHONY: all arm host-tests clean

all: arm host-tests

# Cross-build the static ARM daemon. Zero warnings are required (-Werror).
arm:
	wsl -d $(WSL_DISTRO) -- bash -lc "cd \"$$(wslpath -a '$(CURDIR)')\" && ./build.sh"

# Build and run the offline unit tests. Never touches a camera.
host-tests:
	$(PYTHON) test/run_host_tests.py

clean:
	wsl -d $(WSL_DISTRO) -- bash -lc "cd \"$$(wslpath -a '$(CURDIR)')\" && rm -rf build"
