#ifndef DENSE_H
#define DENSE_H

#include <stddef.h>
#include <stdint.h>

#define BRIDGE_HEADER_SIZE 12u
#define BRIDGE_MAX_PAYLOAD 192u
#define BRIDGE_STATUS  0x10u
#define BRIDGE_QUERY   0x20u
#define BRIDGE_UPDATE  0x30u
#define BRIDGE_ARCHIVE 0x40u

#define BRIDGE_FLAG_STRICT 0x01u
#define BRIDGE_FLAG_TRACE  0x02u
#define BRIDGE_FLAG_PACKED 0x04u
#define BRIDGE_FLAG_ACK    0x08u

typedef struct {
    uint8_t kind;
    uint8_t flags;
    uint8_t sequence;
    const uint8_t *payload;
    size_t length;
} BridgeFrame;

typedef struct {
    uint8_t tag;
    uint8_t mode;
    const uint8_t *bytes;
    size_t size;
} BridgeRecord;

typedef struct {
    uint32_t accepted;
    uint32_t rejected;
    uint32_t sequence;
    uint16_t last_code;
} BridgeSession;

uint8_t bridge_rotate8(uint8_t x, unsigned distance);
uint16_t bridge_read16(const uint8_t *p);
void bridge_write16(uint8_t *p, uint16_t value);
uint8_t bridge_checksum(const uint8_t *header);
size_t bridge_make_frame(uint8_t *dest, size_t cap, uint8_t kind,
                         uint8_t flags, uint8_t sequence,
                         const uint8_t *payload, size_t payload_size);

int bridge_parse_frame(const uint8_t *data, size_t size, BridgeFrame *out);
int bridge_dispatch(const BridgeFrame *frame, BridgeSession *session);
int bridge_process(const uint8_t *data, size_t size);

int bridge_status(const BridgeFrame *frame, BridgeSession *session);
int bridge_query(const BridgeFrame *frame, BridgeSession *session);
int bridge_update(const uint8_t *data, size_t size, BridgeSession *session);
int bridge_archive(const uint8_t *data, size_t size, BridgeSession *session);

int bridge_parse_record(const uint8_t *data, size_t size,
                        BridgeRecord *record, size_t *consumed);
int bridge_check_record(const BridgeRecord *record);
int bridge_store_attribute(const BridgeRecord *record, BridgeSession *session);
int bridge_expand_archive(const BridgeRecord *record, BridgeSession *session);
size_t bridge_encoded_budget(const BridgeRecord *record);
int bridge_unpack_record(const BridgeRecord *record, uint8_t *out,
                         size_t output_limit);

int bridge_log_preview(const uint8_t *data, size_t size);
int bridge_identifier_valid(const uint8_t *data, size_t size);
uint32_t bridge_hash(const uint8_t *data, size_t size);
#endif
