package com.example.myapplication;

import android.content.Context;
import android.util.Log;

/**
 * Drop this into your existing audio processing service.
 * Call isWakeWord() wherever you currently read the TFLite score.
 */
public class WakeWordMatcher {

    private static final String TAG = "WakeWordMatcher";
    private static final String PREFS_NAME = "wakeword";
    private static final String KEY_TEMPLATE = "wake_word_template";
    private static final String KEY_THRESHOLD = "wake_word_threshold";

    private final float[] template;
    private final float threshold;
    private final boolean enrolled;

    public WakeWordMatcher(Context context) {
        float[] loadedTemplate = loadTemplate(context);
        float loadedThreshold  = loadThreshold(context);
        boolean isEnrolled     = isEnrolled(context);

        this.template  = loadedTemplate;
        this.threshold = loadedThreshold;
        this.enrolled  = isEnrolled;

        Log.d(TAG, "WakeWordMatcher loaded. Enrolled: " + enrolled
            + ", threshold: " + threshold
            + ", template size: " + (template != null ? template.length : "null"));
    }

    /**
     * Call this in your live audio loop instead of (or alongside) the TFLite score.
     *
     * @param liveEmbedding  The float[] output from your Stage 3 ONNX embedding
     * @return true if the live audio matches the enrolled wake word
     */
    public boolean isWakeWord(float[] liveEmbedding) {
        if (!enrolled || template == null) {
            Log.w(TAG, "No enrollment found — skipping matcher");
            return false;
        }

        float score = cosineSimilarity(liveEmbedding, template);
        Log.d(TAG, "Similarity score: " + score + " (threshold: " + threshold + ")");

        return score >= threshold;
    }

    /**
     * Returns the raw similarity score (0.0 to 1.0).
     * Useful for debugging or building a confidence meter in the UI.
     */
    public float getSimilarityScore(float[] liveEmbedding) {
        if (!enrolled || template == null) return 0f;
        return cosineSimilarity(liveEmbedding, template);
    }

    public boolean isEnrolled() {
        return enrolled;
    }

    // ─── Math ─────────────────────────────────────────────────────────────────

    private float cosineSimilarity(float[] a, float[] b) {
        if (a.length != b.length) {
            Log.e(TAG, "Embedding size mismatch: " + a.length + " vs " + b.length);
            return 0f;
        }

        float dot = 0f, normA = 0f, normB = 0f;
        for (int i = 0; i < a.length; i++) {
            dot   += a[i] * b[i];
            normA += a[i] * a[i];
            normB += b[i] * b[i];
        }

        if (normA == 0 || normB == 0) return 0f;
        return dot / (float)(Math.sqrt(normA) * Math.sqrt(normB));
    }

    // ─── Persistence ──────────────────────────────────────────────────────────

    private float[] loadTemplate(Context context) {
        String saved = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                              .getString(KEY_TEMPLATE, null);
        if (saved == null) return null;

        String[] parts = saved.split(",");
        float[] template = new float[parts.length];
        for (int i = 0; i < parts.length; i++) {
            template[i] = Float.parseFloat(parts[i]);
        }
        return template;
    }

    private float loadThreshold(Context context) {
        return context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                      .getFloat(KEY_THRESHOLD, 0.75f); // safe fallback
    }

    private boolean isEnrolled(Context context) {
        return context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                      .contains(KEY_TEMPLATE);
    }

    // ─── Utilities ────────────────────────────────────────────────────────────

    /**
     * Call this if the user wants to re-enroll (reset and redo enrollment).
     */
    public static void clearEnrollment(Context context) {
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
               .edit()
               .remove(KEY_TEMPLATE)
               .remove(KEY_THRESHOLD)
               .apply();
        Log.d(TAG, "Enrollment cleared");
    }
}
