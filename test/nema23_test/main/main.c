#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <inttypes.h>
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
#define OUTPUT_ANGLE_DEG 360U  // 1..360, relative angle
#define DIRECTION 0U          // change to 1 to reverse
#define TOTAL_PULSES ((FULL_STEPS * MICROSTEPS * GEAR_RATIO * OUTPUT_ANGLE_DEG + 180U) / 360U)
#define PERIOD_US 1500U       // nominal output speed 0.5 rpm
#define RAMP_STEPS 400U
#define BLOCK 32U
#define CHOPCONF 0x140100C3U
#define FAULT_MASK 0x1E003000U

_Static_assert(OUTPUT_ANGLE_DEG >= 1 && OUTPUT_ANGLE_DEG <= 360, "Angle must be 1..360");
_Static_assert(DIRECTION <= 1, "Direction must be 0 or 1");
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
        ((io >> 1) & 1U) != DIRECTION || (gs & 7U) ||
        (ds & FAULT_MASK)) {
        gpio_set_level(PIN_EN, 1);
        printf("FAULT IOIN=%08" PRIX32 " GSTAT=%08" PRIX32 " DRV_STATUS=%08" PRIX32 "\n", io, gs, ds);
        return false;
    }
    return true;
}

static bool tmc_init(void)
{
    // Wait for VM, never enable outputs here.
    while (1) {
        uint32_t io = tmc_read(0x04);
        if ((io >> 24) == 0x30 && (io & 0x50U) == 0x50U) break;
        printf("Waiting for TMC / EN HIGH: IOIN=%08" PRIX32 "\n", io);
        vTaskDelay(pdMS_TO_TICKS(1000));
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
    gpio_set_level(PIN_DIR, DIRECTION);
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
    uint32_t remaining = TOTAL_PULSES - 1U - index;
    if (remaining < edge) edge = remaining;
    if (edge >= RAMP_STEPS) return PERIOD_US;
    return PERIOD_US + PERIOD_US * (RAMP_STEPS - edge) / RAMP_STEPS;
}

static bool move_once(void)
{
    uint32_t sent = 0;
    rmt_transmit_config_t cfg = {.loop_count = 0, .flags.eot_level = 0};
    if (!healthy(false)) return false;
    gpio_set_level(PIN_EN, 0);
    vTaskDelay(pdMS_TO_TICKS(200));
    if (!healthy(true)) return false;
    printf("START angle=%u pulses=%u\n", OUTPUT_ANGLE_DEG, TOTAL_PULSES);
    while (sent < TOTAL_PULSES) {
        if (gpio_get_level(PIN_BOOT) == 0) {
            gpio_set_level(PIN_EN, 1);
            printf("STOP: BOOT pressed. Completed pulses=%" PRIu32 "\n", sent);
            return false;
        }
        if (!healthy(true)) return false;
        uint32_t n = TOTAL_PULSES - sent;
        if (n > BLOCK) n = BLOCK;
        for (uint32_t i = 0; i < n; ++i) {
            symbols[i] = (rmt_symbol_word_t){
                .level0 = 1, .duration0 = 5,
                .level1 = 0, .duration1 = pulse_period(sent+i)-5,
            };
        }
        esp_err_t e = rmt_transmit(tx_channel, encoder, symbols,
                                    n * sizeof(symbols[0]), &cfg);
        if (e == ESP_OK) e = rmt_tx_wait_all_done(tx_channel, 1000);
        if (e != ESP_OK) {
            gpio_set_level(PIN_EN, 1);
            printf("RMT ERROR: %s; current block position unknown\n", esp_err_to_name(e));
            return false;
        }
        sent += n;
        if (sent % 8000U == 0 || sent == TOTAL_PULSES)
            printf("Progress: %" PRIu32 "/%u\n", sent, TOTAL_PULSES);
    }
    if (!healthy(true)) return false;
    gpio_set_level(PIN_EN, 1);
    printf("DONE: %" PRIu32 " pulses; motor disabled\n", sent);
    return true;
}

void app_main(void)
{
    pins_init();
    spi_init();
    printf("TMC5160 ONE TURN TEST (no GUI)\n");
    if (!tmc_init()) {
        gpio_set_level(PIN_EN, 1);
        printf("INIT FAILED. Fix issue and reset.\n");
        return;
    }
    rmt_init();
    if (!healthy(false)) return;
    printf("READY. Press and release BOOT to move once.\n");
    // Require a fresh press after startup. No automatic movement after reset.
    while (gpio_get_level(PIN_BOOT) == 0) vTaskDelay(pdMS_TO_TICKS(20));
    while (gpio_get_level(PIN_BOOT) != 0) vTaskDelay(pdMS_TO_TICKS(20));
    vTaskDelay(pdMS_TO_TICKS(40));
    while (gpio_get_level(PIN_BOOT) == 0) vTaskDelay(pdMS_TO_TICKS(20));
    vTaskDelay(pdMS_TO_TICKS(40));
    move_once();
    gpio_set_level(PIN_EN, 1);
    printf("Test ended. RESET to prepare another test.\n");
}
