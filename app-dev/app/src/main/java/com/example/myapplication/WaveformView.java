package com.example.myapplication;

import android.animation.ValueAnimator;
import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.LinearGradient;
import android.graphics.Paint;
import android.graphics.RectF;
import android.graphics.Shader;
import android.util.AttributeSet;
import android.view.View;
import android.view.animation.DecelerateInterpolator;

/**
 * Rolling bar waveform visualizer with two sensitivity modes:
 *
 *   NORMAL    — linear scaling, good for voice (which is loud)
 *   SENSITIVE — heavy gamma curve, small ambient sounds make big visual effects
 *
 * Call pushAmplitude(rms) from the UI thread every ~80ms.
 * Call setSensitiveMode(true) when switching to ambience recording.
 */
public class WaveformView extends View {

    // ── Config ────────────────────────────────────────────────────────────────
    private static final int   BAR_COUNT      = 48;
    private static final float BAR_WIDTH_DP   = 5f;
    private static final float BAR_GAP_DP     = 2.5f;
    private static final float MIN_HEIGHT_DP  = 3f;
    private static final float CORNER_RADIUS  = 4f;

    // Sensitive mode: RMS is raised to this power (< 1 = expand small values)
    private static final float SENSITIVE_GAMMA = 0.25f;
    // Normal mode gamma
    private static final float NORMAL_GAMMA    = 0.7f;

    // ── State ─────────────────────────────────────────────────────────────────
    private final float[] rawAmplitudes  = new float[BAR_COUNT];
    private final float[] drawAmplitudes = new float[BAR_COUNT]; // smoothed
    private int           insertIndex    = 0;
    private boolean       sensitiveMode  = false;

    // Per-bar smooth animation targets
    private final float[] targets = new float[BAR_COUNT];

    // ── Paint ─────────────────────────────────────────────────────────────────
    private final Paint barPaint    = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint dimPaint    = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final RectF rectBuffer  = new RectF();

    // Gradient colours — updated on size change
    private int colorTop    = Color.parseColor("#69F0AE"); // bright mint
    private int colorBottom = Color.parseColor("#00897B"); // teal
    private int colorDim    = Color.parseColor("#1E2A28");

    // Sensitive mode gradient
    private int colorSensTop = Color.parseColor("#FFD740"); // amber
    private int colorSensBtm = Color.parseColor("#FF6D00"); // deep orange

    private float density;

    // ── Constructor ───────────────────────────────────────────────────────────
    public WaveformView(Context ctx) { this(ctx, null); }
    public WaveformView(Context ctx, AttributeSet attrs) {
        super(ctx, attrs);
        density = ctx.getResources().getDisplayMetrics().density;
        dimPaint.setColor(colorDim);
        // Start all bars at zero
        java.util.Arrays.fill(rawAmplitudes,  0f);
        java.util.Arrays.fill(drawAmplitudes, 0f);
        java.util.Arrays.fill(targets,        0f);
    }

    // ═════════════════════════════════════════════════════════════════════════
    // Public API
    // ═════════════════════════════════════════════════════════════════════════

    /**
     * Push a new RMS amplitude (0.0–1.0).
     * Must be called on the UI thread.
     */
    public void pushAmplitude(float rms) {
        float gamma   = sensitiveMode ? SENSITIVE_GAMMA : NORMAL_GAMMA;
        float scaled  = (float) Math.pow(Math.max(0f, Math.min(1f, rms)), gamma);

        int idx = insertIndex % BAR_COUNT;
        rawAmplitudes[idx] = scaled;
        targets[idx]       = scaled;
        insertIndex++;

        // Smooth all bars toward their targets (simple lerp each frame)
        for (int i = 0; i < BAR_COUNT; i++) {
            drawAmplitudes[i] = drawAmplitudes[i] * 0.55f + targets[i] * 0.45f;
        }

        invalidate();
    }

    /**
     * true  = sensitive mode (ambient): small RMS → tall bars, amber/orange colour
     * false = normal mode (voice): linear-ish, green colour
     */
    public void setSensitiveMode(boolean sensitive) {
        if (this.sensitiveMode == sensitive) return;
        this.sensitiveMode = sensitive;
        rebuildGradient();
        // Animate colour transition
        invalidate();
    }

    /** Reset all bars to zero (e.g. between phases). */
    public void reset() {
        java.util.Arrays.fill(rawAmplitudes,  0f);
        java.util.Arrays.fill(drawAmplitudes, 0f);
        java.util.Arrays.fill(targets,        0f);
        insertIndex = 0;
        invalidate();
    }

    // ═════════════════════════════════════════════════════════════════════════
    // Drawing
    // ═════════════════════════════════════════════════════════════════════════

    @Override
    protected void onSizeChanged(int w, int h, int oldW, int oldH) {
        super.onSizeChanged(w, h, oldW, oldH);
        rebuildGradient();
    }

    private void rebuildGradient() {
        int h = getHeight();
        if (h <= 0) return;
        int top = sensitiveMode ? colorSensTop : colorTop;
        int btm = sensitiveMode ? colorSensBtm : colorBottom;
        barPaint.setShader(new LinearGradient(0, 0, 0, h, top, btm, Shader.TileMode.CLAMP));
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);

        float w         = getWidth();
        float h         = getHeight();
        float barW      = BAR_WIDTH_DP  * density;
        float gap       = BAR_GAP_DP    * density;
        float minH      = MIN_HEIGHT_DP * density;
        float totalW    = BAR_COUNT * (barW + gap) - gap;
        float startX    = (w - totalW) / 2f;
        float cy        = h / 2f;
        float corner    = CORNER_RADIUS * density;

        for (int i = 0; i < BAR_COUNT; i++) {
            // Oldest bar on the left, newest on the right
            int   dataIdx = (insertIndex + i) % BAR_COUNT;
            float amp     = drawAmplitudes[dataIdx];
            float barH    = Math.max(minH, amp * h * 0.92f);
            float x       = startX + i * (barW + gap);

            rectBuffer.set(x, cy - barH / 2f, x + barW, cy + barH / 2f);

            // Dim background bar (always visible, shows the "slot")
            float dimH = Math.max(minH, h * 0.06f);
            RectF dimRect = new RectF(x, cy - dimH/2f, x + barW, cy + dimH/2f);
            canvas.drawRoundRect(dimRect, corner, corner, dimPaint);

            // Active bar
            if (amp > 0.01f) {
                // Slightly brighten recent bars
                float ageFactor = (float) i / BAR_COUNT; // 0=old, 1=new
                barPaint.setAlpha((int)(180 + ageFactor * 75));
                canvas.drawRoundRect(rectBuffer, corner, corner, barPaint);
            }
        }
    }
}
