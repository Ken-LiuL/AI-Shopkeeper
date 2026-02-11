/**
 * 浏览器隐身脚本 — 参考 puppeteer-extra-plugin-stealth
 * 注入到每个采集页面，隐藏自动化痕迹。
 */
(() => {
    if (window.__stealth_injected) return;
    window.__stealth_injected = true;

    // ── 1. 隐藏 navigator.webdriver ────────────────────────────────────
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined,
        configurable: true,
    });
    // 删除 webdriver 相关属性
    delete navigator.__proto__.webdriver;

    // ── 2. 伪装 chrome.runtime ─────────────────────────────────────────
    if (!window.chrome) window.chrome = {};
    if (!window.chrome.runtime) {
        window.chrome.runtime = {
            connect: function() { return { onMessage: { addListener: function() {} }, postMessage: function() {} }; },
            sendMessage: function() {},
            onMessage: { addListener: function() {} },
            id: undefined,
        };
    }
    // chrome.app
    if (!window.chrome.app) {
        window.chrome.app = {
            isInstalled: false,
            InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' },
            RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' },
            getDetails: function() { return null; },
            getIsInstalled: function() { return false; },
        };
    }
    // chrome.csi
    if (!window.chrome.csi) {
        window.chrome.csi = function() {
            return {
                startE: Date.now(),
                onloadT: Date.now(),
                pageT: Math.random() * 1000 + 500,
                tran: 15,
            };
        };
    }
    // chrome.loadTimes
    if (!window.chrome.loadTimes) {
        window.chrome.loadTimes = function() {
            return {
                commitLoadTime: Date.now() / 1000 - Math.random() * 2,
                connectionInfo: 'h2',
                finishDocumentLoadTime: Date.now() / 1000 - Math.random(),
                finishLoadTime: Date.now() / 1000 - Math.random() * 0.5,
                firstPaintAfterLoadTime: 0,
                firstPaintTime: Date.now() / 1000 - Math.random() * 1.5,
                navigationType: 'Other',
                npnNegotiatedProtocol: 'h2',
                requestTime: Date.now() / 1000 - Math.random() * 3,
                startLoadTime: Date.now() / 1000 - Math.random() * 3,
                wasAlternateProtocolAvailable: false,
                wasFetchedViaSpdy: true,
                wasNpnNegotiated: true,
            };
        };
    }

    // ── 3. Permissions API 伪装 ────────────────────────────────────────
    const origQuery = window.navigator.permissions?.query;
    if (origQuery) {
        window.navigator.permissions.query = function(parameters) {
            if (parameters.name === 'notifications') {
                return Promise.resolve({ state: Notification.permission });
            }
            return origQuery.call(this, parameters);
        };
    }

    // ── 4. Plugins 伪装 ───────────────────────────────────────────────
    // 创建假的 plugin 数组
    function makeFakePlugin(name, description, filename, mimeTypes) {
        const plugin = Object.create(Plugin.prototype);
        Object.defineProperties(plugin, {
            name: { value: name, enumerable: true },
            description: { value: description, enumerable: true },
            filename: { value: filename, enumerable: true },
            length: { value: mimeTypes.length, enumerable: true },
        });
        mimeTypes.forEach((mt, i) => {
            Object.defineProperty(plugin, i, { value: mt, enumerable: true });
        });
        return plugin;
    }

    try {
        const fakePlugins = [
            makeFakePlugin('Chrome PDF Plugin', 'Portable Document Format', 'internal-pdf-viewer', []),
            makeFakePlugin('Chrome PDF Viewer', '', 'mhjfbmdgcfjbbpaeojofohoefgiehjai', []),
            makeFakePlugin('Native Client', '', 'internal-nacl-plugin', []),
        ];
        Object.defineProperty(navigator, 'plugins', {
            get: () => {
                const arr = Object.create(PluginArray.prototype);
                fakePlugins.forEach((p, i) => {
                    Object.defineProperty(arr, i, { value: p, enumerable: true });
                });
                Object.defineProperty(arr, 'length', { value: fakePlugins.length });
                arr.item = (i) => fakePlugins[i] || null;
                arr.namedItem = (name) => fakePlugins.find(p => p.name === name) || null;
                arr.refresh = () => {};
                return arr;
            },
            configurable: true,
        });
    } catch(e) {}

    // ── 5. iframe contentWindow 保护 ──────────────────────────────────
    // 确保 iframe 的 contentWindow 没有暴露自动化特征
    try {
        const origHTMLIFrameElement = HTMLIFrameElement.prototype.__lookupGetter__('contentWindow');
        if (origHTMLIFrameElement) {
            Object.defineProperty(HTMLIFrameElement.prototype, 'contentWindow', {
                get: function() {
                    const iframe = origHTMLIFrameElement.call(this);
                    if (iframe) {
                        try {
                            // 确保 iframe 内的 navigator.webdriver 也被覆盖
                            Object.defineProperty(iframe.navigator, 'webdriver', {
                                get: () => undefined, configurable: true,
                            });
                        } catch(e) {}
                    }
                    return iframe;
                },
                configurable: true,
            });
        }
    } catch(e) {}

    // ── 6. 隐藏 automation indicators ─────────────────────────────────
    // 移除 cdc_ 属性（ChromeDriver 特征）
    try {
        const props = Object.getOwnPropertyNames(document);
        for (const prop of props) {
            if (prop.match(/^cdc_/)) {
                delete document[prop];
            }
        }
    } catch(e) {}

    // 隐藏 $cdc 和 $chrome_asyncScriptInfo
    try {
        delete window.$cdc_asdjflasutopfhvcZLmcfl_;
        delete window.$chrome_asyncScriptInfo;
    } catch(e) {}

    // ── 7. WebRTC 防泄露 ──────────────────────────────────────────────
    // 防止通过 WebRTC 泄露真实 IP
    try {
        const origRTCPeerConnection = window.RTCPeerConnection || window.webkitRTCPeerConnection;
        if (origRTCPeerConnection) {
            window.RTCPeerConnection = function(...args) {
                // 强制使用 relay (TURN) 模式，不泄露本地 IP
                if (args[0] && args[0].iceServers) {
                    args[0].iceTransportPolicy = 'relay';
                }
                return new origRTCPeerConnection(...args);
            };
            window.RTCPeerConnection.prototype = origRTCPeerConnection.prototype;
        }
    } catch(e) {}

    // ── 8. 隐藏 headless 检测 ─────────────────────────────────────────
    // window.outerWidth/outerHeight 不应该为 0
    if (window.outerWidth === 0) {
        Object.defineProperty(window, 'outerWidth', {
            get: () => window.innerWidth, configurable: true,
        });
    }
    if (window.outerHeight === 0) {
        Object.defineProperty(window, 'outerHeight', {
            get: () => window.innerHeight + 85, configurable: true,
        });
    }

    // ── 9. 模拟 MediaDevices ──────────────────────────────────────────
    try {
        if (navigator.mediaDevices && navigator.mediaDevices.enumerateDevices) {
            const origEnum = navigator.mediaDevices.enumerateDevices;
            navigator.mediaDevices.enumerateDevices = async function() {
                const devices = await origEnum.call(this);
                // 确保至少有基本的音视频设备
                if (devices.length === 0) {
                    return [
                        { deviceId: 'default', kind: 'audioinput', label: '', groupId: 'default' },
                        { deviceId: 'default', kind: 'videoinput', label: '', groupId: 'default' },
                        { deviceId: 'default', kind: 'audiooutput', label: '', groupId: 'default' },
                    ];
                }
                return devices;
            };
        }
    } catch(e) {}

    // ── 10. 修正 toString 检测 ────────────────────────────────────────
    // 确保被覆盖的函数 toString() 看起来是 native 的
    const nativeToString = Function.prototype.toString;
    const overrides = new Map();

    function makeNativeString(name) {
        return `function ${name}() { [native code] }`;
    }

    const origToString = Function.prototype.toString;
    Function.prototype.toString = function() {
        if (overrides.has(this)) {
            return makeNativeString(overrides.get(this));
        }
        return origToString.call(this);
    };
    overrides.set(Function.prototype.toString, 'toString');

    // Register our overridden functions
    if (navigator.permissions?.query !== origQuery) {
        overrides.set(navigator.permissions.query, 'query');
    }
})();
