/* Get Start Example

   This example code is in the Public Domain (or CC0 licensed, at your option.)

   Unless required by applicable law or agreed to in writing, this
   software is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
   CONDITIONS OF ANY KIND, either express or implied.
*/

/**
 * In this file, the following code blocks are marked for customization.
 * Each block starts with the comment: "// YOUR CODE HERE"
 * and ends with: "// END OF YOUR CODE".
 *
 * [1] Modify the CSI Buffer and FIFO Lengths:
 *     - Adjust the buffer configuration based on your system if necessary.
 *
 * [2] Implement Algorithms:
 *     - Develop algorithms for motion detection, breathing rate estimation, and
 * MQTT message sending.
 *     - Implement them in their respective functions.
 *
 * [3] Modify Wi-Fi Configuration:
 *     - Modify the Wi-Fi settings–SSID and password to connect to your router.
 *
 * [4] Finish the function `csi_process()`:
 *     - Fill in the group information.
 *     - Process and analyze CSI data in the `csi_process` function.
 *     - Implement your algorithms in this function if on-board. (Task 2)
 *     - Return the results to the host or send the CSI data via MQTT. (Task 3)
 *
 * Feel free to modify these sections to suit your project requirements!
 *
 * Have fun building!
 */

#include "esp_log.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_now.h"
#include "esp_wifi.h"
#include "mqtt_client.h"
#include "nvs_flash.h"
#include "rom/ets_sys.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "credentials.h"

void mqtt_send() {
  // TODO: Implement MQTT message sending using CSI data or Results
  // NOTE: If you implement the algorithm on-board, you can return the results
  // to the host, else send the CSI data.
  return; // Placeholder
}

// #define SKIP_WIFI_CONNECTION

#define CONFIG_WIFI_BAND_MODE WIFI_BAND_MODE_5G_ONLY
#define CONFIG_WIFI_2G_BANDWIDTHS WIFI_BW_HT20
#define CONFIG_WIFI_5G_BANDWIDTHS WIFI_BW_HT20
#define CONFIG_WIFI_2G_PROTOCOL WIFI_PROTOCOL_11N
#define CONFIG_WIFI_5G_PROTOCOL WIFI_PROTOCOL_11N
#define CONFIG_ESP_NOW_PHYMODE WIFI_PHY_MODE_HT20
#define CONFIG_ESP_NOW_RATE WIFI_PHY_RATE_MCS0_LGI
#define CONFIG_FORCE_GAIN 1
#define CONFIG_GAIN_CONTROL CONFIG_FORCE_GAIN

// UPDATE: Define parameters for scan method
#if CONFIG_EXAMPLE_WIFI_ALL_CHANNEL_SCAN
#define DEFAULT_SCAN_METHOD WIFI_ALL_CHANNEL_SCAN
#elif CONFIG_EXAMPLE_WIFI_FAST_SCAN
#define DEFAULT_SCAN_METHOD WIFI_FAST_SCAN
#else
#define DEFAULT_SCAN_METHOD WIFI_FAST_SCAN
#endif /*CONFIG_EXAMPLE_SCAN_METHOD*/
//

static const uint8_t CONFIG_CSI_SEND_MAC[] = {0x50, 0x10, 0x00,
                                              0x00, 0x00, 0x00};

static const char *TAG = "csi_recv";
typedef struct {
  unsigned : 32; /**< reserved */
  unsigned : 32; /**< reserved */
  unsigned : 32; /**< reserved */
  unsigned : 32; /**< reserved */
  unsigned : 32; /**< reserved */
  unsigned : 16; /**< reserved */
  unsigned fft_gain : 8;
  unsigned agc_gain : 8;
  unsigned : 32; /**< reserved */
  unsigned : 32; /**< reserved */
  unsigned : 32; /**< reserved */
  unsigned : 32; /**< reserved */
  unsigned : 32; /**< reserved */
  unsigned : 32; /**< reserved */
} wifi_pkt_rx_ctrl_phy_t;

#if CONFIG_FORCE_GAIN
/**
 * @brief Enable/disable automatic fft gain control and set its value
 * @param[in] force_en true to disable automatic fft gain control
 * @param[in] force_value forced fft gain value
 */
