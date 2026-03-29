import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

const PRODUCT = "Support8";
const BRAND = "shortbreadapps";
const REG = "®";

export const LogoReveal = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const logoScale = spring({ frame, fps, config: { damping: 12, mass: 0.5 } });
  const logoOpacity = interpolate(frame, [0, 8], [0, 1], { extrapolateRight: "clamp" });

  const textProgress = spring({ frame: frame - 10, fps, config: { damping: 14, mass: 0.6 } });
  const textOpacity = interpolate(frame, [10, 18], [0, 1], { extrapolateRight: "clamp" });
  const textY = interpolate(textProgress, [0, 1], [30, 0]);

  const tagProgress = spring({ frame: frame - 30, fps, config: { damping: 16, mass: 0.5 } });
  const tagOpacity = interpolate(frame, [30, 40], [0, 1], { extrapolateRight: "clamp" });
  const tagY = interpolate(tagProgress, [0, 1], [20, 0]);

  const lineWidth = spring({ frame: frame - 20, fps, config: { damping: 18 } });

  const shimmerX = interpolate(frame, [40, 70], [-200, 600], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill
      style={{
        background: "linear-gradient(135deg, #0f0f23 0%, #1a1a3e 50%, #0f0f23 100%)",
        justifyContent: "center",
        alignItems: "center",
        fontFamily: "'SF Pro Display', -apple-system, BlinkMacSystemFont, sans-serif",
      }}
    >
      {/* Subtle grid pattern */}
      <AbsoluteFill style={{ opacity: 0.03 }}>
        <div
          style={{
            width: "100%",
            height: "100%",
            backgroundImage:
              "linear-gradient(rgba(255,255,255,.1) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.1) 1px, transparent 1px)",
            backgroundSize: "40px 40px",
          }}
        />
      </AbsoluteFill>

      {/* Glow behind logo */}
      <div
        style={{
          position: "absolute",
          width: 300,
          height: 300,
          borderRadius: "50%",
          background: "radial-gradient(circle, rgba(99,102,241,0.15) 0%, transparent 70%)",
          transform: `scale(${logoScale})`,
        }}
      />

      <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
        {/* Icon */}
        <div
          style={{
            opacity: logoOpacity,
            transform: `scale(${logoScale})`,
            marginBottom: 24,
          }}
        >
          <svg width="80" height="80" viewBox="0 0 80 80" fill="none">
            <rect
              x="4"
              y="4"
              width="72"
              height="72"
              rx="18"
              fill="url(#grad)"
              stroke="rgba(255,255,255,0.1)"
              strokeWidth="1"
            />
            <defs>
              <linearGradient id="grad" x1="0" y1="0" x2="80" y2="80">
                <stop offset="0%" stopColor="#6366f1" />
                <stop offset="100%" stopColor="#8b5cf6" />
              </linearGradient>
            </defs>
            {/* Chat bubble icon */}
            <path
              d="M24 28C24 25.8 25.8 24 28 24H52C54.2 24 56 25.8 56 28V44C56 46.2 54.2 48 52 48H36L28 54V48C25.8 48 24 46.2 24 44V28Z"
              fill="white"
              opacity="0.95"
            />
            <circle cx="34" cy="36" r="2.5" fill="#6366f1" />
            <circle cx="40" cy="36" r="2.5" fill="#6366f1" />
            <circle cx="46" cy="36" r="2.5" fill="#6366f1" />
          </svg>
        </div>

        {/* Brand name */}
        <div
          style={{
            opacity: textOpacity,
            transform: `translateY(${textY}px)`,
            display: "flex",
            alignItems: "flex-start",
            position: "relative",
            overflow: "hidden",
          }}
        >
          <span
            style={{
              fontSize: 56,
              fontWeight: 800,
              color: "white",
              letterSpacing: "-2px",
            }}
          >
            {PRODUCT}
          </span>

          {/* Shimmer effect */}
          <div
            style={{
              position: "absolute",
              top: 0,
              left: shimmerX,
              width: 60,
              height: "100%",
              background:
                "linear-gradient(90deg, transparent, rgba(255,255,255,0.15), transparent)",
              transform: "skewX(-15deg)",
            }}
          />
        </div>

        {/* Divider line */}
        <div
          style={{
            width: `${lineWidth * 200}px`,
            height: 2,
            background: "linear-gradient(90deg, transparent, #6366f1, transparent)",
            marginTop: 16,
            marginBottom: 16,
          }}
        />

        {/* Tagline */}
        <div
          style={{
            opacity: tagOpacity,
            transform: `translateY(${tagY}px)`,
            fontSize: 16,
            fontWeight: 500,
            color: "rgba(255,255,255,0.45)",
            letterSpacing: "2px",
          }}
        >
          by {BRAND}<span style={{ fontSize: 10, verticalAlign: "super" }}>{REG}</span>
        </div>
      </div>
    </AbsoluteFill>
  );
};
