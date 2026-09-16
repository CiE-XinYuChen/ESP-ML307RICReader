#include <ctype.h>
#include <inttypes.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#include "driver/gpio.h"
#include "driver/uart.h"
#include "esp_err.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define MODEM_UART UART_NUM_1
#define MODEM_TX_PIN GPIO_NUM_2
#define MODEM_RX_PIN GPIO_NUM_0
#define MODEM_DTR_PIN GPIO_NUM_1

#define UART_RX_BUFFER_SIZE 2048
#define AT_RESPONSE_SIZE 512
#define ICCID_SIZE 32
#define IMEI_SIZE 16
#define IMEI_RETRY_MS 1500

#define HEARTBEAT_INTERVAL_MS 500
#define ICCID_READY_REFRESH_MS 5000
#define ICCID_RETRY_MS 1500
#define MODEM_RETRY_MS 1000

static const char *TAG = "xmini_id";

static const int k_baud_rates[] = {
    921600,
    115200,
    460800,
    230400,
    57600,
    38400,
    19200,
    9600,
};

typedef enum {
    ICCID_QUERY_OK,
    ICCID_QUERY_NO_SIM,
    ICCID_QUERY_ERROR,
} iccid_query_result_t;

static int64_t now_ms(void)
{
    return esp_timer_get_time() / 1000;
}

static bool response_has_error(const char *response)
{
    return strstr(response, "ERROR") != NULL || strstr(response, "NO CARRIER") != NULL;
}

static bool send_at_command(const char *command, char *response, size_t response_size, int timeout_ms)
{
    if (response == NULL || response_size < 2) {
        return false;
    }

    response[0] = '\0';
    uart_flush_input(MODEM_UART);

    char wire_command[64];
    int wire_length = snprintf(wire_command, sizeof(wire_command), "%s\r\n", command);
    if (wire_length <= 0 || wire_length >= (int)sizeof(wire_command)) {
        return false;
    }

    if (uart_write_bytes(MODEM_UART, wire_command, wire_length) != wire_length) {
        return false;
    }
    uart_wait_tx_done(MODEM_UART, pdMS_TO_TICKS(100));

    size_t used = 0;
    int64_t deadline = now_ms() + timeout_ms;
    while (now_ms() < deadline && used < response_size - 1) {
        int read = uart_read_bytes(
            MODEM_UART,
            (uint8_t *)response + used,
            response_size - used - 1,
            pdMS_TO_TICKS(20));
        if (read > 0) {
            used += (size_t)read;
            response[used] = '\0';
            if (strstr(response, "\r\nOK\r\n") != NULL || response_has_error(response)) {
                break;
            }
        }
    }

    return strstr(response, "OK") != NULL && !response_has_error(response);
}

static int detect_modem_baud(void)
{
    char response[AT_RESPONSE_SIZE];
    for (size_t i = 0; i < sizeof(k_baud_rates) / sizeof(k_baud_rates[0]); ++i) {
        int baud = k_baud_rates[i];
        ESP_ERROR_CHECK(uart_set_baudrate(MODEM_UART, baud));
        if (send_at_command("AT", response, sizeof(response), 120)) {
            ESP_LOGI(TAG, "ML307R detected at %d baud", baud);
            send_at_command("ATE0", response, sizeof(response), 250);
            return baud;
        }
    }
    return 0;
}

static bool copy_digit_run(const char *begin, char *iccid, size_t iccid_size)
{
    while (*begin != '\0' && !isdigit((unsigned char)*begin)) {
        ++begin;
    }

    const char *end = begin;
    while (isdigit((unsigned char)*end)) {
        ++end;
    }

    size_t length = (size_t)(end - begin);
    if (length < 18 || length > 24 || length >= iccid_size) {
        return false;
    }

    memcpy(iccid, begin, length);
    iccid[length] = '\0';
    return true;
}

static bool copy_prefixed_iccid(const char *begin, char *iccid, size_t iccid_size)
{
    while (isspace((unsigned char)*begin)) {
        ++begin;
    }

    const char *end = begin;
    while (isxdigit((unsigned char)*end)) {
        ++end;
    }

    size_t length = (size_t)(end - begin);
    if (length < 18 || length > 24 || length >= iccid_size || isalnum((unsigned char)*end)) {
        return false;
    }

    for (size_t i = 0; i < length; ++i) {
        iccid[i] = (char)toupper((unsigned char)begin[i]);
    }
    iccid[length] = '\0';
    return true;
}

