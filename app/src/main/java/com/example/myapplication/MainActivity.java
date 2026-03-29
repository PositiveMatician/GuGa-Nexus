package com.example.myapplication;

import android.Manifest;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.view.View;
import android.widget.Button;
import android.widget.TextView;
import android.widget.Toast;
import android.widget.EditText;
import android.content.Intent;
import android.os.Build;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.IntentFilter;
import android.graphics.Color;
import android.os.Handler;
import android.os.Looper;
import android.widget.Switch;
import android.content.SharedPreferences;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputMethodManager;
import com.journeyapps.barcodescanner.ScanContract;
import com.journeyapps.barcodescanner.ScanOptions;
import androidx.activity.result.ActivityResultLauncher;

import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;
import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowInsetsCompat;

public class MainActivity extends AppCompatActivity {

    private static final int REQUEST_RECORD_AUDIO_PERMISSION = 200;
    private TextView statusText;
    private View mainLayout;
    private EditText thresholdInput;
    private Button applyThresholdButton;
    private Switch modelSwitch;
    private androidx.appcompat.widget.SwitchCompat listeningToggle;
    private TextView thresholdLabel;
    private Button manualWakeButton;
    private EditText ipInput;
    private Button saveIpButton;
    private Button scanQrButton;
    private Button pingButton;
    private Button connectSocketButton;
    private EditText manualCommandInput;
    private Button sendManualCommandButton;
    private SharedPreferences prefs;
    private String currentWakeWord = "JARVIS";

    private final ActivityResultLauncher<ScanOptions> qrCodeLauncher = registerForActivityResult(
            new ScanContract(),
            result -> {
                if (result.getContents() != null) {
                    String scannedIp = result.getContents();
                    handleNewIp(scannedIp);
                }
            }
    );
    
    private final BroadcastReceiver wakeWordReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            if ("com.example.myapplication.WAKE_WORD_DETECTED".equals(intent.getAction())) {
                statusText.setText("WAKE WORD DETECTED: " + currentWakeWord + "!");
                if (mainLayout == null) {
                    mainLayout = findViewById(R.id.main);
                }
                mainLayout.setBackgroundColor(Color.GREEN);
                
                new Handler(Looper.getMainLooper()).postDelayed(() -> {
                    mainLayout.setBackgroundColor(Color.WHITE);
                    statusText.setText(ContextCompat.checkSelfPermission(MainActivity.this, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED ? "Status: Listening for Wake Word: " + currentWakeWord : "Status: Listening...");
                }, 2000);
            } else if ("com.example.myapplication.COMMAND_TRANSCRIBED".equals(intent.getAction())) {
                String command = intent.getStringExtra("command");
                statusText.setText("You said: " + command);
            } else if ("com.example.myapplication.PING_RESULT".equals(intent.getAction())) {
                boolean success = intent.getBooleanExtra("success", false);
                if (success) {
                    statusText.setText("Ping Successful! Backend is connected.");
                } else {
                    statusText.setText("Ping Failed. Check IP and Wi-Fi.");
                }
            } else if ("com.example.myapplication.JARVIS_RESPONSE".equals(intent.getAction())) {
                String message = intent.getStringExtra("message");
                statusText.setText("Jarvis: " + message);
            } else if ("com.example.myapplication.SOCKET_CONNECTED".equals(intent.getAction())) {
                statusText.setText("Status: Live Audio Stream Connected");
                statusText.setTextColor(Color.BLUE);
            } else if ("com.example.myapplication.SOCKET_DISCONNECTED".equals(intent.getAction())) {
                statusText.setText("Status: Audio Stream Disconnected");
                statusText.setTextColor(Color.RED);
            }
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);
        
        ViewCompat.setOnApplyWindowInsetsListener(findViewById(R.id.main), (v, insets) -> {
            Insets systemBars = insets.getInsets(WindowInsetsCompat.Type.systemBars());
            v.setPadding(systemBars.left, systemBars.top, systemBars.right, systemBars.bottom);
            return insets;
        });

        statusText = findViewById(R.id.statusText);
        statusText.setText("Status: Ready for Network Config");
        thresholdInput = findViewById(R.id.thresholdInput);
        applyThresholdButton = findViewById(R.id.applyThresholdButton);
        modelSwitch = findViewById(R.id.modelSwitch);
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

        prefs = getSharedPreferences("AssistantPrefs", MODE_PRIVATE);
        String savedIp = prefs.getString("backend_ip", "");
        if (!savedIp.isEmpty()) {
            ipInput.setText(savedIp);
            Intent intent = new Intent("com.example.myapplication.UPDATE_IP");
            intent.putExtra("ip", savedIp);
            sendBroadcast(intent);
        }

        saveIpButton.setOnClickListener(v -> {
            String ip = ipInput.getText().toString();
            handleNewIp(ip);
        });

        scanQrButton.setOnClickListener(v -> {
            ScanOptions options = new ScanOptions();
            options.setDesiredBarcodeFormats(ScanOptions.QR_CODE);
            options.setPrompt("Scan Jarvis Backend QR Code");
            options.setBeepEnabled(true);
            options.setOrientationLocked(false);
            qrCodeLauncher.launch(options);
        });

        pingButton.setOnClickListener(v -> {
            Intent intent = new Intent("com.example.myapplication.PING_BACKEND");
            sendBroadcast(intent);
            statusText.setText("Pinging server...");
        });

