package com.example.myapplication;

import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.widget.Button;
import android.widget.ScrollView;
import android.widget.TextView;

import androidx.appcompat.app.AppCompatActivity;

import java.io.BufferedReader;
import java.io.InputStreamReader;

public class LogViewerActivity extends AppCompatActivity {

    private TextView tvLogs;
    private ScrollView logScrollView;
    private final Handler mainHandler = new Handler(Looper.getMainLooper());

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_log_viewer);

        tvLogs = findViewById(R.id.tvLogs);
        logScrollView = findViewById(R.id.logScrollView);
        Button btnRefresh = findViewById(R.id.btnRefreshLogs);
        Button btnClear = findViewById(R.id.btnClearLogs);

        btnRefresh.setOnClickListener(v -> refreshLogs());
        btnClear.setOnClickListener(v -> clearLogs());

        refreshLogs();
    }

    private void refreshLogs() {
        new Thread(() -> {
            try {
                // Get logs for the current process
                Process process = new ProcessBuilder("logcat", "-d", "-v", "time", "*:I").start();
                BufferedReader bufferedReader = new BufferedReader(
                        new InputStreamReader(process.getInputStream()));

                StringBuilder log = new StringBuilder();
                String line;
                while ((line = bufferedReader.readLine()) != null) {
                    // Filter for our app's logs to reduce noise
                    if (line.contains("VoiceAssistant") || line.contains("WakeWord") || line.contains("MainActivity")) {
                        log.append(line).append("\n");
                    }
                }

                String finalLog = log.toString();
                mainHandler.post(() -> {
                    tvLogs.setText(finalLog.isEmpty() ? "No relevant logs found." : finalLog);
                    // Scroll to bottom
                    logScrollView.post(() -> logScrollView.fullScroll(ScrollView.FOCUS_DOWN));
                });

            } catch (Exception e) {
                Log.e("LogViewer", "Error reading logs", e);
                mainHandler.post(() -> tvLogs.setText("Error reading logs: " + e.getMessage()));
            }
        }).start();
    }

    private void clearLogs() {
        new Thread(() -> {
            try {
                new ProcessBuilder("logcat", "-c").start();
                mainHandler.post(() -> {
                    tvLogs.setText("Logs cleared.");
                    refreshLogs();
                });
            } catch (Exception e) {
                Log.e("LogViewer", "Error clearing logs", e);
            }
        }).start();
    }
}
