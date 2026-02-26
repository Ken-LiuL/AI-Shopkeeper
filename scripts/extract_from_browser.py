"""Extract product data from OpenClaw browser and save to file.

Run after browser has fetched all products into window.__allProducts.
Uses CDP to read data in chunks.
"""

# Read chunks from browser via openclaw CLI or websocket
# For now, just create a simple HTTP server approach

# Actually, let's use a simpler approach: have the browser POST data to a local server
print("Use the following approach:")
print("1. In browser console, data is at window.__allProducts (1914 items)")
print("2. We'll extract via multiple evaluate calls")
