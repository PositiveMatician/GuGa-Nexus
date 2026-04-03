package com.example.myapplication;

import android.annotation.SuppressLint;
import android.app.*;
import android.content.*;
import android.media.*;
import android.os.*;
import android.speech.*;
import android.speech.tts.TextToSpeech;
import android.speech.tts.UtteranceProgressListener;
import android.util.Log;

import androidx.annotation.Nullable;
import androidx.core.app.NotificationCompat;
import androidx.core.content.ContextCompat;

import org.json.*;
import android.util.Base64;
import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;

import java.io.IOException;
import java.net.URISyntaxException;
import java.util.*;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

import io.socket.client.IO;
import io.socket.client.Socket;
import okhttp3.*;

public class VoiceAssistantService extends Service implements WakeWordDetector.WakeWordListener {

    private static final String TAG = "VoiceAssistant";
    private static final String CHANNEL_ID = "VoiceAssistantChannel";
    private static final String RESPONSE_CHANNEL_ID = "AssistantResponseChannel";
    private static final int NOTIFICATION_ID = 1;

    private static final int SAMPLE_RATE = 16000;
    private static final int CHUNK_SIZE = 1280;

    // ✅ Static OkHttpClient
    private static final OkHttpClient HTTP_CLIENT = new OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(10, TimeUnit.SECONDS)
            .build();

    private WakeWordDetector wakeWordDetector;
    private AudioRecord audioRecord;
    private Thread audioThread;
    private final AtomicBoolean isListening = new AtomicBoolean(false);

    private SpeechRecognizer speechRecognizer;
    private Intent recognizerIntent;

    private Socket mSocket;
    private String backendAddress = "";

    private TextToSpeech tts;
    private AudioManager audioManager;
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private boolean receiverRegistered = false;
    /** True only when the listening toggle is ON. Gates TTS, STT, and wake word. */
    private boolean voiceEnabled = true;
    private boolean testingMode = false;

    private String deviceId = "";
    private String token = "";

    private static final String UTTERANCE_ID_WAKE = "wake_utterance";

    // -------------------- Enrollment --------------------
    private final WakeWordEnrollment enrollment = new WakeWordEnrollment();
    /** True while the UI is collecting enrollment samples. */
    private boolean enrolling = false;
    private static final int ENROLLMENT_SAMPLES_REQUIRED = 5;

    // -------------------- Broadcast Receiver --------------------

    private final BroadcastReceiver actionReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            if (intent == null || intent.getAction() == null)
                return;

