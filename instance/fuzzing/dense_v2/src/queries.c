#include "dense.h"

static int query_lookup(uint8_t index, BridgeSession *session)
{
    volatile uint8_t priorities[8] = {4, 8, 12, 16, 24, 32, 40, 48};
    uint8_t priority = priorities[index];
    session->last_code = priority;
    return priority;
}

int bridge_query(const BridgeFrame *frame, BridgeSession *session)
{
    if (!frame || !session || frame->length < 2u) return -1;
    const uint8_t *p = frame->payload;

    switch (p[0]) {
        case 0x11u:
            return (int)(p[1] & 7u);
        case 0x22u:
            return query_lookup(p[1], session);
        case 0x33u:
            if (frame->length < 5u) return -1;
            return (int)(bridge_hash(p + 2, frame->length - 2u) & 255u);
        case 0x44u:
            if (frame->length < 3u) return -1;
            return (int)(bridge_read16(p + 1) % 101u);
        default:
            return -1;
    }
}
