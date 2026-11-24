#!/usr/bin/env bash
# Cài Mosquitto làm broker MQTT chính trên Raspberry Pi + cầu nối lên HiveMQ Cloud.
# Chạy:  cd ~/code/chatbot/deploy/mosquitto && sudo bash setup_mosquitto.sh
# Chạy lại nhiều lần vẫn an toàn (ghi đè cấu hình cũ).
set -euo pipefail
cd "$(dirname "$0")"
[ "$(id -u)" -eq 0 ] || { echo "Hãy chạy bằng sudo."; exit 1; }

echo "== 1. Cài Mosquitto =="
if ! command -v mosquitto >/dev/null; then
  apt-get update -qq && apt-get install -y mosquitto mosquitto-clients
fi
mosquitto -h 2>&1 | head -1

echo
echo "== 2. Mật khẩu =="
# Mật khẩu HiveMQ: lấy sẵn từ file env cũ của face-door/chatbot nếu có
HIVEMQ_PW=""
for f in /etc/chatbot.env /etc/face-door.env; do
  if [ -z "$HIVEMQ_PW" ] && [ -f "$f" ]; then
    HIVEMQ_PW=$(grep -E '^MQTT_PASSWORD=' "$f" | head -1 | cut -d= -f2- || true)
    [ -n "$HIVEMQ_PW" ] && echo "Dùng mật khẩu HiveMQ có sẵn trong $f"
  fi
done
if [ -z "$HIVEMQ_PW" ]; then
  read -rsp "Mật khẩu HiveMQ Cloud (user hvt): " HIVEMQ_PW; echo
fi
# Mật khẩu cho app Android: PHẢI giống LOCAL_PASSWORD trong MqttHandler.java
APP_PW_DEFAULT="SmartHome@Pi2026"
read -rp "Mật khẩu tài khoản 'app' cho app Android [Enter = $APP_PW_DEFAULT]: " APP_PW || true
APP_PW=${APP_PW:-$APP_PW_DEFAULT}
# Mật khẩu cho các script trên Pi: sinh ngẫu nhiên, chỉ lưu trong /etc/smarthome-mqtt.env
PI_PW=$(head -c 18 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 20)

echo
echo "== 3. Tài khoản + phân quyền =="
mosquitto_passwd -c -b /etc/mosquitto/passwd pi "$PI_PW"
mosquitto_passwd -b /etc/mosquitto/passwd app "$APP_PW"
install -m 640 -o root -g mosquitto acl /etc/mosquitto/acl
chown root:mosquitto /etc/mosquitto/passwd && chmod 640 /etc/mosquitto/passwd
echo "Tạo tài khoản: pi (script trên Pi), app (Android)"

echo
echo "== 4. Cấu hình broker + cầu nối HiveMQ =="
install -m 644 smarthome.conf /etc/mosquitto/conf.d/smarthome.conf
# thay mật khẩu bằng python để không vỡ khi mật khẩu có ký tự đặc biệt (@ / & ...)
HIVEMQ_PW="$HIVEMQ_PW" python3 - <<'PY'
import os
s = open("hivemq-bridge.conf.template", encoding="utf-8").read()
s = s.replace("__HIVEMQ_USER__", "hvt").replace("__HIVEMQ_PASSWORD__", os.environ["HIVEMQ_PW"])
open("/etc/mosquitto/conf.d/hivemq-bridge.conf", "w", encoding="utf-8").write(s)
PY
chown root:mosquitto /etc/mosquitto/conf.d/hivemq-bridge.conf && chmod 640 /etc/mosquitto/conf.d/hivemq-bridge.conf

echo
echo "== 5. File cấu hình chung cho gateway / face-door / chatbot =="
PI_PW="$PI_PW" python3 - <<'PY'
import os
s = open("smarthome-mqtt.env.template", encoding="utf-8").read().replace("__PI_PASSWORD__", os.environ["PI_PW"])
open("/etc/smarthome-mqtt.env", "w", encoding="utf-8").write(s)
PY
chmod 600 /etc/smarthome-mqtt.env
echo "Đã ghi /etc/smarthome-mqtt.env"

if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
  ufw allow 1883/tcp comment "MQTT trong nhà" >/dev/null && echo "Đã mở cổng 1883 trên tường lửa ufw"
fi

echo
echo "== 6. Khởi động Mosquitto =="
systemctl enable mosquitto >/dev/null 2>&1
systemctl restart mosquitto
sleep 2
if ! systemctl is-active --quiet mosquitto; then
  echo "LỖI: Mosquitto không chạy. Xem: journalctl -u mosquitto -n 30 --no-pager"; exit 1
fi
echo "Mosquitto đang chạy."

echo
echo "== 7. Tự kiểm tra =="
OUT=$(timeout 3 mosquitto_sub -h 127.0.0.1 -u pi -P "$PI_PW" -t selftest/ping -C 1 & sleep 0.5; \
      mosquitto_pub -h 127.0.0.1 -u pi -P "$PI_PW" -t selftest/ping -m ok; wait) || true
[ "$OUT" = "ok" ] && echo "✔ Broker trong nhà hoạt động" || echo "✘ Không gửi/nhận được tin trên broker trong nhà"
LINK=$(timeout 15 mosquitto_sub -h 127.0.0.1 -u pi -P "$PI_PW" -t smarthome/pi/cloud_link -C 1 || true)
case "$LINK" in
  1) echo "✔ Cầu nối HiveMQ: ĐÃ NỐI (app ở ngoài nhà vẫn điều khiển được)";;
  0) echo "⚠ Cầu nối HiveMQ: CHƯA NỐI (không có Internet hoặc sai mật khẩu HiveMQ). Nhà vẫn chạy trong mạng LAN.";;
  *) echo "⚠ Chưa thấy trạng thái cầu nối. Xem: journalctl -u mosquitto -n 30 --no-pager";;
esac

echo
echo "== XONG. Việc tiếp theo =="
echo "1) Thêm dòng sau vào CUỐI phần [Service] của face-door.service, chatbot.service và service của gateway:"
echo "     EnvironmentFile=-/etc/smarthome-mqtt.env"
echo "   rồi: sudo systemctl daemon-reload && sudo systemctl restart face-door chatbot <gateway>"
echo "2) Địa chỉ IP của Pi (app tự tìm, nếu cần nhập tay trong Cài đặt > Kết nối MQTT & Gateway):"
hostname -I | tr ' ' '\n' | grep -E '^(10|172|192)\.' | sed 's/^/     /'
echo "3) Kiểm tra toàn hệ thống: bash test_offline.sh"
echo "Quay về HiveMQ như cũ: sudo rm /etc/smarthome-mqtt.env rồi restart các service."