            switch (intent.getAction()) {

                case "com.example.myapplication.TOGGLE_LISTENING":
                    boolean state = intent.getBooleanExtra("state", false);
                    voiceEnabled = state;
                    if (state) {
                        startForeground(NOTIFICATION_ID, createNotification("Listening..."));
                        startWakeWordListening();
                    } else {
                        stopWakeWordListening();
                        // Instead of stopping foreground completely, keep it alive for networking
                        // but with a different message.
                        startForeground(NOTIFICATION_ID, createNotification("Active (Silent Mode)"));

                        if (tts != null) tts.stop();
                        // Cancel any pending STT
                        if (speechRecognizer != null) {
                            mainHandler.post(() -> speechRecognizer.cancel());
                        }
                    }
                    break;

                case "com.example.myapplication.UPDATE_IP":
                    backendAddress = intent.getStringExtra("ip");
                    if (backendAddress == null)
                        backendAddress = "";
                    break;

                case "com.example.myapplication.CONNECT_SOCKET":
                    connectWebSocket();
                    break;

                case "com.example.myapplication.SEND_MANUAL_COMMAND":
                    String command = intent.getStringExtra("command");
                    if (command != null)
                        sendCommandToBackend(command);
                    break;

                case "com.example.myapplication.SIMULATE_WAKE_WORD":
                    mainHandler.post(VoiceAssistantService.this::onWakeWordDetected);
                    break;

                case "com.example.myapplication.PING_BACKEND":
                    pingBackend();
                    break;

                case "com.example.myapplication.UPDATE_THRESHOLD": {
                    float threshold = intent.getFloatExtra("threshold", 0.05f);
                    if (wakeWordDetector != null) {
                        wakeWordDetector.setThreshold(threshold);
                        wakeWordDetector.setEnrollmentThreshold(threshold);
                    }
                    // Save it too so it persists
                    getSharedPreferences("wakeword", Context.MODE_PRIVATE).edit()
                        .putFloat("wake_word_threshold", threshold).apply();
                    break;
                }

                case "com.example.myapplication.SWITCH_MODEL":
                    break;

                case "com.example.myapplication.SET_TESTING_MODE":
                    testingMode = intent.getBooleanExtra("enabled", false);
                    Log.d(TAG, "Testing mode set to: " + testingMode);
                    break;

                // ---- Enrollment ----
                case "com.example.myapplication.ENROLLMENT_START":
                    enrollment.clearSamples();
                    enrolling = true;
                    Log.i(TAG, "Enrollment STARTED - collecting samples...");
                    break;

                case "com.example.myapplication.ENROLLMENT_SAVE": {
                    if (enrollment.getSampleCount() >= ENROLLMENT_SAMPLES_REQUIRED) {
                        float[] template    = enrollment.buildTemplate();
                        float   threshold   = enrollment.calibrateThreshold(template);
                        enrollment.saveTemplate(VoiceAssistantService.this, template);
                        enrollment.saveThreshold(VoiceAssistantService.this, threshold);
                        if (wakeWordDetector != null)
                            wakeWordDetector.setEnrollmentMatcher(template, threshold);
                        enrolling = false;
                        Intent done = new Intent("com.example.myapplication.ENROLLMENT_DONE");
                        done.putExtra("threshold", threshold);
                        done.putExtra("samples",   enrollment.getSampleCount());
                        sendBroadcast(done);
                        Log.i(TAG, "Enrollment SAVED successfully. New threshold: " + threshold);
                    } else {
                        Intent need = new Intent("com.example.myapplication.ENROLLMENT_NEED_MORE");
                        need.putExtra("have",  enrollment.getSampleCount());
                        need.putExtra("need",  ENROLLMENT_SAMPLES_REQUIRED);
                        sendBroadcast(need);
                    }
                    break;
                }

                case "com.example.myapplication.ENROLLMENT_CLEAR":
                    enrollment.clearEnrollment(VoiceAssistantService.this);
                    if (wakeWordDetector != null) wakeWordDetector.clearEnrollmentMatcher();
                    enrolling = false;
                    Log.d(TAG, "Enrollment cleared");
                    break;

                case "com.example.myapplication.ENROLLMENT_DONE":
                    Log.i(TAG, "Reloading enrollment data...");
                    if (enrollment.isEnrolled(VoiceAssistantService.this)) {
                        float[] tmpl = enrollment.loadTemplate(VoiceAssistantService.this);
                        float threshold = enrollment.loadThreshold(VoiceAssistantService.this);
                        if (wakeWordDetector != null) {
                            wakeWordDetector.setEnrollmentMatcher(tmpl, threshold);
                            Log.i(TAG, "New enrollment applied. Threshold: " + threshold);
                        }
                    }
                    enrolling = false;
                    break;
            }
        }
    };

    // -------------------- Lifecycle --------------------

    @Override
    public void onCreate() {
        super.onCreate();
        createNotificationChannel();
        audioManager = (AudioManager) getSystemService(Context.AUDIO_SERVICE);
        wakeWordDetector = new WakeWordDetector(this, this);

        // Load any previously saved enrollment and activate it
        if (enrollment.isEnrolled(this)) {
            float[] tmpl      = enrollment.loadTemplate(this);
            float   threshold = enrollment.loadThreshold(this);
            wakeWordDetector.setEnrollmentMatcher(tmpl, threshold);
            Log.d(TAG, "Loaded saved voice enrollment. Threshold: " + threshold);
        }

        initSTT();
        initTTS();
        loadAuth();
    }

    private void loadAuth() {
        SharedPreferences prefs = getSharedPreferences("AssistantPrefs", MODE_PRIVATE);
        deviceId = prefs.getString("device_id", "");
        if (deviceId.isEmpty()) {
            deviceId = UUID.randomUUID().toString().replace("-", "").substring(0, 16);
            prefs.edit().putString("device_id", deviceId).apply();
            Log.d(TAG, "Generated new device ID: " + deviceId);
        }
        token = prefs.getString("token", "");
        Log.d(TAG, "Loaded deviceId: " + deviceId + " (token status: " + (!token.isEmpty() ? "SET" : "MISSING") + ")");
    }

    private void initSTT() {
        mainHandler.post(this::initSpeechRecognizer);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {

        // ALWAYS call startForeground to satisfy Context.startForegroundService requirement
        // Use a generic "Active" message if voice is disabled, otherwise "Listening..."
        startForeground(NOTIFICATION_ID, createNotification(voiceEnabled ? "Listening..." : "Active (Silent Mode)"));

        if (!receiverRegistered) {
            IntentFilter filter = new IntentFilter();
            filter.addAction("com.example.myapplication.TOGGLE_LISTENING");
            filter.addAction("com.example.myapplication.UPDATE_IP");
            filter.addAction("com.example.myapplication.CONNECT_SOCKET");
            filter.addAction("com.example.myapplication.SEND_MANUAL_COMMAND");
            filter.addAction("com.example.myapplication.SIMULATE_WAKE_WORD");
            filter.addAction("com.example.myapplication.PING_BACKEND");
            filter.addAction("com.example.myapplication.UPDATE_THRESHOLD");
            filter.addAction("com.example.myapplication.SWITCH_MODEL");
            filter.addAction("com.example.myapplication.ENROLLMENT_START");
            filter.addAction("com.example.myapplication.ENROLLMENT_SAVE");
            filter.addAction("com.example.myapplication.ENROLLMENT_CLEAR");
            ContextCompat.registerReceiver(this, actionReceiver, filter, ContextCompat.RECEIVER_NOT_EXPORTED);
            receiverRegistered = true;
        }

        // Auto-connect socket if IP was already provided
        if (!backendAddress.isEmpty()) {
            connectWebSocket();
        }

        return START_STICKY;
    }

    @Override
    public void onDestroy() {

        isListening.set(false);

        if (audioRecord != null) {
            try {
                audioRecord.stop();
            } catch (Exception ignored) {
            }
        }

        if (audioThread != null) {
            try {
                audioThread.join(1000);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        }

        if (audioRecord != null) {
            audioRecord.release();
            audioRecord = null;
        }

        if (speechRecognizer != null) {
            mainHandler.post(() -> speechRecognizer.destroy());
        }

        if (mSocket != null) {
            mSocket.disconnect();
            mSocket.off();
        }

        if (tts != null) {
            tts.shutdown();
        }

        unregisterReceiver(actionReceiver);
        super.onDestroy();
    }

    @Nullable
    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    // -------------------- Speech Recognizer --------------------

    private void initSpeechRecognizer() {
        mainHandler.post(() -> {

            if (speechRecognizer != null) {
                speechRecognizer.destroy();
            }

            speechRecognizer = SpeechRecognizer.createSpeechRecognizer(this);

            recognizerIntent = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
            recognizerIntent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL,
                    RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);

            speechRecognizer.setRecognitionListener(new RecognitionListener() {

                @Override
                public void onReadyForSpeech(Bundle params) {
                }

                @Override
                public void onBeginningOfSpeech() {
                }

                @Override
                public void onRmsChanged(float rmsdB) {
                }

                @Override
                public void onBufferReceived(byte[] buffer) {
                }

                @Override
                public void onEndOfSpeech() {
                }

                @Override
                public void onError(int error) {
                    Log.e(TAG, "Speech error: " + error);
                    if (voiceEnabled) resumeWakeWordWithDelay();
                }

                @Override
                public void onResults(Bundle results) {
                    ArrayList<String> matches = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);

                    if (matches != null && !matches.isEmpty()) {
                        String text = matches.get(0);
                        // Always broadcast transcribed text so UI shows it
                        Intent txIntent = new Intent("com.example.myapplication.COMMAND_TRANSCRIBED");
                        txIntent.putExtra("command", text);
                        sendBroadcast(txIntent);
                        sendCommandToBackend(text);
                    }

                    if (voiceEnabled) resumeWakeWordWithDelay();
                }

                @Override
                public void onPartialResults(Bundle partialResults) {
                }

                @Override
                public void onEvent(int eventType, Bundle params) {
                }
            });
        });
    }

    // -------------------- Wake Word --------------------

    @SuppressLint("MissingPermission")
    private void startWakeWordListening() {
        if (isListening.get())
            return;

        int bufferSize = AudioRecord.getMinBufferSize(
                SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT);

        audioRecord = new AudioRecord(
                MediaRecorder.AudioSource.MIC,
                SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
                Math.max(bufferSize, CHUNK_SIZE * 2));

        audioRecord.startRecording();
        isListening.set(true);

        audioThread = new Thread(() -> {
            short[] buffer = new short[CHUNK_SIZE];

            while (isListening.get() && !Thread.currentThread().isInterrupted()) {
                int read = audioRecord.read(buffer, 0, buffer.length);
                if (read > 0 && wakeWordDetector != null) {
                    wakeWordDetector.processAudioChunk(buffer);
                }
            }
        });

        audioThread.start();
    }

    private void stopWakeWordListening() {
        if (!isListening.getAndSet(false))
            return;

        if (audioRecord != null) {
            try {
                audioRecord.stop();
                audioRecord.release();
            } catch (Exception ignored) {
            }
            audioRecord = null;
        }
    }

    @Override
    public void onWakeWordDetected() {
        // Notify UI first (used by testing screen and background)
        sendBroadcast(new Intent("com.example.myapplication.WAKE_WORD_DETECTED"));

        if (testingMode) {
            Log.i(TAG, "Wake word detected in TESTING MODE. Skipping STT flow.");
            return;
        }

        stopWakeWordListening();

        // Speak "Yes sir" and wait for onDone callback to start STT
        if (tts != null && voiceEnabled) {
            Bundle params = new Bundle();
            params.putString(TextToSpeech.Engine.KEY_PARAM_UTTERANCE_ID, UTTERANCE_ID_WAKE);
            tts.speak("Yes sir", TextToSpeech.QUEUE_FLUSH, params, UTTERANCE_ID_WAKE);
        } else {
            // Fallback if voice is disabled or TTS fails
            startSTTFlow();
        }
    }

    @Override
    public void onConfidenceScore(float score) {
        Intent intent = new Intent("com.example.myapplication.WAKE_WORD_SCORE");
        intent.putExtra("score", score);
        sendBroadcast(intent);
    }

    private long lastEnrollmentCaptureTime = 0;


    /**
     * Mutes audio streams, starts SpeechRecognizer, and unmutes after 500ms.
     * This suppresses the unwanted system "beep" sound.
     */
    private void startSTTFlow() {
        mainHandler.post(() -> {
            if (speechRecognizer == null) return;

            // 3. Mute system audio streams to suppress the "beep"
            if (audioManager != null) {
                audioManager.adjustStreamVolume(AudioManager.STREAM_MUSIC, AudioManager.ADJUST_MUTE, 0);
                audioManager.adjustStreamVolume(AudioManager.STREAM_NOTIFICATION, AudioManager.ADJUST_MUTE, 0);
            }

            // 4. Start SpeechRecognizer immediately after muting
            speechRecognizer.cancel();
            speechRecognizer.startListening(recognizerIntent);

            // 5. Unmute after 500ms (enough time for the beep to pass)
            mainHandler.postDelayed(() -> {
                if (audioManager != null) {
                    audioManager.adjustStreamVolume(AudioManager.STREAM_MUSIC, AudioManager.ADJUST_UNMUTE, 0);
                    audioManager.adjustStreamVolume(AudioManager.STREAM_NOTIFICATION, AudioManager.ADJUST_UNMUTE, 0);
                }
            }, 500);
        });
    }

    private void resumeWakeWordWithDelay() {
        mainHandler.postDelayed(this::startWakeWordListening, 800);
    }

    // -------------------- Ping --------------------

    private void pingBackend() {
        if (backendAddress == null || backendAddress.isEmpty()) {
            Intent result = new Intent("com.example.myapplication.PING_RESULT");
            result.putExtra("success", false);
            sendBroadcast(result);
            return;
        }

        String url = "http://" + backendAddress + "/ping";
        Request request = new Request.Builder().url(url).build();
        HTTP_CLIENT.newCall(request).enqueue(new Callback() {
            @Override
            public void onFailure(Call call, IOException e) {
                Log.e(TAG, "Ping failed", e);
                Intent result = new Intent("com.example.myapplication.PING_RESULT");
                result.putExtra("success", false);
                sendBroadcast(result);
            }

            @Override
            public void onResponse(Call call, Response response) throws IOException {
                boolean success = response.isSuccessful();
                response.close();
                Intent result = new Intent("com.example.myapplication.PING_RESULT");
                result.putExtra("success", success);
                sendBroadcast(result);
            }
        });
    }    private void sendCommandToBackend(String command) {
        if (token == null || token.isEmpty()) {
            Log.w(TAG, "Cannot send command: No auth token. Please pair device.");
            return;
        }

        try {
            JSONObject inner = new JSONObject();
            inner.put("phrase", command);
            String plaintext = inner.toString();
            JSONObject encryptedPayload = encryptRequest(plaintext);

            if (encryptedPayload == null) return;
            encryptedPayload.put("device_id", deviceId);

            if (mSocket != null && mSocket.connected()) {
                Log.d(TAG, "[WS] Sending encrypted command");
                mSocket.emit("command", encryptedPayload);
                return;
            }

            if (backendAddress.isEmpty()) return;

            String url = "http://" + backendAddress + "/api/command";
            RequestBody body = RequestBody.create(
                    encryptedPayload.toString(),
                    MediaType.parse("application/json"));

            Request request = new Request.Builder().url(url).post(body).build();
            HTTP_CLIENT.newCall(request).enqueue(new Callback() {
                @Override
                public void onFailure(Call call, IOException e) {
                    Log.e(TAG, "HTTP command failed", e);
                }
                @Override
                public void onResponse(Call call, Response response) {
                    response.close();
                }
            });

        } catch (JSONException e) {
            Log.e(TAG, "JSON error in sendCommand", e);
        }
    }

    private JSONObject encryptRequest(String plaintext) {
        try {
            byte[] keyBytes = hexStringToByteArray(token);
            byte[] iv = new byte[12];
            new SecureRandom().nextBytes(iv);

            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            GCMParameterSpec spec = new GCMParameterSpec(128, iv);
            SecretKeySpec keySpec = new SecretKeySpec(keyBytes, "AES");
            cipher.init(Cipher.ENCRYPT_MODE, keySpec, spec);

            byte[] ciphertext = cipher.doFinal(plaintext.getBytes(StandardCharsets.UTF_8));

            JSONObject res = new JSONObject();
            res.put("iv", Base64.encodeToString(iv, Base64.NO_WRAP));
            res.put("ciphertext", Base64.encodeToString(ciphertext, Base64.NO_WRAP));
            return res;
        } catch (Exception e) {
            Log.e(TAG, "Encryption failed", e);
            return null;
        }
    }

    private String decryptResponse(JSONObject payload) {
        try {
            byte[] keyBytes = hexStringToByteArray(token);
            byte[] iv = Base64.decode(payload.getString("iv"), Base64.DEFAULT);
            byte[] ciphertext = Base64.decode(payload.getString("ciphertext"), Base64.DEFAULT);

            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            GCMParameterSpec spec = new GCMParameterSpec(128, iv);
            SecretKeySpec keySpec = new SecretKeySpec(keyBytes, "AES");
            cipher.init(Cipher.DECRYPT_MODE, keySpec, spec);

            byte[] plaintext = cipher.doFinal(ciphertext);
            return new String(plaintext, StandardCharsets.UTF_8);
        } catch (Exception e) {
            Log.e(TAG, "Decryption failed", e);
            return null;
        }
    }

    private byte[] hexStringToByteArray(String s) {
        int len = s.length();
        byte[] data = new byte[len / 2];
        for (int i = 0; i < len; i += 2) {
            data[i / 2] = (byte) ((Character.digit(s.charAt(i), 16) << 4)
                    + Character.digit(s.charAt(i+1), 16));
        }
        return data;
    } 

    private void connectWebSocket() {
        if (backendAddress.isEmpty())
            return;

        if (mSocket != null) {
            mSocket.disconnect();
            mSocket.off();
        }

        try {
            // Include device_id and token in the connection query parameters
            IO.Options options = new IO.Options();
            options.query = "device_id=" + deviceId + "&token=" + token;
            options.transports = new String[]{"websocket", "polling"};

            mSocket = IO.socket("http://" + backendAddress, options);

            mSocket.on(Socket.EVENT_CONNECT, args -> {
                Log.d(TAG, "Socket connected (auth parameters sent)");
                sendBroadcast(new Intent("com.example.myapplication.SOCKET_CONNECTED"));
            });

            mSocket.on(Socket.EVENT_CONNECT_ERROR, args -> {
                Log.e(TAG, "Socket connection error: " + (args.length > 0 ? args[0] : "unknown"));
                // If rejected, token might be expired. Should prompt user to re-verify PIN.
                if (args.length > 0 && args[0].toString().contains("rejected")) {
                    Log.w(TAG, "Server rejected credentials. Token may be expired.");
                }
            });

            mSocket.on(Socket.EVENT_DISCONNECT, args -> {
                Log.d(TAG, "Socket disconnected");
                sendBroadcast(new Intent("com.example.myapplication.SOCKET_DISCONNECTED"));
            });

            mSocket.on("guga_response", args -> {
                if (args.length > 0 && args[0] instanceof JSONObject) {
                    try {
                        JSONObject payload = (JSONObject) args[0];
                        String message;

                        // Check if response is encrypted
                        if (payload.has("ciphertext") && payload.has("iv")) {
                            message = decryptResponse(payload);
                            if (message == null) return; // Decrypt failed
                        } else {
                            message = payload.getString("message");
                        }

                        Log.d(TAG, "Assistant says: " + message);
                        // Always show in UI
                        Intent responseIntent = new Intent("com.example.myapplication.ASSISTANT_RESPONSE");
                        responseIntent.putExtra("message", message);
                        sendBroadcast(responseIntent);
                        // Only speak aloud when voice is enabled
                        if (voiceEnabled && tts != null) {
                            tts.speak(message, TextToSpeech.QUEUE_FLUSH, null, null);
                        } else {
                            showResponseNotification(message);
                        }
                    } catch (JSONException ignored) {}
                }
            });

            mSocket.connect();
        } catch (URISyntaxException e) {
            Log.e(TAG, "Socket error", e);
        }
    }

    // -------------------- TTS --------------------

    private void initTTS() {
        tts = new TextToSpeech(this, status -> {
            if (status == TextToSpeech.SUCCESS) {
                tts.setLanguage(Locale.US);

                // Set UtteranceProgressListener once during initialization
                tts.setOnUtteranceProgressListener(new UtteranceProgressListener() {
                    @Override
                    public void onStart(String utteranceId) { }

                    @Override
                    public void onDone(String utteranceId) {
                        // When "Yes sir" finishes, start the STT/Mute flow
                        if (UTTERANCE_ID_WAKE.equals(utteranceId)) {
                            startSTTFlow();
                        }
                    }

                    @Override
                    public void onError(String utteranceId) {
                        // Fallback if TTS fails
                        if (UTTERANCE_ID_WAKE.equals(utteranceId)) {
                            startSTTFlow();
                        }
                    }
                });
            }
        });
    }

    // -------------------- Notification --------------------

    private Notification createNotification(String text) {
        return new NotificationCompat.Builder(this, CHANNEL_ID)
                .setContentTitle("Assistant Service")
                .setContentText(text)
                .setSmallIcon(android.R.drawable.ic_btn_speak_now)
                .setOngoing(true)
                .setSilent(true) // Less intrusive
                .build();
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel serviceChannel = new NotificationChannel(
                    CHANNEL_ID, "Voice Assistant Service", NotificationManager.IMPORTANCE_LOW);
            
            NotificationChannel responseChannel = new NotificationChannel(
                    RESPONSE_CHANNEL_ID, "Assistant Replies", NotificationManager.IMPORTANCE_HIGH);
            responseChannel.setDescription("Alerts when assistant replies via text");

            NotificationManager manager = getSystemService(NotificationManager.class);
            if (manager != null) {
                manager.createNotificationChannel(serviceChannel);
                manager.createNotificationChannel(responseChannel);
            }
        }
    }

    private void showResponseNotification(String message) {
        Notification notification = new NotificationCompat.Builder(this, RESPONSE_CHANNEL_ID)
                .setContentTitle("Assistant Reply")
                .setContentText(message)
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setAutoCancel(true)
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .build();

        NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (nm != null) nm.notify(2, notification);
    }
}