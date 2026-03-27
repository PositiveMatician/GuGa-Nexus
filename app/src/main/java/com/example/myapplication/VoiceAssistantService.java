package com.example.myapplication;

import android.annotation.SuppressLint;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import android.os.Build;
import android.os.IBinder;
import android.util.Log;

import androidx.annotation.Nullable;
import androidx.core.app.NotificationCompat;

public class VoiceAssistantService extends Service implements WakeWordDetector.WakeWordListener {

    private static final String CHANNEL_ID = "VoiceAssistantChannel";
    private static final int NOTIFICATION_ID = 1;
    
    private WakeWordDetector wakeWordDetector;
    private AudioRecord audioRecord;
    private Thread audioThread;
    private boolean isListening = false;
    
    private static final int SAMPLE_RATE = 16000;
    private static final int CHUNK_SIZE = 1280; // 80ms

    @Nullable
    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public void onCreate() {
        super.onCreate();
        createNotificationChannel();
        wakeWordDetector = new WakeWordDetector(this, this);
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            CharSequence name = "Voice Assistant Service";
            int importance = NotificationManager.IMPORTANCE_LOW;
            NotificationChannel channel = new NotificationChannel(CHANNEL_ID, name, importance);
            NotificationManager manager = getSystemService(NotificationManager.class);
            if (manager != null) {
                manager.createNotificationChannel(channel);
            }
        }
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        Notification notification = new NotificationCompat.Builder(this, CHANNEL_ID)
                .setContentTitle("Assistant Active")
                .setContentText("Listening for commands...")
                .setSmallIcon(android.R.drawable.ic_btn_speak_now)
                .build();

        startForeground(NOTIFICATION_ID, notification);
        startListening();

        return START_STICKY;
    }

    @SuppressLint("MissingPermission")
    private void startListening() {
        if (isListening) return;

        int bufferSize = AudioRecord.getMinBufferSize(SAMPLE_RATE, 
                AudioFormat.CHANNEL_IN_MONO, 
                AudioFormat.ENCODING_PCM_16BIT);

        if (bufferSize == AudioRecord.ERROR || bufferSize == AudioRecord.ERROR_BAD_VALUE) {
            bufferSize = SAMPLE_RATE * 2;
        }

        audioRecord = new AudioRecord(MediaRecorder.AudioSource.MIC,
                SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
                Math.max(bufferSize, CHUNK_SIZE * 2));

        if (audioRecord.getState() != AudioRecord.STATE_INITIALIZED) {
            Log.e("Assistant", "AudioRecord initialization failed");
            return;
        }

        audioRecord.startRecording();
        isListening = true;

        audioThread = new Thread(() -> {
            // Pre-allocate array outside the loop as requested
            short[] audioBuffer = new short[CHUNK_SIZE];
            
            while (isListening) {
                int bytesRead = audioRecord.read(audioBuffer, 0, audioBuffer.length);
                if (bytesRead == audioBuffer.length) {
                    if (wakeWordDetector != null) {
                        wakeWordDetector.processAudioChunk(audioBuffer);
                    }
                }
            }
        });
        audioThread.start();
    }

    @Override
    public void onWakeWordDetected() {
        Log.d("Assistant", "WAKE WORD DETECTED: JARVIS!");
        Intent intent = new Intent("com.example.myapplication.WAKE_WORD_DETECTED");
        sendBroadcast(intent);
    }

    @Override
    public void onDestroy() {
        isListening = false;
        
        if (audioThread != null) {
            try {
                audioThread.join(500);
            } catch (InterruptedException e) {
                e.printStackTrace();
            }
        }
        
        if (audioRecord != null) {
            try {
                audioRecord.stop();
            } catch (IllegalStateException e) {
                e.printStackTrace();
            }
            audioRecord.release();
        }
        
        if (wakeWordDetector != null) {
            wakeWordDetector.close();
        }
        
        super.onDestroy();
    }
}