        connectSocketButton.setOnClickListener(v -> {
            Intent intent = new Intent("com.example.myapplication.CONNECT_SOCKET");
            sendBroadcast(intent);
            statusText.setText("Connecting Live Audio Stream...");
        });

        applyThresholdButton.setOnClickListener(v -> {
            try {
                float thresholdValue = Float.parseFloat(thresholdInput.getText().toString());
                thresholdLabel.setText("Sensitivity Threshold: " + thresholdValue);
                Intent intent = new Intent("com.example.myapplication.UPDATE_THRESHOLD");
                intent.putExtra("threshold", thresholdValue);
                sendBroadcast(intent);
                Toast.makeText(MainActivity.this, "Threshold applied", Toast.LENGTH_SHORT).show();
            } catch (NumberFormatException e) {
                Toast.makeText(MainActivity.this, "Invalid threshold value", Toast.LENGTH_SHORT).show();
            }
        });

        modelSwitch.setOnCheckedChangeListener((buttonView, isChecked) -> {
            String modelFileName = isChecked ? "alexa_v0.1.tflite" : "hey_jarvis_v0.1.tflite";
            currentWakeWord = isChecked ? "ALEXA" : "JARVIS";
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
                statusText.setText("Status: Ready (Mic Approved).\nListening for Wake Word: " + currentWakeWord);
            } else {
                statusText.setText("Status: Model changed to " + currentWakeWord + ". Waiting for Permissions.");
            }
            
            Intent intent = new Intent("com.example.myapplication.SWITCH_MODEL");
            intent.putExtra("model_file", modelFileName);
            sendBroadcast(intent);
        });

        manualWakeButton.setOnClickListener(v -> {
            Intent intent = new Intent("com.example.myapplication.SIMULATE_WAKE_WORD");
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

        listeningToggle.setOnCheckedChangeListener((buttonView, isChecked) -> {
            if (isChecked) {
                if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) 
                        != PackageManager.PERMISSION_GRANTED) {
                    ActivityCompat.requestPermissions(this, 
                            new String[]{Manifest.permission.RECORD_AUDIO}, 
                            REQUEST_RECORD_AUDIO_PERMISSION);
                    // Revert toggle until permission is granted
                    listeningToggle.setChecked(false);
                } else {
                    startListeningAgent(true);
                }
            } else {
                startListeningAgent(false);
            }
        });
    }

    private void startListeningAgent(boolean start) {
        // Ensure service is running
        Intent serviceIntent = new Intent(this, VoiceAssistantService.class);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(serviceIntent);
        } else {
            startService(serviceIntent);
        }

        // Send toggle broadcast
        Intent intent = new Intent("com.example.myapplication.TOGGLE_LISTENING");
        intent.putExtra("state", start);
        sendBroadcast(intent);

        if (start) {
            statusText.setText("Status: Listening for Wake Word: " + currentWakeWord);
        } else {
            statusText.setText("Status: Sleeping (Mic Off)");
        }
    }

    private void sendManualCommand() {
        String command = manualCommandInput.getText().toString().trim();
        if (!command.isEmpty()) {
            Intent intent = new Intent("com.example.myapplication.SEND_MANUAL_COMMAND");
            intent.putExtra("command", command);
            sendBroadcast(intent);
            
            manualCommandInput.setText("");
            statusText.setText("Sent: " + command);
            
            // Close keyboard
            InputMethodManager imm = (InputMethodManager) getSystemService(Context.INPUT_METHOD_SERVICE);
            if (imm != null) {
                imm.hideSoftInputFromWindow(manualCommandInput.getWindowToken(), 0);
            }
        }
    }

    private void onPermissionsApproved() {
        listeningToggle.setChecked(true);
        startListeningAgent(true);
        Toast.makeText(this, "Microphone Access Granted", Toast.LENGTH_SHORT).show();
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, @NonNull String[] permissions, @NonNull int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQUEST_RECORD_AUDIO_PERMISSION) {
            if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                onPermissionsApproved();
            } else {
                statusText.setText("Status: Permission Denied. Cannot proceed.");
            }
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        IntentFilter filter = new IntentFilter();
        filter.addAction("com.example.myapplication.WAKE_WORD_DETECTED");
        filter.addAction("com.example.myapplication.COMMAND_TRANSCRIBED");
        filter.addAction("com.example.myapplication.PING_RESULT");
        filter.addAction("com.example.myapplication.JARVIS_RESPONSE");
        filter.addAction("com.example.myapplication.SOCKET_CONNECTED");
        filter.addAction("com.example.myapplication.SOCKET_DISCONNECTED");
        ContextCompat.registerReceiver(this, wakeWordReceiver, 
                filter, 
                ContextCompat.RECEIVER_NOT_EXPORTED);
    }

    @Override
    protected void onPause() {
        super.onPause();
        unregisterReceiver(wakeWordReceiver);
    }

    private void handleNewIp(String ip) {
        ipInput.setText(ip);
        prefs.edit().putString("backend_ip", ip).apply();
        
        Intent intent = new Intent("com.example.myapplication.UPDATE_IP");
        intent.putExtra("ip", ip);
        sendBroadcast(intent);
        
        statusText.setText("IP Saved: " + ip);
        
        // Auto-ping after 0.5s
        new Handler(Looper.getMainLooper()).postDelayed(() -> {
            Intent pingIntent = new Intent("com.example.myapplication.PING_BACKEND");
            sendBroadcast(pingIntent);
            statusText.setText("Auto-pinging server...");
        }, 500);
    }
}