static bool extract_iccid(const char *response, char *iccid, size_t iccid_size)
{
    const char *marker = strstr(response, "+ICCID:");
    if (marker != NULL && copy_prefixed_iccid(marker + strlen("+ICCID:"), iccid, iccid_size)) {
        return true;
    }

    // Some firmware revisions return the identifier without a +ICCID prefix.
    for (const char *cursor = response; *cursor != '\0'; ++cursor) {
        if (isdigit((unsigned char)*cursor) &&
            (cursor == response || !isdigit((unsigned char)cursor[-1])) &&
            copy_digit_run(cursor, iccid, iccid_size)) {
            return true;
        }
    }
    return false;
}

static iccid_query_result_t query_iccid(char *iccid, size_t iccid_size)
{
    char response[AT_RESPONSE_SIZE];
    bool ok = send_at_command("AT+ICCID", response, sizeof(response), 1200);

    if (strstr(response, "+CME ERROR: 10") != NULL ||
        strstr(response, "SIM not inserted") != NULL ||
        strstr(response, "SIM NOT INSERTED") != NULL) {
        return ICCID_QUERY_NO_SIM;
    }

    if (!ok || !extract_iccid(response, iccid, iccid_size)) {
        ESP_LOGW(TAG, "Unable to read ICCID: %s", response[0] == '\0' ? "no response" : response);
        return ICCID_QUERY_ERROR;
    }
    return ICCID_QUERY_OK;
}

static bool extract_imei(const char *response, char *imei, size_t imei_size)
{
    // Only accept a complete response line, not digits in an echo or a URC.
    for (const char *line = response; *line != '\0';) {
        const char *end = line + strcspn(line, "\r\n");
        const char *value = line;
        while (value < end && isspace((unsigned char)*value)) ++value;
        if (strncmp(value, "+CGSN:", 6) == 0) value += 6;
        while (value < end && isspace((unsigned char)*value)) ++value;
        bool quoted = value < end && *value == '"';
        if (quoted) ++value;
        const char *digits = value;
        while (value < end && isdigit((unsigned char)*value)) ++value;
        size_t length = (size_t)(value - digits);
        if (quoted && value < end && *value == '"') ++value;
        else if (quoted) length = 0;
        while (value < end && isspace((unsigned char)*value)) ++value;
        if (length == 15 && length < imei_size && value == end) {
            memcpy(imei, digits, length);
            imei[length] = '\0';
            return true;
        }
        line = end;
        while (*line == '\r' || *line == '\n') ++line;
    }
    return false;
}

static bool query_imei(char *imei, size_t imei_size)
{
    char response[AT_RESPONSE_SIZE];
    if (send_at_command("AT+CGSN=1", response, sizeof(response), 1200) &&
        extract_imei(response, imei, imei_size)) {
        return true;
    }
    ESP_LOGW(TAG, "Unable to read IMEI; will retry");
    return false;
}

