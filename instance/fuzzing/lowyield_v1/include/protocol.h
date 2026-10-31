#ifndef PROTOCOL_H
#define PROTOCOL_H

#include <stddef.h>
#include <stdint.h>

#define FRAME_HEADER_SIZE 10
#define FRAME_MAGIC_0 'N'
#define FRAME_MAGIC_1 'M'
#define FRAME_MAGIC_2 'S'
#define FRAME_MAGIC_3 'G'
#define FRAME_VERSION 1

#define MSG_STATUS 0x10
#define MSG_DATA   0x20
#define MSG_ADMIN  0x7f

#define ADMIN_VERSION 2
#define ADMIN_PRIVILEGE 0xd3
#define ADMIN_MODE_RLE 0x52
#define RECORD_TAG_ATTRIBUTE 0x42
#define RECORD_ENCODING_RLE  0x01

#define MAX_PAYLOAD 96
#define MAX_KEY_LEN 8
#define MAX_ENCODED_VALUE 24

typedef enum {
    PARSE_OK = 0,
    PARSE_SHORT,
    PARSE_MAGIC,
    PARSE_VERSION,
    PARSE_LENGTH,
    PARSE_CHECKSUM,
    PARSE_TYPE,
    PARSE_FORMAT,
    PARSE_AUTH,
    PARSE_RECORD
} ParseResult;

typedef struct {
    uint8_t version;
    uint8_t type;
    uint8_t flags;
    uint8_t channel;
    uint8_t nonce;
    const uint8_t *payload;
    size_t payload_len;
} Frame;

typedef struct {
    uint8_t tag;
    uint8_t encoding;
    const uint8_t *key;
    size_t key_len;
    const uint8_t *encoded;
    size_t encoded_len;
} ParsedRecord;

uint8_t frame_checksum(const uint8_t *header_without_checksum);
ParseResult parse_frame(const uint8_t *data, size_t size, Frame *out);
int process_frame(const uint8_t *data, size_t size);

int process_status_payload(const uint8_t *data, size_t size);
int process_data_payload(const uint8_t *data, size_t size);
int process_admin_frame(const Frame *frame);

ParseResult parse_attribute_record(const uint8_t *data, size_t size,
                                   ParsedRecord *out, size_t *consumed);
size_t record_storage_hint(const ParsedRecord *record);
size_t record_decode_value(const ParsedRecord *record, uint8_t *output);
int store_attribute_record(const ParsedRecord *record);

uint16_t read_be16(const uint8_t *p);
uint8_t rotate_left8(uint8_t value, unsigned amount);
uint8_t admin_session_token(uint8_t nonce, uint8_t channel);
int ascii_key_valid(const uint8_t *key, size_t len);

#endif
