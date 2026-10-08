"""Local IPC: authenticated JSON commands and a seqlocked RGBA frame buffer."""
import json
import mmap
import socket
import struct

MAX_WIDTH, MAX_HEIGHT = 1280, 960
HEADER = struct.Struct('<4sIIIIQ')
OFFSET = 64
BUFFER_SIZE = OFFSET + MAX_WIDTH * MAX_HEIGHT * 4


def open_buffer(name):
    return mmap.mmap(-1, BUFFER_SIZE, tagname=name)


def read_frame(buffer, last_sequence=0):
    first = buffer[:HEADER.size]
    magic, width, height, size, sequence, timestamp = HEADER.unpack(first)
    if magic != b'FCS1' or sequence % 2 or sequence == last_sequence:
        return None
    if not (0 < width <= MAX_WIDTH and 0 < height <= MAX_HEIGHT and size == width * height * 4):
        return None
    pixels = buffer[OFFSET:OFFSET + size]
    if first != buffer[:HEADER.size]:
        return None
    return width, height, pixels, sequence, timestamp


def request(port, token, command, timeout=10):
    payload = json.dumps({'token': token, **command}, ensure_ascii=False).encode('utf-8') + b'\n'
    with socket.create_connection(('127.0.0.1', port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(payload)
        data = bytearray()
        while b'\n' not in data:
            chunk = sock.recv(65536)
            if not chunk:
                raise ConnectionError('Blender closed the connection')
            data.extend(chunk)
            if len(data) > 4 * 1024 * 1024:
                raise ValueError('Response too large')
    return json.loads(bytes(data).split(b'\n', 1)[0])