static void format_sta_mac(char *output, size_t output_size)
{
    uint8_t mac[6] = {0};
    esp_err_t result = esp_read_mac(mac, ESP_MAC_WIFI_STA);
    if (result != ESP_OK) {
        ESP_LOGE(TAG, "Failed to read STA MAC: %s", esp_err_to_name(result));
        snprintf(output, output_size, "00:00:00:00:00:00");
        return;
    }

    snprintf(output, output_size, "%02X:%02X:%02X:%02X:%02X:%02X",
             mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
}

static void emit_device_info(const char *status, const char *sta_mac, const char *iccid, const char *imei, int modem_baud)
{
    printf(
        "{\"protocol\":\"xmini-id-v1\",\"board\":\"xmini-c3-4g\","
        "\"status\":\"%s\",\"sta_mac\":\"%s\",\"iccid\":\"%s\","
        "\"imei\":\"%s\",\"modem_baud\":%d,\"uptime_ms\":%" PRIi64 "}\n",
        status,
        sta_mac,
        iccid,
        imei,
        modem_baud,
        now_ms());
    fflush(stdout);
}

static void initialize_modem_uart(void)
{
    gpio_config_t dtr_config = {
        .pin_bit_mask = 1ULL << MODEM_DTR_PIN,
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&dtr_config));
    ESP_ERROR_CHECK(gpio_set_level(MODEM_DTR_PIN, 0));

    uart_config_t uart_config = {
        .baud_rate = k_baud_rates[0],
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };

    ESP_ERROR_CHECK(uart_driver_install(MODEM_UART, UART_RX_BUFFER_SIZE, 0, 0, NULL, 0));
    ESP_ERROR_CHECK(uart_param_config(MODEM_UART, &uart_config));
    ESP_ERROR_CHECK(uart_set_pin(
        MODEM_UART,
        MODEM_TX_PIN,
        MODEM_RX_PIN,
        UART_PIN_NO_CHANGE,
        UART_PIN_NO_CHANGE));
    ESP_ERROR_CHECK(gpio_set_pull_mode(MODEM_RX_PIN, GPIO_PULLUP_ONLY));
}

void app_main(void)
{
    setvbuf(stdout, NULL, _IOLBF, 0);

    char sta_mac[18];
    char iccid[ICCID_SIZE] = "";
    char imei[IMEI_SIZE] = "";
    const char *status = "detecting_modem";
    int modem_baud = 0;
    int consecutive_query_failures = 0;
    int64_t next_modem_probe = 0;
    int64_t next_iccid_query = 0;
    int64_t next_imei_query = 0;
    int64_t next_heartbeat = 0;

    format_sta_mac(sta_mac, sizeof(sta_mac));
    initialize_modem_uart();
    vTaskDelay(pdMS_TO_TICKS(200));

    ESP_LOGI(TAG, "xmini-c3-4g identifier reader started; STA MAC=%s", sta_mac);

    while (true) {
        int64_t current = now_ms();

        if (modem_baud == 0 && current >= next_modem_probe) {
            status = "detecting_modem";
            modem_baud = detect_modem_baud();
            if (modem_baud == 0) {
                status = "modem_not_found";
                next_modem_probe = current + MODEM_RETRY_MS;
            } else {
                status = "reading_iccid";
                consecutive_query_failures = 0;
                next_iccid_query = current;
                next_imei_query = current;
            }
        }

        if (modem_baud != 0 && imei[0] == '\0' && current >= next_imei_query) {
            query_imei(imei, sizeof(imei));
            next_imei_query = now_ms() + IMEI_RETRY_MS;
        }

        if (modem_baud != 0 && current >= next_iccid_query) {
            char latest_iccid[ICCID_SIZE] = "";
            iccid_query_result_t result = query_iccid(latest_iccid, sizeof(latest_iccid));
            if (result == ICCID_QUERY_OK) {
                snprintf(iccid, sizeof(iccid), "%s", latest_iccid);
                status = "ready";
                consecutive_query_failures = 0;
                next_iccid_query = current + ICCID_READY_REFRESH_MS;
            } else if (result == ICCID_QUERY_NO_SIM) {
                iccid[0] = '\0';
                status = "no_sim";
                consecutive_query_failures = 0;
                next_iccid_query = current + ICCID_RETRY_MS;
            } else {
                ++consecutive_query_failures;
                if (iccid[0] == '\0') {
                    status = "iccid_error";
                }
                next_iccid_query = current + ICCID_RETRY_MS;

                if (consecutive_query_failures >= 3) {
                    ESP_LOGW(TAG, "Modem stopped responding; starting baud detection again");
                    modem_baud = 0;
                    iccid[0] = '\0';
                    imei[0] = '\0';
                    status = "modem_not_found";
                    next_modem_probe = current + MODEM_RETRY_MS;
                }
            }
        }

        if (current >= next_heartbeat) {
            emit_device_info(status, sta_mac, iccid, imei, modem_baud);
            next_heartbeat = current + HEARTBEAT_INTERVAL_MS;
        }

        vTaskDelay(pdMS_TO_TICKS(25));
    }
}
