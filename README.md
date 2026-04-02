# GuGa Nexus - Android Assistant & Linux Server

GuGa Nexus is a minimalist, secure, and privacy-focused ecosystem that allows you to sync notifications and run remote commands between your Android devices and a Linux host.

## Project Structure

- **`alpha-model/`**: The latest stable release of the **GuGa** Android application, featuring a premium minimalist UI and secure communication.
- **`beta-model/`**: The nightly build/development version used for experimental features, including ongoing work for **Wake-Word** integration.
- **`server/`**: The **GuGu** Python-based backend that runs on your Linux machine to handle command processing and notification forwarding.

## Key Features

- **End-to-End Encryption**: AES-256-GCM encrypted communication between the Android app and the server.
- **Zero-Trust PIN Pairing**: Secure initial device handshake.
- **OS Notification Sync**: Automatically forwards Linux system notifications to your Android device via D-Bus.
- **Minimalist Aesthetic**: Professional, distraction-free branding.
- **Remote Execution**: Securely trigger commands on your host machine from your phone.

## Getting Started (Server)

1. Navigate to the `server/` directory.
2. Run the setup script: `python3 post.py` (This will install dependencies and system tools).
3. Start the server: `python3 server.py`.
4. Scan the generated QR code or enter the pairing PIN in the GuGa Android app.

## License

Personal project - All rights reserved.
