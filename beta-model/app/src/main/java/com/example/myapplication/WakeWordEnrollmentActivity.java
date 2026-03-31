package com.example.myapplication;

import android.Manifest;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.view.View;
import android.widget.Button;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

public class WakeWordEnrollmentActivity extends AppCompatActivity {

    private static final String TAG = "WW_Enroll";

    // ── Config ────────────────────────────────────────────────────────────────
    private static final int   TOTAL_SAMPLES    = 5;
    private static final int   SAMPLE_RATE      = 16000;
    private static final int   EMBEDDING_SIZE   = 96;    
    private static final float SIMILARITY_FLOOR = 0.60f;

    // ── State machine ─────────────────────────────────────────────────────────
    private enum Phase {
        IDLE,
        COLLECTING_SILENCE,
        COLLECTING_AMBIENCE,
        WAITING_TO_RECORD,
        ACTIVELY_RECORDING,
        DONE
    }
    private Phase currentPhase = Phase.IDLE;

    // ── Audio ─────────────────────────────────────────────────────────────────
    private AudioRecord         audioRecord;
    private final AtomicBoolean keepRecording = new AtomicBoolean(false);
    private final Object        audioLock     = new Object();
    private volatile float      rmsLevel      = 0f;

    // ── Enrollment data ───────────────────────────────────────────────────────
    private final List<float[]> positiveEmbeddings  = new ArrayList<>(); // your voice
    private final List<float[]> negativeEmbeddings  = new ArrayList<>(); // silence + ambience combined
    private final List<float[]> currentSampleChunks = new ArrayList<>();
    private int currentSampleIndex = 0;

    // ── UI ────────────────────────────────────────────────────────────────────
    private TextView    tvPhaseTitle, tvPhaseDetail, tvLog, tvSampleCount, tvWaveLabel;
    private Button      btnAction;
    private ProgressBar progressSpinner;
    private WaveformView waveformView;
    private View[]      sampleDots;

    // ── Threading ─────────────────────────────────────────────────────────────
    private final ExecutorService executor    = Executors.newSingleThreadExecutor();
    private final Handler         mainHandler = new Handler(Looper.getMainLooper());
    private Runnable              rmsUpdater;

