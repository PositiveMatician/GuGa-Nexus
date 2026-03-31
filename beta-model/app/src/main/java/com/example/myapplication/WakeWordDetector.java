package com.example.myapplication;

import android.content.Context;
import android.content.res.AssetManager;
import android.util.Log;


import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.FloatBuffer;
import java.util.Arrays;
import java.util.Collections;

import ai.onnxruntime.OnnxTensor;
import ai.onnxruntime.OrtEnvironment;
import ai.onnxruntime.OrtSession;

public class WakeWordDetector {
    private static final String TAG = "WakeWordDetector";
    private static WakeWordDetector instance;

    public static WakeWordDetector getInstance() {
        return instance;
    }
    
    private final WakeWordListener listener;
    private OrtEnvironment env;
    private OrtSession melspecSession;
    private OrtSession embeddingSession;

    // Buffer dimensions based on openWakeWord
    private static final int CHUNK_SIZE = 1280;
    private static final int MELSPEC_FEATURES = 76;
    private static final int EMBEDDING_FEATURES = 96;
    private static final int EMBEDDING_BUFFER_SIZE = 16;
    private static final int MEL_FRAMES = 76;
    private static final int MEL_BINS = 32;

    // Pre-allocated arrays and buffers to prevent GC stuttering during processAudioChunk
    private final float[][] melspecInputArray = new float[1][CHUNK_SIZE];
    private final float[] currentEmbedding = new float[EMBEDDING_FEATURES];
    
    // Flat buffer for Mel features to accommodate sliding window shape [1, 76, 32, 1]
    private final float[] melBuffer = new float[MEL_FRAMES * MEL_BINS];
    private final FloatBuffer melFloatBuffer = FloatBuffer.wrap(melBuffer);
    private final float[] newMelData = new float[160]; // 5 * 32
    private final long[] embInputShape = {1, MEL_FRAMES, MEL_BINS, 1};
    

    public interface WakeWordListener {
        void onWakeWordDetected();
        /** Called every frame with the latest confidence score (cosine similarity). */
        default void onConfidenceScore(float score) {}
    }

    // Optional enrollment matcher — set after enrollment is complete
    private float[] enrolledTemplate   = null;
    private float   enrollmentThreshold = 0.75f;
    private boolean useEnrollmentMatcher = false;

    /** Activate personalized cosine-similarity matching with a saved template. */
    public void setEnrollmentMatcher(float[] template, float threshold) {
        this.enrolledTemplate     = template;
        this.enrollmentThreshold  = threshold;
        this.useEnrollmentMatcher = (template != null);
    }

    /** Deactivate enrollment matching. */
    public void clearEnrollmentMatcher() {
        this.enrolledTemplate     = null;
        this.useEnrollmentMatcher = false;
    }

    public WakeWordDetector(Context context, WakeWordListener listener) {
        this.listener = listener;
        instance = this;
        try {
            initModels(context);
        } catch (Exception e) {
            Log.e(TAG, "Error initializing models", e);
        }
    }

    private void initModels(Context context) throws Exception {
        // Copy assets to internal storage so C++ can read them
        String melspecPath = copyAsset(context, "openwakeword/melspectrogram.onnx");
        String embeddingPath = copyAsset(context, "openwakeword/embedding_model.onnx");

        // Init ONNX env and sessions
        env = OrtEnvironment.getEnvironment();
        OrtSession.SessionOptions options = new OrtSession.SessionOptions();
        melspecSession = env.createSession(melspecPath, options);
        embeddingSession = env.createSession(embeddingPath, options);
        Log.i(TAG, "ONNX Models Initialized.");
    }

    private String copyAsset(Context context, String assetPath) throws IOException {
        File outFile = new File(context.getFilesDir(), new File(assetPath).getName());
        if (!outFile.exists()) {
            AssetManager assetManager = context.getAssets();
            try (InputStream in = assetManager.open(assetPath);
                 FileOutputStream out = new FileOutputStream(outFile)) {
                byte[] buffer = new byte[1024];
                int read;
                while ((read = in.read(buffer)) != -1) {
                    out.write(buffer, 0, read);
                }
            }
        }
        return outFile.getAbsolutePath();
    }

    public void setThreshold(float newThreshold) {
        this.enrollmentThreshold = newThreshold;
    }

    public void setEnrollmentThreshold(float newThreshold) {
        this.enrollmentThreshold = newThreshold;
    }

