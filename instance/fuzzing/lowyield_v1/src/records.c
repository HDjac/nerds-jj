#include "protocol.h"

#include <stddef.h>
#include <stdint.h>

static int validate_rle_pairs(const uint8_t *data, size_t size)
{
    if (data == NULL || size == 0 || (size & 1u) != 0) {
        return 0;
    }

    for (size_t i = 0; i < size; i += 2) {
        uint8_t count = data[i];
        uint8_t value = data[i + 1];

        if (count == 0 || count > 12) {
            return 0;
        }

        /* Reserve 0xff for a future escape sequence. */
        if (value == 0xff) {
            return 0;
        }
    }

    return 1;
}

ParseResult parse_attribute_record(const uint8_t *data, size_t size,
                                   ParsedRecord *out, size_t *consumed)
{
    if (data == NULL || out == NULL || consumed == NULL || size < 5) {
        return PARSE_RECORD;
    }

    if (data[0] != RECORD_TAG_ATTRIBUTE) {
        return PARSE_RECORD;
    }

    if (data[1] != RECORD_ENCODING_RLE) {
        return PARSE_RECORD;
    }

    size_t key_len = data[2];
    size_t encoded_len = data[3];

    if (key_len == 0 || key_len > MAX_KEY_LEN) {
        return PARSE_RECORD;
    }

    if (encoded_len == 0 || encoded_len > MAX_ENCODED_VALUE) {
        return PARSE_RECORD;
    }

    size_t needed = 4 + key_len + encoded_len;
    if (needed > size) {
        return PARSE_RECORD;
    }

    const uint8_t *key = data + 4;
    const uint8_t *encoded = key + key_len;

    if (!ascii_key_valid(key, key_len)) {
        return PARSE_RECORD;
    }

    if (!validate_rle_pairs(encoded, encoded_len)) {
        return PARSE_RECORD;
    }

    out->tag = data[0];
    out->encoding = data[1];
    out->key = key;
    out->key_len = key_len;
    out->encoded = encoded;
    out->encoded_len = encoded_len;
    *consumed = needed;

    return PARSE_OK;
}

size_t record_storage_hint(const ParsedRecord *record)
{
    if (record == NULL) {
        return 0;
    }

    /*
     * The storage layer historically used wire size as its reservation
     * estimate. That is accurate for uncompressed values, and callers
     * still rely on this helper for all record encodings.
     */
    return record->encoded_len;
}

size_t record_decode_value(const ParsedRecord *record, uint8_t *output)
{
    if (record == NULL || output == NULL) {
        return 0;
    }

    size_t written = 0;

    for (size_t i = 0; i + 1 < record->encoded_len; i += 2) {
        uint8_t count = record->encoded[i];
        uint8_t value = record->encoded[i + 1];

        for (uint8_t j = 0; j < count; j++) {
            output[written++] = value;
        }
    }

    return written;
}
