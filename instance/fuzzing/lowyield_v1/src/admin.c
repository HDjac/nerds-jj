#include "protocol.h"

#include <stddef.h>
#include <stdint.h>

static int matches4(const uint8_t *p, char a, char b, char c, char d)
{
    return p[0] == (uint8_t)a && p[1] == (uint8_t)b &&
           p[2] == (uint8_t)c && p[3] == (uint8_t)d;
}

static int validate_admin_prefix(const Frame *frame)
{
    const uint8_t *p = frame->payload;

    if (frame->payload_len < 18) {
        return 0;
    }

    if (!matches4(p, 'A', 'U', 'T', 'H')) {
        return 0;
    }

    if (p[4] != ADMIN_VERSION) {
        return 0;
    }

    if (p[5] != ADMIN_PRIVILEGE) {
        return 0;
    }

    if (p[6] != 'I' || p[7] != 'M') {
        return 0;
    }

    if (!matches4(p + 8, 'R', 'O', 'O', 'T')) {
        return 0;
    }

    if (p[12] != ADMIN_MODE_RLE) {
        return 0;
    }

    uint8_t expected = admin_session_token(frame->nonce, frame->channel);
    if (p[13] != expected) {
        return 0;
    }

    return 1;
}

static int process_import_records(const uint8_t *data, size_t size)
{
    if (size < 4) {
        return 0;
    }

    uint8_t record_count = data[0];
    uint16_t section_len = read_be16(data + 1);
    uint8_t trailer = data[3];

    if (record_count != 1) {
        return 0;
    }

    if (section_len < 8 || (size_t)section_len + 4 > size) {
        return 0;
    }

    if (trailer != (uint8_t)(record_count ^ 0x6b)) {
        return 0;
    }

    ParsedRecord record;
    size_t consumed = 0;

    ParseResult result = parse_attribute_record(data + 4, section_len,
                                                &record, &consumed);
    if (result != PARSE_OK) {
        return 0;
    }

    if (consumed != section_len) {
        return 0;
    }

    return store_attribute_record(&record);
}

int process_admin_frame(const Frame *frame)
{
    if (frame == NULL || !validate_admin_prefix(frame)) {
        return 0;
    }

    const uint8_t *payload = frame->payload;
    size_t payload_len = frame->payload_len;

    /* Bytes 14..15 are a compact request identifier. */
    uint16_t request_id = read_be16(payload + 14);
    if ((request_id & 0x0f00u) != 0x0500u) {
        return 0;
    }

    uint8_t guard = payload[16];
    if (guard != (uint8_t)((request_id & 0xffu) ^ 0xa6u)) {
        return 0;
    }

    uint8_t reserved = payload[17];
    if (reserved != 0) {
        return 0;
    }

    return process_import_records(payload + 18, payload_len - 18);
}
