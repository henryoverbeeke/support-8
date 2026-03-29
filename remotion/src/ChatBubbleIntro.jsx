import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

export const ChatBubbleIntro = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const bubbles = [
    { delay: 0, text: "Hi, I need help!", side: "right", color: "#6366f1" },
    { delay: 18, text: "Of course! How can I assist?", side: "left", color: "#f1f5f9", textColor: "#1e293b" },
    { delay: 36, text: "That was incredibly fast!", side: "right", color: "#6366f1" },
  ];

  const dotPulse = (i) => {
    const d = frame - 54;
    if (d < 0) return 0;
    const f = (d + i * 4) % 24;
    return interpolate(f, [0, 6, 12], [0.3, 1, 0.3], { extrapolateRight: "clamp" });
  };

  return (
    <AbsoluteFill
      style={{
        background: "linear-gradient(135deg, #0f0f23 0%, #1a1a3e 50%, #0f0f23 100%)",
        justifyContent: "center",
        alignItems: "center",
        fontFamily: "'SF Pro Display', -apple-system, BlinkMacSystemFont, sans-serif",
        padding: 60,
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 16, width: 500 }}>
        {bubbles.map((b, i) => {
          const prog = spring({ frame: frame - b.delay, fps, config: { damping: 12, mass: 0.5 } });
          const opacity = interpolate(frame, [b.delay, b.delay + 6], [0, 1], { extrapolateRight: "clamp" });
          const scale = interpolate(prog, [0, 1], [0.7, 1]);
          const y = interpolate(prog, [0, 1], [30, 0]);

          return (
            <div
              key={i}
              style={{
                alignSelf: b.side === "right" ? "flex-end" : "flex-start",
                opacity,
                transform: `translateY(${y}px) scale(${scale})`,
                transformOrigin: b.side === "right" ? "bottom right" : "bottom left",
              }}
            >
              <div
                style={{
                  background: b.color,
                  color: b.textColor || "white",
                  padding: "14px 22px",
                  borderRadius: 20,
                  borderBottomRightRadius: b.side === "right" ? 4 : 20,
                  borderBottomLeftRadius: b.side === "left" ? 4 : 20,
                  fontSize: 20,
                  fontWeight: 500,
                  maxWidth: 350,
                  boxShadow: "0 4px 20px rgba(0,0,0,0.2)",
                }}
              >
                {b.text}
              </div>
            </div>
          );
        })}

        {/* Typing indicator */}
        {frame >= 54 && (
          <div
            style={{
              alignSelf: "flex-start",
              opacity: interpolate(frame, [54, 60], [0, 1], { extrapolateRight: "clamp" }),
            }}
          >
            <div
              style={{
                background: "#f1f5f9",
                padding: "14px 22px",
                borderRadius: 20,
                borderBottomLeftRadius: 4,
                display: "flex",
                gap: 6,
                boxShadow: "0 4px 20px rgba(0,0,0,0.2)",
              }}
            >
              {[0, 1, 2].map((i) => (
                <div
                  key={i}
                  style={{
                    width: 10,
                    height: 10,
                    borderRadius: "50%",
                    background: "#6366f1",
                    opacity: dotPulse(i),
                  }}
                />
              ))}
            </div>
          </div>
        )}
      </div>
    </AbsoluteFill>
  );
};
