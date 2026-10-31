#include "protocol.h"

#include <stddef.h>
#include <stdint.h>

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
{
    /* Full binary frame path with no input transformation. */
    process_frame(data, size);
    return 0;
}
