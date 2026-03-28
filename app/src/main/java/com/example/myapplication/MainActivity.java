package com.example.myapplication;

import android.Manifest;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.view.View;
import android.widget.Button;
import android.widget.TextView;
import android.widget.Toast;
import android.content.Intent;
import android.os.Build;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.IntentFilter;
import android.graphics.Color;
import android.os.Handler;
import android.os.Looper;
import android.widget.EditText;
import android.widget.Switch;
import android.content.SharedPreferences;

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
    private Button initButton;
    private View mainLayout;
    private EditText thresholdInput;
    private Button applyThresholdButton;
    private Switch modelSwitch;
    private TextView thresholdLabel;
    private Button manualWakeButton;
    private EditText ipInput;
    private Button saveIpButton;
    private Button pingButton;
    private SharedPreferences prefs;
    private String currentWakeWord = "JARVIS";
    
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
        initButton = findViewById(R.id.initButton);
        thresholdInput = findViewById(R.id.thresholdInput);
        applyThresholdButton = findViewById(R.id.applyThresholdButton);
        modelSwitch = findViewById(R.id.modelSwitch);
        thresholdLabel = findViewById(R.id.thresholdLabel);
        manualWakeButton = findViewById(R.id.manualWakeButton);
        ipInput = findViewById(R.id.ipInput);
        saveIpButton = findViewById(R.id.saveIpButton);
        pingButton = findViewById(R.id.pingButton);

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
            prefs.edit().putString("backend_ip", ip).apply();
            Intent intent = new Intent("com.example.myapplication.UPDATE_IP");
            intent.putExtra("ip", ip);
            sendBroadcast(intent);
            statusText.setText("IP Saved");
        });

        pingButton.setOnClickListener(v -> {
            Intent intent = new Intent("com.example.myapplication.PING_BACKEND");
            sendBroadcast(intent);
            statusText.setText("Pinging server...");
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

        initButton.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                if (ContextCompat.checkSelfPermission(MainActivity.this, Manifest.permission.RECORD_AUDIO) 
                        != PackageManager.PERMISSION_GRANTED) {
                    ActivityCompat.requestPermissions(MainActivity.this, 
                            new String[]{Manifest.permission.RECORD_AUDIO}, 
                            REQUEST_RECORD_AUDIO_PERMISSION);
                } else {
                    onPermissionsApproved();
                }
            }
        });
    }

    private void onPermissionsApproved() {
        statusText.setText("Status: Ready (Mic Approved).\nListening for Wake Word: " + currentWakeWord);
        Toast.makeText(this, "Microphone Access Granted", Toast.LENGTH_SHORT).show();

        Intent intent = new Intent(this, VoiceAssistantService.class);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(intent);
        } else {
            startService(intent);
        }
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
        ContextCompat.registerReceiver(this, wakeWordReceiver, 
                filter, 
                ContextCompat.RECEIVER_NOT_EXPORTED);
    }

    @Override
    protected void onPause() {
        super.onPause();
        unregisterReceiver(wakeWordReceiver);
    }
}