#include "dense.h"
#include <string.h>

int bridge_log_preview(const uint8_t *data, size_t size)
{
    if (!data || size == 0u) return 0;
    char fragment[12];
    size_t requested = size;
    if (requested > sizeof(fragment) - 1u) {
        requested = sizeof(fragment) - 1u;
    }
    memcpy(fragment, data, requested);
    fragment[requested] = '\0';
    return (int)requested;
}
