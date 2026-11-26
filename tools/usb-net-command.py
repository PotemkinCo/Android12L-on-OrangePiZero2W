#!/usr/bin/env python3
"""Run a shell script on the experimental USB-only board control endpoint."""
import argparse
from pathlib import Path
import re
import secrets
import socket
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("script", type=Path)
    parser.add_argument("--board", default="192.168.246.2")
    parser.add_argument("--port", type=int, default=2323)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    token = secrets.token_hex(12)
    script = (b"(\nexec 2>&1\n" + args.script.read_bytes() +
              f"\n)\ntask_command_status=$?\nprintf '\\n__OPI_RESULT_{token}_%s__\\n' \"$task_command_status\"\n".encode())
    output = bytearray()
    with socket.create_connection((args.board, args.port), timeout=args.timeout) as connection:
        connection.sendall(script)
        connection.shutdown(socket.SHUT_WR)
        while chunk := connection.recv(65536):
            output.extend(chunk)
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
    result = re.search(rb"__OPI_RESULT_" + token.encode() + rb"_(\d+)__", output)
    if not result:
        raise RuntimeError("The board did not return a command completion status")
    raise SystemExit(int(result.group(1)))


if __name__ == "__main__":
    main()