extern void phy_fft_scale_force(bool force_en, uint8_t force_value);

/**
 * @brief Enable/disable automatic gain control and set its value
 * @param[in] force_en true to disable automatic gain control
 * @param[in] force_value forced gain value
 */
extern void phy_force_rx_gain(int force_en, int force_value);
#endif

static void wifi_event_handler(void *arg, esp_event_base_t event_base,
                               int32_t event_id, void *event_data);
static bool wifi_connected = false;

/// Wi-Fi Initialization
void wifi_init() {
  ESP_ERROR_CHECK(esp_event_loop_create_default());
  ESP_ERROR_CHECK(esp_netif_init());
  esp_netif_create_default_wifi_sta();

  wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
  ESP_ERROR_CHECK(esp_wifi_init(&cfg));

  ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
  ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));

  esp_event_handler_instance_t instance_any_id;
  esp_event_handler_instance_t instance_got_ip;
  ESP_ERROR_CHECK(esp_event_handler_instance_register(
      WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler, NULL,
      &instance_any_id));
  ESP_ERROR_CHECK(esp_event_handler_instance_register(
      IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event_handler, NULL,
      &instance_got_ip));

  // [3] YOUR CODE HERE
  // You need to modify the ssid and password to match your Wi-Fi network.
  wifi_config_t wifi_config = {
      .sta =
          {
              .ssid = WIFI_SSID,
              .password = WIFI_PASSWORD,
              .threshold.authmode = WIFI_AUTH_WPA2_PSK,
              // UPDATES: only use this scan method when you want to connect
              // your mobile phone's hotpot
              // .scan_method = DEFAULT_SCAN_METHOD,
              //

              .pmf_cfg = {.capable = true, .required = false},
          },
  };
  // [3] END OF YOUR CODE

  ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
  ESP_ERROR_CHECK(esp_wifi_start());
  ESP_LOGI(TAG, "wifi_init finished.");
}

//------------------------------------------------------WiFi Event
// Handler------------------------------------------------------
static void wifi_event_handler(void *arg, esp_event_base_t event_base,
                               int32_t event_id, void *event_data) {
  if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
    ESP_LOGI(TAG, "Trying to connect to AP...");
    esp_wifi_connect();
  } else if (event_base == WIFI_EVENT &&
             event_id == WIFI_EVENT_STA_DISCONNECTED) {
    ESP_LOGI(TAG, "Connection failed! Retrying...");
    wifi_connected = false;
    esp_wifi_connect();
  } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
    ip_event_got_ip_t *event = (ip_event_got_ip_t *)event_data;
    ESP_LOGI(TAG, "Got IP:" IPSTR, IP2STR(&event->ip_info.ip));
    wifi_connected = true;

    wifi_ap_record_t ap_info;
    if (esp_wifi_sta_get_ap_info(&ap_info) == ESP_OK) {
      ESP_LOGI(TAG, "Connected to AP - SSID: %s, Channel: %d, RSSI: %d",
               ap_info.ssid, ap_info.primary, ap_info.rssi);
    }
  }
}

/// ESP-NOW Initialization
static void initialize_esp_now() {
  ESP_ERROR_CHECK(esp_now_init());
  ESP_ERROR_CHECK(esp_now_set_pmk((uint8_t *)"pmk1234567890123"));
  ESP_LOGI(TAG, "================ ESP NOW Ready ================");
  ESP_LOGI(TAG, "esp_now_init finished.");
}

