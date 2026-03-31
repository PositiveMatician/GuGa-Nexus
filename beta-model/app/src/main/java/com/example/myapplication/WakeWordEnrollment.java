package com.example.myapplication;

import android.content.Context;

import java.util.ArrayList;
import java.util.List;

/**
 * Manages the voice enrollment pipeline.
 *
 * Flow:
 *  1. User says the wake word N times → addEnrollmentSample() per sample.
 *  2. Call buildTemplate() to mean-pool all samples into one representative vector.
 *  3. Call calibrateThreshold() to auto-calculate a robust similarity threshold.
 *  4. Call saveTemplate() / saveThreshold() to persist to SharedPreferences.
 *  5. On next launch, call loadTemplate() / loadThreshold() to restore.
 */
public class WakeWordEnrollment {

    private static final String PREFS_NAME    = "wakeword";
    private static final String KEY_TEMPLATE  = "wake_word_template";
    private static final String KEY_THRESHOLD = "wake_word_threshold";

    // Must match the ONNX embedding model output size
    public static final int EMBEDDING_SIZE = 96;

    // Collected raw embeddings from the user during enrollment
    private final List<float[]> enrollmentEmbeddings = new ArrayList<>();

    // -----------------------------------------------------------------------
    // Sample collection
    // -----------------------------------------------------------------------

    /** Add one embedding recorded while the user said the wake word. */
    public void addEnrollmentSample(float[] embedding) {
        float[] copy = new float[embedding.length];
        System.arraycopy(embedding, 0, copy, 0, embedding.length);
        enrollmentEmbeddings.add(copy);
    }

    public int getSampleCount() {
        return enrollmentEmbeddings.size();
    }

    public void clearSamples() {
        enrollmentEmbeddings.clear();
    }

    // -----------------------------------------------------------------------
    // Template building
    // -----------------------------------------------------------------------

    /**
     * Mean-pools all enrollment embeddings into a single representative vector.
     * Call only after all samples have been added.
     */
    public float[] buildTemplate() {
        if (enrollmentEmbeddings.isEmpty()) return null;

        float[] template = new float[EMBEDDING_SIZE];
        for (float[] emb : enrollmentEmbeddings) {
            for (int i = 0; i < EMBEDDING_SIZE; i++) {
                template[i] += emb[i];
            }
        }
        for (int i = 0; i < EMBEDDING_SIZE; i++) {
            template[i] /= enrollmentEmbeddings.size();
        }
        return template;
    }

    // -----------------------------------------------------------------------
    // Threshold calibration
    // -----------------------------------------------------------------------

    /**
     * Auto-calibrates the cosine-similarity threshold from enrollment data.
     *
     * Strategy: find the lowest similarity among the user's own enrollment
     * samples vs. the template, then set the threshold 8% below that worst
     * case so the user's own voice always passes, with a small safety margin.
     */
    public float calibrateThreshold(float[] template) {
        if (enrollmentEmbeddings.isEmpty() || template == null) return 0.75f;

        float minSelfSimilarity = 1.0f;
        for (float[] emb : enrollmentEmbeddings) {
            float score = cosineSimilarity(emb, template);
            if (score < minSelfSimilarity) {
                minSelfSimilarity = score;
            }
        }
        // 8% margin below worst self-similarity
        return minSelfSimilarity * 0.92f;
    }

    // -----------------------------------------------------------------------
    // Persistence
    // -----------------------------------------------------------------------

    /** Save the template vector to SharedPreferences as a CSV string. */
    public void saveTemplate(Context context, float[] template) {
        if (template == null) return;
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < template.length; i++) {
            if (i > 0) sb.append(',');
            sb.append(template[i]);
        }
        prefs(context).edit().putString(KEY_TEMPLATE, sb.toString()).apply();
    }

    /** Load the saved template, or return null if none has been saved. */
    public float[] loadTemplate(Context context) {
        String saved = prefs(context).getString(KEY_TEMPLATE, null);
        if (saved == null) return null;
        String[] parts = saved.split(",");
        float[] template = new float[parts.length];
        for (int i = 0; i < parts.length; i++) {
            template[i] = Float.parseFloat(parts[i]);
        }
        return template;
    }

    /** Save the calibrated threshold. */
    public void saveThreshold(Context context, float threshold) {
        prefs(context).edit().putFloat(KEY_THRESHOLD, threshold).apply();
    }

    /** Load the saved threshold, defaulting to 0.75 if not set. */
    public float loadThreshold(Context context) {
        return prefs(context).getFloat(KEY_THRESHOLD, 0.75f);
    }

    /** Returns true if a template has been saved (enrollment is complete). */
    public boolean isEnrolled(Context context) {
        return prefs(context).contains(KEY_TEMPLATE);
    }

    /** Clears all saved enrollment data. */
    public void clearEnrollment(Context context) {
        prefs(context).edit().remove(KEY_TEMPLATE).remove(KEY_THRESHOLD).apply();
        enrollmentEmbeddings.clear();
    }

    // -----------------------------------------------------------------------
    // Helpers
    // -----------------------------------------------------------------------

    /** Cosine similarity in [−1, 1]. Returns 0 if either vector is zero. */
    public static float cosineSimilarity(float[] a, float[] b) {
        float dot = 0f, normA = 0f, normB = 0f;
        for (int i = 0; i < a.length; i++) {
            dot   += a[i] * b[i];
            normA += a[i] * a[i];
            normB += b[i] * b[i];
        }
        if (normA == 0f || normB == 0f) return 0f;
        return dot / (float) (Math.sqrt(normA) * Math.sqrt(normB));
    }

    private android.content.SharedPreferences prefs(Context context) {
        return context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
    }
}
