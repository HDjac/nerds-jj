#include "dense.h"

uint8_t bridge_checksum(const uint8_t *header)
{
    uint8_t acc = 0x6du;
    for (size_t i = 0; i < 10u; ++i) {
        acc = bridge_rotate8(acc, 1u);
        acc ^= header[i];
        acc = (uint8_t)(acc + 0x17u);
    }
    return acc;
}

size_t bridge_make_frame(uint8_t *dest, size_t capacity, uint8_t kind,
                         uint8_t flags, uint8_t sequence,
                         const uint8_t *payload, size_t payload_size)
{
    if (!dest || (!payload && payload_size) ||
        payload_size > BRIDGE_MAX_PAYLOAD ||
        capacity < BRIDGE_HEADER_SIZE + payload_size) return 0;

    dest[0] = 'B';
    dest[1] = 'R';
    dest[2] = 'D';
    dest[3] = 'G';
    dest[4] = 1u;
    dest[5] = kind;
    dest[6] = flags;
    dest[7] = sequence;
    bridge_write16(dest + 8, (uint16_t)payload_size);
    dest[10] = bridge_checksum(dest);
    dest[11] = (uint8_t)(dest[10] ^ 0xa5u);

    for (size_t i = 0; i < payload_size; ++i) {
        dest[BRIDGE_HEADER_SIZE + i] = payload[i];
    }
    return BRIDGE_HEADER_SIZE + payload_size;
}
