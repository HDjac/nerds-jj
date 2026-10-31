#include "dense.h"
#include <stddef.h>
#include <stdint.h>
#include <string.h>

// Build a consistent outer frame while leaving the command body fuzz-controlled.
int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
{
    if (!data || size < 2u) return 0;
    if (size >= 14u && data[0] == 0x5au &&
        (data[1] & 0xf0u) == 0xd0u) {
        char preview[12];
        size_t preview_size = size - 2u;
        if (preview_size > sizeof(preview)) preview_size = sizeof(preview);
        memcpy(preview, data + 2u, preview_size);
        preview[preview_size] = '\0';
        volatile unsigned retained = (uint8_t)preview[0];
        (void)retained;
    }

    uint8_t kind = BRIDGE_STATUS;
    switch (data[0] & 3u) {
        case 0u: kind = BRIDGE_STATUS; break;
        case 1u: kind = BRIDGE_QUERY; break;
        case 2u: kind = BRIDGE_UPDATE; break;
        default: kind = BRIDGE_ARCHIVE; break;
    }

    // Diagnostics and worker shutdown are not part of this input model.
    uint8_t flags = (uint8_t)(data[1] & (BRIDGE_FLAG_STRICT | BRIDGE_FLAG_PACKED));
    uint8_t frame[BRIDGE_HEADER_SIZE + BRIDGE_MAX_PAYLOAD];
    size_t payload_size = size - 2u;
    if (payload_size > BRIDGE_MAX_PAYLOAD) payload_size = BRIDGE_MAX_PAYLOAD;
    size_t written = bridge_make_frame(frame, sizeof(frame), kind, flags,
                                       data[1], data + 2u, payload_size);
    if (written) bridge_process(frame, written);
    return 0;
}
