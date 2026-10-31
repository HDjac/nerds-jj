#include "protocol.h"

#include <stddef.h>
#include <stdint.h>

static uint32_t fold_status_bytes(const uint8_t *data, size_t size)
{
    uint32_t state = 0x6d2b79f5u;

    for (size_t i = 0; i < size; i++) {
        state ^= data[i];
        state *= 16777619u;
        state ^= state >> 13;
    }

    return state;
}

int process_status_payload(const uint8_t *data, size_t size)
{
    if (data == NULL || size < 2) {
        return 0;
    }

    uint8_t opcode = data[0];
    uint8_t count = data[1];

    if (opcode > 4) {
        return 0;
    }

    if ((size_t)count + 2 > size) {
        return 0;
    }

    volatile uint32_t folded = fold_status_bytes(data + 2, count);
    (void)folded;

    return 1;
}
