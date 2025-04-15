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
 * [1] Fill in the group information.
 *
 * Have fun building!
 */

#include "esp_log.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_now.h"
#include "esp_wifi.h"
#include "esp_wifi_types_generic.h"
#include "nvs_flash.h"
#include <unistd.h>

#include "credentials.h"

#define CONFIG_LESS_INTERFERENCE_CHANNEL 149
#define CONFIG_WIFI_BAND_MODE WIFI_BAND_MODE_5G_ONLY
#define CONFIG_WIFI_2G_BANDWIDTHS WIFI_BW_HT20
#define CONFIG_WIFI_5G_BANDWIDTHS WIFI_BW_HT20
#define CONFIG_WIFI_2G_PROTOCOL WIFI_PROTOCOL_11N
#define CONFIG_WIFI_5G_PROTOCOL WIFI_PROTOCOL_11N
#define CONFIG_ESP_NOW_PHYMODE WIFI_PHY_MODE_HT20
#define CONFIG_ESP_NOW_RATE WIFI_PHY_RATE_MCS0_LGI
#define CONFIG_SEND_FREQUENCY 100

#if CONFIG_EXAMPLE_WIFI_ALL_CHANNEL_SCAN
#define DEFAULT_SCAN_METHOD WIFI_ALL_CHANNEL_SCAN
#elif CONFIG_EXAMPLE_WIFI_FAST_SCAN
#define DEFAULT_SCAN_METHOD WIFI_FAST_SCAN
#else
#define DEFAULT_SCAN_METHOD WIFI_FAST_SCAN
#endif /*CONFIG_EXAMPLE_SCAN_METHOD*/

static const uint8_t CONFIG_CSI_SEND_MAC[] = {0x50, 0x10, 0x00,
                                              0x00, 0x00, 0x00};
static const char *TAG = "csi_send";

static void wifi_init() {
  ESP_ERROR_CHECK(esp_event_loop_create_default());
  ESP_ERROR_CHECK(esp_netif_init());
  esp_netif_create_default_wifi_sta();

  wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
  ESP_ERROR_CHECK(esp_wifi_init(&cfg));

  ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
  ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));

  // ESP_ERROR_CHECK(esp_wifi_start());
  // esp_wifi_set_band_mode(CONFIG_WIFI_BAND_MODE);
  // wifi_protocols_t protocols = {.ghz_2g = CONFIG_WIFI_2G_PROTOCOL,
  //                               .ghz_5g = CONFIG_WIFI_5G_PROTOCOL};
  // ESP_ERROR_CHECK(esp_wifi_set_protocols(ESP_IF_WIFI_STA, &protocols));
  // wifi_bandwidths_t bandwidth = {.ghz_2g = CONFIG_WIFI_2G_BANDWIDTHS,
  //                                .ghz_5g = CONFIG_WIFI_5G_BANDWIDTHS};
  // ESP_ERROR_CHECK(esp_wifi_set_bandwidths(ESP_IF_WIFI_STA, &bandwidth));
  // ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));

  // if ((CONFIG_WIFI_BAND_MODE == WIFI_BAND_MODE_2G_ONLY &&
  //      CONFIG_WIFI_2G_BANDWIDTHS == WIFI_BW_HT20) ||
  //     (CONFIG_WIFI_BAND_MODE == WIFI_BAND_MODE_5G_ONLY &&
  //      CONFIG_WIFI_5G_BANDWIDTHS == WIFI_BW_HT20)) {
  //   ESP_ERROR_CHECK(esp_wifi_set_channel(CONFIG_LESS_INTERFERENCE_CHANNEL,
  //                                        WIFI_SECOND_CHAN_NONE));
  // } else {
  //   ESP_ERROR_CHECK(esp_wifi_set_channel(CONFIG_LESS_INTERFERENCE_CHANNEL,
  //                                        WIFI_SECOND_CHAN_BELOW));
  // }
  ESP_ERROR_CHECK(esp_wifi_set_mac(WIFI_IF_STA, CONFIG_CSI_SEND_MAC));

  wifi_config_t wifi_config = {
      .sta =
          {
              .ssid = WIFI_SSID,
              .password = WIFI_PASSWORD,
              .threshold.authmode = AUTH_MODE,
              // enable the line below only when using a mobile hotspot
              .scan_method = DEFAULT_SCAN_METHOD,
              .pmf_cfg = {.capable = true, .required = false},
          },
  };

  ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
  ESP_ERROR_CHECK(esp_wifi_start());
  ESP_LOGI(TAG, "wifi_init finished.");
}

