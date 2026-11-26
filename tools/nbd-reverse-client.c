/* SPDX-License-Identifier: MIT
 * Board-side NBD attachment. The laptop connects outward to the board, so
 * no inbound firewall exception or kernel NBD driver is needed on the laptop.
 */
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/nbd.h>
#include <linux/fs.h>
#include <netinet/in.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <sys/sysmacros.h>
#include <dirent.h>
#include <glob.h>
#include <unistd.h>
#include <sys/time.h>

static int trace_fd = -1;
static void trace(const char *what) {
    printf("NBD_STAGE %s\n", what);
    if (trace_fd >= 0) dprintf(trace_fd, "<6>opi-nbd: %s\n", what);
}
static void fail(const char *what) {
    int saved = errno;
    if (trace_fd >= 0) dprintf(trace_fd, "<3>opi-nbd: %s: %s\n", what, strerror(saved));
    errno = saved; perror(what); exit(1);
}
static void protect_disk_client(void) {
    int fd = open("/proc/self/oom_score_adj", O_WRONLY | O_CLOEXEC);
    if (fd < 0) fail("open oom_score_adj");
    const char value[] = "-1000\n";
    ssize_t written;
    do { written = write(fd, value, sizeof(value) - 1); } while (written < 0 && errno == EINTR);
    if (written != sizeof(value) - 1) {
        if (written >= 0) errno = EIO;
        fail("protect root-disk client from OOM");
    }
    close(fd);
    trace("root-disk client oom_score_adj=-1000");
}
static int traced_ioctl(int fd, unsigned long request, unsigned long arg, const char *name) {
    trace(name);
    int result = ioctl(fd, request, arg), saved = errno;
    printf("NBD_IOCTL_DONE %s result=%d errno=%d\n", name, result, result ? saved : 0);
    if (trace_fd >= 0) dprintf(trace_fd, "<6>opi-nbd: %s result=%d errno=%d\n", name, result, result ? saved : 0);
    errno = saved;
    return result;
}
static int idle_disconnect(void) {
    FILE *mounts = fopen("/proc/self/mountinfo", "r");
    if (!mounts) fail("mountinfo");
    char *line = NULL; size_t capacity = 0; unsigned major_number, minor_number;
    while (getline(&line, &capacity, mounts) >= 0) {
        if (sscanf(line, "%*u %*u %u:%u", &major_number, &minor_number) == 2 && major_number == 43) {
            fprintf(stderr, "Refusing to disconnect a mounted NBD device\n"); return 1;
        }
    }
    free(line); fclose(mounts);
    glob_t paths = {0};
    if (glob("/sys/class/block/nbd0*/holders", 0, NULL, &paths)) return 1;
    for (size_t i = 0; i < paths.gl_pathc; i++) {
        DIR *dir = opendir(paths.gl_pathv[i]);
        if (!dir) return 1;
        struct dirent *entry;
        while ((entry = readdir(dir))) if (entry->d_name[0] != '.') {
            fprintf(stderr, "Refusing to disconnect NBD with device-mapper/other holders\n"); return 1;
        }
        closedir(dir);
    }
    globfree(&paths);
    int fd = open("/dev/nbd0", O_RDWR | O_CLOEXEC);
    if (fd < 0) fail("open /dev/nbd0");
    int result = traced_ioctl(fd, NBD_DISCONNECT, 0UL, "NBD_DISCONNECT");
    close(fd); return result ? 1 : 0;
}
static uint64_t be64(const unsigned char *p) {
    uint64_t v = 0;
    for (int i = 0; i < 8; i++) v = (v << 8) | p[i];
    return v;
}
static int read_all(int fd, void *buf, size_t len) {
    unsigned char *p = buf;
    while (len) {
        ssize_t n = read(fd, p, len);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return -1;
        p += n; len -= (size_t)n;
    }
    return 0;
}
int main(int argc, char **argv) {
    setvbuf(stdout, NULL, _IOLBF, 0);
    if (getenv("OPI_NBD_LOG_KMSG")) trace_fd = open("/dev/kmsg", O_WRONLY | O_CLOEXEC | O_NONBLOCK);
    if (argc == 2 && !strcmp(argv[1], "--disconnect")) return idle_disconnect();
    if (argc != 4) {
        fprintf(stderr, "Usage: %s BOARD_USB_IP PORT USB_INTERFACE\n", argv[0]);
        return 2;
    }
    protect_disk_client();
    char *end;
    long port = strtol(argv[2], &end, 10);
    if (*end || port < 1024 || port > 65535) return 2;
    struct sockaddr_in address = {.sin_family = AF_INET, .sin_port = htons((uint16_t)port)};
    if (inet_pton(AF_INET, argv[1], &address.sin_addr) != 1) return 2;
    int listener = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0), yes = 1;
    if (listener < 0) fail("socket");
    if (setsockopt(listener, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes))) fail("SO_REUSEADDR");
    if (setsockopt(listener, SOL_SOCKET, SO_BINDTODEVICE, argv[3], strlen(argv[3]) + 1)) fail("SO_BINDTODEVICE");
    if (bind(listener, (struct sockaddr *)&address, sizeof(address))) fail("bind USB address");
    if (listen(listener, 1)) fail("listen");
    printf("Waiting for laptop disk server at %s:%ld\n", argv[1], port); fflush(stdout);
    unsigned char greeting[152];
    int network;
    uint64_t size;
    uint32_t flags;
    for (;;) {
        network = accept(listener, NULL, NULL);
        if (network < 0 && errno == EINTR) continue;
        if (network < 0) fail("accept");
        struct timeval bounded = {.tv_sec = 5};
        if (setsockopt(network, SOL_SOCKET, SO_RCVTIMEO, &bounded, sizeof(bounded))) fail("greeting timeout");
        /* Android uses its ADB port to exempt infrastructure from VPN socket
         * destruction. During bootstrap we own that listener; after accepting
         * the disk connection, close it so adbd can bind the same port. Reject
         * eager ADB reconnects before consuming the rest of an NBD greeting.
         */
        if (read_all(network, greeting, 8) || be64(greeting) != UINT64_C(0x4e42444d41474943)
                || read_all(network, greeting + 8, sizeof(greeting) - 8)) {
            trace("ignored non-NBD or incomplete USB peer before disk attachment");
            close(network); continue;
        }
        size = be64(greeting + 16);
        flags = ((uint32_t)greeting[24] << 24) | ((uint32_t)greeting[25] << 16)
              | ((uint32_t)greeting[26] << 8) | greeting[27];
        if (be64(greeting + 8) != UINT64_C(0x420281861253) || size < 512 || size % 512
                || size > (UINT64_C(1) << 42) || flags != (NBD_FLAG_HAS_FLAGS | NBD_FLAG_SEND_FLUSH)) {
            trace("ignored unsupported NBD greeting"); close(network); continue;
        }
        struct timeval unlimited = {0};
        if (setsockopt(network, SOL_SOCKET, SO_RCVTIMEO, &unlimited, sizeof(unlimited))) fail("clear greeting timeout");
        break;
    }
    close(listener);
    trace("greeting received");
    trace("opening /dev/nbd0");
    int block = open("/dev/nbd0", O_RDWR | O_CLOEXEC);
    if (block < 0) fail("open /dev/nbd0");
    trace("opened /dev/nbd0");
    if (traced_ioctl(block, NBD_SET_BLKSIZE, 512UL, "NBD_SET_BLKSIZE")) fail("NBD_SET_BLKSIZE");
    if (traced_ioctl(block, NBD_SET_SIZE_BLOCKS, (unsigned long)(size / 512), "NBD_SET_SIZE_BLOCKS")) fail("NBD_SET_SIZE_BLOCKS");
    if (traced_ioctl(block, NBD_SET_FLAGS, (unsigned long)flags, "NBD_SET_FLAGS")) fail("NBD_SET_FLAGS");
    if (getenv("OPI_NBD_SKIP_TIMEOUT")) trace("NBD_SET_TIMEOUT skipped for diagnostic");
    else if (traced_ioctl(block, NBD_SET_TIMEOUT, 60UL, "NBD_SET_TIMEOUT")) fail("NBD_SET_TIMEOUT");
    if (traced_ioctl(block, NBD_SET_SOCK, (unsigned long)network, "NBD_SET_SOCK")) fail("NBD_SET_SOCK");
    printf("NBD_ATTACHED bytes=%llu device=/dev/nbd0\n", (unsigned long long)size); fflush(stdout);
    int status = traced_ioctl(block, NBD_DO_IT, 0UL, "NBD_DO_IT"), saved = errno;
    ioctl(block, NBD_CLEAR_QUE, 0UL);
    ioctl(block, NBD_CLEAR_SOCK, 0UL);
    close(block); close(network);
    if (status && saved != EPIPE) { errno = saved; fail("NBD_DO_IT"); }
    return 0;
}
