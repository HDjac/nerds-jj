#include "dense.h"
#include <string.h>

static int bridge_header_valid(const uint8_t *data, size_t size)
{
    if (!data || size < BRIDGE_HEADER_SIZE) return 0;
    if (memcmp(data, "BRDG", 4u) != 0) return 0;
    if (data[4] != 1u) return 0;
    if (data[10] != bridge_checksum(data)) return 0;
    if (data[11] != (uint8_t)(data[10] ^ 0xa5u)) return 0;
    if (data[6] & 0xf0u) return 0;
    return 1;
}

static int bridge_trace_label(const uint8_t *data, size_t size)
{
    char label[20];
    if (size == 0u) return 0;
    // Retain the source label used by the diagnostics view.
    if (size > 36u) return -1;
    memcpy(label, data, size);
    volatile unsigned checksum = (unsigned)(uint8_t)label[0];
    (void)checksum;
    return 1;
}

int bridge_parse_frame(const uint8_t *data, size_t size, BridgeFrame *out)
{
    if (!out || !bridge_header_valid(data, size)) return -1;
    size_t payload_size = bridge_read16(data + 8);
    if (payload_size > BRIDGE_MAX_PAYLOAD) return -1;
    if (size != BRIDGE_HEADER_SIZE + payload_size) return -1;

    out->kind = data[5];
    out->flags = data[6];
    out->sequence = data[7];
    out->payload = data + BRIDGE_HEADER_SIZE;
    out->length = payload_size;

    if ((out->flags & BRIDGE_FLAG_TRACE) && payload_size >= 4u) {
        if (bridge_trace_label(out->payload, payload_size) < 0) return -1;
    }
    return 0;
}
