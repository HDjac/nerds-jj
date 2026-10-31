#include "protocol.h"

#include <string.h>

uint8_t frame_checksum(const uint8_t *h)
{
    uint8_t acc = 0x91;

    for (size_t i = 4; i < 9; i++) {
        acc = rotate_left8(acc, 1);
        acc ^= h[i];
        acc = (uint8_t)(acc + 0x2d);
    }

    return acc;
}

static int valid_type(uint8_t type)
{
    return type == MSG_STATUS || type == MSG_DATA || type == MSG_ADMIN;
}

static int valid_flags(uint8_t flags)
{
    /* Only the low three flag bits are currently defined. */
    return (flags & 0xf8u) == 0;
}

ParseResult parse_frame(const uint8_t *data, size_t size, Frame *out)
{
    if (data == NULL || out == NULL || size < FRAME_HEADER_SIZE) {
        return PARSE_SHORT;
    }

    if (data[0] != FRAME_MAGIC_0 ||
        data[1] != FRAME_MAGIC_1 ||
        data[2] != FRAME_MAGIC_2 ||
        data[3] != FRAME_MAGIC_3) {
        return PARSE_MAGIC;
    }

    if (data[4] != FRAME_VERSION) {
        return PARSE_VERSION;
    }

    if (!valid_type(data[5]) || !valid_flags(data[6])) {
        return PARSE_TYPE;
    }

    size_t payload_len = data[8];
    if (payload_len > MAX_PAYLOAD) {
        return PARSE_LENGTH;
    }

    if (size < FRAME_HEADER_SIZE + payload_len) {
        return PARSE_LENGTH;
    }

    if (frame_checksum(data) != data[9]) {
        return PARSE_CHECKSUM;
    }

    out->version = data[4];
    out->type = data[5];
    out->flags = data[6];
    out->channel = data[7];
    out->nonce = data[6] ^ data[7] ^ data[8];
    out->payload = data + FRAME_HEADER_SIZE;
    out->payload_len = payload_len;

    return PARSE_OK;
}
