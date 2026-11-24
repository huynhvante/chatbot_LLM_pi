#!/usr/bin/env bash
# Kiểm tra hệ thống chạy qua Mosquitto trên Pi. Chạy: sudo bash test_offline.sh
# Thử 2 lần: lúc có Internet và lúc đã TẮT 4G/rút mạng (hotspot vẫn bật) -> kết quả mục 1-4 phải giống nhau.
set -u
[ -f /etc/smarthome-mqtt.env ] || { echo "Chưa có /etc/smarthome-mqtt.env (chạy setup_mosquitto.sh trước)"; exit 1; }
set -a; . /etc/smarthome-mqtt.env; set +a
A=(-h 127.0.0.1 -u "$MQTT_USERNAME" -P "$MQTT_PASSWORD")
ok(){ echo "  ✔ $*"; }; bad(){ echo "  ✘ $*"; }

echo "== Internet =="
if timeout 3 bash -c 'exec 3<>/dev/tcp/1.1.1.1/53' 2>/dev/null; then echo "  Pi ĐANG có Internet"; else echo "  Pi KHÔNG có Internet (đúng kịch bản demo offline)"; fi

echo "== 1. Broker trong nhà =="
systemctl is-active --quiet mosquitto && ok "mosquitto đang chạy" || bad "mosquitto KHÔNG chạy"

echo "== 2. Các script đã nối vào broker trong nhà =="
for t in "home/gateway/status:gateway" "smarthome/chatbot/status:chatbot"; do
  v=$(timeout 3 mosquitto_sub "${A[@]}" -t "${t%%:*}" -C 1 2>/dev/null)
  [ "$v" = "online" ] && ok "${t##*:}: online" || bad "${t##*:}: '${v:-không có tin}' (service đã thêm EnvironmentFile và restart chưa?)"
done
n=$(ss -tn state established '( sport = :1883 )' 2>/dev/null | tail -n +2 | wc -l)
echo "  Số kết nối tới cổng 1883: $n (gateway + face-door + chatbot + app đang mở)"

echo "== 3. Chatbot trả lời qua broker trong nhà =="
id="test$RANDOM"
r=$(timeout 15 mosquitto_sub "${A[@]}" -t smarthome/chatbot/response -C 1 2>/dev/null & sleep 0.5; \
    mosquitto_pub "${A[@]}" -t smarthome/chatbot/request -m "{\"id\":\"$id\",\"text\":\"trạng thái cả nhà\"}"; wait)
echo "$r" | grep -q "$id" && ok "chatbot trả lời: $(echo "$r" | python3 -c 'import sys,json;print(json.load(sys.stdin)["reply"].splitlines()[0])' 2>/dev/null)" \
  || bad "chatbot không trả lời trong 15s"

echo "== 4. Phân quyền: tài khoản app KHÔNG được giả lệnh mở cửa face_unlock =="
read -rp "  Mật khẩu tài khoản app [Enter = SmartHome@Pi2026]: " APW; APW=${APW:-SmartHome@Pi2026}
got=$(timeout 3 mosquitto_sub "${A[@]}" -t home/livingroom/door/face_unlock -C 1 2>/dev/null & sleep 0.5; \
      mosquitto_pub -h 127.0.0.1 -u app -P "$APW" -t home/livingroom/door/face_unlock -m TEST_KHONG_MO 2>/dev/null; wait)
[ -z "$got" ] && ok "bị chặn đúng (ACL)" || bad "KHÔNG bị chặn: kiểm tra /etc/mosquitto/acl"

echo "== 5. Cầu nối HiveMQ =="
l=$(timeout 3 mosquitto_sub "${A[@]}" -t smarthome/pi/cloud_link -C 1 2>/dev/null)
case "$l" in 1) ok "đã nối (app ở xa dùng được)";; 0) echo "  - chưa nối (bình thường nếu đang tắt Internet)";; *) bad "không rõ";; esac

echo "== IP để app kết nối trong nhà =="
hostname -I | tr ' ' '\n' | grep -E '^(10|172|192)\.' | sed 's/^/  /'
