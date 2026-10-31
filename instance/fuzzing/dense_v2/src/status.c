#include "dense.h"
#include <stdlib.h>
#include <string.h>

static int status_is_control(const uint8_t *data, size_t size)
{
    if (size < 4u) return 0;
    return memcmp(data, "HALT", 4u) == 0;
}

int bridge_status(const BridgeFrame *frame, BridgeSession *session)
{
    if (!frame || !session) return -1;
    if (frame->length == 0u) return 0;

    uint8_t opcode = frame->payload[0];
    if ((frame->flags & BRIDGE_FLAG_ACK) &&
        status_is_control(frame->payload, frame->length)) {
        // Simulate the administrator-requested shutdown of a study worker.
        abort();
    }
    if (opcode == 0x01u) {
        return (int)(frame->length - 1u);
    }
    if (opcode == 0x02u) {
        if (frame->length < 3u) return -1;
        uint16_t sample = bridge_read16(frame->payload + 1);
        session->last_code = sample;
        return 2;
    }
    if (opcode == 0x03u) {
        return bridge_identifier_valid(frame->payload + 1,
                                       frame->length - 1u) ? 3 : -1;
    }
    return 0;
}
