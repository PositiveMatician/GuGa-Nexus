package com.example.myapplication;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.graphics.Color;
import android.os.Bundle;
import android.text.Editable;
import android.text.TextWatcher;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.TextView;
import android.widget.Toast;

import androidx.appcompat.app.AppCompatActivity;
import androidx.appcompat.widget.SwitchCompat;

public class WakeWordTestingActivity extends AppCompatActivity {

    private TextView tvCurrentScore, tvConfidenceLog, tvStatus;
    private EditText etThreshold;
    private SwitchCompat toggleDetection;
    private Button btnSimulate;

    private static final String ACTION_SCORE = "com.example.myapplication.WAKE_WORD_SCORE";
    private static final String ACTION_DETECTED = "com.example.myapplication.WAKE_WORD_DETECTED";
    private static final String ACTION_TOGGLE = "com.example.myapplication.TOGGLE_LISTENING";
    private static final String ACTION_UPDATE_THRESHOLD = "com.example.myapplication.UPDATE_THRESHOLD";
    private static final String ACTION_SIMULATE = "com.example.myapplication.SIMULATE_WAKE_WORD";
    private static final String ACTION_SET_TESTING_MODE = "com.example.myapplication.SET_TESTING_MODE";

    private final StringBuilder scoreLog = new StringBuilder();

    private final BroadcastReceiver receiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            String action = intent.getAction();
            if (ACTION_SCORE.equals(action)) {
                float score = intent.getFloatExtra("score", 0f);
                updateScore(score);
            } else if (ACTION_DETECTED.equals(action)) {
                onWakeWordDetected();
            }
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_wake_word_testing);

        tvCurrentScore = findViewById(R.id.tv_current_score);
        tvConfidenceLog = findViewById(R.id.tv_confidence_log);
        tvStatus = findViewById(R.id.tv_status);
        etThreshold = findViewById(R.id.et_threshold);
        toggleDetection = findViewById(R.id.toggle_detection);
        btnSimulate = findViewById(R.id.btn_simulate_wake);

        loadInitialThreshold();

        toggleDetection.setOnCheckedChangeListener((btn, isChecked) -> {
            Intent intent = new Intent(ACTION_TOGGLE);
            intent.putExtra("state", isChecked);
            sendBroadcast(intent);
            tvStatus.setText(isChecked ? "Status: Listening..." : "Status: Idle");
        });

        btnSimulate.setOnClickListener(v -> sendBroadcast(new Intent(ACTION_SIMULATE)));

        etThreshold.addTextChangedListener(new TextWatcher() {
            @Override public void beforeTextChanged(CharSequence s, int start, int count, int after) {}
            @Override public void onTextChanged(CharSequence s, int start, int before, int count) {}
            @Override public void afterTextChanged(Editable s) {
                applyThreshold(s.toString());
            }
        });

        IntentFilter filter = new IntentFilter();
        filter.addAction(ACTION_SCORE);
        filter.addAction(ACTION_DETECTED);
        registerReceiver(receiver, filter, Context.RECEIVER_EXPORTED);
    }

    @Override
    protected void onResume() {
        super.onResume();
        Intent intent = new Intent(ACTION_SET_TESTING_MODE);
        intent.putExtra("enabled", true);
        sendBroadcast(intent);
    }

    @Override
    protected void onPause() {
        super.onPause();
        Intent intent = new Intent(ACTION_SET_TESTING_MODE);
        intent.putExtra("enabled", false);
        sendBroadcast(intent);
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        unregisterReceiver(receiver);
    }

    private void loadInitialThreshold() {
        float threshold = getSharedPreferences("wakeword", MODE_PRIVATE)
                .getFloat("wake_word_threshold", 0.85f);
        etThreshold.setText(String.valueOf(threshold));
    }

    private void applyThreshold(String raw) {
        try {
            float val = Float.parseFloat(raw);
            Intent intent = new Intent(ACTION_UPDATE_THRESHOLD);
            intent.putExtra("threshold", val);
            sendBroadcast(intent);
        } catch (NumberFormatException ignored) {}
    }

    private void updateScore(float score) {
        tvCurrentScore.setText(String.format("%.4f", score));
        
        // Add to log
        scoreLog.insert(0, String.format("%.4f", score) + "\n");
        if (scoreLog.length() > 500) scoreLog.setLength(500);
        tvConfidenceLog.setText(scoreLog.toString().trim());

        // Visual feedback based on score
        if (score > 0.5) tvCurrentScore.setTextColor(Color.parseColor("#FFC107")); // Amber
        else tvCurrentScore.setTextColor(Color.WHITE);
    }

    private void onWakeWordDetected() {
        tvCurrentScore.setTextColor(Color.GREEN);
        tvStatus.setText("WAKE WORD DETECTED!");
        tvStatus.postDelayed(() -> {
            if (toggleDetection.isChecked()) tvStatus.setText("Status: Listening...");
            else tvStatus.setText("Status: Idle");
        }, 2000);
    }
}
