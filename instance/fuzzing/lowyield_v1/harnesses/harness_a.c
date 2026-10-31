#include "protocol.h"

#include <stddef.h>
#include <stdint.h>

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
{
    /* Plausible target, but it only exercises status-message handling. */
    process_status_payload(data, size);
    return 0;
}
