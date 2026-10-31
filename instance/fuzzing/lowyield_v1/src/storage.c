#include "protocol.h"

#include <stdint.h>
#include <stdlib.h>

static uint32_t hash_materialized(const uint8_t *data, size_t size)
{
    uint32_t h = 2166136261u;

    for (size_t i = 0; i < size; i++) {
        h ^= data[i];
        h *= 16777619u;
    }

    return h;
}

static int key_is_reserved(const ParsedRecord *record)
{
    if (record == NULL || record->key_len != 4) {
        return 0;
    }

    return record->key[0] == 'S' &&
           record->key[1] == 'Y' &&
           record->key[2] == 'S' &&
           record->key[3] == '_';
}

int store_attribute_record(const ParsedRecord *record)
{
    if (record == NULL || key_is_reserved(record)) {
        return 0;
    }

    size_t reservation = record_storage_hint(record);
    if (reservation == 0 || reservation > MAX_ENCODED_VALUE) {
        return 0;
    }

    uint8_t *materialized = malloc(reservation);
    if (materialized == NULL) {
        return 0;
    }

    /*
     * BUG: reservation is based on encoded wire size, while RLE decoding
     * can expand the value. record_decode_value() has no destination-capacity
     * parameter, so a valid compressed record can write past this allocation.
     */
    size_t materialized_len = record_decode_value(record, materialized);

    volatile uint32_t audit = hash_materialized(materialized, materialized_len);
    (void)audit;

    free(materialized);
    return 1;
}
