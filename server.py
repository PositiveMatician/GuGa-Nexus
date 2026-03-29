from flask import Flask, request, jsonify, render_template_string
from flask_socketio import SocketIO, emit
import socket
import qrcode

app = Flask(__name__)
# cors_allowed_origins="*" allows your phone's browser to connect without security blocks
# eventlet or gevent are recommended for production Socket.IO servers
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# ---------------------------------------------------------
# THE BROWSER DASHBOARD (Served to anyone who visits the IP)
# ---------------------------------------------------------
HTML_PAGE = """
<!DOCTYPE html>
<html>
<head>
    <title>Jarvis Web Terminal</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <script src="https://cdn.socket.io/4.7.2/socket.io.min.js"></script>
    <style>
        body { background: #121212; color: #00ff00; font-family: monospace; padding: 20px; }
        #chat { height: 300px; overflow-y: auto; border: 1px solid #333; padding: 10px; margin-bottom: 10px; }
        input { width: 70%; padding: 10px; background: #222; border: 1px solid #444; color: white; }
        button { padding: 10px 20px; background: #00ff00; color: black; border: none; cursor: pointer; }
    </style>
</head>
<body>
    <h2>Jarvis Web Terminal</h2>
    <div id="chat"></div>
    <input type="text" id="commandInput" placeholder="Type a command (Silent Mode)..." onkeypress="handleEnter(event)">
    <button onclick="sendCommand()">Send</button>

    <script>
        // This single line handles WebSockets AND the HTTP Fallback automatically!
        const socket = io();
        const chat = document.getElementById('chat');

        socket.on('connect', () => {
            chat.innerHTML += '<p>[SYSTEM] Connected to Jarvis via ' + socket.io.engine.transport.name + '</p>';
        });

        // Listen for Jarvis speaking back
        socket.on('jarvis_response', (data) => {
            chat.innerHTML += '<p><b>Jarvis:</b> ' + data.message + '</p>';
            chat.scrollTop = chat.scrollHeight; // Auto-scroll
        });

        function sendCommand() {
            const input = document.getElementById('commandInput');
            if(input.value.trim() !== "") {
                chat.innerHTML += '<p><b>You:</b> ' + input.value + '</p>';
                // Send to Python
                socket.emit('command', { phrase: input.value });
                input.value = '';
            }
        }

        function handleEnter(e) {
            if(e.key === 'Enter') sendCommand();
        }
    </script>
</body>
</html>
"""

# Serve the HTML page when a browser hits the IP
@app.route('/')
def web_interface():
    return render_template_string(HTML_PAGE)

# ---------------------------------------------------------
# HTTP ROUTES (For Connectivity)
# ---------------------------------------------------------

@app.route('/ping')
def ping():
    """Support the Android app's connectivity check."""
    return jsonify({"status": "online"}), 200

@app.route('/api/command', methods=['POST'])
def handle_command_api():
    """Fallback HTTP POST route for commands."""
    data = request.json if request.is_json else {}
    command = data.get('command', '')
    print(f"\n[JARVIS] API Command Received: '{command}'")
    
    # Process the command logic here...
    response_msg = f"Executing (API): {command}"
    
    # For HTTP, we just return the response
    return jsonify({"message": response_msg}), 200

# ---------------------------------------------------------
# THE SOCKET.IO BRAIN (Handles both App and Browser)
# ---------------------------------------------------------

@socketio.on('connect')
def handle_connect():
    print("\n[JARVIS] New client connected!")
    emit('jarvis_response', {'message': 'Connection established. Jarvis online.'})

@socketio.on('request_status')
def handle_request_status(data):
    """Client-triggered status check."""
    emit('jarvis_response', {'message': 'Jarvis is fully synchronized.'})

@socketio.on('disconnect')
def handle_disconnect():
    print("[JARVIS] Client disconnected.")

@socketio.on('command')
def handle_command(data):
    command = data.get('phrase', '')
    print(f"\n[JARVIS] Command Received: '{command}'")
    
    # Process the command logic here...
    response_msg = f"{command}"
    
    # Broadcast the reply back to the specific client that asked
    emit('jarvis_response', {'message': response_msg})

# A helper to push notifications unprompted (e.g., from other Python scripts)
def notify_all_clients(message):
    socketio.emit('jarvis_response', {'message': message})

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Doesn't even have to be reachable
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

if __name__ == '__main__':
    local_ip = get_local_ip()
    port = 6769
    
    print(f"Starting Universal Jarvis Backend on http://{local_ip}:{port}")
    
    # Generate and display the QR Code for the Android app
    print("Generating Pairing QR Code...")
    qr = qrcode.make(local_ip)
    # Note: qr.show() requires an image viewer to be installed on the system
    try:
        qr.show()
    except Exception as e:
        print(f"Could not show QR code automatically: {e}")
        print(f"Manually pair using IP: {local_ip}")
    
    # Notice we use socketio.run instead of app.run now!
    socketio.run(app, host='0.0.0.0', port=port)
