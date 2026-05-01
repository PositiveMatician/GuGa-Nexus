# GuGa Android App Tutorial

Welcome to the **GuGa** Android client! This guide will help you master all the advanced features we've built to make your remote terminal interactions seamless and powerful.

---

## 1. Getting Started
### Connection & Pairing
- **First Launch**: Enter your Linux machine's IP address.
- **Pairing**: The app will show a **8-digit PIN**. On your Linux machine, run:
  ```bash
  guga --approve
  ```
- **Trust**: Once approved, your device is trusted and will connect automatically in the future.

---

## 2. Core Messaging
### Sending Commands
- Type any command in the bottom input field and hit **SEND**.
- **Bypass Mode (`~`)**: Toggle the `~` button to send an "explicit command" (sets `request_id=None`). Use this when you want to run a new command without it being tied to a previous interactive context.

### Receiving Responses
- Responses from your server appear in real-time.
- **TTS (Text-to-Speech)**: Toggle TTS in the Advanced Settings to have messages read aloud. (Default is OFF).

---

## 3. Advanced Interactions
### Swipe-to-Reply
- **Action**: Swipe any bot message to the **LEFT**.
- **Behavior**: The message will move slightly (5% of screen width) to reveal the reply intent.
- **UI**: A preview bar appears above the input field showing which message you are replying to. This automatically attaches the `request_id` and `message_id` to your next reply.

### Selection Mode (Bulk Actions)
- **Enter**: Long-press any message.
- **Visuals**: Selected messages turn **White** with **Black text** for clear visibility.
- **Toolbar**: Icons appear at the bottom:
    - 🗑️ **Delete**: Remove selected messages from local history.
    - 📤 **Copy**: Copy selected messages to clipboard (formatted with titles).
    - ✈️ **Reply**: (If 1 message selected) Quickly start a reply to that message.
- **Exit**: Click the **X** button on the left of the toolbar.

---

## 4. Intelligent Navigation
### Review Mode (Smart Scroll)
- If you scroll up more than **4 messages**, the app enters **Review Mode**.
- **Effect**: New incoming messages will be added to the bottom silently without jumping your screen. This allows you to read history without interruption.
- **Exit**: Sending a reply or scrolling back to the bottom returns you to **Auto-Scroll Mode**.

### Global Search
- Access via **Advanced Settings** -> **Search Chats**.
- Search through your entire message history (both your commands and server responses).
- Click any result to **jump** directly to that message in the main chat.

---

## 5. Productivity Tools
### Regex Title Filtering
- Access via **Advanced Settings** -> **Filter Section**.
- Enter a **Regex** pattern (e.g., `^System.*` or `Error`).
- **Effect**: Only messages whose titles match the regex will be shown. Others are still stored but hidden from view.
- **Clear**: Leave the field empty to show all messages.

### Hide Reply Field
- Toggle **Hide Reply Field** in Advanced Settings if you only want to monitor output without seeing the input bar.

---

## 6. Interactive Terminal Prompts
- When a remote command asks for input (like a password or confirmation), GuGa will show the prompt as a message.
- The **Reply Preview** will automatically activate, ensuring your next input is sent back to that specific interactive process.

---

### Tips
- **Animations**: Watch for smooth transitions when opening settings or the search overlay.
- **Offline**: The app stores history locally, so you can always review previous sessions even when disconnected.

Happy Command-ing! 🚀
