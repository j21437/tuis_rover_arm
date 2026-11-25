#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <inttypes.h>
#include <string.h>
#include <stdarg.h>
#include "driver/usb_serial_jtag.h"
#include "driver/usb_serial_jtag_vfs.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "driver/rmt_tx.h"
#include "driver/rmt_encoder.h"
#include "esp_err.h"

#define PIN_STEP GPIO_NUM_4
#define PIN_DIR  GPIO_NUM_5
#define PIN_EN   GPIO_NUM_6
#define PIN_CS   GPIO_NUM_10
#define PIN_MOSI GPIO_NUM_11
#define PIN_SCK  GPIO_NUM_12
#define PIN_MISO GPIO_NUM_13
#define PIN_BOOT GPIO_NUM_0

#define FULL_STEPS 200U
#define MICROSTEPS 16U
#define GEAR_RATIO 25U
#define PPR (FULL_STEPS * MICROSTEPS * GEAR_RATIO)
#define RAMP_STEPS 400U
#define BLOCK 32U
#define CHOPCONF 0x140100C3U
#define FAULT_MASK 0x1E003000U
#define LINK_TIMEOUT_US 3000000LL
static unsigned angle_deg = 360, direction = 0, requested_direction = 0;
static uint32_t total_pulses = 0, period_us = 1500, sent = 0;
static bool ready = false, busy = false, pending = false, stop_requested = false, rmt_created = false;
static int64_t last_ping = 0;
static char line[96];
static size_t line_len = 0;
static bool overflow = false;

// Direct USB Serial/JTAG I/O, not stdin. No infinite write waits.
static void usb_printf(const char *fmt, ...)
{
    char buf[256];
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    if (n > 0) {
        size_t size = (size_t)n < sizeof(buf) ? (size_t)n : sizeof(buf)-1;
        (void)usb_serial_jtag_write_bytes(buf, size, pdMS_TO_TICKS(20)+1);
    }
}
#define printf(...) usb_printf(__VA_ARGS__)

static spi_device_handle_t spi;
static rmt_channel_handle_t tx_channel;
static rmt_encoder_handle_t encoder;
static rmt_symbol_word_t symbols[BLOCK];

static void checked(esp_err_t err)
{
    if (err != ESP_OK) {
        gpio_set_level(PIN_EN, 1);
        ESP_ERROR_CHECK(err);
    }
}