/// CSI Callback Function
static void wifi_csi_rx_cb(void *ctx, wifi_csi_info_t *info) {
  if (!info || !info->buf)
    return;

  ESP_LOGI(TAG, "CSI callback triggered");

  if (!info || !info->buf) {
    ESP_LOGW(TAG, "<%s> wifi_csi_cb", esp_err_to_name(ESP_ERR_INVALID_ARG));
    return;
  }

  ESP_LOGI(TAG, "Received MAC: " MACSTR ", Expected MAC: " MACSTR,
           MAC2STR(info->mac), MAC2STR(CONFIG_CSI_SEND_MAC));

  if (memcmp(info->mac, CONFIG_CSI_SEND_MAC, 6)) {
    ESP_LOGI(TAG, "MAC address doesn't match, skipping packet");
    return;
  }

  wifi_pkt_rx_ctrl_phy_t *phy_info = (wifi_pkt_rx_ctrl_phy_t *)info;
  static int s_count = 0;

  const wifi_pkt_rx_ctrl_t *rx_ctrl = &info->rx_ctrl;
  ets_printf("CSI_DATA,%d," MACSTR ",%d,%d,%d,%d,%d,%d,%d,%d,%d", s_count++,
             MAC2STR(info->mac), rx_ctrl->rssi, rx_ctrl->rate,
             rx_ctrl->noise_floor, phy_info->fft_gain, phy_info->agc_gain,
             rx_ctrl->channel, rx_ctrl->timestamp, rx_ctrl->sig_len,
             rx_ctrl->rx_state);
  ets_printf(",%d,%d,\"[%d", info->len, info->first_word_invalid, info->buf[0]);

  for (int i = 1; i < info->len; i++) {
    ets_printf(",%d", info->buf[i]);
  }
  ets_printf("]\"\n");
}

/// Connect to Wi-Fi
bool try_connect_to_wifi_with_timeout(int timeout) {
  int retry_count = 0;
  while (retry_count < timeout) {
    vTaskDelay(pdMS_TO_TICKS(1000));
    retry_count++;
    ESP_LOGI(TAG, "Waiting for Wi-Fi connection... (%d/%d)", retry_count,
             timeout);
    wifi_ap_record_t ap_info;
    if (esp_wifi_sta_get_ap_info(&ap_info) == ESP_OK) {
      ESP_LOGI(TAG, "Connected to SSID: %s, RSSI: %d, Channel: %d",
               ap_info.ssid, ap_info.rssi, ap_info.primary);
      return true;
    }
  }
  return false;
}

/// CSI Config Initialize
static void wifi_csi_init() {
  ESP_ERROR_CHECK(esp_wifi_set_promiscuous(true));
  wifi_csi_config_t csi_config = {.enable = true,
                                  .acquire_csi_legacy = false,
                                  .acquire_csi_force_lltf = false,
                                  .acquire_csi_ht20 = true,
                                  .acquire_csi_ht40 = true,
                                  .acquire_csi_vht = false,
                                  .acquire_csi_su = false,
                                  .acquire_csi_mu = false,
                                  .acquire_csi_dcm = false,
                                  .acquire_csi_beamformed = false,
                                  .acquire_csi_he_stbc_mode = 2,
                                  .val_scale_cfg = 0,
                                  .dump_ack_en = false,
                                  .reserved = false};
  ESP_ERROR_CHECK(esp_wifi_set_csi_config(&csi_config));
  ESP_ERROR_CHECK(esp_wifi_set_csi_rx_cb(wifi_csi_rx_cb, NULL));
  ESP_ERROR_CHECK(esp_wifi_set_csi(true));
}

void print_mac() {
  uint8_t mac[6];
  esp_err_t ret = esp_wifi_get_mac(WIFI_IF_STA, mac);
  if (ret == ESP_OK) {
    ESP_LOGI(TAG, "Device MAC Address: " MACSTR, MAC2STR(mac));
  } else {
    ESP_LOGE(TAG, "Failed to get MAC address: %s", esp_err_to_name(ret));
  }
}

void app_main() {
  // Initialize NVS
  esp_err_t ret = nvs_flash_init();
  if (ret == ESP_ERR_NVS_NO_FREE_PAGES ||
      ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
    ESP_ERROR_CHECK(nvs_flash_erase());
    ret = nvs_flash_init();
  }
  ESP_ERROR_CHECK(ret);

  wifi_init();
  print_mac();

#ifndef SKIP_WIFI_CONNECTION
  if (!try_connect_to_wifi_with_timeout(20)) {
    ESP_LOGE(TAG, "Failed to connect to Wi-Fi. Exiting...");
    return;
  }
#endif

  initialize_esp_now();
  wifi_csi_init();
}
