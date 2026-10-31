#include "dense.h"
#include <stddef.h>
#include <stdint.h>

// Full application interface: mutations must preserve framing and routing.
int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
{
    bridge_process(data, size);
    return 0;
}
