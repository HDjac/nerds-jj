#include "dense.h"

static int bridge_update_header(const uint8_t *data, size_t size,
                                size_t *offset, uint8_t *count)
{
    if (!data || size < 4u || !offset || !count) return -1;
    if (data[0] != 0xa6u || data[1] != 1u) return -1;
    if (data[2] > 3u) return -1;
    uint8_t expected = (uint8_t)(data[2] ^ 0x5cu);
    if (data[3] != expected) return -1;
    *count = data[2];
    *offset = 4u;
    return 0;
}

int bridge_update(const uint8_t *data, size_t size, BridgeSession *session)
{
    if (!session) return -1;
    size_t offset = 0;
    uint8_t count = 0;
    if (bridge_update_header(data, size, &offset, &count) != 0) return -1;
    int total = 0;

    for (unsigned i = 0; i < count; ++i) {
        if (offset > size) return -1;
        BridgeRecord record;
        size_t consumed = 0;
        int status = bridge_parse_record(data + offset, size - offset,
                                         &record, &consumed);
        if (status != 0) return -1;
        offset += consumed;
        int stored = bridge_store_attribute(&record, session);
        if (stored < 0) return -1;
        total += stored;
    }
    if (offset != size) return -1;
    return total;
}