    // ═════════════════════════════════════════════════════════════════════════
    // Lifecycle
    // ═════════════════════════════════════════════════════════════════════════

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_wake_word_enrollment);
        initViews();
        checkPermissions();
        Log.i(TAG, "=== WakeWordEnrollmentActivity created ===");
        logUI("Ready. Find a quiet spot and tap Begin.");
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        keepRecording.set(false);
        stopAudioRecord();
        stopRmsUpdater();
        executor.shutdownNow();
        Log.i(TAG, "=== onDestroy — resources released ===");
    }

    // ═════════════════════════════════════════════════════════════════════════
    // Views
    // ═════════════════════════════════════════════════════════════════════════

    private void initViews() {
        tvPhaseTitle    = findViewById(R.id.tv_phase_title);
        tvPhaseDetail   = findViewById(R.id.tv_phase_detail);
        tvLog           = findViewById(R.id.tv_log);
        tvSampleCount   = findViewById(R.id.tv_sample_count);
        tvWaveLabel     = findViewById(R.id.tv_wave_label);
        btnAction       = findViewById(R.id.btn_action);
        progressSpinner = findViewById(R.id.progress_spinner);
        waveformView    = findViewById(R.id.waveform_view);

        sampleDots = new View[]{
            findViewById(R.id.dot_1), findViewById(R.id.dot_2), findViewById(R.id.dot_3),
            findViewById(R.id.dot_4), findViewById(R.id.dot_5)
        };

        progressSpinner.setVisibility(View.GONE);
        btnAction.setOnClickListener(v -> onActionButtonClicked());
        enterPhase(Phase.IDLE);
    }

    // ═════════════════════════════════════════════════════════════════════════
    // Phase machine
    // ═════════════════════════════════════════════════════════════════════════

    private void onActionButtonClicked() {
        Log.i(TAG, "Button tapped in phase=" + currentPhase);
        switch (currentPhase) {
            case IDLE:
                enterPhase(Phase.COLLECTING_SILENCE);
                break;
            case COLLECTING_SILENCE:
                stopSilenceCollection();
                break;
            case COLLECTING_AMBIENCE:
                stopAmbienceCollection();
                break;
            case WAITING_TO_RECORD:
                enterPhase(Phase.ACTIVELY_RECORDING);
                break;
            case ACTIVELY_RECORDING:
                stopSampleRecording();
                break;
            case DONE:
                saveAndFinish();
                break;
        }
    }

    private void enterPhase(Phase phase) {
        currentPhase = phase;
        Log.i(TAG, ">>> Phase → " + phase
            + "  pos=" + positiveEmbeddings.size()
            + "  neg=" + negativeEmbeddings.size());

        switch (phase) {

            case IDLE:
                tvPhaseTitle.setText("Train Your Wake Word");
                tvPhaseDetail.setText(
                    "We need three things:\n" +
                    "  1. Silence samples\n" +
                    "  2. Room ambience samples\n" +
                    "  3. Your voice saying the wake word × 5\n\n" +
                    "Find a quiet spot and tap Begin.");
                btnAction.setText("Begin");
                tvSampleCount.setText("0 / " + TOTAL_SAMPLES);
                setWaveLabel(false);
                break;

            case COLLECTING_SILENCE:
                tvPhaseTitle.setText("Step 1 — Capture Silence");
                tvPhaseDetail.setText(
                    "Stay completely quiet. Don't speak, don't move.\n\n" +
                    "This teaches what true silence sounds like.\n\n" +
                    "Tap Done when you've held silence for ~5 seconds.");
                btnAction.setText("Done — silence captured");
                setWaveLabel(false);
                waveformView.setSensitiveMode(false);
                waveformView.reset();
                logUI("Step 1: Stay silent…");
                startSilenceCollection();
                break;

            case COLLECTING_AMBIENCE:
                tvPhaseTitle.setText("Step 2 — Capture Room Ambience");
                tvPhaseDetail.setText(
                    "Now let your room make its normal sounds.\n\n" +
                    "Open a window, let traffic/birds/fan come through.\n" +
                    "Don't speak — just let the environment breathe.\n\n" +
                    "Tap Done after a few seconds.");
                btnAction.setText("Done — ambience captured");
                waveformView.setSensitiveMode(true);
                waveformView.reset();
                setWaveLabel(true);
                logUI("Step 2: Let your room make noise…");
                startAmbienceCollection();
                break;

            case WAITING_TO_RECORD:
                tvPhaseTitle.setText("Step 3 — Sample " + (currentSampleIndex + 1) + " of " + TOTAL_SAMPLES);
                tvPhaseDetail.setText(
                    "Tap START, say your wake word clearly, then tap STOP.\n\n" +
                    "Tip: vary your distance — close first, then arm's length.");
                btnAction.setText("▶  START");
                waveformView.setSensitiveMode(false);
                waveformView.reset();
                setWaveLabel(false);
                logUI("Ready for sample " + (currentSampleIndex + 1) + ". Tap START.");
                break;

            case ACTIVELY_RECORDING:
                tvPhaseTitle.setText("Listening… speak now");
                tvPhaseDetail.setText("Say your wake word, then tap STOP.");
                btnAction.setText("■  STOP");
                logUI("Recording sample " + (currentSampleIndex + 1) + "…");
                startSampleRecording();
                break;

            case DONE:
                tvPhaseTitle.setText("All Samples Collected");
                tvPhaseDetail.setText("Tap Save to build your personal wake word.");
                btnAction.setText("Save Wake Word");
                waveformView.reset();
                logUI("All " + TOTAL_SAMPLES + " samples done. Tap Save.");
                break;
        }
    }

    private void setWaveLabel(boolean sensitiveMode) {
        if (tvWaveLabel == null) return;
        if (sensitiveMode) {
            tvWaveLabel.setText("Sensitive mode — even faint sounds show here");
        } else {
            tvWaveLabel.setText("Green bars = mic is hearing audio");
        }
    }

    private void startSilenceCollection() {
        Log.i(TAG, "Silence collection starting");
        keepRecording.set(true);
        startAudioRecord();
        startRmsUpdater();

        executor.execute(() -> {
            int collected = 0;
            while (keepRecording.get()) {
                float[] chunk = captureAudioChunk(400);
                if (chunk == null) { Log.w(TAG, "Silence chunk null"); continue; }

                float rms = computeRms(chunk);
                float[] emb = extractEmbedding(chunk);
                if (emb != null) {
                    negativeEmbeddings.add(emb);
                    collected++;
                    final int c = collected;
                    final float r = rms;
                    mainHandler.post(() ->
                        logUI("Silence[" + c + "] rms=" + String.format("%.5f", r)));
                }
            }
        });
    }

    private void stopSilenceCollection() {
        keepRecording.set(false);
        stopAudioRecord();
        stopRmsUpdater();
        logUI("Silence done: " + negativeEmbeddings.size() + " chunks.");
        enterPhase(Phase.COLLECTING_AMBIENCE);
    }

    private void startAmbienceCollection() {
        Log.i(TAG, "Ambience collection starting");
        keepRecording.set(true);
        startAudioRecord();
        startRmsUpdater();

        executor.execute(() -> {
            int collected = 0;
            while (keepRecording.get()) {
                float[] chunk = captureAudioChunk(400);
                if (chunk == null) { Log.w(TAG, "Ambience chunk null"); continue; }

                float rms = computeRms(chunk);
                float[] emb = extractEmbedding(chunk);
                if (emb != null) {
                    negativeEmbeddings.add(emb);
                    collected++;
                    final int c = collected;
                    final float r = rms;
                    final boolean hasSound = rms > 0.005f;
                    mainHandler.post(() ->
                        logUI("Ambience[" + c + "] rms=" + String.format("%.5f", r)
                            + (hasSound ? " ← sound detected!" : " (quiet)")));
                }
            }
        });
    }

    private void stopAmbienceCollection() {
        keepRecording.set(false);
        stopAudioRecord();
        stopRmsUpdater();
        logUI("Ambience done. Total negative chunks: " + negativeEmbeddings.size());
        currentSampleIndex = 0;
        enterPhase(Phase.WAITING_TO_RECORD);
    }

    private void startSampleRecording() {
        currentSampleChunks.clear();
        keepRecording.set(true);
        startAudioRecord();
        startRmsUpdater();

        executor.execute(() -> {
            while (keepRecording.get()) {
                float[] chunk = captureAudioChunk(150);
                if (chunk == null) { Log.w(TAG, "Voice chunk null"); continue; }
                float[] emb = extractEmbedding(chunk);
                if (emb != null) currentSampleChunks.add(emb);
            }
        });
    }

    private void stopSampleRecording() {
        keepRecording.set(false);
        stopAudioRecord();
        stopRmsUpdater();

        List<float[]> chunks = new ArrayList<>(currentSampleChunks);
        if (chunks.size() < 3) {
            logUI("⚠ Too short. Hold longer and speak clearly.");
            enterPhase(Phase.WAITING_TO_RECORD);
            return;
        }

        float[] utteranceEmb = meanPool(chunks);
        positiveEmbeddings.add(utteranceEmb);
        currentSampleIndex++;

        final int dotIdx = currentSampleIndex - 1;
        if (dotIdx < sampleDots.length) {
            mainHandler.post(() ->
                sampleDots[dotIdx].setBackgroundResource(R.drawable.dot_filled));
        }
        mainHandler.post(() -> tvSampleCount.setText(currentSampleIndex + " / " + TOTAL_SAMPLES));
        logUI("✓ Sample " + currentSampleIndex + " saved.");

        if (currentSampleIndex >= TOTAL_SAMPLES) {
            enterPhase(Phase.DONE);
        } else {
            enterPhase(Phase.WAITING_TO_RECORD);
        }
    }

    private void saveAndFinish() {
        btnAction.setEnabled(false);
        progressSpinner.setVisibility(View.VISIBLE);
        logUI("Building model…");

        executor.execute(() -> {
            try {
                float[] template = meanPool(positiveEmbeddings);

                float minPosSim = 1.0f;
                for (float[] emb : positiveEmbeddings) {
                    float sim = cosineSimilarity(emb, template);
                    if (sim < minPosSim) minPosSim = sim;
                }

                float maxNegSim = 0f;
                for (float[] emb : negativeEmbeddings) {
                    float sim = cosineSimilarity(emb, template);
                    if (sim > maxNegSim) maxNegSim = sim;
                }

                float threshold = calibrateThreshold(minPosSim, maxNegSim);
                saveTemplate(template);
                saveThreshold(threshold);

                mainHandler.post(() -> {
                    progressSpinner.setVisibility(View.GONE);
                    logUI("✓ Saved! Threshold: " + String.format("%.3f", threshold));
                    Toast.makeText(this, "Enrollment complete!", Toast.LENGTH_LONG).show();
                    // Notify service to reload models
                    sendBroadcast(new Intent("com.example.myapplication.ENROLLMENT_DONE"));
                    mainHandler.postDelayed(() -> { setResult(RESULT_OK); finish(); }, 2000);
                });

            } catch (Exception e) {
                Log.e(TAG, "Save failed", e);
                mainHandler.post(() -> {
                    progressSpinner.setVisibility(View.GONE);
                    logUI("❌ Error: " + e.getMessage());
                    btnAction.setEnabled(true);
                });
            }
        });
    }

    private void startAudioRecord() {
        synchronized (audioLock) {
            if (audioRecord != null) return;
            int minBuf  = AudioRecord.getMinBufferSize(SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
            audioRecord = new AudioRecord(
                MediaRecorder.AudioSource.MIC, SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, Math.max(minBuf, SAMPLE_RATE * 2));
            audioRecord.startRecording();
        }
    }

    private void stopAudioRecord() {
        synchronized (audioLock) {
            if (audioRecord == null) return;
            try { audioRecord.stop(); audioRecord.release(); } catch (Exception e) {}
            audioRecord = null;
        }
    }

    private float[] captureAudioChunk(int durationMs) {
        int numSamples = (SAMPLE_RATE * durationMs) / 1000;
        short[] buf = new short[numSamples];
        int read;
        synchronized (audioLock) {
            if (audioRecord == null) return null;
            read = audioRecord.read(buf, 0, numSamples);
        }
        if (read <= 0) return null;

        float[] out = new float[read];
        float sum = 0;
        for (int i = 0; i < read; i++) {
            out[i] = buf[i] / 32768.0f;
            sum += out[i] * out[i];
        }
        rmsLevel = (float) Math.sqrt(sum / read);
        return out;
    }

    private void startRmsUpdater() {
        stopRmsUpdater();
        rmsUpdater = new Runnable() {
            @Override public void run() {
                if (waveformView != null) waveformView.pushAmplitude(rmsLevel);
                mainHandler.postDelayed(this, 80);
            }
        };
        mainHandler.post(rmsUpdater);
    }

    private void stopRmsUpdater() {
        if (rmsUpdater != null) { mainHandler.removeCallbacks(rmsUpdater); rmsUpdater = null; }
        if (waveformView != null) waveformView.pushAmplitude(0f);
    }

    private float[] extractEmbedding(float[] audioFloat) {
        WakeWordDetector detector = WakeWordDetector.getInstance();
        if (detector != null) {
            return detector.extractEmbedding(audioFloat);
        }
        Log.e(TAG, "WakeWordDetector instance null!");
        return null;
    }

    private float[] meanPool(List<float[]> embeddings) {
        float[] result = new float[EMBEDDING_SIZE];
        for (float[] e : embeddings) for (int i = 0; i < EMBEDDING_SIZE; i++) result[i] += e[i];
        for (int i = 0; i < EMBEDDING_SIZE; i++) result[i] /= embeddings.size();
        return result;
    }

    private float cosineSimilarity(float[] a, float[] b) {
        float dot = 0, na = 0, nb = 0;
        for (int i = 0; i < a.length; i++) { dot += a[i]*b[i]; na += a[i]*a[i]; nb += b[i]*b[i]; }
        return (na == 0 || nb == 0) ? 0f : dot / (float)(Math.sqrt(na) * Math.sqrt(nb));
    }

    private float computeRms(float[] s) {
        float sum = 0; for (float v : s) sum += v*v;
        return (float) Math.sqrt(sum / s.length);
    }

    private float calibrateThreshold(float minPos, float maxNeg) {
        float midpoint  = (minPos + maxNeg) / 2f;
        float threshold = midpoint + (minPos - midpoint) * 0.3f; 
        threshold = Math.max(threshold, SIMILARITY_FLOOR);
        threshold = Math.min(threshold, minPos - 0.01f);
        return threshold;
    }

    private void saveTemplate(float[] t) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < t.length; i++) { sb.append(t[i]); if (i < t.length-1) sb.append(","); }
        getSharedPreferences("wakeword", Context.MODE_PRIVATE).edit()
            .putString("wake_word_template", sb.toString())
            .apply();
        Log.i(TAG, "Template saved");
    }

    private void saveThreshold(float v) {
        getSharedPreferences("wakeword", Context.MODE_PRIVATE).edit()
            .putFloat("wake_word_threshold", v).apply();
    }

    private void checkPermissions() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
                != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(this,
                new String[]{Manifest.permission.RECORD_AUDIO}, 101);
        }
    }

    private final StringBuilder logBuffer = new StringBuilder();

    private void logUI(String msg) {
        mainHandler.post(() -> {
            logBuffer.insert(0, msg + "\n");
            String[] lines = logBuffer.toString().split("\n");
            if (lines.length > 10) {
                logBuffer.setLength(0);
                for (int i = 0; i < 10; i++) logBuffer.append(lines[i]).append("\n");
            }
            if (tvLog != null) tvLog.setText(logBuffer.toString().trim());
        });
    }
}