static void wifi_esp_now_init(esp_now_peer_info_t peer) {
  ESP_ERROR_CHECK(esp_now_init());
  ESP_ERROR_CHECK(esp_now_set_pmk((uint8_t *)"pmk1234567890123"));
  esp_now_rate_config_t rate_config = {.phymode = CONFIG_ESP_NOW_PHYMODE,
                                       .rate = CONFIG_ESP_NOW_RATE,
                                       .ersu = false,
                                       .dcm = false};
  ESP_ERROR_CHECK(esp_now_add_peer(&peer));
  ESP_ERROR_CHECK(esp_now_set_peer_rate_config(peer.peer_addr, &rate_config));
}

bool try_connect_to_wifi_with_timeout(int timeout, wifi_ap_record_t *ap_info) {
  int retry_count = 0;
  while (retry_count < timeout) {
    vTaskDelay(pdMS_TO_TICKS(1000));
    retry_count++;
    ESP_LOGI(TAG, "Waiting for Wi-Fi connection... (%d/%d)", retry_count,
             timeout);
    if (esp_wifi_sta_get_ap_info(ap_info) == ESP_OK) {
      ESP_LOGI(TAG, "Connected to SSID: %s, RSSI: %d, Channel: %d",
               ap_info->ssid, ap_info->rssi, ap_info->primary);
      return true;
    }
  }
  return false;
}

void app_main() {
  /**
   * @breif Initialize NVS
   */
  esp_err_t ret = nvs_flash_init();
  if (ret == ESP_ERR_NVS_NO_FREE_PAGES ||
      ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
    ESP_ERROR_CHECK(nvs_flash_erase());
    ret = nvs_flash_init();
  }
  ESP_ERROR_CHECK(ret);

  wifi_init();

  wifi_ap_record_t ap_info = {0};
  if (!try_connect_to_wifi_with_timeout(20, &ap_info)) {
    ESP_LOGE(TAG, "Failed to connect to Wi-Fi. Exiting...");
    return;
  }

  ESP_LOGI(TAG, "Channel is %d", ap_info.primary);

  // Initialize ESP-NOW
  esp_now_peer_info_t peer = {
      .channel = CONFIG_LESS_INTERFERENCE_CHANNEL,
      .ifidx = WIFI_IF_STA,
      .encrypt = false,
      .peer_addr = {0xff, 0xff, 0xff, 0xff, 0xff, 0xff},
  };
  wifi_esp_now_init(peer);

  // Get Device MAC Address
  uint8_t mac[6];
  esp_wifi_get_mac(WIFI_IF_STA, mac);

  ESP_LOGI(TAG, "================ CSI SEND ================");
  ESP_LOGI(TAG, "wifi_channel: %d, send_frequency: %d, mac: " MACSTR,
           CONFIG_LESS_INTERFERENCE_CHANNEL, CONFIG_SEND_FREQUENCY,
           MAC2STR(mac));

  for (uint8_t count = 0;; ++count) {
    // 使用 ESP-NOW 发送数据包，触发 RX 端采集 CSI 数据
    esp_err_t ret = esp_now_send(peer.peer_addr, &count, sizeof(uint8_t));
    // ESP_LOGI(TAG, "sending with count: %d", count);
    if (ret != ESP_OK) {
      ESP_LOGW(TAG, "free_heap: %ld <%s> ESP-NOW send error",
               esp_get_free_heap_size(), esp_err_to_name(ret));
    }
    // 控制发送频率，确保 TX 与 RX 端在相同信道下进行同步采集
    usleep(1000000 / CONFIG_SEND_FREQUENCY);
  }
}
