# 🤖 AI店长 — 牵牛花智能客服 Chrome Extension

Auto-reply to customer messages on Meituan's 牵牛花 (qnh.meituan.com) merchant platform using AI.

## Features

- **WebSocket interception** — captures incoming customer messages in real-time
- **DOM observer fallback** — works even if WS structure changes
- **Two modes**: auto-fill (you click send) or auto-send (fully automatic)
- **Floating panel** — draggable, minimizable, shows status & recent replies
- **Configurable** — backend URL, API key, store ID via popup settings

## Installation

1. Open Chrome → `chrome://extensions/`
2. Enable **Developer mode** (top right)
3. Click **Load unpacked**
4. Select this `chrome-extension/` folder
5. Navigate to `https://qnh.meituan.com/` — the panel appears automatically

## Configuration

Click the extension icon in the toolbar to open settings:

| Setting | Default | Description |
|---------|---------|-------------|
| 启用 | ✅ | Enable/disable the assistant |
| 回复模式 | 自动填充 | `auto-fill` or `auto-send` |
| API 地址 | `https://ai-shopkeeper-1dl4.onrender.com/api/v1/customer-service/chat` | Backend URL |
| API Key | — | Optional Bearer token |
| 店铺 ID | — | Optional store identifier |

## Architecture

```
manifest.json          — Manifest V3 config
background.js          — Service worker, API calls with retry
content_script.js      — Injected into qnh.meituan.com, panel UI
injected.js            — Page-level WebSocket interceptor
popup.html / popup.js  — Extension popup settings
panel.css              — Floating panel styles
icons/                 — Extension icons
```

## API Contract

```
POST /api/v1/customer-service/chat
{
  "message": "customer text",
  "session_id": "conversation_id",
  "customer_info": {},
  "store_id": "optional"
}

Response: { "reply": "AI-generated response" }
```

## Tuning for Production

The WebSocket message parsing in `injected.js` and `content_script.js` uses heuristic field matching. After inspecting real 牵牛花 WebSocket traffic:

1. Open DevTools → Network → WS on `qnh.meituan.com`
2. Observe message structure when a customer sends a message
3. Update `extractCustomerMessage()` in `content_script.js` to match exact fields
4. Similarly update DOM selectors in `startDOMObserver()` for the chat UI

## License

Internal use only.
