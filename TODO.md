# Manual Testing Protocol — Phase 20.1: Client-Generated PIN & Approval

This protocol covers manual verification of the new pairing system. Before starting, ensure the `guga` service is running on your Linux machine and you have access a web browser.

---

## Suite 2: Multi-Device Management

### 3. Concurrent Pairing Requests
1.  Open a browser client AND the Android app simultaneously.
2.  Point both to your server.
3.  Run `guga --approve`.
4.  **Verify**: Both devices appear in the list with their respective names and DIFFERENT unique PINs.
5.  Use `[A] approve all`.
6.  **Verify**: Both the browser and the phone successfully pair at the same time.

### 4. Interactive "Watch" Mode
1.  Run `guga --approve --watch`.
2.  Initiate pairing from a device.
3.  **Verify**: The CLI automatically detects the new request and prompts you: `[A] approve [R] reject [S] skip`.
4.  Choose `[A]`.
5.  **Verify**: The device pairs immediately and the CLI continues watching.
6. Check in watch mode what would happen if multiple devices are trying to connect , does skipping currently shown devices shows the next device correctly?

---

## Suite 3: Security & Rate Limiting

### 5. Manual Rejection
1.  Initiate pairing from a device.
2.  Run `guga --approve`.
3.  Choose `[R] reject all` or provide the index of the device and type `r` (if prompted in watch mode).
4.  **Verify**: The CLI shows "Rejected".
5.  **Verify**: The client (app or browser) stops polling and shows an error or "Rejected".

### 6. Rate Limiting (Brute Force Protection)
1.  Initiate pairing from a device (Device A).
2.  Manually use `curl` or a script to call `POST /api/verify_pin` for Device A with a WRONG PIN 5 times.
3.  **Verify**: After the 5th attempt, the server returns 401 "too many attempts".
4.  Immediately try to initiate a NEW pairing request from Device A (`/api/hello`).
5.  **Verify**: Server returns 429 "too many failed attempts".
6.  Wait 10 minutes (or restart the daemon for testing). Verify the block is lifted.

### 7. Localhost-Only Protection
1.  From a DIFFERENT machine on the same network, try to access:
    `http://<server-ip>:6769/api/pending`
2.  **Verify**: The browser or curl receives a **403 Forbidden**.
3.  Repeat for `POST /api/approve`.
4.  **Verify**: Access is denied. Only the local machine can manage pairings.

---

## Suite 4: TTL and Edge Cases

### 8. Pairing Request Expiration (TTL)
1.  Initiate pairing from a device.
2.  **Wait 5 minutes** without running `guga --approve`.
3.  Run `guga --approve`.
4.  **Verify**: The request has automatically disappeared from the list.
5.  **Verify**: The client shows "expired" or "timed out".

### 9. Force Re-pair
1.  Pair a device successfully.
2.  In the Android app settings, tap "Clear Auth" or re-scan the QR code to trigger a new handshake.
3.  **Verify**: Even though the device was previously trusted, the server receives a new pairing request because `force_pair` was used.
4.  Complete the approval flow.
5.  **Verify**: The old token is replaced by a new one, and sync continues.

### 10. Device Name Fallback
1.  Use a generic client (like `curl`) to call `/api/hello` without a `device_name`.
2.  Run `guga --approve`.
3.  **Verify**: The device appears as "Unknown Device".