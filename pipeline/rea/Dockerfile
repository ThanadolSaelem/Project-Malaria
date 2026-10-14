# =============================================================================
# REA (Reverse Engineer Anything) — MCP server + full RE toolchain (arm64-native)
# -----------------------------------------------------------------------------
# REA (github.com/morluto/rea, npm rea-agents) เป็น MCP server ให้ agent (Tiel)
# แกะ: binary (Ghidra), APK/Android (apktool+JADX), JS/Electron, .NET, WASM,
# firmware (binwalk/unblob), เว็บไซต์ (Chrome CDP), พฤติกรรม runtime
#
# REA พูด MCP แบบ stdio เท่านั้น → ครอบด้วย supergateway แปลงเป็น streamable-HTTP
# ให้ HarnessRouter ต่อด้วย url เดียว:  http://rea-mcp:8007/mcp
#
# ⚠️ base = Ubuntu 24.04 (ไม่ใช่ node:debian) เพราะ REA ตรวจ host แล้วปฏิเสธ
#    Debian 12 (unsupported_host). REA รองรับ: macOS 12+, Ubuntu 24.04+, Fedora 41+,
#    Arch ฯลฯ → Ubuntu 24.04 ทำให้ `rea doctor` host ผ่าน
#
# ออกแบบ "ทนพลาด": tool หนัก (Ghidra/binwalk/unblob/jadx) ถ้าลงไม่สำเร็จจะข้าม
# (WARN) ไม่ล้ม build — REA มี readiness ต่อ provider (rea doctor) รายงานเอง
# image ใหญ่/build นาน → profile "full" (opt-in). IDA/Hopper (commercial/GUI) ไม่ลง
# =============================================================================
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_BREAK_SYSTEM_PACKAGES=1