static void pins_init(void)
{
    gpio_set_level(PIN_EN, 1);
    checked(gpio_set_direction(PIN_EN, GPIO_MODE_OUTPUT));
    gpio_set_level(PIN_EN, 1);
    gpio_set_level(PIN_DIR, 0);
    checked(gpio_set_direction(PIN_DIR, GPIO_MODE_OUTPUT));
    gpio_set_level(PIN_DIR, 0);
    gpio_set_level(PIN_STEP, 0);
    checked(gpio_set_direction(PIN_STEP, GPIO_MODE_OUTPUT));
    gpio_set_level(PIN_STEP, 0);
    gpio_config_t button = {
        .pin_bit_mask = 1ULL << PIN_BOOT,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    checked(gpio_config(&button));
}

static void spi_init(void)
{
    spi_bus_config_t bus = {
        .mosi_io_num = PIN_MOSI, .miso_io_num = PIN_MISO,
        .sclk_io_num = PIN_SCK, .quadwp_io_num = -1,
        .quadhd_io_num = -1, .max_transfer_sz = 5,
    };
    spi_device_interface_config_t dev = {
        .clock_speed_hz = 500000, .mode = 3,
        .spics_io_num = PIN_CS, .queue_size = 1,
    };
    checked(spi_bus_initialize(SPI2_HOST, &bus, SPI_DMA_DISABLED));
    checked(spi_bus_add_device(SPI2_HOST, &dev, &spi));
}

static uint32_t tmc_read(uint8_t address)
{
    uint8_t tx[5] = {address & 0x7F, 0, 0, 0, 0};
    uint8_t rx[5] = {0};
    spi_transaction_t t = {.length = 40, .tx_buffer = tx, .rx_buffer = rx};
    checked(spi_device_polling_transmit(spi, &t));
    checked(spi_device_polling_transmit(spi, &t));
    return ((uint32_t)rx[1] << 24) | ((uint32_t)rx[2] << 16) |
           ((uint32_t)rx[3] << 8) | rx[4];
}

static void tmc_write(uint8_t address, uint32_t value)
{
    uint8_t tx[5] = {address | 0x80, (uint8_t)(value >> 24),
        (uint8_t)(value >> 16), (uint8_t)(value >> 8), (uint8_t)value};
    spi_transaction_t t = {.length = 40, .tx_buffer = tx};
    checked(spi_device_polling_transmit(spi, &t));
}

static bool healthy(bool enabled)
{
    uint32_t io = tmc_read(0x04);
    uint32_t gs = tmc_read(0x01);
    uint32_t ds = tmc_read(0x6F);
    if ((io >> 24) != 0x30 || !(io & (1U << 6)) ||
        ((io >> 4) & 1U) != (enabled ? 0U : 1U) ||
        ((io >> 1) & 1U) != direction || (gs & 7U) ||
        (ds & FAULT_MASK)) {
        gpio_set_level(PIN_EN, 1);
        printf("FAULT IOIN=%08" PRIX32 " GSTAT=%08" PRIX32 " DRV_STATUS=%08" PRIX32 "\n", io, gs, ds);
        return false;
    }
    return true;
}

static bool tmc_init(void)
{
    // INIT is explicit, and USB remains responsive if VM is off.
    uint32_t initial_io = tmc_read(0x04);
    if ((initial_io >> 24) != 0x30 || (initial_io & 0x50U) != 0x50U) {
        printf("ERR SPI_OR_EN IOIN=%08" PRIX32 "\n", initial_io);
        return false;
    }
    vTaskDelay(pdMS_TO_TICKS(500));
    tmc_write(0x6C, 0);          // TOFF=0: chopper disabled
    tmc_write(0x01, 7);          // clear latched startup flags
    vTaskDelay(pdMS_TO_TICKS(200));
    if (tmc_read(0x01) & 7U) {
        printf("GSTAT did not clear; abort.\n");
        return false;
    }
    // Check STEP and DIR wiring with EN HIGH and chopper disabled.
    for (unsigned level = 0; level < 4; ++level) {
        gpio_set_level(PIN_STEP, level & 1U);
        gpio_set_level(PIN_DIR, (level >> 1) & 1U);
        vTaskDelay(pdMS_TO_TICKS(20));
        uint32_t io = tmc_read(0x04);
        if ((io >> 24) != 0x30 || !(io & 0x10U) ||
            (io & 3U) != level) {
            gpio_set_level(PIN_STEP, 0);
            printf("STEP/DIR/EN wiring check FAILED: level=%u IOIN=%08" PRIX32 "\n", level, io);
            return false;
        }
    }
    gpio_set_level(PIN_STEP, 0);
    gpio_set_level(PIN_DIR, direction);
    tmc_write(0x00, 0);          // SpreadCycle, single-edge STEP
    tmc_write(0x0B, 67);         // GLOBALSCALER, ~0.80 A RMS at Rsense=0.075 ohm
    tmc_write(0x10, 0x00061F0A); // IHOLD=10, IRUN=31, IHOLDDELAY=6
    tmc_write(0x11, 10);
    tmc_write(0x6D, 0);          // CoolStep off
    tmc_write(0x6C, CHOPCONF);   // MRES=4 (16), interpolation on, TOFF=3
    uint32_t ch = tmc_read(0x6C);
    printf("CHOPCONF=%08" PRIX32 "\n", ch);
    return ch == CHOPCONF && healthy(false);
}

static void rmt_init(void)
{
    rmt_tx_channel_config_t cfg = {
        .gpio_num = PIN_STEP,
        .clk_src = RMT_CLK_SRC_DEFAULT,
        .resolution_hz = 1000000,
        .mem_block_symbols = 48,
        .trans_queue_depth = 1,
    };
    rmt_copy_encoder_config_t ecfg = {};
    checked(rmt_new_tx_channel(&cfg, &tx_channel));
    checked(rmt_new_copy_encoder(&ecfg, &encoder));
    checked(rmt_enable(tx_channel));
}

static uint32_t pulse_period(uint32_t index)
{
    uint32_t edge = index;
    uint32_t remaining = total_pulses - 1U - index;
    if (remaining < edge) edge = remaining;
    if (edge >= RAMP_STEPS) return period_us;
    return period_us + period_us * (RAMP_STEPS - edge) / RAMP_STEPS;
}

static void status(void)
{
    printf("STATE %s %" PRIu32 " %" PRIu32 "\n",
           busy ? "MOVING" : ready ? "READY" : "NOT_READY", sent, total_pulses);
}

static void command(const char *cmd)
{
    if (!strcmp(cmd,"HELLO")) {
        printf("HELLO RMT_GUI_V1\n"); status();
    } else if (!strcmp(cmd,"PING")) {
        last_ping = esp_timer_get_time();
        printf("PONG\n");
    } else if (!strcmp(cmd,"STATUS")) {
        status();
    } else if (!strcmp(cmd,"STOP")) {
        stop_requested = true; pending = false;
        gpio_set_level(PIN_EN, 1);
        printf("OK STOP\n");
        if (!busy) status();
    } else if (!strcmp(cmd,"INIT")) {
        if (busy || pending) { printf("ERR BUSY\n"); return; }
        gpio_set_level(PIN_EN, 1);
        if (rmt_created) {
            // RMT owns STEP after initialization; never rerun GPIO pin test on it.
            if (ready && healthy(false) && tmc_read(0x6C) == CHOPCONF) {
                printf("OK INIT\n"); status();
            } else { ready=false; printf("ERR RESET_REQUIRED\n"); status(); }
            return;
        }
        direction=0; sent=0; total_pulses=0;
        ready = tmc_init();
        if (ready) { rmt_init(); rmt_created=true; ready=healthy(false); }
        if (ready) printf("OK INIT\n"); else printf("ERR INIT_FAILED\n");
        status();
    } else {
        int a, per, d; char extra;
        if (sscanf(cmd,"MOVE %d %d %d %c", &a, &per, &d, &extra) != 3) {
            printf("ERR COMMAND\n"); return;
        }
        if (busy || pending || !ready) { printf("ERR NOT_READY_OR_BUSY\n"); return; }
        if (a < 1 || a > 360 || per < 150 || per > 3000 || (d != 0 && d != 1)) {
            printf("ERR RANGE\n"); return;
        }
        if (esp_timer_get_time()-last_ping > LINK_TIMEOUT_US || last_ping == 0) {
            printf("ERR NO_HEARTBEAT\n"); return;
        }
        if (gpio_get_level(PIN_BOOT)==0) { printf("ERR BOOT_HELD\n"); return; }
        angle_deg=(unsigned)a; period_us=(uint32_t)per;
        // Set the new direction in move_once, after disabling output.
        requested_direction=(unsigned)d;
        total_pulses=(PPR*angle_deg+180U)/360U;
        sent=0; stop_requested=false; pending=true;
    }
}

static void poll_usb(void)
{
    char buf[64];
    // Bounded work per call, even when host sends continuously.
    for (int pass=0; pass<4; ++pass) {
        int n=usb_serial_jtag_read_bytes(buf,sizeof(buf),0);
        if (n<=0) break;
        for (int i=0; i<n; ++i) {
            char c=buf[i];
            if (c=='\n' || c=='\r') {
                if (!overflow && line_len) { line[line_len]=0; command(line); }
                line_len=0; overflow=false;
            } else if (!overflow) {
                if (line_len<sizeof(line)-1) line[line_len++]=c;
                else { line_len=0; overflow=true; }
            }
        }
    }
}

static bool abort_requested(void)
{
    return stop_requested || gpio_get_level(PIN_BOOT)==0 ||
           esp_timer_get_time()-last_ping > LINK_TIMEOUT_US;
}

static const char *move_once(void)
{
    rmt_transmit_config_t cfg = {.loop_count = 0, .flags.eot_level = 0};
    gpio_set_level(PIN_EN, 1);
    direction=requested_direction;
    gpio_set_level(PIN_DIR, direction);
    vTaskDelay(pdMS_TO_TICKS(20)+1);
    if (!healthy(false) || tmc_read(0x6C)!=CHOPCONF) { ready=false; return "FAULT"; }
    if (abort_requested()) return "STOPPED";
    gpio_set_level(PIN_EN, 0);
    vTaskDelay(pdMS_TO_TICKS(200));
    poll_usb();
    if (abort_requested()) return "STOPPED";
    if (!healthy(true)) { ready=false; return "FAULT"; }
    printf("START %u %" PRIu32 " %" PRIu32 " %u\n", angle_deg,total_pulses,period_us,direction);
    int64_t last_report=esp_timer_get_time();
    while (sent < total_pulses) {
        poll_usb();
        if (abort_requested()) return "STOPPED";
        if (!healthy(true)) { ready=false; return "FAULT"; }
        uint32_t n=total_pulses-sent;
        if(n>BLOCK) n=BLOCK;
        for(uint32_t i=0;i<n;++i) {
            symbols[i]=(rmt_symbol_word_t){.level0=1,.duration0=5,
                .level1=0,.duration1=pulse_period(sent+i)-5};
        }
        esp_err_t e=rmt_transmit(tx_channel,encoder,symbols,n*sizeof(symbols[0]),&cfg);
        if(e==ESP_OK) e=rmt_tx_wait_all_done(tx_channel,1000);
        if(e!=ESP_OK) {
            ready=false; gpio_set_level(PIN_EN,1);
            printf("ERR RMT %s; current block unknown\n",esp_err_to_name(e));
            return "FAULT";
        }
        sent+=n;
        if(esp_timer_get_time()-last_report>=500000 || sent==total_pulses) {
            status(); last_report=esp_timer_get_time();
        }
    }
    if (!healthy(true)) { ready=false; return "FAULT"; }
    return "DONE";
}

void app_main(void)
{
    pins_init();
    usb_serial_jtag_driver_config_t usb_cfg = {.tx_buffer_size=1024,.rx_buffer_size=1024};
    checked(usb_serial_jtag_driver_install(&usb_cfg));
    usb_serial_jtag_vfs_use_driver();
    spi_init();
    printf("HELLO RMT_GUI_V1\n");
    while(1) {
        poll_usb();
        if (pending) {
            pending=false; busy=true;
            const char *result=move_once();
            gpio_set_level(PIN_EN,1);
            busy=false;
            printf("END %s %" PRIu32 "\n",result,sent);
            status();
        }
        vTaskDelay(1);
    }
}
