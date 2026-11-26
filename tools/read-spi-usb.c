/* Read-only vendor F3/03 logical-flash reader; never sends F3/01 (write).
 * Requires the successful F0/00 legacy handshake from catch-fel first.
 * Offset zero assumes no F3/00 private-partition handshake has been sent.
 */
#define main catch_fel_main_unused
#include "catch-fel.c"
#undef main
#include <errno.h>

static int read_sectors(libusb_device_handle *h, uint32_t sector,
                        uint32_t count, uint32_t tag, unsigned char *buffer)
{
    unsigned char cbw[31] = {0}, status[13] = {0};
    int done = 0;
    memcpy(cbw, "USBC", 4);
    put32(cbw + 4, tag);
    put32(cbw + 8, count * 512);
    cbw[12] = 0x80;
    cbw[14] = 16;
    cbw[15] = 0xf3;
    cbw[16] = 3;
    put32(cbw + 19, sector);
    put32(cbw + 23, count);
    int r = libusb_bulk_transfer(h, 0x02, cbw, sizeof cbw, &done, 1000);
    if (r || done != 31) goto fail;
    r = libusb_bulk_transfer(h, 0x81, buffer, count * 512, &done, 5000);
    if (r || done != (int)(count * 512)) goto fail;
    r = libusb_bulk_transfer(h, 0x81, status, sizeof status, &done, 1000);
    if (r || done != 13 || memcmp(status, "USBS", 4) ||
        get32(status + 4) != tag || status[12] != 0) {
        fprintf(stderr, "Invalid read status, sector %u: status=%u\n", sector, status[12]);
        return -1;
    }
    return 0;
fail:
    fprintf(stderr, "Read sector %u: %s (%d bytes)\n", sector, libusb_error_name(r), done);
    return -1;
}

int main(int argc, char **argv)
{
    if (argc != 4 && argc != 5) {
        fprintf(stderr, "Usage: %s START_SECTOR SECTOR_COUNT NEW_OUTPUT_FILE [--physical]\n", argv[0]);
        return 2;
    }
    char *end1, *end2;
    errno = 0;
    unsigned long start = strtoul(argv[1], &end1, 0);
    unsigned long count = strtoul(argv[2], &end2, 0);
    int physical = argc == 5 && !strcmp(argv[4], "--physical");
    unsigned long limit = physical ? 32768 : 30752;
    if ((argc == 5 && !physical) || errno || *end1 || *end2 || !count || start >= limit || count > limit - start) {
        fputs("Read must be within the 16 MiB logical flash range.\n", stderr);
        return 2;
    }
    setvbuf(stdout, NULL, _IOLBF, 0);
    libusb_context *context = NULL;
    if (libusb_init(&context)) return 1;
    libusb_device_handle *h = libusb_open_device_with_vid_pid(context, 0x1f3a, 0xefe8);
    if (!h) { fputs("Allwinner device unavailable.\n", stderr); libusb_exit(context); return 1; }
    struct libusb_device_descriptor descriptor;
    int r = libusb_get_device_descriptor(libusb_get_device(h), &descriptor);
    if (r || descriptor.bcdDevice != 0xffff) {
        fputs("Not the expected vendor U-Boot interface.\n", stderr);
        libusb_close(h); libusb_exit(context); return 1;
    }
    r = libusb_claim_interface(h, 0);
    if (r) { fprintf(stderr, "Claim: %s\n", libusb_error_name(r)); libusb_close(h); libusb_exit(context); return 1; }
    FILE *output = fopen(argv[3], "wbx");
    if (!output) { perror("Output file"); libusb_release_interface(h, 0); libusb_close(h); libusb_exit(context); return 1; }
    unsigned char *buffer = malloc(256 * 512);
    if (!buffer) { fclose(output); libusb_release_interface(h, 0); libusb_close(h); libusb_exit(context); return 1; }
    unsigned long read_count = 0;
    while (read_count < count) {
        uint32_t chunk = count - read_count > 256 ? 256 : (uint32_t)(count - read_count);
        /* The stock SPI logical offset is 0x7e0 sectors (0xfc000 bytes).
         * uint32_t addition in the vendor driver permits a physical read
         * using the corresponding wrapped logical sector. All resulting
         * physical sectors remain within the 16 MiB chip. */
        uint32_t wire_sector = (uint32_t)(start + read_count - (physical ? 0x7e0u : 0u));
        if (read_sectors(h, wire_sector, chunk, 0x53504900 + read_count, buffer) ||
            fwrite(buffer, 512, chunk, output) != chunk) { r = -1; break; }
        read_count += chunk;
    }
    if (fclose(output)) r = -1;
    printf("Read %lu / %lu sectors (%lu bytes) into %s; %s.\n",
           read_count, count, read_count * 512, argv[3], r ? "INCOMPLETE" : "complete");
    free(buffer); libusb_release_interface(h, 0); libusb_close(h); libusb_exit(context);
    return r ? 1 : 0;
}
