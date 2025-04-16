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
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "freertos/queue.h"
#include "freertos/task.h"

#include "credentials.h"

#define CONFIG_WIFI_BAND_MODE WIFI_BAND_MODE_2G_ONLY
#define CONFIG_WIFI_2G_BANDWIDTHS WIFI_BW_HT20
#define CONFIG_WIFI_5G_BANDWIDTHS WIFI_BW_HT20
#define CONFIG_WIFI_2G_PROTOCOL WIFI_PROTOCOL_11N
#define CONFIG_WIFI_5G_PROTOCOL WIFI_PROTOCOL_11N
#define CONFIG_ESP_NOW_PHYMODE WIFI_PHY_MODE_HT20
#define CONFIG_ESP_NOW_RATE WIFI_PHY_RATE_MCS0_LGI
#define CONFIG_FORCE_GAIN 1
#define CONFIG_GAIN_CONTROL CONFIG_FORCE_GAIN

#if CONFIG_EXAMPLE_WIFI_ALL_CHANNEL_SCAN
#define DEFAULT_SCAN_METHOD WIFI_ALL_CHANNEL_SCAN
#elif CONFIG_EXAMPLE_WIFI_FAST_SCAN
#define DEFAULT_SCAN_METHOD WIFI_FAST_SCAN
#else
#define DEFAULT_SCAN_METHOD WIFI_FAST_SCAN
#endif /*CONFIG_EXAMPLE_SCAN_METHOD*/

static const uint8_t CONFIG_CSI_SEND_MAC[] = {0x50, 0x10, 0x00,
                                              0x00, 0x00, 0x00};

static const char *TAG = "csi_recv";

static esp_mqtt_client_handle_t mqtt_client = NULL;

typedef struct {
  char data[2048];
} csi_data_t;

// Create a queue to hold CSI data
static QueueHandle_t csi_queue = NULL;
#define CSI_QUEUE_SIZE 10 // Adjust based on memory constraints and data rate

static void csi_processing_task(void *pvParameters) {
  csi_data_t csi_item;

  while (1) {
    // Add a timeout to avoid blocking indefinitely
    if (xQueueReceive(csi_queue, &csi_item, pdMS_TO_TICKS(1000)) == pdTRUE) {
      if (mqtt_client != NULL) {
        esp_mqtt_client_publish(mqtt_client, "esp32/csi", csi_item.data, 0, 1,
                                0);
        // ESP_LOGI(TAG, "CSI data sent to MQTT");
      } else {
        ESP_LOGW(TAG, "MQTT client not ready, discarding CSI data");
      }
    }
    // Always include this delay to prevent watchdog timeouts
    vTaskDelay(pdMS_TO_TICKS(10));
  }
}

static void mqtt_send(esp_mqtt_client_handle_t client, const char *data) {
  if (client != NULL) {
    esp_mqtt_client_publish(client, "esp32/csi", data, 0, 1, 0);
  } else {
    ESP_LOGE(TAG, "MQTT client is NULL. Cannot send data.");
  }
}

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
  if (!info || !info->buf) {
    return;
  }

  if (memcmp(info->mac, CONFIG_CSI_SEND_MAC, 6)) {
    return;
  }

  static int sample_counter = 0;
  if (sample_counter++ % 5 != 0) {
    return;
  }

  static int s_count = 0;

  ESP_LOGI(TAG, "CSI data received: %d", s_count);

  const wifi_pkt_rx_ctrl_t *rx_ctrl = &info->rx_ctrl;

  // Create an item to add to the queue
  csi_data_t csi_item;
  memset(csi_item.data, 0, sizeof(csi_item.data));

  // Format the CSI data string
  char *ptr = csi_item.data;
  int remaining = sizeof(csi_item.data) - 1;

  wifi_pkt_rx_ctrl_phy_t *phy_info = (wifi_pkt_rx_ctrl_phy_t *)info;
  int written = snprintf(
      ptr, remaining, "CSI_DATA,%d," MACSTR ",%d,%d,%d,%d,%d,%d,%d,%d,%d",
      s_count++, MAC2STR(info->mac), rx_ctrl->rssi, rx_ctrl->rate,
      rx_ctrl->noise_floor, phy_info->fft_gain, phy_info->agc_gain,
      rx_ctrl->channel, rx_ctrl->timestamp, rx_ctrl->sig_len,
      rx_ctrl->rx_state);

  ptr += written;
  remaining -= written;

  // Add the second part
  written = snprintf(ptr, remaining, ",%d,%d,\"[%d", info->len,
                     info->first_word_invalid, info->buf[0]);
  ptr += written;
  remaining -= written;

  // Add the array values
  for (int i = 1; i < info->len && remaining > 0; i++) {
    written = snprintf(ptr, remaining, ",%d", info->buf[i]);
    ptr += written;
    remaining -= written;
  }

  // Add closing brackets
  written = snprintf(ptr, remaining, "]\"");


  // Try to add the item to the queue without blocking
  if (xQueueSend(csi_queue, &csi_item, 0) != pdTRUE) {
    ESP_LOGW(TAG, "CSI queue full, discarding data");
  }
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

