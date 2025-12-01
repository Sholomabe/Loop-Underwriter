"""
Combined server that runs:
1. Streamlit app directly on port 5000 (main process)
2. Flask webhook server on port 8080 (background thread)

When published, port 5000 serves the Streamlit UI directly.
The webhook server runs internally and can be accessed via internal routing.
"""

import subprocess
import threading
import time
import sys
import os

def run_flask_webhooks():
    """Run Flask webhook server on port 8080 in background"""
    from webhook_server import app
    app.run(host='0.0.0.0', port=8080, debug=False, threaded=True, use_reloader=False)

def run_streamlit():
    """Run Streamlit on port 5000 as main process"""
    cmd = [
        sys.executable, "-m", "streamlit", "run", "app.py",
        "--server.port", "5000",
        "--server.address", "0.0.0.0",
        "--server.headless", "true"
    ]
    subprocess.run(cmd)

if __name__ == '__main__':
    from database import init_db
    init_db()
    
    flask_thread = threading.Thread(target=run_flask_webhooks, daemon=True)
    flask_thread.start()
    print("Flask webhook server started on port 8080")
    
    time.sleep(1)
    
    print("Starting Streamlit on port 5000...")
    run_streamlit()
