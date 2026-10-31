#include "dense.h"

int bridge_parse_record(const uint8_t *data, size_t size,
                        BridgeRecord *record, size_t *consumed)
{
    if (!data || !record || !consumed || size < 4u) return -1;
    uint8_t tag = data[0];
    uint8_t mode = data[1];
    size_t record_length = bridge_read16(data + 2);
    if (record_length > size - 4u) return -1;

    record->tag = tag;
    record->mode = mode;
    record->bytes = data + 4;
    record->size = record_length;
    *consumed = 4u + record_length;
    return bridge_check_record(record);
}

int bridge_check_record(const BridgeRecord *record)
{
    if (!record || !record->bytes) return -1;
    if (record->tag != 0x41u && record->tag != 0x72u &&
        record->tag != 0x93u) return -1;
    if (record->mode > 3u) return -1;
    if (record->size > 128u) return -1;
    if (record->mode == 2u && (record->size & 1u)) return -1;
    if (record->tag == 0x93u && record->size < 4u) return -1;
    return 0;
}
