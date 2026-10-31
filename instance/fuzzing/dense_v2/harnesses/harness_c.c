#include "dense.h"
#include <stddef.h>
#include <stdint.h>
#include <string.h>

// Exercise record-oriented APIs without assuming the application frame format.
int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
{
    if (!data || size < 2u) return 0;
    BridgeSession session;
    memset(&session, 0, sizeof(session));

    if ((data[0] & 1u) == 0u) {
        bridge_update(data + 1u, size - 1u, &session);
    } else {
        bridge_archive(data + 1u, size - 1u, &session);
    }
    return 0;
}
