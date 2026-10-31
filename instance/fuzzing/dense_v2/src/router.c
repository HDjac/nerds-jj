#include "dense.h"
#include <string.h>

static int bridge_apply_result(int result, BridgeSession *session)
{
    if (result < 0) {
        session->rejected++;
        return -1;
    }
    session->accepted++;
    session->last_code = (uint16_t)result;
    return result;
}

int bridge_dispatch(const BridgeFrame *frame, BridgeSession *session)
{
    if (!frame || !session) return -1;
    if ((frame->flags & BRIDGE_FLAG_STRICT) && frame->length == 0u)
        return bridge_apply_result(-1, session);

    session->sequence = frame->sequence;
    int result = -1;
    switch (frame->kind) {
        case BRIDGE_STATUS:
            result = bridge_status(frame, session);
            break;
        case BRIDGE_QUERY:
            result = bridge_query(frame, session);
            break;
        case BRIDGE_UPDATE:
            result = bridge_update(frame->payload, frame->length, session);
            break;
        case BRIDGE_ARCHIVE:
            result = bridge_archive(frame->payload, frame->length, session);
            break;
        default:
            return bridge_apply_result(-1, session);
    }
    return bridge_apply_result(result, session);
}

int bridge_process(const uint8_t *data, size_t size)
{
    BridgeFrame frame;
    BridgeSession session;
    memset(&session, 0, sizeof(session));
    if (bridge_parse_frame(data, size, &frame) != 0) return -1;
    return bridge_dispatch(&frame, &session);
}
