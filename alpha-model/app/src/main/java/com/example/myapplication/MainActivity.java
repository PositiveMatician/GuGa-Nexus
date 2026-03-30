package com.example.myapplication;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputMethodManager;
import android.util.Log;
import android.widget.Button;
import android.widget.EditText;
import android.widget.TextView;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.appcompat.widget.SwitchCompat;

import com.journeyapps.barcodescanner.ScanContract;
import com.journeyapps.barcodescanner.ScanOptions;

import androidx.activity.result.ActivityResultLauncher;

public class MainActivity extends AppCompatActivity {
    private static final String TAG = "GuGaUI";

    private static final String PREFS_NAME = "AlphaPrefs";
    private static final String PREF_BACKEND_IP = "backend_ip";
    private static final String PREF_TTS_ENABLED = "tts_enabled";

    private static final String ACTION_PING_RESULT = "com.example.myapplication.PING_RESULT";
    private static final String ACTION_GUGA_RESPONSE = "com.example.myapplication.GUGA_RESPONSE";
    private static final String ACTION_SOCKET_CONNECTED = "com.example.myapplication.SOCKET_CONNECTED";
    private static final String ACTION_SOCKET_DISCONNECTED = "com.example.myapplication.SOCKET_DISCONNECTED";
    private static final String ACTION_UPDATE_IP = "com.example.myapplication.UPDATE_IP";
    private static final String ACTION_PING_BACKEND = "com.example.myapplication.PING_BACKEND";
    private static final String ACTION_CONNECT_SOCKET = "com.example.myapplication.CONNECT_SOCKET";
    private static final String ACTION_SEND_MANUAL_COMMAND = "com.example.myapplication.SEND_MANUAL_COMMAND";
    private static final String ACTION_SET_TTS_ENABLED = "com.example.myapplication.SET_TTS_ENABLED";

    private TextView statusText, chatDisplay;
    private EditText ipInput, manualCommandInput;
    private Button saveIpButton, scanQrButton, pingButton, connectSocketButton, sendManualCommandButton, toggleSettingsButton;
    private SwitchCompat ttsToggle;
    private android.view.View settingsOverlay, connectionOverlay, mainContent;

    private boolean isSettingsOpen = false;
    private boolean isBackendOnline = false;

    private SharedPreferences prefs;
    private final Handler mainHandler = new Handler(Looper.getMainLooper());

    private final ActivityResultLauncher<ScanOptions> qrCodeLauncher = registerForActivityResult(new ScanContract(),
            result -> {
                if (result.getContents() != null) {
                    handleNewIp(result.getContents());
                }
            });

    private final BroadcastReceiver serviceReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            String action = intent.getAction();
            if (action == null) return;

            switch (action) {
                case ACTION_PING_RESULT:
                    boolean success = intent.getBooleanExtra("success", false);
                    isBackendOnline = success;
                    Log.d(TAG, "Ping result received: " + success);
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

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE);
        bindViews();
        setupListeners();
        restoreState();
        updateConnectionVisibility();

        // Start background service
        startService(new Intent(this, GuGaService.class));
    }

    private void bindViews() {
        statusText = findViewById(R.id.statusText);
        chatDisplay = findViewById(R.id.chatDisplay);
        ipInput = findViewById(R.id.ipInput);
        saveIpButton = findViewById(R.id.saveIpButton);
        scanQrButton = findViewById(R.id.scanQrButton);
        pingButton = findViewById(R.id.pingButton);
        connectSocketButton = findViewById(R.id.connectSocketButton);
        manualCommandInput = findViewById(R.id.manualCommandInput);
        sendManualCommandButton = findViewById(R.id.sendManualCommandButton);
        ttsToggle = findViewById(R.id.ttsToggle);
        toggleSettingsButton = findViewById(R.id.toggleSettingsButton);
        settingsOverlay = findViewById(R.id.settingsOverlay);
        connectionOverlay = findViewById(R.id.connectionOverlay);
        mainContent = findViewById(R.id.mainContent);
    }

    private void setupListeners() {
        saveIpButton.setOnClickListener(v -> handleNewIp(ipInput.getText().toString()));
        scanQrButton.setOnClickListener(v -> {
            ScanOptions options = new ScanOptions();
            options.setDesiredBarcodeFormats(ScanOptions.QR_CODE);
            options.setPrompt("Scan Backend IP");
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
            Log.d(TAG, "Toggle Settings button clicked");
            toggleSettings();
        });
        
        sendManualCommandButton.setOnClickListener(v -> {
            Log.d(TAG, "Send Command button clicked");
            sendManualCommand();
        });
        manualCommandInput.setOnEditorActionListener((v, actionId, event) -> {
            if (actionId == EditorInfo.IME_ACTION_SEND) {
                Log.d(TAG, "IME Send action triggered");
                sendManualCommand();
                return true;
            }
            return false;
        });

        ttsToggle.setOnCheckedChangeListener((bv, isChecked) -> {
            Log.d(TAG, "TTS Toggle changed: " + isChecked);
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

    private void handleNewIp(String ip) {
        String clean = ip.trim().replace("http://", "").replace("https://", "");
        if (clean.endsWith("/")) clean = clean.substring(0, clean.length() - 1);
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
        
        // When closing settings, refresh connection visibility
        if (!isSettingsOpen) {
            updateConnectionVisibility();
        }
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
}