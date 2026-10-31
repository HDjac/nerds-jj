CC := /usr/bin/clang-19
CFLAGS = -g -O1 -fno-omit-frame-pointer -Iinclude -fsanitize=fuzzer,address,undefined
LDFLAGS = -fsanitize=fuzzer,address,undefined
GCC_LIBDIR := $(shell dirname $$(gcc -print-file-name=libstdc++.so))
COMMON = src/util.c src/frame.c src/status.c src/data.c src/records.c src/storage.c src/admin.c src/router.c

all: fuzz_a fuzz_b fuzz_c

fuzz_a: $(COMMON) harnesses/harness_a.c
	$(CC) $(CFLAGS) $^ -L$(GCC_LIBDIR) $(LDFLAGS) -o $@

fuzz_b: $(COMMON) harnesses/harness_b.c
	$(CC) $(CFLAGS) $^ -L$(GCC_LIBDIR) $(LDFLAGS) -o $@

fuzz_c: $(COMMON) harnesses/harness_c.c
	$(CC) $(CFLAGS) $^ -L$(GCC_LIBDIR) $(LDFLAGS) -o $@

clean:
	rm -f fuzz_a fuzz_b fuzz_c
	rm -rf corpus artifacts calibration
