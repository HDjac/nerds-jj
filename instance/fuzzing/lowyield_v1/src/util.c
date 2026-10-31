#include "protocol.h"

#include <ctype.h>

uint16_t read_be16(const uint8_t *p)
{
    return (uint16_t)(((uint16_t)p[0] << 8) | p[1]);
}

uint8_t rotate_left8(uint8_t value, unsigned amount)
{
    amount &= 7u;
    if (amount == 0) {
        return value;
    }
    return (uint8_t)((value << amount) | (value >> (8u - amount)));
}

uint8_t admin_session_token(uint8_t nonce, uint8_t channel)
{
    uint8_t mixed = (uint8_t)(nonce ^ 0x5a);
    mixed = rotate_left8(mixed, 3);
    mixed = (uint8_t)(mixed + (uint8_t)(channel * 17u));
    return (uint8_t)(mixed ^ 0xc7);
}

int ascii_key_valid(const uint8_t *key, size_t len)
{
    if (key == NULL || len == 0 || len > MAX_KEY_LEN) {
        return 0;
    }

    for (size_t i = 0; i < len; i++) {
        unsigned char c = key[i];
        if (!(isalnum(c) || c == '_' || c == '-')) {
            return 0;
        }
    }

    return 1;
}
