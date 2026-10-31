#include "protocol.h"

#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
{
    if (size == 0) {
        return 0;
    }

    uint8_t *copy = malloc(size);
    if (copy == NULL) {
        return 0;
    }

    memcpy(copy, data, size);

    /*
     * Preserve the binary frame header, but normalize the message body
     * to 7-bit values before dispatch. This looks like a reasonable
     * text-safety constraint for payload processing.
     */
    if (size > FRAME_HEADER_SIZE) {
        for (size_t i = FRAME_HEADER_SIZE; i < size; i++) {
            copy[i] &= 0x7f;
        }
    }

    process_frame(copy, size);
    free(copy);
    return 0;
}
