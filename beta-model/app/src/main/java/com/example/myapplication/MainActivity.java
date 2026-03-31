package com.example.myapplication;

import android.Manifest;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputMethodManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.Switch;
import android.widget.TextView;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.appcompat.widget.SwitchCompat;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;
import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowInsetsCompat;

import com.journeyapps.barcodescanner.ScanContract;
import com.journeyapps.barcodescanner.ScanOptions;

import androidx.activity.result.ActivityResultLauncher;

public class MainActivity extends AppCompatActivity {

    // -----------------------------------------------------------------------
    // Constants
    // -----------------------------------------------------------------------
    private static final int REQUEST_RECORD_AUDIO_PERMISSION = 200;
    private static final String PREFS_NAME = "AssistantPrefs";
    private static final String PREF_BACKEND_IP = "backend_ip";
    private static final int WAKE_FLASH_DURATION_MS = 2000;

    // Broadcast action constants — single source of truth, avoids typos
    private static final String ACTION_WAKE_WORD_DETECTED = "com.example.myapplication.WAKE_WORD_DETECTED";
    private static final String ACTION_COMMAND_TRANSCRIBED = "com.example.myapplication.COMMAND_TRANSCRIBED";
    private static final String ACTION_PING_RESULT = "com.example.myapplication.PING_RESULT";
    private static final String ACTION_ASSISTANT_RESPONSE = "com.example.myapplication.ASSISTANT_RESPONSE";
    private static final String ACTION_SOCKET_CONNECTED = "com.example.myapplication.SOCKET_CONNECTED";
    private static final String ACTION_SOCKET_DISCONNECTED = "com.example.myapplication.SOCKET_DISCONNECTED";
    private static final String ACTION_UPDATE_THRESHOLD = "com.example.myapplication.UPDATE_THRESHOLD";
    private static final String ACTION_SWITCH_MODEL = "com.example.myapplication.SWITCH_MODEL";
    private static final String ACTION_SIMULATE_WAKE_WORD = "com.example.myapplication.SIMULATE_WAKE_WORD";
    private static final String ACTION_UPDATE_IP = "com.example.myapplication.UPDATE_IP";
    private static final String ACTION_PING_BACKEND = "com.example.myapplication.PING_BACKEND";
    private static final String ACTION_CONNECT_SOCKET = "com.example.myapplication.CONNECT_SOCKET";
    private static final String ACTION_SEND_MANUAL_COMMAND = "com.example.myapplication.SEND_MANUAL_COMMAND";
    private static final String ACTION_TOGGLE_LISTENING = "com.example.myapplication.TOGGLE_LISTENING";

    // -----------------------------------------------------------------------
    // Views
    // -----------------------------------------------------------------------
    private TextView statusText;
    private android.view.View mainLayout;
    private EditText thresholdInput;
    private Button applyThresholdButton;
    private SwitchCompat listeningToggle;
    private TextView thresholdLabel;
    private Button manualWakeButton;
    private EditText ipInput;
    private Button saveIpButton;
    private Button scanQrButton;
    private Button pingButton;
    private Button connectSocketButton;
    private EditText manualCommandInput;
    private Button sendManualCommandButton;
    private Button trainVoiceButton;
    private Button btnViewLogs;
    private Button btnTestWakeWord;

    // -----------------------------------------------------------------------
    // State
    // -----------------------------------------------------------------------
    private SharedPreferences prefs;
    private String currentWakeWord = "Personal";

    // Single shared handler — never allocate a new Handler on the fly
    private final Handler mainHandler = new Handler(Looper.getMainLooper());

    // -----------------------------------------------------------------------
    // QR scanner launcher
    // -----------------------------------------------------------------------
    private final ActivityResultLauncher<ScanOptions> qrCodeLauncher = registerForActivityResult(new ScanContract(),
            result -> {
                if (result.getContents() != null) {
                    handleNewIp(result.getContents());
                }
            });

