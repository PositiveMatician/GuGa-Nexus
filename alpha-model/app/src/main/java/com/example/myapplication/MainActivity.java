package com.example.myapplication;

import android.app.AlertDialog;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.util.Log;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputMethodManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import androidx.appcompat.app.AppCompatActivity;
import androidx.appcompat.widget.SwitchCompat;
import androidx.activity.result.ActivityResultLauncher;

import com.journeyapps.barcodescanner.ScanContract;
import com.journeyapps.barcodescanner.ScanOptions;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;

import okhttp3.Call;
import okhttp3.Callback;
import okhttp3.MediaType;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;

public class MainActivity extends AppCompatActivity {
    private static final String TAG = "GuGaUI";

    private static final String PREFS_NAME = "AlphaPrefs";
    private static final String PREF_BACKEND_IP = "backend_ip";
    private static final String PREF_TTS_ENABLED = "tts_enabled";

    private static final String ACTION_PING_RESULT       = "com.example.myapplication.PING_RESULT";
    private static final String ACTION_GUGA_RESPONSE     = "com.example.myapplication.GUGA_RESPONSE";
    private static final String ACTION_SOCKET_CONNECTED  = "com.example.myapplication.SOCKET_CONNECTED";
    private static final String ACTION_SOCKET_DISCONNECTED = "com.example.myapplication.SOCKET_DISCONNECTED";
    private static final String ACTION_UPDATE_IP         = "com.example.myapplication.UPDATE_IP";
    private static final String ACTION_PING_BACKEND      = "com.example.myapplication.PING_BACKEND";
    private static final String ACTION_CONNECT_SOCKET    = "com.example.myapplication.CONNECT_SOCKET";
    private static final String ACTION_SEND_MANUAL_COMMAND = "com.example.myapplication.SEND_MANUAL_COMMAND";
    private static final String ACTION_SET_TTS_ENABLED   = "com.example.myapplication.SET_TTS_ENABLED";
    private static final String ACTION_SAVE_AUTH_TOKEN   = "com.example.myapplication.SAVE_AUTH_TOKEN";

    private TextView statusText, chatDisplay;
    private EditText ipInput, manualCommandInput;
    private Button saveIpButton, scanQrButton, pingButton, connectSocketButton, sendManualCommandButton, toggleSettingsButton;
    private SwitchCompat ttsToggle;
    private android.view.View settingsOverlay, connectionOverlay, mainContent;

    private boolean isSettingsOpen = false;
    private boolean isBackendOnline = false;

    private SharedPreferences prefs;
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final OkHttpClient httpClient = new OkHttpClient();

    // ----------------------------------------------------------------
    // QR Scanner
    // ----------------------------------------------------------------

    private final ActivityResultLauncher<ScanOptions> qrCodeLauncher = registerForActivityResult(
            new ScanContract(),
            result -> {
                if (result.getContents() != null) {
                    String scannedIp = cleanIp(result.getContents());
                    // Save IP immediately, then start handshake
                    ipInput.setText(scannedIp);
                    prefs.edit().putString(PREF_BACKEND_IP, scannedIp).apply();
                    Intent updateIntent = new Intent(ACTION_UPDATE_IP);
                    updateIntent.putExtra("ip", scannedIp);
                    sendBroadcast(updateIntent);
                    statusText.setText("Connecting to GuGu...");
                    performHandshake(scannedIp);
                }
            });

    // ----------------------------------------------------------------
    // Broadcast Receiver
    // ----------------------------------------------------------------

    private final BroadcastReceiver serviceReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            String action = intent.getAction();
            if (action == null) return;

