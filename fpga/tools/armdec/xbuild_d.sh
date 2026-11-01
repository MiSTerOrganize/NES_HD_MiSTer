#!/bin/sh
# xbuild_d.sh - cross-build the hdarm daemon (hdarm4.c as a library + hdarm_daemon.c) for the
# Cortex-A9. Runs inside debian:bookworm. /src = tools/armdec, /out = where the binary goes.
# Same flags as xbuild.sh (see the measurements there): -O3 and no position-independent code.
set -e
if ! command -v arm-linux-gnueabihf-gcc >/dev/null 2>&1; then
    apt-get update -qq >/dev/null
    apt-get install -y -qq gcc-arm-linux-gnueabihf >/dev/null
fi
F="-O3 -fno-pie -mcpu=cortex-a9 -mfloat-abi=hard -mfpu=neon -Wall"
arm-linux-gnueabihf-gcc $F -DHDARM_LIB -c -o /tmp/hdarm4.o /src/hdarm4.c
arm-linux-gnueabihf-gcc $F -c -o /tmp/daemon.o /src/hdarm_daemon.c
arm-linux-gnueabihf-gcc $F -c -o /tmp/romfix_arm.o /src/romfix_arm.c
arm-linux-gnueabihf-gcc $F -c -o /tmp/aud_arm.o /src/aud_arm.c
arm-linux-gnueabihf-gcc -static -no-pie -o /out/hdarm_daemon_a9 /tmp/daemon.o /tmp/hdarm4.o \
	/tmp/romfix_arm.o /tmp/aud_arm.o -lm -lpthread
ls -l /out/hdarm_daemon_a9
