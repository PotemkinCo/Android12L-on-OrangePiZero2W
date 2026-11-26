/* SPDX-License-Identifier: MIT
 * Direct filesystem I/O benchmark for the disposable laptop-backed test image.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

static double now(void) {
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t)) { perror("clock"); exit(1); }
    return t.tv_sec + t.tv_nsec / 1e9;
}
static void fail(const char *what) { perror(what); exit(1); }
static void io(int fd, void *buffer, size_t length, off_t offset, int write_op) {
    ssize_t n;
    do { n = write_op ? pwrite(fd, buffer, length, offset) : pread(fd, buffer, length, offset); }
    while (n < 0 && errno == EINTR);
    if (n != (ssize_t)length) fail(write_op ? "pwrite" : "pread");
}
int main(int argc, char **argv) {
    if (argc != 2 || strncmp(argv[1], "/data/local/tmp/opi-storage-benchmark/", 38)) return 2;
    alarm(60);
    void *buffer;
    if (posix_memalign(&buffer, 4096, 131072)) return 1;
    memset(buffer, 0x5a, 131072);
    int fd = open(argv[1], O_CREAT | O_EXCL | O_RDWR | O_DIRECT | O_NOFOLLOW, 0600);
    if (fd < 0) fail("open test file O_DIRECT");
    double start = now();
    for (int i = 0; i < 128; i++) io(fd, buffer, 131072, (off_t)i * 131072, 1);
    if (fsync(fd)) fail("fsync");
    double writes = now() - start;
    start = now();
    for (int i = 0; i < 128; i++) io(fd, buffer, 131072, (off_t)i * 131072, 0);
    double reads = now() - start;
    uint32_t random = 0x12345678;
    start = now();
    for (int i = 0; i < 1024; i++) {
        random ^= random << 13; random ^= random >> 17; random ^= random << 5;
        io(fd, buffer, 4096, (off_t)(random % 4096) * 4096, 0);
    }
    double random_reads = now() - start;
    start = now();
    for (int i = 0; i < 256; i++) {
        random ^= random << 13; random ^= random >> 17; random ^= random << 5;
        io(fd, buffer, 4096, (off_t)(random % 4096) * 4096, 1);
        if (fsync(fd)) fail("synchronous random write");
    }
    double random_writes = now() - start;
    printf("{\"sequential_write_MiB_s\":%.2f,\"sequential_read_MiB_s\":%.2f,"
           "\"random_4K_read_iops\":%.1f,\"random_4K_read_ms\":%.3f,"
           "\"random_4K_fsync_write_iops\":%.1f,\"random_4K_fsync_write_ms\":%.3f,"
           "\"direct_io\":true,\"test_file_MiB\":16}\n",
           16 / writes, 16 / reads, 1024 / random_reads, random_reads * 1000 / 1024,
           256 / random_writes, random_writes * 1000 / 256);
    close(fd); free(buffer);
    return 0;
}
