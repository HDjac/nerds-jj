from pathlib import Path

root = Path("seed_base")
root.mkdir(exist_ok=True)


def checksum(header):
    acc = 0x91
    for b in header[4:9]:
        acc = ((acc << 1) | (acc >> 7)) & 0xff
        acc ^= b
        acc = (acc + 0x2d) & 0xff
    return acc

# Valid status frame. This teaches the fuzzer the outer framing format
# without giving it a valid administrative request.
payload = bytes([1, 4]) + b"PING"
header = bytearray(b"NMSG")
header += bytes([1, 0x10, 0x00, 0x01, len(payload), 0])
header[9] = checksum(header)
(root / "status-frame").write_bytes(header + payload)

# Useful lexical fragments, but neither is itself a valid frame.
(root / "auth-fragment").write_bytes(b"AUTH")
(root / "root-fragment").write_bytes(b"ROOT")
(root / "record-fragment").write_bytes(bytes([0x42, 0x01, 0x03, 0x04]) + b"key" + bytes([2, ord('A'), 2, ord('B')]))
