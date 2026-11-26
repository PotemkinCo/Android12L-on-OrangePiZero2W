/*
 * Catch the Allwinner vendor U-Boot auto-FEL window.
 * Source: orangepi-xunlong/u-boot-orangepi, commit
 * 66e2615a13f7e2b3ee269fd0ec027db117c493b7,
 * cmd/sunxi_auto_fel.c and drivers/sunxi_usb/usb_burn.c.
 *
 * Allowed requests: F8/00 (probe), F8/02 (enter FEL), and F0/00
 * (legacy handshake only). No memory upload, storage, key or efuse commands.
 */
#define _POSIX_C_SOURCE 200809L
#include <libusb.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static int legacy_hold;

static void put32(unsigned char *p, uint32_t value)
{
    p[0] = value; p[1] = value >> 8; p[2] = value >> 16; p[3] = value >> 24;
}

static uint32_t get32(const unsigned char *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 |
           (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

static double now(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (double)t.tv_sec + (double)t.tv_nsec / 1e9;
}

static int exchange(libusb_device_handle *h, unsigned char out,
                    unsigned char in, unsigned char opcode, unsigned char command,
                    uint32_t tag, const char *expected)
{
    if (!((opcode == 0xf8 && (command == 0 || command == 2)) ||
          (opcode == 0xf0 && command == 0))) return -1;
    unsigned char cbw[31] = {0}, reply[64] = {0}, status[13] = {0};
    int done = 0;
    /* Standard USB bulk-only wrapper, little-endian signature "USBC". */
    memcpy(cbw, "USBC", 4);
    put32(cbw + 4, tag);
    put32(cbw + 8, 32);
    cbw[12] = 0x80; /* device-to-host payload */
    cbw[14] = 16;
    cbw[15] = opcode;
    cbw[16] = command;
    int r = libusb_bulk_transfer(h, out, cbw, sizeof cbw, &done, 400);
    if (r || done != (int)sizeof cbw) {
        fprintf(stderr, "Command transfer: %s (%d bytes)\n", libusb_error_name(r), done);
        return -1;
    }
    r = libusb_bulk_transfer(h, in, reply, sizeof reply, &done, 500);
    if (command == 2 && r == LIBUSB_ERROR_NO_DEVICE) {
        puts("USB disconnected following FEL request; verify the new device with sunxi-fel version.");
        return 0;
    }
    if (r || done != 32 || memcmp(reply, expected, strlen(expected))) {
        fprintf(stderr, "Unexpected probe reply: %s (%d bytes): ", libusb_error_name(r), done);
        for (int i = 0; i < done && i < (int)sizeof reply; i++) fprintf(stderr, "%02x", reply[i]);
        fputc('\n', stderr);
        return -1;
    }
    printf("Reply: %.*s\n", done, reply);
    r = libusb_bulk_transfer(h, in, status, sizeof status, &done, 500);
    if (r || done != 13 || memcmp(status, "USBS", 4) ||
        get32(status + 4) != tag || status[12] != 0) {
        /* Enter-FEL may reset before its final status packet is sent. */
        if (command == 2 && (r == LIBUSB_ERROR_NO_DEVICE || r == LIBUSB_ERROR_TIMEOUT)) {
            puts("FEL acknowledgement received; awaiting reset.");
            return 0;
        }
        fprintf(stderr, "Invalid status: %s (%d bytes)\n", libusb_error_name(r), done);
        return -1;
    }
    return 0;
}

static int catch_device(libusb_device *device)
{
    struct libusb_config_descriptor *config = NULL;
    libusb_device_handle *h = NULL;
    unsigned char in = 0, out = 0;
    int interface = -1;
    int r = libusb_get_config_descriptor(device, 0, &config);
    if (r) return -1;
    if (config->bNumInterfaces == 1) {
        const struct libusb_interface *iface = &config->interface[0];
        for (int a = 0; a < iface->num_altsetting; a++) {
            const struct libusb_interface_descriptor *d = &iface->altsetting[a];
            if (d->bAlternateSetting || d->bInterfaceClass != 0xff ||
                d->bInterfaceSubClass != 0xff || d->bInterfaceProtocol != 0xff ||
                d->bNumEndpoints != 2) continue;
            for (int e = 0; e < d->bNumEndpoints; e++) {
                const struct libusb_endpoint_descriptor *ep = &d->endpoint[e];
                if ((ep->bmAttributes & LIBUSB_TRANSFER_TYPE_MASK) != LIBUSB_TRANSFER_TYPE_BULK) continue;
                if (ep->bEndpointAddress & LIBUSB_ENDPOINT_IN) in = ep->bEndpointAddress;
                else out = ep->bEndpointAddress;
            }
            if (in && out) { interface = d->bInterfaceNumber; break; }
        }
    }
    if (interface < 0) {
        puts("Descriptor does not match vendor recovery; no commands sent.");
        libusb_free_config_descriptor(config);
        return -1;
    }
    r = libusb_open(device, &h);
    if (r) {
        fprintf(stderr, "Open device: %s; USB write access is required.\n", libusb_error_name(r));
        libusb_free_config_descriptor(config);
        return -1;
    }
    int active = 0;
    r = libusb_get_configuration(h, &active);
    if (!r && active != config->bConfigurationValue)
        r = libusb_set_configuration(h, config->bConfigurationValue);
    if (!r) r = libusb_claim_interface(h, interface);
    if (r) {
        fprintf(stderr, "Claim interface: %s\n", libusb_error_name(r));
    } else {
        printf("Interface %d, endpoints IN=%02x OUT=%02x\n", interface, in, out);
        r = exchange(h, out, in, legacy_hold ? 0xf0 : 0xf8, 0,
                     0x4f504901, legacy_hold ? "usb_burn_handshake" : "usb_update_probe_ok");
        if (!r && legacy_hold) {
            puts("Legacy handshake verified. No key or storage commands sent. Checking whether USB stays available.");
        } else if (!r) {
            puts("Recovery handshake verified; requesting FEL (no flash writes).");
            r = exchange(h, out, in, 0xf8, 2, 0x4f504902, "usb_update_efex");
        }
        libusb_release_interface(h, interface);
    }
    libusb_close(h);
    libusb_free_config_descriptor(config);
    return r;
}

int main(int argc, char **argv)
{
    double seconds = 180;
    if (argc > 3) return 2;
    if (argc >= 2) {
        char *end = NULL;
        seconds = strtod(argv[1], &end);
        if (!end || *end || !(seconds >= 1 && seconds <= 600)) {
            fprintf(stderr, "Usage: %s [wait-seconds: 1..600] [--legacy-hold]\n", argv[0]);
            return 2;
        }
    }
    if (argc == 3) {
        if (strcmp(argv[2], "--legacy-hold")) return 2;
        legacy_hold = 1;
    }
    setvbuf(stdout, NULL, _IOLBF, 0);
    libusb_context *context = NULL;
    int r = libusb_init(&context);
    if (r) { fprintf(stderr, "USB initialization: %s\n", libusb_error_name(r)); return 1; }
    printf("Waiting %.0f seconds for 1f3a:efe8 U-Boot recovery (bcdDevice=ffff).\n", seconds);
    if (legacy_hold) puts("Mode: legacy handshake only (F0/00); no subsequent vendor commands.");
    double deadline = now() + seconds;
    unsigned previous = 0;
    while (now() < deadline) {
        libusb_device **devices = NULL;
        ssize_t count = libusb_get_device_list(context, &devices);
        if (count < 0) { fprintf(stderr, "USB enumeration failed.\n"); break; }
        for (ssize_t i = 0; i < count; i++) {
            struct libusb_device_descriptor descriptor;
            if (libusb_get_device_descriptor(devices[i], &descriptor) ||
                descriptor.idVendor != 0x1f3a || descriptor.idProduct != 0xefe8) continue;
            unsigned id = libusb_get_bus_number(devices[i]) * 256u + libusb_get_device_address(devices[i]);
            if (id == previous) continue;
            previous = id;
            printf("Detected bus %u device %u, bcdDevice=%04x.\n",
                   libusb_get_bus_number(devices[i]), libusb_get_device_address(devices[i]), descriptor.bcdDevice);
            if (descriptor.bcdDevice != 0xffff) {
                puts("Non-U-Boot Allwinner device present; use sunxi-fel version to identify it. No vendor commands sent.");
                libusb_free_device_list(devices, 1);
                libusb_exit(context);
                return 0;
            }
            r = catch_device(devices[i]);
            libusb_free_device_list(devices, 1);
            libusb_exit(context);
            return r ? 1 : 0;
        }
        libusb_free_device_list(devices, 1);
        const struct timespec delay = {0, 10000000};
        nanosleep(&delay, NULL);
    }
    puts("No matching recovery device appeared before timeout.");
    libusb_exit(context);
    return 3;
}
