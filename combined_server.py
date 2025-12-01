"""
Combined server that handles both:
1. Webhook endpoints (Flask) on /koncile-callback, /incoming-email, etc.
2. Streamlit app (proxied from internal port)

This allows both the webhooks AND the Streamlit UI to be accessible
on the same port 5000 when published.
"""

from flask import Flask, request, jsonify, Response
import subprocess
import requests
import threading
import time
import os
import sys

app = Flask(__name__)

STREAMLIT_PORT = 8501  # Internal Streamlit port

# Start Streamlit as subprocess
streamlit_process = None

def start_streamlit():
    global streamlit_process
    cmd = [
        sys.executable, "-m", "streamlit", "run", "app.py",
        "--server.port", str(STREAMLIT_PORT),
        "--server.address", "127.0.0.1",
        "--server.headless", "true",
        "--browser.serverAddress", "localhost"
    ]
    streamlit_process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print(f"Streamlit started on internal port {STREAMLIT_PORT}")

# Import webhook handlers
from webhook_server import (
    incoming_email,
    koncile_callback,
    gmail_webhook,
    health_check
)

# Register webhook routes
app.add_url_rule('/incoming-email', 'incoming_email', incoming_email, methods=['POST'])
app.add_url_rule('/koncile-callback', 'koncile_callback', koncile_callback, methods=['POST'])
app.add_url_rule('/gmail-webhook', 'gmail_webhook', gmail_webhook, methods=['POST'])
app.add_url_rule('/health', 'health_check', health_check, methods=['GET'])

# Proxy all other requests to Streamlit
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS'])
def proxy_to_streamlit(path):
    """Proxy requests to Streamlit"""
    try:
        # Build the URL to forward to Streamlit
        url = f"http://127.0.0.1:{STREAMLIT_PORT}/{path}"
        
        # Forward query string
        if request.query_string:
            url += f"?{request.query_string.decode()}"
        
        # Forward the request
        resp = requests.request(
            method=request.method,
            url=url,
            headers={key: value for key, value in request.headers if key.lower() != 'host'},
            data=request.get_data(),
            cookies=request.cookies,
            allow_redirects=False,
            stream=True
        )
        
        # Build response
        excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
        headers = [(name, value) for name, value in resp.raw.headers.items()
                   if name.lower() not in excluded_headers]
        
        response = Response(resp.content, resp.status_code, headers)
        return response
        
    except requests.exceptions.ConnectionError:
        return "Streamlit is starting up, please wait...", 503

# WebSocket proxy for Streamlit's live updates
@app.route('/_stcore/stream', methods=['GET'])
def streamlit_stream():
    """Handle Streamlit WebSocket upgrade requests"""
    try:
        url = f"http://127.0.0.1:{STREAMLIT_PORT}/_stcore/stream"
        if request.query_string:
            url += f"?{request.query_string.decode()}"
            
        resp = requests.get(
            url,
            headers={key: value for key, value in request.headers if key.lower() != 'host'},
            stream=True
        )
        
        return Response(
            resp.iter_content(chunk_size=1024),
            content_type=resp.headers.get('content-type', 'text/event-stream')
        )
    except:
        return "", 503

if __name__ == '__main__':
    # Start Streamlit in background
    streamlit_thread = threading.Thread(target=start_streamlit, daemon=True)
    streamlit_thread.start()
    
    # Give Streamlit time to start
    time.sleep(3)
    
    # Initialize database
    from database import init_db
    init_db()
    
    # Run Flask on port 5000
    print("Combined server starting on port 5000...")
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