void print_mac_addr() {
  uint8_t mac[6];
  esp_err_t ret = esp_wifi_get_mac(WIFI_IF_STA, mac);
  if (ret == ESP_OK) {
    ESP_LOGI(TAG, "Device MAC Address: " MACSTR, MAC2STR(mac));
  } else {
    ESP_LOGE(TAG, "Failed to get MAC address: %s", esp_err_to_name(ret));
  }
}

static void log_error_if_nonzero(const char *message, int error_code) {
  if (error_code != 0) {
    ESP_LOGE(TAG, "Last error %s: 0x%x", message, error_code);
  }
}

/*
 * @brief Event handler registered to receive MQTT events
 *
 *  This function is called by the MQTT client event loop.
 *
 * @param handler_args user data registered to the event.
 * @param base Event base for the handler(always MQTT Base in this example).
 * @param event_id The id for the received event.
 * @param event_data The data for the event, esp_mqtt_event_handle_t.
 */
static void mqtt_event_handler(void *handler_args, esp_event_base_t base,
                               int32_t event_id, void *event_data) {
  ESP_LOGD(TAG,
           "Event dispatched from event loop base=%s, event_id=%" PRIi32 "",
           base, event_id);
  esp_mqtt_event_handle_t event = event_data;
  esp_mqtt_client_handle_t client = event->client;
  switch ((esp_mqtt_event_id_t)event_id) {
  case MQTT_EVENT_CONNECTED:
    ESP_LOGI(TAG, "MQTT_EVENT_CONNECTED");
    // esp_mqtt_client_publish(client, "esp32/csi", "esp32 connected!", 0, 1,
    // 0);
    // mqtt_send(client, "esp32 connected!");
    // esp_mqtt_client_subscribe(client, "esp32/csi", 0);
    break;
  case MQTT_EVENT_DISCONNECTED:
    ESP_LOGI(TAG, "MQTT_EVENT_DISCONNECTED");
    break;
  case MQTT_EVENT_SUBSCRIBED:
    ESP_LOGI(TAG, "MQTT_EVENT_SUBSCRIBED, msg_id=%d", event->msg_id);
    break;
  case MQTT_EVENT_UNSUBSCRIBED:
    ESP_LOGI(TAG, "MQTT_EVENT_UNSUBSCRIBED, msg_id=%d", event->msg_id);
    break;
  case MQTT_EVENT_PUBLISHED:
    // ESP_LOGI(TAG, "MQTT_EVENT_PUBLISHED, msg_id=%d", event->msg_id);
    break;
  case MQTT_EVENT_DATA:
    ESP_LOGI(TAG, "MQTT_EVENT_DATA");
    printf("TOPIC=%.*s\r\n", event->topic_len, event->topic);
    printf("DATA=%.*s\r\n", event->data_len, event->data);
    break;
  case MQTT_EVENT_ERROR:
    ESP_LOGI(TAG, "MQTT_EVENT_ERROR");
    if (event->error_handle->error_type == MQTT_ERROR_TYPE_TCP_TRANSPORT) {
      log_error_if_nonzero("reported from esp-tls",
                           event->error_handle->esp_tls_last_esp_err);
      log_error_if_nonzero("reported from tls stack",
                           event->error_handle->esp_tls_stack_err);
      log_error_if_nonzero("captured as transport's socket errno",
                           event->error_handle->esp_transport_sock_errno);
      ESP_LOGI(TAG, "Last errno string (%s)",
               strerror(event->error_handle->esp_transport_sock_errno));
    }
    break;
  default:
    ESP_LOGI(TAG, "Other event id:%d", event->event_id);
    break;
  }
}

esp_mqtt_client_handle_t mqtt_app_start(void) {
  esp_mqtt_client_config_t mqtt_cfg = {
      .broker.address.uri = COMPUTER_IP,
  };
  esp_mqtt_client_handle_t client = esp_mqtt_client_init(&mqtt_cfg);
  /* The last argument may be used to pass data to the event handler, in this
   * example mqtt_event_handler */
  esp_mqtt_client_register_event(client, ESP_EVENT_ANY_ID, mqtt_event_handler,
                                 NULL);
  esp_mqtt_client_start(client);
  return client;
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

  // Create CSI data queue
  csi_queue = xQueueCreate(CSI_QUEUE_SIZE, sizeof(csi_data_t));
  if (csi_queue == NULL) {
    ESP_LOGE(TAG, "Failed to create CSI queue");
    return;
  }

  // Create task to process CSI data
  xTaskCreate(csi_processing_task, "csi_proc", 81920, NULL, 5, NULL);

  wifi_init();
  print_mac_addr();

  if (!try_connect_to_wifi_with_timeout(20)) {
    ESP_LOGE(TAG, "Failed to connect to Wi-Fi. Exiting...");
    return;
  }

  initialize_esp_now();
  wifi_csi_init();

  // Initialize MQTT client and store handle in global variable
  mqtt_client = mqtt_app_start();
}
