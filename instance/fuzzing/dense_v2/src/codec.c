#include "dense.h"
#include <string.h>

size_t bridge_encoded_budget(const BridgeRecord *record)
{
    if (!record) return 0;
    if (record->mode == 0u) return record->size + 1u;
    if (record->mode == 1u) return record->size;
    if (record->mode == 2u) return record->size * 2u;
    return record->size + 4u;
}

static int bridge_run_is_supported(uint8_t count, uint8_t value)
{
    if (count == 0u) return 0;
    if (value == 0xffu && count > 64u) return 0;
    return 1;
}

int bridge_unpack_record(const BridgeRecord *record, uint8_t *out,
                         size_t output_limit)
{
    if (!record || !out) return -1;
    if (record->mode != 2u) return -1;
    if (record->size & 1u) return -1;
    size_t decoded = 0u;

    for (size_t i = 0; i < record->size; i += 2u) {
        uint8_t repeat = record->bytes[i];
        uint8_t value = record->bytes[i + 1u];
        if (!bridge_run_is_supported(repeat, value)) continue;
        if (decoded + repeat > output_limit) break;
        memset(out + decoded, value, repeat);
        decoded += repeat;
    }
    return (int)decoded;
}
