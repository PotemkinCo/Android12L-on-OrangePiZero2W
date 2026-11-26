/* SPDX-License-Identifier: MIT
 * Volatile H616 watchdog control for bounded USB boot diagnostics.
 */
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include <time.h>

int main(int argc, char **argv) {
    int guarding = argc == 3 && !strcmp(argv[1], "--guard");
    unsigned guard_seconds = 0;
    if (guarding) {
        char *end;
        unsigned long seconds = strtoul(argv[2], &end, 10);
        if (*end || seconds < 1 || seconds > 600) return 2;
        guard_seconds = (unsigned)seconds;
    }
    if (!guarding && (argc != 2 || (strcmp(argv[1], "--read") &&
                     strcmp(argv[1], "--arm") && strcmp(argv[1], "--kick") && strcmp(argv[1], "--stop")))) {
        fprintf(stderr, "Usage: %s --read|--arm|--kick|--stop|--guard SECONDS\n", argv[0]);
        return 2;
    }
    int writing = strcmp(argv[1], "--read") != 0;
    int fd = open("/dev/mem", (writing ? O_RDWR : O_RDONLY) | O_SYNC | O_CLOEXEC);
    if (fd < 0) { perror("open /dev/mem"); return 1; }
    volatile uint32_t *base = mmap(NULL, 4096, PROT_READ | (writing ? PROT_WRITE : 0),
                                   MAP_SHARED, fd, 0x03009000);
    close(fd);
    if (base == MAP_FAILED) { perror("map watchdog MMIO"); return 1; }
    uint32_t mode = base[0xb8 / 4];
    if (!strcmp(argv[1], "--arm")) {
        base[0xb4 / 4] = 0x16aa0001;
        base[0xb8 / 4] = 0x16aa00b1;
        base[0xb0 / 4] = 0x14af;
    }
    if (guarding) {
        struct timespec started, now, interval = {.tv_sec = 2};
        if (clock_gettime(CLOCK_MONOTONIC, &started)) return 1;
        while (base[0xb8 / 4] & 1U) {
            if (clock_gettime(CLOCK_MONOTONIC, &now)) return 1;
            if (now.tv_sec - started.tv_sec >= guard_seconds) break;
            base[0xb0 / 4] = 0x14af;
            __sync_synchronize();
            nanosleep(&interval, NULL);
        }
        printf("H616 watchdog guard finished; mode=0x%08x\n", base[0xb8 / 4]);
        munmap((void *)base, 4096);
        return 0;
    }
    if (!strcmp(argv[1], "--kick")) base[0xb0 / 4] = 0x14af;
    if (!strcmp(argv[1], "--stop")) base[0xb8 / 4] = (mode & ~1U) | 0x16aa0000;
    __sync_synchronize();
    uint32_t result = base[0xb8 / 4];
    printf("H616 watchdog mode=0x%08x enabled=%u\n", result, result & 1U);
    munmap((void *)base, 4096);
    if (!strcmp(argv[1], "--stop")) return (result & 1U) ? 1 : 0;
    if (!strcmp(argv[1], "--arm")) return (result & 0xf1U) == 0xb1U ? 0 : 1;
    return 0;
}
