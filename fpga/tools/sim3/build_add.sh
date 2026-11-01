#!/bin/sh
# Build the hd3_add testbenches: obj/add64 (NL=64, run_add.sh's EXE) and obj/add (NL=16, its
# SMALL_EXE).
cd "$(dirname "$0")"
R=../../rtl/hdpack
L="hd3_add_tb.sv $R/hd3_dict.sv $R/hd3_lookup.sv $R/hd3_add.sv"
OBJ=obj/add64 VFLAGS=-GNL=64 sh build_one.sh hd3_add_tb tb_add.cpp $L || exit 1
OBJ=obj/add sh build_one.sh hd3_add_tb tb_add.cpp $L || exit 1
