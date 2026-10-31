#include "dense.h"
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

static int store_string(const uint8_t *data, size_t size,
                        BridgeSession *session)
{
    char scratch[24];
    if (size < 2u || size > 64u) return -1;
    uint8_t claimed = data[0];
    if (claimed > size - 1u) return -1;
    memcpy(scratch, data + 1u, claimed);
    session->last_code = (uint16_t)(uint8_t)scratch[0];
    return claimed;
}

int bridge_store_attribute(const BridgeRecord *record, BridgeSession *session)
{
    if (bridge_check_record(record) != 0 || !session) return -1;
    if (record->tag != 0x41u) return 0;
    if (record->mode == 0u) {
        return store_string(record->bytes, record->size, session);
    }
    if (record->mode == 1u) {
        if (record->size < 2u) return -1;
        return (int)bridge_read16(record->bytes);
    }
    if (record->mode == 2u) {
        return (int)(bridge_hash(record->bytes, record->size) & 0x7fu);
    }
    return (int)record->size;
}

int bridge_expand_archive(const BridgeRecord *record, BridgeSession *session)
{
    if (bridge_check_record(record) != 0 || !session) return -1;
    if (record->tag != 0x93u || record->mode != 2u) return 0;

    // The storage layer uses the budget supplied by the record layer.
    size_t capacity = bridge_encoded_budget(record);
    uint8_t *expanded = malloc(capacity ? capacity : 1u);
    if (!expanded) return -1;

    int decoded = bridge_unpack_record(record, expanded, 192u);
    if (decoded > 0) session->last_code = expanded[0];
    free(expanded);
    return decoded;
}
