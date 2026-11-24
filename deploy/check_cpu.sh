#!/usr/bin/env bash
# Đo CPU/nhiệt độ/RAM trên Pi khi chạy chatbot. Chạy:  bash check_cpu.sh [số_giây=30]
# Trong lúc script chạy, hãy gửi vài câu từ app (cả câu thường lẫn câu phải dùng LLM).
DUR=${1:-30}

echo "== Dịch vụ =="
for s in ollama chatbot face-door; do
  printf "%-10s %s\n" "$s" "$(systemctl is-active $s 2>/dev/null)"
done
echo
echo "== Giới hạn đang áp dụng cho ollama =="
systemctl show ollama -p CPUAffinity -p CPUQuotaPerSecUSec -p Nice -p MemoryMax 2>/dev/null
echo
echo "== Model đang nạp =="
ollama ps 2>/dev/null || echo "(không gọi được ollama)"
echo
echo "== RAM =="
free -h | head -2
echo
echo "== Theo dõi ${DUR}s: CPU tổng, từng nhân, nhiệt độ, throttle =="
printf "%-8s %6s  %-23s %6s %s\n" "giờ" "CPU%" "nhân0/1/2/3 (%)" "°C" "throttle"
prev=$(grep '^cpu' /proc/stat)
for ((i=0; i<DUR; i++)); do
  sleep 1
  cur=$(grep '^cpu' /proc/stat)
  out=$(paste <(echo "$prev") <(echo "$cur") | awk '{
      n=(NF/2); t1=0;t2=0; for(j=2;j<=n;j++){t1+=$j}; for(j=n+2;j<=NF;j++){t2+=$j};
      i1=$5+$6; i2=$(n+5)+$(n+6); d=t2-t1; p=(d>0)?100*(1-(i2-i1)/d):0;
      printf "%s:%.0f ", $1, p }')
  prev=$cur
  tot=$(echo "$out" | grep -o 'cpu:[0-9]*' | cut -d: -f2)
  cores=$(echo "$out" | grep -o 'cpu[0-9]:[0-9]*' | cut -d: -f2 | paste -sd/)
  temp=$(awk '{printf "%.1f", $1/1000}' /sys/class/thermal/thermal_zone0/temp)
  thr=$(vcgencmd get_throttled 2>&1 | grep -o 'throttled=0x[0-9a-fA-F]*' | cut -d= -f2)
  printf "%-8s %6s  %-23s %6s %s\n" "$(date +%T)" "$tot" "$cores" "$temp" "${thr:--}"
done
echo
echo "== Top tiến trình =="
ps -eo pid,psr,ni,pcpu,pmem,comm --sort=-pcpu | head -8
echo
echo "Gợi ý đọc kết quả: nhân 2-3 lên cao khi LLM chạy là đúng; nhân 0-1 phải còn trống cho face-door."
echo "throttle khác 0x0 nghĩa là Pi đã bị hạ xung (nóng hoặc thiếu nguồn) -> cần tản nhiệt/nguồn 5V5A."
