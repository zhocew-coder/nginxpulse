#!/bin/bash
# Security fix verification script
export PYTHONPATH=/home/joyce/workspace/nginxpulse/forecast-service
cd /home/joyce/workspace/nginxpulse/forecast-service

PY=/home/joyce/miniconda3/envs/workbuddy/bin/python

# Start server
$PY -m uvicorn app.api.main:app --host 127.0.0.1 --port 18123 &
SERVER_PID=$!
sleep 3

BASE="http://127.0.0.1:18123/api/forecast/v1"

echo "=== 1. CORS evil.com ==="
ORIG=$(curl -sI --noproxy '*' --max-time 5 -H "Origin: http://evil.com" "$BASE/eligibility/rules" | grep -i "access-control-allow-origin")
if [ -z "$ORIG" ]; then echo "PASS - No CORS header for evil.com"; else echo "FAIL - Got: $ORIG"; fi

echo "=== 2. CORS legit ==="
ORIG=$(curl -sI --noproxy '*' --max-time 5 -H "Origin: http://localhost:8088" "$BASE/eligibility/rules" | grep -i "access-control-allow-origin")
if [ -n "$ORIG" ]; then echo "PASS - $ORIG"; else echo "FAIL - No CORS header for legit origin"; fi

echo "=== 3. Empty app_name ==="
RESP=$(curl -s --noproxy '*' --max-time 5 -X POST "$BASE/eligibility/evaluate" -H "Content-Type: application/json" -d '{"app_name":"","uri_template":""}')
echo "Response: $RESP"

echo "=== 4. Invalid horizon ==="
RESP=$(curl -s --noproxy '*' --max-time 5 -X POST "$BASE/predict" -H "Content-Type: application/json" -d '{"app_name":"core-banking","horizon":"abc"}')
echo "Response: $RESP"

echo "=== 5. Empty question ==="
RESP=$(curl -s --noproxy '*' --max-time 5 -X POST "$BASE/agent/chat" -H "Content-Type: application/json" -d '{"question":""}')
echo "Response: $RESP"

echo "=== 6. History endpoint ==="
RESP=$(curl -s --noproxy '*' --max-time 5 "$BASE/history?app_name=core-banking&hours=1")
echo "$RESP" | head -c 200

echo ""
echo "=== 7. Body size limit ==="
$PY -c "import json; print(json.dumps({'app_name':'x'*2000000}))" > /home/joyce/workspace/.tmp/big.json
RESP=$(curl -s --noproxy '*' --max-time 5 -X POST "$BASE/eligibility/evaluate" -H "Content-Type: application/json" -d @/home/joyce/workspace/.tmp/big.json)
echo "Response: $RESP"

echo ""
echo "=== 8. Predict still works ==="
RESP=$(curl -s --noproxy '*' --max-time 60 -X POST "$BASE/predict" -H "Content-Type: application/json" -d '{"app_name":"core-banking","horizon":"24h"}')
echo "$RESP" | $PY -c "import sys,json; d=json.load(sys.stdin); print(f'forecast_id={d.get(\"forecast_id\",\"ERR\")} model={d.get(\"model\",\"ERR\")} points={len(d.get(\"points\",[]))}')" 2>/dev/null || echo "ERROR: $RESP" | head -c 200

kill $SERVER_PID 2>/dev/null
echo ""
echo "=== DONE ==="
