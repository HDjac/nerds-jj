#include "dense.h"

static uint8_t archive_credential(uint8_t sequence, uint8_t count)
{
    return bridge_rotate8((uint8_t)(sequence ^ 0x4du), 2u) ^ count;
}

static int archive_open(const uint8_t *data, size_t size,
                        size_t *offset, uint8_t *count)
{
    if (!data || !offset || !count || size < 6u) return -1;
    if (data[0] != 0xd4u || data[1] != 0x51u) return -1;
    if (data[3] > 3u) return -1;
    if (data[4] != archive_credential(data[2], data[3])) return -1;
    if (data[5] != 0xe1u) return -1;
    *offset = 6u;
    *count = data[3];
    return 0;
}

int bridge_archive(const uint8_t *data, size_t size, BridgeSession *session)
{
    if (!session) return -1;
    size_t offset = 0;
    uint8_t count = 0;
    if (archive_open(data, size, &offset, &count) != 0) return -1;

    int total = 0;
    for (unsigned i = 0; i < count; ++i) {
        if (offset > size) return -1;
        BridgeRecord record;
        size_t consumed = 0;
        if (bridge_parse_record(data + offset, size - offset,
                                &record, &consumed) != 0) return -1;
        offset += consumed;

        if (record.tag == 0x93u) {
            int expanded = bridge_expand_archive(&record, session);
            if (expanded < 0) return -1;
            total += expanded;
        } else {
            total += bridge_store_attribute(&record, session);
        }
    }
    if (offset != size) return -1;
    return total;
}
