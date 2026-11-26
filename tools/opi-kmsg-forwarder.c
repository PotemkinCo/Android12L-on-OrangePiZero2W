/* SPDX-License-Identifier: MIT
 * Follow only new kernel messages over the private USB endpoint. Open all
 * resources before Android changes its root filesystem; no later path access.
 */
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

int main(void) {
    int input = open("/dev/kmsg", O_RDONLY | O_CLOEXEC | O_NONBLOCK);
    if (input < 0) { perror("open kmsg"); return 1; }
    if (lseek(input, 0, SEEK_END) < 0) { perror("seek kmsg"); return 1; }
    int network = socket(AF_INET, SOCK_DGRAM | SOCK_CLOEXEC | SOCK_NONBLOCK, 0);
    if (network < 0) { perror("socket"); return 1; }
    const char interface[] = "usb0";
    if (setsockopt(network, SOL_SOCKET, SO_BINDTODEVICE, interface, sizeof(interface))) {
        perror("bind USB interface"); return 1;
    }
    struct sockaddr_in local = {.sin_family = AF_INET};
    struct sockaddr_in remote = {.sin_family = AF_INET, .sin_port = htons(6666)};
    if (inet_pton(AF_INET, "192.168.246.2", &local.sin_addr) != 1 ||
        inet_pton(AF_INET, "192.168.246.1", &remote.sin_addr) != 1 ||
        bind(network, (struct sockaddr *)&local, sizeof(local))) {
        perror("bind private USB address"); return 1;
    }
    struct pollfd source = {.fd = input, .events = POLLIN};
    char buffer[8192];
    for (;;) {
        int ready = poll(&source, 1, 1000);
        if (ready < 0 && errno == EINTR) continue;
        if (ready < 0) { perror("poll kmsg"); return 1; }
        if (!ready) continue;
        ssize_t length = read(input, buffer, sizeof(buffer));
        if (length < 0 && (errno == EINTR || errno == EAGAIN || errno == EPIPE)) continue;
        if (length < 0) { perror("read kmsg"); return 1; }
        if (!length) continue;
        /* UDP may drop diagnostics. Never block root-disk I/O for logging. */
        (void)sendto(network, buffer, (size_t)length, MSG_DONTWAIT,
                     (struct sockaddr *)&remote, sizeof(remote));
    }
}
