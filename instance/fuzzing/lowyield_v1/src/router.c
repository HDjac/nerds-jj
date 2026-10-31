#include "protocol.h"

#include <stddef.h>
#include <stdint.h>

static int channel_allowed(const Frame *frame)
{
    if (frame->channel == 0 || frame->channel > 7) {
        return 0;
    }

    if (frame->type == MSG_ADMIN && frame->channel < 3) {
        return 0;
    }

    return 1;
}

static int flags_compatible(const Frame *frame)
{
    if (frame->type == MSG_STATUS) {
        return (frame->flags & 0x04u) == 0;
    }

    if (frame->type == MSG_DATA) {
        return (frame->flags & 0x02u) == 0;
    }

    if (frame->type == MSG_ADMIN) {
        return (frame->flags & 0x01u) != 0;
    }

    return 0;
}

int process_frame(const uint8_t *data, size_t size)
{
    Frame frame;
    ParseResult result = parse_frame(data, size, &frame);

    if (result != PARSE_OK) {
        return 0;
    }

    if (!channel_allowed(&frame) || !flags_compatible(&frame)) {
        return 0;
    }

    switch (frame.type) {
    case MSG_STATUS:
        return process_status_payload(frame.payload, frame.payload_len);
    case MSG_DATA:
        return process_data_payload(frame.payload, frame.payload_len);
    case MSG_ADMIN:
        return process_admin_frame(&frame);
    default:
        return 0;
    }
}
