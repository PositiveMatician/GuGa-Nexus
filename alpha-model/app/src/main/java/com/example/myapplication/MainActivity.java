package com.example.myapplication;

import android.app.AlertDialog;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.media.AudioManager;
import android.media.Ringtone;
import android.media.RingtoneManager;
import android.media.ToneGenerator;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.provider.Settings;
import android.util.Log;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputMethodManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import androidx.activity.OnBackPressedCallback;
import androidx.appcompat.app.AppCompatActivity;
import androidx.appcompat.widget.SwitchCompat;
import androidx.activity.result.ActivityResultLauncher;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import com.journeyapps.barcodescanner.ScanContract;
import com.journeyapps.barcodescanner.ScanOptions;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;
import java.util.ArrayList;
import java.util.List;

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
    private static final String ACTION_SET_FOREGROUND    = "com.example.myapplication.SET_FOREGROUND";

    private TextView statusText;
    private RecyclerView chatRecyclerView;
    private ChatAdapter chatAdapter;
    private List<ChatMessage> chatMessages = new ArrayList<>();
    
    private EditText ipInput, manualCommandInput;
    private Button saveIpButton, scanQrButton, pingButton, connectSocketButton, sendManualCommandButton, toggleSettingsButton, clearHistoryButton;
    private SwitchCompat ttsToggle;
    private android.view.View settingsOverlay, connectionOverlay, mainContent;

    private boolean isSettingsOpen = false;
    private boolean isBackendOnline = false;
    private boolean isSocketConnected = false;

    private SharedPreferences prefs;
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final OkHttpClient httpClient = new OkHttpClient();
    private ToneGenerator toneGenerator;

    // ----------------------------------------------------------------
    // QR Scanner
    // ----------------------------------------------------------------

    private final ActivityResultLauncher<ScanOptions> qrCodeLauncher = registerForActivityResult(
            new ScanContract(),
            result -> {
                if (result.getContents() != null) {
                    String scannedUrl = result.getContents().trim();
                    if (scannedUrl.endsWith("/")) scannedUrl = scannedUrl.substring(0, scannedUrl.length() - 1);
                    
                    vibrate(); 
                    
                    ipInput.setText(scannedUrl);
                    prefs.edit().putString(PREF_BACKEND_IP, scannedUrl).apply();
                    Intent updateIntent = new Intent(ACTION_UPDATE_IP);
                    updateIntent.putExtra("ip", scannedUrl);
                    sendBroadcast(updateIntent);
                    statusText.setText("Connecting to GuGu...");
                    performHandshake(scannedUrl);
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
                    updateConnectionVisibility();
                    statusText.setText(success ? "STATUS: BACKEND ONLINE" : "STATUS: PING FAILED");
                    statusText.setTextColor(Color.WHITE);
                    break;
                case ACTION_SOCKET_CONNECTED:
                    isSocketConnected = true;
                    updateConnectionVisibility();
                    statusText.setText("STATUS: LIVE SYNC ACTIVE");
                    statusText.setTextColor(Color.WHITE);
                    break;
                case ACTION_SOCKET_DISCONNECTED:
                    isSocketConnected = false;
                    updateConnectionVisibility();
                    statusText.setText("STATUS: DISCONNECTED");
                    statusText.setTextColor(Color.GRAY);
                    break;
                case ACTION_GUGA_RESPONSE:
                    String msg = intent.getStringExtra("message");
                    if (msg != null) {
                        appendChat(new ChatMessage(msg, false));
                        playTing();
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
        toneGenerator = new ToneGenerator(AudioManager.STREAM_NOTIFICATION, 100);

        initViews();
        setupHistory();
        setupListeners();
        setupBackButton();

        IntentFilter filter = new IntentFilter();
        filter.addAction(ACTION_PING_RESULT);
        filter.addAction(ACTION_SOCKET_CONNECTED);
        filter.addAction(ACTION_SOCKET_DISCONNECTED);
        filter.addAction(ACTION_GUGA_RESPONSE);
        registerReceiver(serviceReceiver, filter, Context.RECEIVER_EXPORTED);

        startService(new Intent(this, GuGaService.class));

        String currentIp = prefs.getString(PREF_BACKEND_IP, "");
        if (!currentIp.isEmpty()) {
            ipInput.setText(currentIp);
            performHandshake(currentIp);
        }
    }

    private void setupBackButton() {
        getOnBackPressedDispatcher().addCallback(this, new OnBackPressedCallback(true) {
            @Override
            public void handleOnBackPressed() {
                if (isSettingsOpen) {
                    toggleSettings();
                } else {
                    setEnabled(false);
                    MainActivity.this.onBackPressed();
                    // On newer API, just finish() might be better, but this works for general cases
                }
            }
        });
    }

    @Override
    protected void onStart() {
        super.onStart();
        sendForegroundState(true);
    }

    @Override
    protected void onStop() {
        super.onStop();
        sendForegroundState(false);
    }

    private void sendForegroundState(boolean isForeground) {
        Intent intent = new Intent(ACTION_SET_FOREGROUND);
        intent.putExtra("isForeground", isForeground);
        sendBroadcast(intent);
    }

    @Override
    protected void onDestroy() {
        unregisterReceiver(serviceReceiver);
        if (toneGenerator != null) toneGenerator.release();
        super.onDestroy();
    }

    // ----------------------------------------------------------------
    // Setup
    // ----------------------------------------------------------------

    private void initViews() {
        statusText           = findViewById(R.id.statusText);
        chatRecyclerView     = findViewById(R.id.chatRecyclerView);
        ipInput              = findViewById(R.id.ipInput);
        saveIpButton         = findViewById(R.id.saveIpButton);
        scanQrButton         = findViewById(R.id.scanQrButton);
        pingButton           = findViewById(R.id.pingButton);
        connectSocketButton  = findViewById(R.id.connectSocketButton);
        manualCommandInput   = findViewById(R.id.manualCommandInput);
        sendManualCommandButton = findViewById(R.id.sendManualCommandButton);
        ttsToggle            = findViewById(R.id.ttsToggle);
        toggleSettingsButton = findViewById(R.id.toggleSettingsButton);
        clearHistoryButton   = findViewById(R.id.clearHistoryButton);
        settingsOverlay      = findViewById(R.id.settingsOverlay);
        connectionOverlay    = findViewById(R.id.connectionOverlay);
        mainContent          = findViewById(R.id.mainContent);

        chatAdapter = new ChatAdapter(chatMessages);
        chatRecyclerView.setLayoutManager(new LinearLayoutManager(this));
        chatRecyclerView.setAdapter(chatAdapter);

        boolean ttsEnabled = prefs.getBoolean(PREF_TTS_ENABLED, true);
        ttsToggle.setChecked(ttsEnabled);
        updateTtsToggleColor(ttsEnabled);
    }

    private void setupHistory() {
        List<ChatMessage> history = ChatHistory.load(this);
        chatMessages.addAll(history);
        chatAdapter.notifyDataSetChanged();
        if (!chatMessages.isEmpty()) {
            chatRecyclerView.scrollToPosition(chatMessages.size() - 1);
        }
    }

    private void setupListeners() {
        saveIpButton.setOnClickListener(v -> handleNewIp(ipInput.getText().toString()));
        scanQrButton.setOnClickListener(v -> {
            ScanOptions options = new ScanOptions();
            options.setDesiredBarcodeFormats(ScanOptions.QR_CODE);
            options.setPrompt("Scan GuGu IP");
            options.setBeepEnabled(false);
            options.setOrientationLocked(false);
            qrCodeLauncher.launch(options);
        });

        pingButton.setOnClickListener(v -> sendBroadcast(new Intent(ACTION_PING_BACKEND)));
        connectSocketButton.setOnClickListener(v -> {
            String ip = ipInput.getText().toString().trim();
            if (!ip.isEmpty()) performHandshake(ip);
        });

        ttsToggle.setOnCheckedChangeListener((btn, checked) -> {
            prefs.edit().putBoolean(PREF_TTS_ENABLED, checked).apply();
            updateTtsToggleColor(checked);
            Intent intent = new Intent(ACTION_SET_TTS_ENABLED);
            intent.putExtra("enabled", checked);
            sendBroadcast(intent);
        });

        sendManualCommandButton.setOnClickListener(v -> sendManualCommand());
        manualCommandInput.setOnEditorActionListener((v, actionId, event) -> {
            if (actionId == EditorInfo.IME_ACTION_SEND) {
                sendManualCommand();
                return true;
            }
            return false;
        });

        toggleSettingsButton.setOnClickListener(v -> toggleSettings());

        clearHistoryButton.setOnClickListener(v -> {
            new AlertDialog.Builder(this)
                .setTitle("Clear History")
                .setMessage("Delete all saved messages?")
                .setPositiveButton("Clear", (dialog, which) -> {
                    ChatHistory.clear(this);
                    chatMessages.clear();
                    chatAdapter.notifyDataSetChanged();
                    Toast.makeText(this, "History cleared", Toast.LENGTH_SHORT).show();
                })
                .setNegativeButton("Cancel", null)
                .show();
        });
    }

    private void updateTtsToggleColor(boolean enabled) {
        int color = enabled ? Color.WHITE : Color.GRAY;
        ttsToggle.setTextColor(color);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            ttsToggle.setThumbTintList(android.content.res.ColorStateList.valueOf(color));
        }
    }

    // ----------------------------------------------------------------
    // Phase 11 Handshake
    // ----------------------------------------------------------------

    private String fetchAndroidId() {
        return Settings.Secure.getString(getContentResolver(), Settings.Secure.ANDROID_ID);
    }

    private void performHandshake(String ipBase) {
        performHandshake(ipBase, false);
    }

    private void performHandshake(String ipBase, boolean forcePair) {
        String url = cleanIp(ipBase) + "/api/hello";
        String deviceId = fetchAndroidId();
        
        try {
            JSONObject payload = new JSONObject();
            payload.put("device_id", deviceId);
            payload.put("force_pair", forcePair);
            
            RequestBody body = RequestBody.create(payload.toString(), MediaType.parse("application/json"));
            Request request = new Request.Builder().url(url).post(body).build();

            httpClient.newCall(request).enqueue(new Callback() {
                @Override
                public void onFailure(Call call, IOException e) {
                    mainHandler.post(() -> statusText.setText("HANDSHAKE FAILED"));
                }

                @Override
                public void onResponse(Call call, Response response) throws IOException {
                    try {
                        String responseBody = response.body().string();
                        JSONObject json = new JSONObject(responseBody);
                        String status = json.getString("status");

                        if ("trusted".equals(status)) {
                            String token = SecurityUtils.getAuthToken(MainActivity.this);
                            if (token == null) {
                                mainHandler.post(() -> performHandshake(ipBase, true));
                            } else {
                                mainHandler.post(() -> {
                                    statusText.setText("TRUSTED DEVICE");
                                    sendBroadcast(new Intent(ACTION_CONNECT_SOCKET));
                                });
                            }
                        } else if ("pin_required".equals(status)) {
                            mainHandler.post(() -> showPinDialog(ipBase, deviceId));
                        }
                    } catch (Exception e) {
                        Log.e(TAG, "Handshake response error", e);
                    } finally {
                        response.close();
                    }
                }
            });
        } catch (Exception e) {
            Log.e(TAG, "Handshake request error", e);
        }
    }

    private void showPinDialog(String ip, String deviceId) {
        EditText pinInput = new EditText(this);
        pinInput.setInputType(android.text.InputType.TYPE_CLASS_NUMBER | android.text.InputType.TYPE_NUMBER_VARIATION_PASSWORD);
        pinInput.setHint("8-digit PIN");
        pinInput.setTextColor(Color.WHITE);
        pinInput.setHintTextColor(Color.GRAY);

        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(64, 32, 64, 0);
        layout.addView(pinInput);

        new AlertDialog.Builder(this)
                .setTitle("Pair Device")
                .setMessage("Enter the PIN shown on your GuGu dashboard:")
                .setView(layout)
                .setPositiveButton("VERIFY", (dialog, which) -> {
                    String pin = pinInput.getText().toString().trim();
                    if (!pin.isEmpty()) verifyPin(ip, deviceId, pin);
                })
                .setNegativeButton("Cancel", null)
                .show();
    }

    private void verifyPin(String ip, String deviceId, String pin) {
        String url = cleanIp(ip) + "/api/verify_pin";
        try {
            JSONObject body = new JSONObject();
            body.put("device_id", deviceId);
            body.put("pin", pin);
            body.put("client_type", "app");

            RequestBody reqBody = RequestBody.create(body.toString(), MediaType.parse("application/json"));
            Request request = new Request.Builder().url(url).post(reqBody).build();

            httpClient.newCall(request).enqueue(new Callback() {
                @Override
                public void onFailure(Call call, IOException e) {
                    mainHandler.post(() -> statusText.setText("VERIFICATION FAILED"));
                }

                @Override
                public void onResponse(Call call, Response response) throws IOException {
                    try {
                        String responseBody = response.body().string();
                        if (response.isSuccessful()) {
                            JSONObject json = new JSONObject(responseBody);
                            String token = json.getString("token");
                            
                            SecurityUtils.saveAuthToken(MainActivity.this, token);
                            
                            Intent intent = new Intent(ACTION_SAVE_AUTH_TOKEN);
                            intent.putExtra("token", token);
                            sendBroadcast(intent);
                            
                            mainHandler.post(() -> {
                                statusText.setText("PAIRED SUCCESSFULLY");
                                sendBroadcast(new Intent(ACTION_CONNECT_SOCKET));
                            });
                        } else {
                            mainHandler.post(() -> Toast.makeText(MainActivity.this, "Invalid PIN", Toast.LENGTH_SHORT).show());
                        }
                    } catch (Exception e) {
                        Log.e(TAG, "PIN verification error", e);
                    } finally {
                        response.close();
                    }
                }
            });
        } catch (Exception e) {
            Log.e(TAG, "PIN verification build error", e);
        }
    }

    // ----------------------------------------------------------------
    // Helpers
    // ----------------------------------------------------------------

    private String cleanIp(String ip) {
        String clean = ip.trim();
        if (clean.endsWith("/")) clean = clean.substring(0, clean.length() - 1);
        if (!clean.startsWith("http")) clean = "http://" + clean;
        return clean;
    }

    private void handleNewIp(String ip) {
        String clean = cleanIp(ip);
        if (clean.isEmpty()) return;
        ipInput.setText(clean);
        prefs.edit().putString(PREF_BACKEND_IP, clean).apply();
        Intent intent = new Intent(ACTION_UPDATE_IP);
        intent.putExtra("ip", clean);
        sendBroadcast(intent);
        statusText.setText("IP UPDATED");
        performHandshake(clean);
    }

    private void toggleSettings() {
        isSettingsOpen = !isSettingsOpen;
        settingsOverlay.setVisibility(isSettingsOpen ? android.view.View.VISIBLE : android.view.View.GONE);
        toggleSettingsButton.setText(isSettingsOpen ? "<" : ">");
        if (!isSettingsOpen) updateConnectionVisibility();
    }

    private void updateConnectionVisibility() {
        if (isBackendOnline || isSocketConnected) {
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
        appendChat(new ChatMessage(cmd, true));
        Intent intent = new Intent(ACTION_SEND_MANUAL_COMMAND);
        intent.putExtra("command", cmd);
        sendBroadcast(intent);
        manualCommandInput.setText("");
        hideKeyboard();
    }

    private void appendChat(ChatMessage message) {
        mainHandler.post(() -> {
            chatMessages.add(message);
            chatAdapter.notifyItemInserted(chatMessages.size() - 1);
            chatRecyclerView.scrollToPosition(chatMessages.size() - 1);
            ChatHistory.save(this, chatMessages);
        });
    }

    private void playTing() {
        boolean ttsEnabled = prefs.getBoolean(PREF_TTS_ENABLED, true);
        if (ttsEnabled) return; // Silent if TTS on

        try {
            Uri notification = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION);
            Ringtone r = RingtoneManager.getRingtone(getApplicationContext(), notification);
            r.play();
        } catch (Exception e) {
            if (toneGenerator != null) toneGenerator.startTone(ToneGenerator.TONE_PROP_BEEP, 200);
        }
    }

    private void vibrate() {
        Vibrator v = (Vibrator) getSystemService(Context.VIBRATOR_SERVICE);
        if (v != null && v.hasVibrator()) {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                v.vibrate(VibrationEffect.createOneShot(100, VibrationEffect.DEFAULT_AMPLITUDE));
            } else {
                v.vibrate(100);
            }
        }
    }

    private void hideKeyboard() {
        InputMethodManager imm = (InputMethodManager) getSystemService(INPUT_METHOD_SERVICE);
        if (imm != null) imm.hideSoftInputFromWindow(manualCommandInput.getWindowToken(), 0);
    }
}