    // -----------------------------------------------------------------------
    // BroadcastReceiver
    // -----------------------------------------------------------------------
    private final BroadcastReceiver serviceReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            if (intent == null || intent.getAction() == null)
                return;

            switch (intent.getAction()) {

                case ACTION_WAKE_WORD_DETECTED:
                    statusText.setText("WAKE WORD DETECTED!");
                    mainLayout.setBackgroundColor(Color.GREEN);
                    // Restore background using the shared handler — no new allocation
                    mainHandler.postDelayed(() -> {
                        mainLayout.setBackgroundColor(getDefaultBackground());
                        statusText.setText(buildListeningStatus());
                    }, WAKE_FLASH_DURATION_MS);
                    break;

                case ACTION_COMMAND_TRANSCRIBED:
                    statusText.setText("You said: " + intent.getStringExtra("command"));
                    break;

                case ACTION_PING_RESULT:
                    boolean success = intent.getBooleanExtra("success", false);
                    statusText.setText(success
                            ? "Ping Successful! Backend is connected."
                            : "Ping Failed. Check IP and Wi-Fi.");
                    break;

                case ACTION_ASSISTANT_RESPONSE:
                    statusText.setText("Assistant: " + intent.getStringExtra("message"));
                    break;

                case ACTION_SOCKET_CONNECTED:
                    statusText.setText("Status: Live Audio Stream Connected");
                    statusText.setTextColor(Color.BLUE);
                    break;

                case ACTION_SOCKET_DISCONNECTED:
                    statusText.setText("Status: Audio Stream Disconnected");
                    statusText.setTextColor(Color.RED);
                    break;
            }
        }
    };

    // -----------------------------------------------------------------------
    // Lifecycle
    // -----------------------------------------------------------------------
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        // Start the service immediately so networking (socket/ping) is always available
        Intent serviceIntent = new Intent(this, VoiceAssistantService.class);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(serviceIntent);
        } else {
            startService(serviceIntent);
        }

        applyWindowInsets();
        bindViews();
        setupListeners();
        restoreSavedIp();
    }

    @Override
    protected void onResume() {
        super.onResume();
        ContextCompat.registerReceiver(this, serviceReceiver,
                buildIntentFilter(), ContextCompat.RECEIVER_NOT_EXPORTED);
    }

    @Override
    protected void onPause() {
        super.onPause();
        try {
            unregisterReceiver(serviceReceiver);
        } catch (IllegalArgumentException ignored) {
            // Receiver wasn't registered — safe to ignore
        }
    }

    // -----------------------------------------------------------------------
    // Initialisation helpers
    // -----------------------------------------------------------------------
    private void applyWindowInsets() {
        ViewCompat.setOnApplyWindowInsetsListener(findViewById(R.id.main), (v, insets) -> {
            Insets systemBars = insets.getInsets(WindowInsetsCompat.Type.systemBars());
            v.setPadding(systemBars.left, systemBars.top, systemBars.right, systemBars.bottom);
            return insets;
        });
    }

    private void bindViews() {
        mainLayout = findViewById(R.id.main);
        statusText = findViewById(R.id.statusText);
        thresholdInput = findViewById(R.id.thresholdInput);
        applyThresholdButton = findViewById(R.id.applyThresholdButton);
        thresholdLabel = findViewById(R.id.thresholdLabel);
        manualWakeButton = findViewById(R.id.manualWakeButton);
        ipInput = findViewById(R.id.ipInput);
        saveIpButton = findViewById(R.id.saveIpButton);
        scanQrButton = findViewById(R.id.scanQrButton);
        pingButton = findViewById(R.id.pingButton);
        connectSocketButton = findViewById(R.id.connectSocketButton);
        listeningToggle = findViewById(R.id.listeningToggle);
        manualCommandInput = findViewById(R.id.manualCommandInput);
        sendManualCommandButton = findViewById(R.id.sendManualCommandButton);
        trainVoiceButton = findViewById(R.id.trainVoiceButton);
        btnViewLogs = findViewById(R.id.btnViewLogs);
        btnTestWakeWord = findViewById(R.id.btnTestWakeWord);

        statusText.setText("Status: Ready for Network Config");
    }

    private void setupListeners() {
        saveIpButton.setOnClickListener(v -> handleNewIp(ipInput.getText().toString()));

        scanQrButton.setOnClickListener(v -> {
            ScanOptions options = new ScanOptions();
            options.setDesiredBarcodeFormats(ScanOptions.QR_CODE);
            options.setPrompt("Scan Assistant Backend QR Code");
            options.setBeepEnabled(true);
            options.setOrientationLocked(false);
            qrCodeLauncher.launch(options);
        });

        pingButton.setOnClickListener(v -> {
            sendBroadcast(new Intent(ACTION_PING_BACKEND));
            statusText.setText("Pinging server...");
        });

        connectSocketButton.setOnClickListener(v -> {
            sendBroadcast(new Intent(ACTION_CONNECT_SOCKET));
            statusText.setText("Connecting Live Audio Stream...");
        });

        applyThresholdButton.setOnClickListener(v -> applyThreshold());


        manualWakeButton.setOnClickListener(v -> sendBroadcast(new Intent(ACTION_SIMULATE_WAKE_WORD)));

        sendManualCommandButton.setOnClickListener(v -> sendManualCommand());

        manualCommandInput.setOnEditorActionListener((v, actionId, event) -> {
            if (actionId == EditorInfo.IME_ACTION_SEND) {
                sendManualCommand();
                return true;
            }
            return false;
        });

        listeningToggle.setOnCheckedChangeListener((buttonView, isChecked) -> {
            if (isChecked && !hasAudioPermission()) {
                ActivityCompat.requestPermissions(this,
                        new String[] { Manifest.permission.RECORD_AUDIO },
                        REQUEST_RECORD_AUDIO_PERMISSION);
                // Revert until permission granted
                listeningToggle.setChecked(false);
            } else {
                startListeningAgent(isChecked);
            }
        });

        trainVoiceButton.setOnClickListener(v -> {
            Intent intent = new Intent(this, WakeWordEnrollmentActivity.class);
            startActivity(intent);
        });

        btnViewLogs.setOnClickListener(v -> startActivity(new Intent(this, LogViewerActivity.class)));
        btnTestWakeWord.setOnClickListener(v -> startActivity(new Intent(this, WakeWordTestingActivity.class)));
    }

    private void restoreSavedIp() {
        prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE);
        String savedIp = prefs.getString(PREF_BACKEND_IP, "");
        if (!savedIp.isEmpty()) {
            ipInput.setText(savedIp);
            broadcastIpUpdate(savedIp);
            // Auto-connect socket after IP is registered by the service
            mainHandler.postDelayed(() -> sendBroadcast(new Intent(ACTION_CONNECT_SOCKET)), 700);
        }
    }

    // -----------------------------------------------------------------------
    // Actions
    // -----------------------------------------------------------------------
    private void applyThreshold() {
        String raw = thresholdInput.getText().toString();
        try {
            float value = Float.parseFloat(raw);
            thresholdLabel.setText("Sensitivity Threshold: " + value);
            Intent intent = new Intent(ACTION_UPDATE_THRESHOLD);
            intent.putExtra("threshold", value);
            sendBroadcast(intent);
            Toast.makeText(this, "Threshold applied", Toast.LENGTH_SHORT).show();
        } catch (NumberFormatException e) {
            Toast.makeText(this, "Invalid threshold value", Toast.LENGTH_SHORT).show();
        }
    }


    private void sendManualCommand() {
        String command = manualCommandInput.getText().toString().trim();
        if (command.isEmpty())
            return;

        Intent intent = new Intent(ACTION_SEND_MANUAL_COMMAND);
        intent.putExtra("command", command);
        sendBroadcast(intent);

        manualCommandInput.setText("");
        statusText.setText("Sent: " + command);
        hideKeyboard();
    }

    private void startListeningAgent(boolean start) {
        // Service is already running from onCreate; just send the toggle broadcast
        Intent toggleIntent = new Intent(ACTION_TOGGLE_LISTENING);
        toggleIntent.putExtra("state", start);
        sendBroadcast(toggleIntent);

        statusText.setText(start
                ? "Status: Listening for Wake Word: " + currentWakeWord
                : "Status: Sleeping (Mic Off)");
    }

    /** Called after the user grants RECORD_AUDIO permission. */
    private void onPermissionsApproved() {
        listeningToggle.setChecked(true);
        startListeningAgent(true);
        Toast.makeText(this, "Microphone Access Granted", Toast.LENGTH_SHORT).show();
    }

    @Override
    public void onRequestPermissionsResult(int requestCode,
            @NonNull String[] permissions,
            @NonNull int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQUEST_RECORD_AUDIO_PERMISSION) {
            if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                onPermissionsApproved();
            } else {
                statusText.setText("Status: Permission Denied. Cannot proceed.");
            }
        }
    }

    /**
     * Normalises the IP string, saves it to prefs, notifies the service,
     * and auto-pings after a short delay.
     */
    private void handleNewIp(String ip) {
        // Strip common scheme prefixes — consistent with sanitizeIp() in the service
        String clean = ip.trim();
        if (clean.startsWith("https://"))
            clean = clean.substring(8);
        else if (clean.startsWith("http://"))
            clean = clean.substring(7);
        if (clean.endsWith("/"))
            clean = clean.substring(0, clean.length() - 1);

        ipInput.setText(clean);
        prefs.edit().putString(PREF_BACKEND_IP, clean).apply();
        broadcastIpUpdate(clean);
        statusText.setText("IP Saved: " + clean);

        // Auto-ping after short delay so the service has time to process the IP update,
        // then connect socket shortly after
        mainHandler.postDelayed(() -> {
            sendBroadcast(new Intent(ACTION_PING_BACKEND));
            statusText.setText("Auto-pinging server...");
        }, 500);
        mainHandler.postDelayed(() -> sendBroadcast(new Intent(ACTION_CONNECT_SOCKET)), 1200);
    }

    // -----------------------------------------------------------------------
    // Utility helpers
    // -----------------------------------------------------------------------
    private void broadcastIpUpdate(String ip) {
        Intent intent = new Intent(ACTION_UPDATE_IP);
        intent.putExtra("ip", ip);
        sendBroadcast(intent);
    }

    private boolean hasAudioPermission() {
        return ContextCompat.checkSelfPermission(this,
                Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED;
    }

    private String buildListeningStatus() {
        return hasAudioPermission()
                ? "Status: Listening for your Wake Word"
                : "Status: Ready (Waiting to Toggle)";
    }

    /** Returns the window background colour so we don't hardcode Color.WHITE. */
    private int getDefaultBackground() {
        android.util.TypedValue typedValue = new android.util.TypedValue();
        getTheme().resolveAttribute(android.R.attr.windowBackground, typedValue, true);
        // Fall back to white if the attribute isn't a colour resource
        if (typedValue.type >= android.util.TypedValue.TYPE_FIRST_COLOR_INT
                && typedValue.type <= android.util.TypedValue.TYPE_LAST_COLOR_INT) {
            return typedValue.data;
        }
        return Color.BLACK;
    }

    private void hideKeyboard() {
        InputMethodManager imm = (InputMethodManager) getSystemService(Context.INPUT_METHOD_SERVICE);
        if (imm != null) {
            imm.hideSoftInputFromWindow(manualCommandInput.getWindowToken(), 0);
        }
    }

    private IntentFilter buildIntentFilter() {
        IntentFilter filter = new IntentFilter();
        filter.addAction(ACTION_WAKE_WORD_DETECTED);
        filter.addAction(ACTION_COMMAND_TRANSCRIBED);
        filter.addAction(ACTION_PING_RESULT);
        filter.addAction(ACTION_ASSISTANT_RESPONSE);
        filter.addAction(ACTION_SOCKET_CONNECTED);
        filter.addAction(ACTION_SOCKET_DISCONNECTED);
        return filter;
    }
}