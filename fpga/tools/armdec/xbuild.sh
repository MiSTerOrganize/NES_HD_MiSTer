#!/bin/sh
# xbuild.sh - cross-build hdarm4 for the DE10-Nano's Cortex-A9 (static, armhf).
# Runs inside debian:bookworm (gcc 12, the compiler the ARM instruction counts are measured
# with - see cg_arm.sh). /src = tools/armdec, /out = where the binary goes.
#
# Flags, measured 2026-10-22 on four reference frames (warm ARM instructions per frame):
#   -O2 (Debian default PIE)        CV0060 12.99M  CV0250 12.18M  a034 9.00M  p053 12.68M
#   -O2 -fno-pie                    CV0060 12.29M  CV0250 11.66M  a034 8.94M  p053 12.53M
#   -O3 -fno-pie                    CV0060 11.67M  CV0250 11.02M  a034 8.74M  p053 12.39M
# Debian's gcc compiles position-independent by default, so every global costs a pc-relative
# literal load plus an add; the main loop reads globals on nearly every pixel. -O3 alone was
# no better than -fno-pie alone (CV0060 12.30M), the two together are best.
set -e
if ! command -v arm-linux-gnueabihf-gcc >/dev/null 2>&1; then
    apt-get update -qq >/dev/null
    apt-get install -y -qq gcc-arm-linux-gnueabihf >/dev/null
fi
arm-linux-gnueabihf-gcc -O3 -fno-pie -no-pie -mcpu=cortex-a9 -mfloat-abi=hard -mfpu=neon -static \
    -o /out/hdarm4_a9 /src/hdarm4.c -lm
ls -l /out/hdarm4_a9
