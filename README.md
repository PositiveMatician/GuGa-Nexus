<p align="center">
  <img src="alpha-model/app/src/main/assets/logo.png" width="128" height="128" />
</p>

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

## 🚀 Quick Start Tutorial

To get the **GuGa Nexus** ecosystem running, follow these steps:

### 1. 🖥️ Linux Server (GuGu)
The server acts as the central hub for your commands and notifications.
- **Download**: You only need the `server/` folder from this repository.
- **Setup**:
    ```bash
    cd server
    python3 post.py  # Automatically installs dependencies and system tools
    ```
- **Run**:
    ```bash
    python3 server.py
    ```
- **Pairing**: Once started, a QR code and an 8-digit PIN will be displayed on your terminal.

### 2. 📲 Android App (GuGa)
The mobile app is your remote control for the Linux host.
- **Download**: ⚠️ **Do not build from source unless you are a developer.** 
- **Stable Release**: Download the [GuGa-Alpha.apk](https://github.com/PositiveMatician/GuGa-Nexus/releases/tag/v1.0.0) for a reliable, premium experience.
- **Nightly Build**: Download the [GuGa-Beta-Nightly.apk](https://github.com/PositiveMatician/GuGa-Nexus/releases/tag/nightly) for experimental features.
- **Installation**: Sideload the APK onto your Android device.

---

## 🎮 How to Use

1.  **Connect**: Open the **GuGa** app on your phone.
2.  **Pairing**:
    *   Tap the **Settings** arrow (`>`) on the home screen.
    *   Tap **SCAN QR** and scan the code shown on your server terminal, OR manually enter the IP address.
    *   Enter the 8-digit PIN displayed on your server to establish a **Zero-Trust** connection.
3.  **Interaction**:
    *   Once connected, the status will show **LIVE SYNC ACTIVE**.
    *   Type commands in the chat box to interact with your Linux host.
    *   System notifications from your Linux machine will automatically appear as notifications on your phone!
4.  **Persistence**: Tap **LIVE PERSISTENCE** in settings to keep the connection active even when the app is in the background.

---

## License

Personal project - All rights reserved.