            switch (action) {
                case ACTION_PING_RESULT:
                    boolean success = intent.getBooleanExtra("success", false);
                    isBackendOnline = success;
                    Log.d(TAG, "Ping result: " + success);
                    updateConnectionVisibility();
                    statusText.setText(success ? "STATUS: BACKEND ONLINE" : "STATUS: PING FAILED");
                    statusText.setTextColor(success ? Color.WHITE : Color.RED);
                    break;
                case ACTION_SOCKET_CONNECTED:
                    Log.d(TAG, "Socket connected");
                    statusText.setText("STATUS: LIVE SYNC ACTIVE");
                    statusText.setTextColor(Color.WHITE);
                    break;
                case ACTION_SOCKET_DISCONNECTED:
                    Log.d(TAG, "Socket disconnected");
                    statusText.setText("STATUS: DISCONNECTED");
                    statusText.setTextColor(Color.GRAY);
                    break;
                case ACTION_GUGA_RESPONSE:
                    String message = intent.getStringExtra("message");
                    Log.d(TAG, "Assistant response: " + message);
                    appendChat("GuGu: " + message);
                    if (!ttsToggle.isChecked()) {
                        Toast.makeText(context, "GuGu: " + message, Toast.LENGTH_SHORT).show();
                    }
                    break;
            }
        }
    };

    // ----------------------------------------------------------------
    // Lifecycle
    // ----------------------------------------------------------------

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE);
        bindViews();
        setupListeners();
        restoreState();
        updateConnectionVisibility();

        startService(new Intent(this, GuGaService.class));
    }

    @Override
    protected void onResume() {
        super.onResume();
        IntentFilter filter = new IntentFilter();
        filter.addAction(ACTION_PING_RESULT);
        filter.addAction(ACTION_GUGA_RESPONSE);
        filter.addAction(ACTION_SOCKET_CONNECTED);
        filter.addAction(ACTION_SOCKET_DISCONNECTED);
        registerReceiver(serviceReceiver, filter, Context.RECEIVER_EXPORTED);
    }

    @Override
    protected void onPause() {
        super.onPause();
        unregisterReceiver(serviceReceiver);
    }

    // ----------------------------------------------------------------
    // View Setup
    // ----------------------------------------------------------------

    private void bindViews() {
        statusText           = findViewById(R.id.statusText);
        chatDisplay          = findViewById(R.id.chatDisplay);
        ipInput              = findViewById(R.id.ipInput);
        saveIpButton         = findViewById(R.id.saveIpButton);
        scanQrButton         = findViewById(R.id.scanQrButton);
        pingButton           = findViewById(R.id.pingButton);
        connectSocketButton  = findViewById(R.id.connectSocketButton);
        manualCommandInput   = findViewById(R.id.manualCommandInput);
        sendManualCommandButton = findViewById(R.id.sendManualCommandButton);
        ttsToggle            = findViewById(R.id.ttsToggle);
        toggleSettingsButton = findViewById(R.id.toggleSettingsButton);
        settingsOverlay      = findViewById(R.id.settingsOverlay);
        connectionOverlay    = findViewById(R.id.connectionOverlay);
        mainContent          = findViewById(R.id.mainContent);
    }

    private void setupListeners() {
        saveIpButton.setOnClickListener(v -> handleNewIp(ipInput.getText().toString()));

        scanQrButton.setOnClickListener(v -> {
            ScanOptions options = new ScanOptions();
            options.setDesiredBarcodeFormats(ScanOptions.QR_CODE);
            options.setPrompt("Scan GuGu Backend QR");
            options.setBeepEnabled(true);
            options.setOrientationLocked(false);
            qrCodeLauncher.launch(options);
        });

        pingButton.setOnClickListener(v -> {
            Log.d(TAG, "Ping button clicked");
            sendBroadcast(new Intent(ACTION_PING_BACKEND));
        });

        connectSocketButton.setOnClickListener(v -> {
            Log.d(TAG, "Connect Socket button clicked");
            sendBroadcast(new Intent(ACTION_CONNECT_SOCKET));
        });

        toggleSettingsButton.setOnClickListener(v -> {
            Log.d(TAG, "Toggle settings clicked");
            toggleSettings();
        });

        sendManualCommandButton.setOnClickListener(v -> {
            Log.d(TAG, "Send button clicked");
            sendManualCommand();
        });

        manualCommandInput.setOnEditorActionListener((v, actionId, event) -> {
            if (actionId == EditorInfo.IME_ACTION_SEND) {
                sendManualCommand();
                return true;
            }
            return false;
        });

        ttsToggle.setOnCheckedChangeListener((bv, isChecked) -> {
            Log.d(TAG, "TTS toggle: " + isChecked);
            prefs.edit().putBoolean(PREF_TTS_ENABLED, isChecked).apply();
            Intent intent = new Intent(ACTION_SET_TTS_ENABLED);
            intent.putExtra("enabled", isChecked);
            sendBroadcast(intent);
        });
    }

    private void restoreState() {
        String ip = prefs.getString(PREF_BACKEND_IP, "");
        if (!ip.isEmpty()) {
            ipInput.setText(ip);
            mainHandler.postDelayed(() -> sendBroadcast(new Intent(ACTION_PING_BACKEND)), 500);
        }
        ttsToggle.setChecked(prefs.getBoolean(PREF_TTS_ENABLED, true));
    }

    // ----------------------------------------------------------------
    // Phase 10.1: Cryptographic Handshake
    // ----------------------------------------------------------------

    /** Gets the device's stable Android ID. */
    private String fetchAndroidId() {
        return Settings.Secure.getString(getContentResolver(), Settings.Secure.ANDROID_ID);
    }

    /**
     * Step 1: Send /api/hello to the server with the device ID.
     * Determines whether to connect directly (trusted) or show PIN dialog.
     */
    private void performHandshake(String ip) {
        String deviceId = fetchAndroidId();
        Log.d(TAG, "Performing handshake with ip=" + ip + " device=" + deviceId);

        try {
            JSONObject body = new JSONObject();
            body.put("device_id", deviceId);
            RequestBody reqBody = RequestBody.create(body.toString(), MediaType.parse("application/json"));
            Request request = new Request.Builder()
                    .url("http://" + ip + "/api/hello")
                    .post(reqBody)
                    .build();

            httpClient.newCall(request).enqueue(new Callback() {
                @Override
                public void onFailure(Call call, IOException e) {
                    Log.e(TAG, "Handshake failed", e);
                    mainHandler.post(() -> statusText.setText("HANDSHAKE FAILED"));
                }

                @Override
                public void onResponse(Call call, Response response) throws IOException {
                    try {
                        String responseBody = response.body().string();
                        JSONObject json = new JSONObject(responseBody);
                        String status = json.getString("status");

                        if ("trusted".equals(status)) {
                            Log.d(TAG, "Device already trusted — connecting");
                            mainHandler.post(() -> {
                                statusText.setText("STATUS: TRUSTED DEVICE");
                                statusText.setTextColor(Color.WHITE);
                                connectSocket();
                            });
                        } else if ("pin_required".equals(status)) {
                            Log.d(TAG, "PIN required — showing dialog");
                            mainHandler.post(() -> showPinDialog(ip, deviceId));
                        }
                    } catch (JSONException e) {
                        Log.e(TAG, "Handshake parse error", e);
                    } finally {
                        response.close();
                    }
                }
            });
        } catch (JSONException e) {
            Log.e(TAG, "Handshake build error", e);
        }
    }

    /**
     * Step 2: Show PIN entry dialog. Called when server requests PIN pairing.
     */
    private void showPinDialog(String ip, String deviceId) {
        EditText pinInput = new EditText(this);
        pinInput.setInputType(android.text.InputType.TYPE_CLASS_NUMBER | android.text.InputType.TYPE_NUMBER_VARIATION_PASSWORD);
        pinInput.setHint("8-digit pairing PIN");
        pinInput.setTextColor(Color.WHITE);
        pinInput.setHintTextColor(Color.GRAY);

        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(64, 32, 64, 0);
        layout.addView(pinInput);

        new AlertDialog.Builder(this, android.R.style.Theme_Material_Dialog_Alert)
                .setTitle("Pair with GuGu")
                .setMessage("Enter the 8-digit PIN shown on your desktop:")
                .setView(layout)
                .setPositiveButton("PAIR", (dialog, which) -> {
                    String pin = pinInput.getText().toString().trim();
                    if (!pin.isEmpty()) {
                        verifyPin(ip, deviceId, pin);
                    }
                })
                .setNegativeButton("Cancel", null)
                .show();
    }

    /**
     * Step 3: Submit PIN to /api/verify_pin. On success, save token and connect.
     */
    private void verifyPin(String ip, String deviceId, String pin) {
        mainHandler.post(() -> statusText.setText("Verifying PIN..."));
        try {
            JSONObject body = new JSONObject();
            body.put("device_id", deviceId);
            body.put("pin", pin);
            RequestBody reqBody = RequestBody.create(body.toString(), MediaType.parse("application/json"));
            Request request = new Request.Builder()
                    .url("http://" + ip + "/api/verify_pin")
                    .post(reqBody)
                    .build();

            httpClient.newCall(request).enqueue(new Callback() {
                @Override
                public void onFailure(Call call, IOException e) {
                    Log.e(TAG, "PIN verification failed", e);
                    mainHandler.post(() -> {
                        statusText.setText("VERIFICATION FAILED");
                        statusText.setTextColor(Color.RED);
                    });
                }

                @Override
                public void onResponse(Call call, Response response) throws IOException {
                    try {
                        String responseBody = response.body().string();
                        if (response.code() == 401) {
                            Log.w(TAG, "Wrong PIN entered");
                            mainHandler.post(() -> {
                                statusText.setText("WRONG PIN — Try again");
                                statusText.setTextColor(Color.RED);
                                Toast.makeText(MainActivity.this, "Incorrect PIN", Toast.LENGTH_SHORT).show();
                            });
                            return;
                        }
                        JSONObject json = new JSONObject(responseBody);
                        String token = json.getString("token");
                        Log.d(TAG, "Pairing successful, token received.");

                        // Save token securely via service
                        Intent tokenIntent = new Intent(ACTION_SAVE_AUTH_TOKEN);
                        tokenIntent.putExtra("token", token);
                        sendBroadcast(tokenIntent);

                        mainHandler.post(() -> {
                            statusText.setText("Device Paired & Secured");
                            statusText.setTextColor(Color.WHITE);
                            connectSocket();
                        });
                    } catch (JSONException e) {
                        Log.e(TAG, "PIN verify parse error", e);
                    } finally {
                        response.close();
                    }
                }
            });
        } catch (JSONException e) {
            Log.e(TAG, "PIN verify build error", e);
        }
    }

    /** Broadcasts the connect-socket action to the service. */
    private void connectSocket() {
        sendBroadcast(new Intent(ACTION_CONNECT_SOCKET));
    }

    // ----------------------------------------------------------------
    // IP & UI Helpers
    // ----------------------------------------------------------------

    private String cleanIp(String ip) {
        String clean = ip.trim().replace("http://", "").replace("https://", "");
        if (clean.endsWith("/")) clean = clean.substring(0, clean.length() - 1);
        return clean;
    }

    private void handleNewIp(String ip) {
        String clean = cleanIp(ip);
        ipInput.setText(clean);
        prefs.edit().putString(PREF_BACKEND_IP, clean).apply();
        Intent intent = new Intent(ACTION_UPDATE_IP);
        intent.putExtra("ip", clean);
        sendBroadcast(intent);
        statusText.setText("IP UPDATED: " + clean);
    }

    private void toggleSettings() {
        isSettingsOpen = !isSettingsOpen;
        settingsOverlay.setVisibility(isSettingsOpen ? android.view.View.VISIBLE : android.view.View.GONE);
        toggleSettingsButton.setText(isSettingsOpen ? "<" : ">");
        if (!isSettingsOpen) updateConnectionVisibility();
    }

    private void updateConnectionVisibility() {
        if (isBackendOnline) {
            connectionOverlay.setVisibility(android.view.View.GONE);
            mainContent.setVisibility(android.view.View.VISIBLE);
        } else {
            connectionOverlay.setVisibility(android.view.View.VISIBLE);
            mainContent.setVisibility(android.view.View.GONE);
        }
    }

    private void sendManualCommand() {
        String cmd = manualCommandInput.getText().toString().trim();
        if (cmd.isEmpty()) return;
        appendChat("You: " + cmd);
        Intent intent = new Intent(ACTION_SEND_MANUAL_COMMAND);
        intent.putExtra("command", cmd);
        sendBroadcast(intent);
        manualCommandInput.setText("");
        hideKeyboard();
    }

    private void appendChat(String text) {
        String current = chatDisplay.getText().toString();
        if (current.startsWith("Ready for GuGu")) current = "";
        chatDisplay.setText(text + "\n\n" + current);
    }

    private void hideKeyboard() {
        InputMethodManager imm = (InputMethodManager) getSystemService(INPUT_METHOD_SERVICE);
        if (imm != null) imm.hideSoftInputFromWindow(manualCommandInput.getWindowToken(), 0);
    }
}