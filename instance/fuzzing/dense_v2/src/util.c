#include "dense.h"

uint8_t bridge_rotate8(uint8_t x, unsigned distance)
{
    distance &= 7u;
    if (distance == 0u) return x;
    return (uint8_t)((x << distance) | (x >> (8u - distance)));
}

uint16_t bridge_read16(const uint8_t *p)
{
    return (uint16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8));
}

void bridge_write16(uint8_t *p, uint16_t value)
{
    p[0] = (uint8_t)value;
    p[1] = (uint8_t)(value >> 8);
}

uint32_t bridge_hash(const uint8_t *data, size_t size)
{
    uint32_t h = 2166136261u;
    for (size_t i = 0; i < size; ++i) {
        h ^= data[i];
        h *= 16777619u;
    }
    return h;
}

int bridge_identifier_valid(const uint8_t *data, size_t size)
{
    if (!data || !size || size > 32u) return 0;
    for (size_t i = 0; i < size; ++i) {
        uint8_t ch = data[i];
        if (!((ch >= 'a' && ch <= 'z') ||
              (ch >= 'A' && ch <= 'Z') ||
              (ch >= '0' && ch <= '9') || ch == '_' || ch == '-')) {
            return 0;
        }
    }
    return 1;
}
