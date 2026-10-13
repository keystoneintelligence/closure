#!/bin/bash
set -e
# Ubuntu relocates the upstream bin/lib layout. Its binaries need this etc root;
# sourcing the upstream bashrc would refer to helper scripts the package omits.
export WM_PROJECT_DIR=/usr/share/openfoam
export WM_PROJECT=OpenFOAM
# Bound the guest process group even if the Windows/WSL bridge disappears.
# This deadline is shorter than the bridge's 180 s timeout.
exec /usr/bin/timeout --signal=TERM --kill-after=5s 165s /usr/bin/python3 "$1" "$2"