# ── ชั้น 1: base + Node 22 (NodeSource) + python + cargo(สำหรับ binwalk) + wabt + extractors ─
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl wget git unzip xz-utils ca-certificates gnupg \
      python3 python3-pip python3-venv python3-dev build-essential pkg-config \
      cargo \
      wabt p7zip-full zstd lz4 lzop unar e2fsprogs \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && node --version && npm --version \
    && rm -rf /var/lib/apt/lists/*

# chromium (เว็บวิเคราะห์) — Ubuntu ให้ผ่าน snap (ใช้ใน container ไม่ได้) → best-effort
# arm64 ไม่มี Google Chrome .deb ด้วย → ถ้าข้าม ฟีเจอร์เว็บจะยังไม่พร้อม (ตั้ง CHROME_BIN
# ชี้ไป chrome นอกคอนเทนเนอร์ผ่าน CDP ได้ — REA attach แบบ remote อยู่แล้ว)
RUN apt-get update \
    && (apt-get install -y --no-install-recommends chromium-browser \
        || apt-get install -y --no-install-recommends chromium \
        || echo "WARN chromium skip (web analysis จะยังไม่พร้อมในคอนเทนเนอร์)") ; \
    rm -rf /var/lib/apt/lists/*

# ── ชั้น 2: JDK 21 (Temurin, arm64 tarball) — Ghidra ต้อง JDK 21, apktool ก็ใช้ ──
RUN curl -fsSL "https://api.adoptium.net/v3/binary/latest/21/ga/linux/aarch64/jdk/hotspot/normal/eclipse" \
      -o /tmp/jdk.tar.gz \
    && mkdir -p /opt/jdk && tar -xzf /tmp/jdk.tar.gz -C /opt/jdk --strip-components=1 \
    && rm /tmp/jdk.tar.gz && /opt/jdk/bin/java -version || echo "WARN jdk skip"
ENV JAVA_HOME=/opt/jdk
ENV PATH="/opt/jdk/bin:${PATH}"

# ── ชั้น 3: Ghidra (ดึง release ล่าสุดจาก GitHub) → /opt/ghidra ───────────────
RUN set -e; \
    URL=$(curl -fsSL https://api.github.com/repos/NationalSecurityAgency/ghidra/releases/latest \
          | grep -o 'https://[^"]*_PUBLIC_[0-9]*\.zip' | head -1); \
    echo "Ghidra: $URL"; \
    curl -fsSL "$URL" -o /tmp/ghidra.zip \
    && unzip -q /tmp/ghidra.zip -d /opt && rm /tmp/ghidra.zip \
    && mv /opt/ghidra_*_PUBLIC /opt/ghidra \
    && echo "✓ ghidra" || echo "WARN ghidra skip"
ENV GHIDRA_INSTALL_DIR=/opt/ghidra

# ── ชั้น 4: apktool (wrapper + jar ล่าสุด) ────────────────────────────────────
RUN curl -fsSL https://raw.githubusercontent.com/iBotPeaches/Apktool/master/scripts/linux/apktool \
      -o /usr/local/bin/apktool \
    && JAR=$(curl -fsSL https://api.github.com/repos/iBotPeaches/Apktool/releases/latest \
             | grep -o 'https://[^"]*apktool_[0-9.]*\.jar' | head -1) \
    && curl -fsSL "$JAR" -o /usr/local/bin/apktool.jar \
    && chmod +x /usr/local/bin/apktool /usr/local/bin/apktool.jar \
    && echo "✓ apktool" || echo "WARN apktool skip"

# ── ชั้น 5: JADX (Java-source จาก APK) → /opt/jadx/bin ───────────────────────
RUN URL=$(curl -fsSL https://api.github.com/repos/skylot/jadx/releases/latest \
          | grep -o 'https://[^"]*jadx-[0-9.]*\.zip' | head -1); \
    curl -fsSL "$URL" -o /tmp/jadx.zip \
    && unzip -q /tmp/jadx.zip -d /opt/jadx && rm /tmp/jadx.zip \
    && echo "✓ jadx" || echo "WARN jadx skip"
ENV PATH="/opt/jadx/bin:${PATH}"

# ── ชั้น 6: binwalk 3.x — ลอง prebuilt arm64 ก่อน ไม่งั้น build จาก source (cargo) ─
RUN set -e; \
    URL=$(curl -fsSL https://api.github.com/repos/ReFirmLabs/binwalk/releases/latest \
          | grep -oE 'https://[^"]*(aarch64|arm64)[^"]*linux[^"]*\.tar\.gz' | head -1); \
    if [ -n "$URL" ]; then \
      curl -fsSL "$URL" -o /tmp/bw.tgz && tar -xzf /tmp/bw.tgz -C /tmp && rm /tmp/bw.tgz \
      && install -m755 "$(find /tmp -type f -name binwalk | head -1)" /usr/local/bin/binwalk \
      && echo "✓ binwalk (prebuilt) $(/usr/local/bin/binwalk --version 2>/dev/null)"; \
    else \
      echo "ไม่มี prebuilt arm64 → build จาก source (cargo install binwalk)…"; \
      cargo install --root /usr/local binwalk \
      && echo "✓ binwalk (cargo) $(/usr/local/bin/binwalk --version 2>/dev/null)"; \
    fi || echo "WARN binwalk skip (ตั้ง REA_BINWALK_COMMAND เองได้)"

# ── ชั้น 7: unblob (pip — หนัก/เปราะ; ทนพลาด) ────────────────────────────────
RUN pip3 install --no-cache-dir unblob && echo "✓ unblob" || echo "WARN unblob skip"

# ── ชั้น 8: REA (rea-agents) + supergateway (stdio→HTTP bridge) ──────────────
#   pin เวอร์ชัน rea-agents กัน supply-chain (อยากอัปเดต: เปลี่ยนเลขแล้ว rebuild)
RUN npm install -g rea-agents@6.4.0 supergateway \
    && rea --version && echo "✓ rea + supergateway"

# ── env ให้ REA หา tool เจอ (readiness: rea doctor / rea inspect-*) ──────────
ENV REA_APKTOOL_COMMAND=/usr/local/bin/apktool \
    REA_BINWALK_COMMAND=/usr/local/bin/binwalk \
    REA_UNBLOB_COMMAND=/usr/local/bin/unblob \
    CHROME_BIN=/usr/bin/chromium

# เป้าหมายที่จะแกะ (APK/binary/firmware) วางใน pipeline/rea-targets/ → เห็นที่ /work/targets
WORKDIR /work
RUN mkdir -p /work/targets

# ครอบ stdio ของ `rea mcp` เป็น streamable-HTTP บน :8007 path /mcp
EXPOSE 8007
CMD ["sh","-c","supergateway --stdio 'rea mcp' --outputTransport streamableHttp --host 0.0.0.0 --port 8007 --streamableHttpPath /mcp"]