    public void processAudioChunk(short[] pcmChunk) {
        if (pcmChunk.length != CHUNK_SIZE) {
            Log.w(TAG, "Chunk size must be " + CHUNK_SIZE);
            return;
        }

        // Convert short to float [-1.0, 1.0] 
        for (int i = 0; i < CHUNK_SIZE; i++) {
            melspecInputArray[0][i] = (float) pcmChunk[i];
        }
        Log.v(TAG, "Stage 1: Audio Normalized");

        OnnxTensor melspecTensor = null;
        OnnxTensor melOutputTensor = null;
        OnnxTensor embInputTensor = null;
        OnnxTensor embOutputTensor = null;
        OrtSession.Result melspecResult = null;
        OrtSession.Result embeddingResult = null;

        try {
            // Stage 1: Mel Spectrogram
            melspecTensor = OnnxTensor.createTensor(env, melspecInputArray);
            melspecResult = melspecSession.run(Collections.singletonMap("input", melspecTensor));
            Log.v(TAG, "Stage 2: Mel ONNX Complete");
            
            // Extract Flat Data
            melOutputTensor = (OnnxTensor) melspecResult.get(0);
            FloatBuffer melOutputBuffer = melOutputTensor.getFloatBuffer();
            int floatsReturned = melOutputBuffer.remaining();
            
            if (floatsReturned <= newMelData.length) {
                melOutputBuffer.get(newMelData, 0, floatsReturned);
                
                // Rolling Buffer Logic: Shift existing data left
                System.arraycopy(melBuffer, floatsReturned, melBuffer, 0, melBuffer.length - floatsReturned);
                // Insert new floats at the end
                System.arraycopy(newMelData, 0, melBuffer, melBuffer.length - floatsReturned, floatsReturned);
            }

            // Rewind wrapped buffer for OnnxTensor
            melFloatBuffer.position(0);

            // Stage 2: Embedding
            embInputTensor = OnnxTensor.createTensor(env, melFloatBuffer, embInputShape);
            embeddingResult = embeddingSession.run(Collections.singletonMap("input_1", embInputTensor));
            Log.v(TAG, "Stage 3: Embedding ONNX Complete");
            
            // Safe Extraction
            embOutputTensor = (OnnxTensor) embeddingResult.get(0);
            embOutputTensor.getFloatBuffer().get(currentEmbedding);

            Log.v(TAG, "Stage 4: Buffer updated");


            boolean triggered = false;
            // Scoring logic: ONLY use personalized cosine-similarity
            if (useEnrollmentMatcher && enrolledTemplate != null) {
                float score = WakeWordEnrollment.cosineSimilarity(currentEmbedding, enrolledTemplate);
                if (listener != null) listener.onConfidenceScore(score);
                Log.i(TAG, "Enrollment cosine score: " + score + " (Threshold: " + enrollmentThreshold + ")");
                triggered = score >= enrollmentThreshold;
            } else {
                Log.d(TAG, "No enrollment active. Skip scoring.");
            }

            if (triggered) {
                if (listener != null) listener.onWakeWordDetected();
            }

        } catch (Exception e) {
            Log.e(TAG, "Inference error", e);
        } finally {
            // Clean up ONNX resources for this frame to strictly prevent memory leaks
            // Note: melOutputTensor and embOutputTensor belong to result objects and MUST NOT be manually closed
            if (melspecTensor != null) melspecTensor.close();
            if (embInputTensor != null) embInputTensor.close();
            if (melspecResult != null) melspecResult.close();
            if (embeddingResult != null) embeddingResult.close();
        }
    }

    public void switchWakeWordModel(Context context, String modelFileName) {
        try {
            Log.d(TAG, "Switched model to: " + modelFileName);
        } catch (Exception e) {
            Log.e(TAG, "Error switching wake word model", e);
        }
    }

    public void close() {
        try {
            if (instance == this) instance = null;
            if (melspecSession != null) melspecSession.close();
            if (embeddingSession != null) embeddingSession.close();
            if (env != null) env.close();
        } catch (Exception e) {
            Log.e(TAG, "Error closing models", e);
        }
    }

    /**
     * Extracts a 96-dim embedding from a raw float array [-1, 1].
     * Synchronized to prevent concurrent ONNX runs.
     */
    public synchronized float[] extractEmbedding(float[] audioFloat) {
        if (env == null || melspecSession == null || embeddingSession == null) {
            Log.e(TAG, "Models not initialized");
            return null;
        }

        OnnxTensor melspecTensor = null;
        OnnxTensor melOutputTensor = null;
        OnnxTensor embInputTensor = null;
        OnnxTensor embOutputTensor = null;
        OrtSession.Result melspecResult = null;
        OrtSession.Result embeddingResult = null;

        try {
            // 1. Mel Spectrogram
            float[][] input = new float[1][audioFloat.length];
            System.arraycopy(audioFloat, 0, input[0], 0, audioFloat.length);
            
            melspecTensor = OnnxTensor.createTensor(env, input);
            melspecResult = melspecSession.run(Collections.singletonMap("input", melspecTensor));

            // 2. Rolling buffer update (Mel)
            melOutputTensor = (OnnxTensor) melspecResult.get(0);
            FloatBuffer melOutputBuffer = melOutputTensor.getFloatBuffer();
            int floatsReturned = melOutputBuffer.remaining();
            
            if (floatsReturned <= newMelData.length) {
                melOutputBuffer.get(newMelData, 0, floatsReturned);
                System.arraycopy(melBuffer, floatsReturned, melBuffer, 0, melBuffer.length - floatsReturned);
                System.arraycopy(newMelData, 0, melBuffer, melBuffer.length - floatsReturned, floatsReturned);
            }
            melFloatBuffer.position(0);

            // 3. Embedding
            embInputTensor = OnnxTensor.createTensor(env, melFloatBuffer, embInputShape);
            embeddingResult = embeddingSession.run(Collections.singletonMap("input_1", embInputTensor));
            
            embOutputTensor = (OnnxTensor) embeddingResult.get(0);
            float[] embedding = new float[EMBEDDING_FEATURES];
            embOutputTensor.getFloatBuffer().get(embedding);
            
            return embedding;

        } catch (Exception e) {
            Log.e(TAG, "Inference failed", e);
            return null;
        } finally {
            if (melspecTensor != null) melspecTensor.close();
            if (embInputTensor != null) embInputTensor.close();
            if (melspecResult != null) melspecResult.close();
            if (embeddingResult != null) embeddingResult.close();
        }
    }
}
