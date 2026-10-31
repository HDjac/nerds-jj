#include "protocol.h"

#include <stddef.h>
#include <stdint.h>

static uint16_t rolling_sum(const uint8_t *data, size_t size)
{
    uint16_t total = 0;

    for (size_t i = 0; i < size; i++) {
        total = (uint16_t)(total + data[i]);
        total = (uint16_t)((total << 1) | (total >> 15));
    }

    return total;
}

int process_data_payload(const uint8_t *data, size_t size)
{
    if (data == NULL || size < 4) {
        return 0;
    }

    uint8_t format = data[0];
    uint8_t declared = data[1];

    if (format != 1 && format != 2) {
        return 0;
    }

    if ((size_t)declared + 2 > size) {
        return 0;
    }

    volatile uint16_t summary = rolling_sum(data + 2, declared);
    (void)summary;

    return 1;
}
