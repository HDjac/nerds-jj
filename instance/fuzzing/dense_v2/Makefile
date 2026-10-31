CC ?= /usr/bin/clang-19
CC := /usr/bin/clang-19
CFLAGS = -g -O1 -fno-omit-frame-pointer -Wall -Wextra -Iinclude -fsanitize=fuzzer,address,undefined -fno-sanitize-recover=undefined
SRC = $(wildcard src/*.c)
.PHONY: all clean
all: fuzz_a fuzz_b fuzz_c
fuzz_a: $(SRC) harnesses/harness_a.c include/dense.h
	$(CC) $(CFLAGS) $(SRC) harnesses/harness_a.c -o $@
fuzz_b: $(SRC) harnesses/harness_b.c include/dense.h
	$(CC) $(CFLAGS) $(SRC) harnesses/harness_b.c -o $@
fuzz_c: $(SRC) harnesses/harness_c.c include/dense.h
	$(CC) $(CFLAGS) $(SRC) harnesses/harness_c.c -o $@
clean:
	rm -f fuzz_a fuzz_b fuzz_c
