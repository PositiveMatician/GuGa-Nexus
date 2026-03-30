# Android Voice Assistant & Backend

A powerful, low-latency Voice Assistant system consisting of an Android application (Java) and a Python backend (Flask/Socket.IO).

## Features

### Android Application
- **Wake Word Detection**: Real-time listening for custom wake words (e.g., "ASSISTANT", "ALEXA") using openWakeWord/TFLite.
- **Dynamic Networking**: QR code integration for instant LAN pairing with the backend.
- **Foreground Service**: Persistent operation in the background with a system notification for reliable connectivity.
- **Dual Communication Modes**: Uses WebSockets for real-time live audio/response and HTTP fallback for command processing.
- **Silent Mode**: A toggle to disable voice features (MIC, STT, TTS) while keeping the networking and text display active.
- **Manual Input**: Send text commands directly to the server via an integrated console.

### Python Backend
- **Asynchronous Processing**: Non-blocking message broadcasting to all connected clients.
- **Web Dashboard**: A real-time web interface for monitoring and sending commands to the assistant.
- **Interactive Shell**: A terminal-based shell for live interaction with connected devices.
- **Robust API**: REST endpoints for health checks, client listing, and broadcasting.

## Usage & API Reference

The backend provides several HTTP endpoints for monitoring and interacting with connected Android clients.

### 1. Health Check
Verify the server status and see how many clients are currently connected.
```bash
curl -X GET http://localhost:6769/ping
```

### 2. List Connected Clients
Retrieve a list of all active Socket.IO session IDs. You'll need these IDs for targeted messaging.
```bash
curl -X GET http://localhost:6769/clients
```

### 3. Broadcast to All Clients
Send a message that will show as text on all connected devices (and be spoken aloud if their voice toggle is ON).
```bash
curl -X POST http://localhost:6769/send \
     -H "Content-Type: application/json" \
     -d '{"message": "Attention everyone: Update available!"}'
```

### 4. Direct Message to Specific Client
Send a private message to a specific device using its unique session ID (obtained from `/clients`).
```bash
# Replace <sid> with an actual session ID
curl -X POST http://localhost:6769/send/<sid> \
     -H "Content-Type: application/json" \
     -d '{"message": "Hey, this is just for you."}'
```

### 5. HTTP Command Fallback
Simulate a command being sent from a device. The server will process it and broadcast the response back to all clients.
```bash
curl -X POST http://localhost:6769/api/command \
     -H "Content-Type: application/json" \
     -d '{"command": "what time is it?"}'
```


## TODO

the server should only allow /send traffic from the same device the server is running on

only trusted devices can create a socket connection , so I need to be able to differentiate between trusted and untrusted devices. Ability to allow temporary trust to browser which expires in a hour and have to be redone.

the fullscreen version still have purple. it needs to be all black , find all traces of other colors rather than white and black in alpha model