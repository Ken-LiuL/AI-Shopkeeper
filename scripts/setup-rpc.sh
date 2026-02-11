#!/usr/bin/env bash
# setup-rpc.sh — RPC 设备采集环境搭建
# 检查依赖、安装 Python 包、配置 mitmproxy 证书
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[✓]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[✗]${NC} $*"; }

echo "============================================"
echo "  AI 店长 — RPC 设备采集环境搭建"
echo "============================================"
echo

# ── 1. 检查 ADB ──────────────────────────────────────────────────────
echo "1. 检查 ADB..."
if command -v adb &>/dev/null; then
    ADB_VERSION=$(adb version | head -1)
    info "ADB 已安装: $ADB_VERSION"
else
    error "ADB 未安装"
    echo "  macOS:   brew install android-platform-tools"
    echo "  Ubuntu:  sudo apt install android-tools-adb"
    echo "  或从 https://developer.android.com/studio#command-tools 下载"
    exit 1
fi

# ── 2. 检查 Python ───────────────────────────────────────────────────
echo
echo "2. 检查 Python..."
PYTHON="python3"
if ! command -v $PYTHON &>/dev/null; then
    error "Python3 未安装"
    exit 1
fi
PY_VERSION=$($PYTHON --version)
info "Python: $PY_VERSION"

# ── 3. 安装 Python 依赖 ─────────────────────────────────────────────
echo
echo "3. 安装 Python 依赖..."

PACKAGES=(
    "uiautomator2"
    "mitmproxy"
    "adbutils"
)

for pkg in "${PACKAGES[@]}"; do
    if $PYTHON -c "import ${pkg//-/_}" 2>/dev/null; then
        info "$pkg 已安装"
    else
        warn "安装 $pkg..."
        pip install "$pkg" -q
        info "$pkg 安装完成"
    fi
done

# ── 4. 检查 mitmproxy ───────────────────────────────────────────────
echo
echo "4. 检查 mitmproxy..."
if command -v mitmdump &>/dev/null; then
    MITM_VERSION=$(mitmdump --version | head -1)
    info "mitmproxy: $MITM_VERSION"
else
    warn "mitmdump 命令不在 PATH 中，尝试安装..."
    pip install mitmproxy -q
fi

# ── 5. 生成 mitmproxy 证书 ──────────────────────────────────────────
echo
echo "5. mitmproxy 证书..."
CERT_DIR="$HOME/.mitmproxy"
if [ -f "$CERT_DIR/mitmproxy-ca-cert.cer" ]; then
    info "CA 证书已存在: $CERT_DIR/mitmproxy-ca-cert.cer"
else
    warn "首次运行 mitmproxy 以生成证书..."
    timeout 3 mitmdump -q 2>/dev/null || true
    if [ -f "$CERT_DIR/mitmproxy-ca-cert.cer" ]; then
        info "CA 证书已生成"
    else
        warn "请手动运行一次 mitmdump 生成证书"
    fi
fi

# ── 6. Android 设备证书安装指南 ──────────────────────────────────────
echo
echo "6. Android 证书安装指南:"
echo "   ┌──────────────────────────────────────────────────────────┐"
echo "   │ 方法 A: 通过浏览器安装（Android 6 及以下）              │"
echo "   │   1. 设备设置代理指向本机 8080 端口                     │"
echo "   │   2. 浏览器访问 http://mitm.it                         │"
echo "   │   3. 下载并安装 Android 证书                            │"
echo "   ├──────────────────────────────────────────────────────────┤"
echo "   │ 方法 B: 系统级证书（Android 7+ 需要 Root）              │"
echo "   │   1. adb push ~/.mitmproxy/mitmproxy-ca-cert.cer /sdcard│"
echo "   │   2. 使用 Magisk 模块 MagiskTrustUserCerts              │"
echo "   │      或手动复制到 /system/etc/security/cacerts/          │"
echo "   ├──────────────────────────────────────────────────────────┤"
echo "   │ 方法 C: SSL Pinning 绕过                                │"
echo "   │   安装 JustTrustMe 或 TrustMeAlready (Xposed/LSPosed)   │"
echo "   └──────────────────────────────────────────────────────────┘"

# ── 7. 检查已连接的设备 ─────────────────────────────────────────────
echo
echo "7. 检查已连接的 Android 设备..."
DEVICES=$(adb devices 2>/dev/null | grep -c "device$" || true)
if [ "$DEVICES" -gt 0 ]; then
    info "检测到 $DEVICES 台设备:"
    adb devices -l | grep "device " | sed 's/^/   /'
else
    warn "未检测到 Android 设备"
    echo "   请连接设备或启动模拟器后重试"
fi

# ── 8. 创建数据目录 ─────────────────────────────────────────────────
echo
echo "8. 创建数据目录..."
mkdir -p data/meituan_raw
info "data/meituan_raw 已创建"

echo
echo "============================================"
echo "  环境搭建完成！"
echo ""
echo "  启动采集:"
echo "    1. 启动 mitmproxy:"
echo "       mitmdump -s src/rpc/proxy.py -p 8080"
echo ""
echo "    2. 设置设备代理:"
echo "       adb shell settings put global http_proxy <host_ip>:8080"
echo ""
echo "    3. 运行采集:"
echo "       python -m src.rpc.scheduler"
echo "============================================"
