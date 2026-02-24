/**
 * background.js — Service worker for AI店长 Chrome Extension.
 * Handles communication with the AI backend.
 */

const DEFAULT_API_URL = 'https://ai-shopkeeper-1dl4.onrender.com/api/v1/customer-service/chat';
const MAX_RETRIES = 2;
const RETRY_DELAY_MS = 1000;

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'CUSTOMER_MESSAGE') {
    handleCustomerMessage(message.payload)
      .then((result) => sendResponse(result))
      .catch((err) => sendResponse({ success: false, error: err.message }));
    return true; // keep channel open for async response
  }
});

async function handleCustomerMessage(payload) {
  const settings = await chrome.storage.sync.get(['apiUrl', 'apiKey', 'storeId']);
  const apiUrl = settings.apiUrl || DEFAULT_API_URL;

  const body = {
    message: payload.message,
    session_id: payload.session_id,
    customer_info: payload.customer_info || {},
  };

  if (settings.storeId) {
    body.store_id = settings.storeId;
  }

  const headers = {
    'Content-Type': 'application/json',
  };
  if (settings.apiKey) {
    headers['Authorization'] = `Bearer ${settings.apiKey}`;
  }

  let lastError;
  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    try {
      const response = await fetch(apiUrl, {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
      });

      if (!response.ok) {
        const errText = await response.text().catch(() => '');
        throw new Error(`HTTP ${response.status}: ${errText.slice(0, 200)}`);
      }

      const data = await response.json();
      const reply = data.reply || data.message || data.response || data.data?.reply || '';

      if (!reply) {
        return { success: false, error: '后台返回空回复' };
      }

      return { success: true, reply };
    } catch (err) {
      lastError = err;
      if (attempt < MAX_RETRIES) {
        await new Promise((r) => setTimeout(r, RETRY_DELAY_MS * (attempt + 1)));
      }
    }
  }

  return { success: false, error: lastError?.message || '请求失败' };
}
