# =============================================================================
# verify.ps1 — เวอร์ชัน PowerShell ของ verify.sh (สำหรับ Windows ที่ไม่มี WSL/bash)
#   1) LiteLLM ตอบและ "big-brain" ทะลุถึง provider จริง
#   2) HexStrike server (:8888) มีชีวิต
#   3) HexStrike MCP (:8001) endpoint ตอบ
# ใช้:  powershell -ExecutionPolicy Bypass -File pipeline\verify.ps1
#   หรือ  .\verify.ps1   (ถ้า execution policy อนุญาต)
# =============================================================================
$ErrorActionPreference = "SilentlyContinue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$litellm = if ($env:LITELLM_URL) { $env:LITELLM_URL } else { "http://localhost:4000" }
$mcpUrl  = if ($env:MCP_URL)     { $env:MCP_URL }     else { "http://localhost:8001/mcp" }
$hxHealth = if ($env:HX_HEALTH)  { $env:HX_HEALTH }   else { "http://localhost:8888/health" }

$script:pass = 0; $script:fail = 0
function Ok($m)  { Write-Host "  [OK] $m"   -ForegroundColor Green; $script:pass++ }
function No($m)  { Write-Host "  [XX] $m"   -ForegroundColor Red;   $script:fail++ }

Write-Host "-- 1. LiteLLM (provider switch) -------------------------"
$live = try { Invoke-WebRequest "$litellm/health/liveliness" -UseBasicParsing -TimeoutSec 5 } catch { $null }
if (-not $live) { $live = try { Invoke-WebRequest "$litellm/v1/models" -UseBasicParsing -TimeoutSec 5 } catch { $null } }
if ($live) {
    Ok "LiteLLM ตอบที่ $litellm"
    Write-Host "  -> ยิง big-brain ผ่าน provider จริง (ใช้ key ใน .env)..."
    # max_tokens สูงหน่อย: deepseek-v4-flash เป็น reasoning model ถ้าน้อยเกินจะใช้ token
    # ไปกับการคิดจนหมดก่อนพ่น content -> content ว่างทั้งที่ provider ตอบสำเร็จ
    $body = @{ model="big-brain"; messages=@(@{role="user";content="reply with the single word: ok"}); max_tokens=256 } | ConvertTo-Json -Depth 5
    $r = try {
        Invoke-RestMethod "$litellm/v1/chat/completions" -Method Post -ContentType "application/json" -Body $body -TimeoutSec 90
    } catch { $null }
    if ($r -and $r.choices) {
        # ผ่านทันทีถ้าได้ completion object กลับมา (provider ทะลุ) content จะว่างก็ได้
        Ok "big-brain ทะลุถึง provider (ได้ completion กลับมา)"
        $msg = $r.choices[0].message
        $txt = if ($msg.content) { $msg.content } elseif ($msg.reasoning_content) { "[reasoning] " + $msg.reasoning_content } else { "(content ว่าง — reasoning model, แต่ tunnel ใช้ได้)" }
        $txt = ($txt -replace "`n"," ")
        Write-Host ("     " + $txt.Substring(0, [Math]::Min(140, $txt.Length)))
    } else {
        No "big-brain ยังไม่ทะลุ — เช็คชื่อโมเดลใน litellm-config.yaml / key ใน .env"
    }
} else {
    No "LiteLLM ไม่ตอบที่ $litellm (ยังไม่ได้ up? port ผิด?)"
}

Write-Host "-- 2. HexStrike server (tools) --------------------------"
$h = try { Invoke-RestMethod $hxHealth -TimeoutSec 8 } catch { $null }
if ($h -and ($h.status -or $h.version)) {
    Ok "server :8888 มีชีวิต (status=$($h.status))"
    if ($null -ne $h.all_essential_tools_available) {
        Write-Host "     all_essential_tools_available = $($h.all_essential_tools_available)"
    }
} else {
    No "server ไม่ตอบที่ $hxHealth (--profile full ขึ้นหรือยัง?)"
}

Write-Host "-- 3. HexStrike MCP endpoint ----------------------------"
# MCP streamable-http: แค่เช็คว่า port ตอบ (400/406 = มีชีวิต, refused = ยังไม่ขึ้น)
$code = $null
try {
    $resp = Invoke-WebRequest $mcpUrl -Method Post -UseBasicParsing -TimeoutSec 8 `
        -Headers @{ "Accept" = "application/json, text/event-stream" } `
        -ContentType "application/json" -Body '{"jsonrpc":"2.0","id":1,"method":"ping"}'
    $code = $resp.StatusCode
} catch {
    if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode }
}
if ($code) { Ok "MCP endpoint ตอบ (HTTP $code) ที่ $mcpUrl" }
else       { No "MCP endpoint ไม่ตอบที่ $mcpUrl (hexstrike-mcp container ขึ้นหรือยัง?)" }

Write-Host "---------------------------------------------------------"
Write-Host "ผ่าน $script:pass / ล้มเหลว $script:fail"
if ($script:fail -eq 0) { Write-Host "พร้อมไปเปิด Console: http://localhost:3000" -ForegroundColor Green }
else                    { Write-Host "แก้ที่ [XX] ก่อน แล้วรันซ้ำ" -ForegroundColor Yellow }
exit $script:fail
