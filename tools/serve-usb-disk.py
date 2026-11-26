#!/usr/bin/env python3
"""Serve a regular disk-image file to the Orange Pi over its USB network link.

The laptop initiates the connection. No laptop NBD kernel driver, raw disk
access, inbound network listener, root privilege, or Linux-only API is used.
"""
import argparse
from collections import Counter
import errno
import fcntl
import json
import os
from pathlib import Path
import socket
import stat
import struct
import sys
import time

REQUEST = struct.Struct(">II8sQI")
REPLY = struct.Struct(">II8s")
MAX_REQUEST = 8 * 1024 * 1024


def receive(connection, length):
    data = bytearray()
    while len(data) < length:
        chunk = connection.recv(length - len(data))
        if not chunk:
            raise EOFError("Board closed the disk connection")
        data.extend(chunk)
    return data


def connect(host, port, wait, source_address):
    deadline = time.monotonic() + wait
    while True:
        try:
            return socket.create_connection((host, port), timeout=2,
                                            source_address=(source_address, 0) if source_address else None)
        except OSError as error:
            if time.monotonic() >= deadline or (not isinstance(error, TimeoutError) and error.errno not in (
                    errno.ECONNREFUSED, errno.ENETUNREACH, errno.EHOSTUNREACH,
                    errno.ETIMEDOUT, errno.EADDRNOTAVAIL)):
                raise
            time.sleep(.5)


def serve(image, host, port, wait=0, source_address=None, progress_seconds=0, trace_requests=0):
    fd = os.open(image, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size < 512 or info.st_size % 512:
            raise ValueError("Image must be an existing regular file with a nonzero, sector-aligned size")
        counts = Counter()
        request_number = 0
        next_progress = time.monotonic() + progress_seconds
        with connect(host, port, wait, source_address) as connection:
            # A mounted disk may legitimately be idle for hours. The board's
            # NBD driver times out outstanding I/O, rather than idle sockets.
            connection.settimeout(None)
            # Standard old-style NBD handshake; our board-side attachment
            # intentionally accepts only this bounded, single-image variant.
            connection.sendall(struct.pack(">QQQI124x", 0x4E42444D41474943, 0x420281861253, info.st_size, 5))
            print(json.dumps({"status": "connected", "image": str(image), "bytes": info.st_size, "board": host}), flush=True)
            try:
                while True:
                    magic, operation, handle, offset, length = REQUEST.unpack(receive(connection, REQUEST.size))
                    if magic != 0x25609513 or length > MAX_REQUEST:
                        raise ValueError("Invalid or oversized disk request")
                    command, flags = operation & 0xFFFF, operation >> 16
                    if command == 2:  # NBD_CMD_DISC has no reply.
                        break
                    payload = receive(connection, length) if command == 1 else None
                    error, result = 0, b""
                    try:
                        if flags:
                            raise OSError(errno.EOPNOTSUPP, "Unadvertised request flags")
                        if offset > info.st_size or length > info.st_size - offset:
                            raise OSError(errno.EINVAL, "Request outside image")
                        if command == 0:
                            result = os.pread(fd, length, offset)
                            if len(result) != length:
                                raise OSError(errno.EIO, "Short image read")
                            counts["read_bytes"] += length
                        elif command == 1:
                            written = 0
                            while written < length:
                                n = os.pwrite(fd, payload[written:], offset + written)
                                if not n:
                                    raise OSError(errno.EIO, "Short image write")
                                written += n
                            counts["write_bytes"] += length
                        elif command == 3 and length == 0:
                            os.fsync(fd)
                        else:
                            raise OSError(errno.EOPNOTSUPP, "Unsupported disk operation")
                        counts[{0: "reads", 1: "writes", 3: "flushes"}[command]] += 1
                    except OSError as failure:
                        error, result = failure.errno or errno.EIO, b""
                        counts["errors"] += 1
                    connection.sendall(REPLY.pack(0x67446698, error, handle) + result)
                    request_number += 1
                    if request_number <= trace_requests:
                        print(json.dumps({"status": "request", "number": request_number,
                                          "operation": command, "offset": offset,
                                          "bytes": length, "error": error}), flush=True)
                    if progress_seconds and time.monotonic() >= next_progress:
                        print(json.dumps({"status": "progress", "counts": dict(counts)}), flush=True)
                        next_progress = time.monotonic() + progress_seconds
            except EOFError:
                pass
            finally:
                os.fsync(fd)
                print(json.dumps({"status": "closed", "counts": dict(counts)}), flush=True)
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--board", default="192.168.246.2")
    parser.add_argument("--port", type=int, default=10809)
    parser.add_argument("--wait", type=float, default=0, help="seconds to retry only the initial connection")
    parser.add_argument("--host-address", default="192.168.246.1", help="bind outgoing USB traffic to this local address")
    parser.add_argument("--progress-seconds", type=float, default=10, help="report active request counts (default 10 seconds); zero disables")
    parser.add_argument("--trace-requests", type=int, default=0, help="log metadata for this many initial requests")
    parser.add_argument("--instance-token", help="runtime ownership token for safe portable shutdown")
    args = parser.parse_args()
    if not 0 <= args.wait <= 3600:
        parser.error('--wait must be between zero and 3600 seconds')
    if not 0 <= args.progress_seconds <= 3600 or not 0 <= args.trace_requests <= 1000:
        parser.error('invalid progress interval or request count')
    if args.instance_token is not None and (len(args.instance_token) != 32
            or any(c not in '0123456789abcdef' for c in args.instance_token)):
        parser.error('invalid runtime instance token')
    serve(args.image, args.board, args.port, args.wait, args.host_address,
          args.progress_seconds, args.trace_requests)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as failure:
        print(str(failure), file=sys.stderr)
        raise SystemExit(1)
