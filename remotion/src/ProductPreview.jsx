import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
  Sequence,
} from "remotion";

const BG = "linear-gradient(135deg, #0f0f23 0%, #1a1a3e 50%, #0f0f23 100%)";
const FONT = "'SF Pro Display', -apple-system, BlinkMacSystemFont, sans-serif";
const PRIMARY = "#6366f1";
const GRID_OPACITY = 0.03;

const Grid = () => (
  <AbsoluteFill style={{ opacity: GRID_OPACITY }}>
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
);

const FadeText = ({ children, style }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const prog = spring({ frame, fps, config: { damping: 14, mass: 0.6 } });
  const opacity = interpolate(frame, [0, 10], [0, 1], { extrapolateRight: "clamp" });
  const y = interpolate(prog, [0, 1], [40, 0]);

  return (
    <div style={{ opacity, transform: `translateY(${y}px)`, ...style }}>
      {children}
    </div>
  );
};

const SceneFadeOut = ({ children, durationInFrames }) => {
  const frame = useCurrentFrame();
  const fadeOut = interpolate(
    frame,
    [durationInFrames - 15, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );
  return <AbsoluteFill style={{ opacity: fadeOut }}>{children}</AbsoluteFill>;
};

// ── Scene 1: Logo reveal (0–4s = frames 0–120) ──
const SceneLogo = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const dur = 120;

  const iconScale = spring({ frame, fps, config: { damping: 12, mass: 0.5 } });
  const iconOp = interpolate(frame, [0, 10], [0, 1], { extrapolateRight: "clamp" });
  const nameOp = interpolate(frame, [15, 25], [0, 1], { extrapolateRight: "clamp" });
  const nameProg = spring({ frame: frame - 15, fps, config: { damping: 14, mass: 0.6 } });
  const nameY = interpolate(nameProg, [0, 1], [30, 0]);
  const lineW = spring({ frame: frame - 30, fps, config: { damping: 18 } });
  const byOp = interpolate(frame, [40, 52], [0, 1], { extrapolateRight: "clamp" });
  const byProg = spring({ frame: frame - 40, fps, config: { damping: 16, mass: 0.5 } });
  const byY = interpolate(byProg, [0, 1], [20, 0]);
  const shimmer = interpolate(frame, [55, 90], [-200, 700], { extrapolateRight: "clamp" });

  return (
    <SceneFadeOut durationInFrames={dur}>
      <AbsoluteFill style={{ background: BG, justifyContent: "center", alignItems: "center", fontFamily: FONT }}>
        <Grid />
        <div style={{ position: "absolute", width: 300, height: 300, borderRadius: "50%", background: "radial-gradient(circle, rgba(99,102,241,0.15) 0%, transparent 70%)", transform: `scale(${iconScale})` }} />
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
          <div style={{ opacity: iconOp, transform: `scale(${iconScale})`, marginBottom: 28 }}>
            <svg width="90" height="90" viewBox="0 0 80 80" fill="none">
              <rect x="4" y="4" width="72" height="72" rx="18" fill="url(#g1)" stroke="rgba(255,255,255,0.1)" strokeWidth="1" />
              <defs><linearGradient id="g1" x1="0" y1="0" x2="80" y2="80"><stop offset="0%" stopColor="#6366f1" /><stop offset="100%" stopColor="#8b5cf6" /></linearGradient></defs>
              <path d="M24 28C24 25.8 25.8 24 28 24H52C54.2 24 56 25.8 56 28V44C56 46.2 54.2 48 52 48H36L28 54V48C25.8 48 24 46.2 24 44V28Z" fill="white" opacity="0.95" />
              <circle cx="34" cy="36" r="2.5" fill="#6366f1" /><circle cx="40" cy="36" r="2.5" fill="#6366f1" /><circle cx="46" cy="36" r="2.5" fill="#6366f1" />
            </svg>
          </div>
          <div style={{ opacity: nameOp, transform: `translateY(${nameY}px)`, position: "relative", overflow: "hidden" }}>
            <span style={{ fontSize: 64, fontWeight: 800, color: "white", letterSpacing: "-2px" }}>Support8</span>
            <div style={{ position: "absolute", top: 0, left: shimmer, width: 80, height: "100%", background: "linear-gradient(90deg, transparent, rgba(255,255,255,0.12), transparent)", transform: "skewX(-15deg)" }} />
          </div>
          <div style={{ width: `${lineW * 220}px`, height: 2, background: "linear-gradient(90deg, transparent, #6366f1, transparent)", marginTop: 18, marginBottom: 18 }} />
          <div style={{ opacity: byOp, transform: `translateY(${byY}px)`, fontSize: 17, fontWeight: 500, color: "rgba(255,255,255,0.4)", letterSpacing: "2px" }}>
            by shortbreadapps<span style={{ fontSize: 10, verticalAlign: "super" }}>®</span>
          </div>
        </div>
      </AbsoluteFill>
    </SceneFadeOut>
  );
};

// ── Scene 2: Dashboard overview (4–8.5s = frames 120–255) ──
const SceneDashboard = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const dur = 135;

  const cardProg = (delay) => spring({ frame: frame - delay, fps, config: { damping: 14, mass: 0.5 } });

  const cards = [
    { label: "Active Chats", value: "12", delay: 15 },
    { label: "Avg Response", value: "< 2 min", delay: 25 },
    { label: "Team Online", value: "4 agents", delay: 35 },
  ];

  return (
    <SceneFadeOut durationInFrames={dur}>
      <AbsoluteFill style={{ background: BG, justifyContent: "center", alignItems: "center", fontFamily: FONT }}>
        <Grid />
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 40 }}>
          <FadeText style={{ textAlign: "center" }}>
            <div style={{ fontSize: 18, fontWeight: 600, color: PRIMARY, letterSpacing: "3px", textTransform: "uppercase", marginBottom: 12 }}>Your Dashboard</div>
            <div style={{ fontSize: 42, fontWeight: 800, color: "white", letterSpacing: "-1px" }}>Everything at a glance</div>
          </FadeText>
          <div style={{ display: "flex", gap: 24 }}>
            {cards.map((c, i) => {
              const p = cardProg(c.delay);
              const op = interpolate(frame, [c.delay, c.delay + 10], [0, 1], { extrapolateRight: "clamp" });
              const y = interpolate(p, [0, 1], [50, 0]);
              return (
                <div key={i} style={{ opacity: op, transform: `translateY(${y}px)`, background: "rgba(18,18,26,0.9)", border: "1px solid rgba(42,42,58,0.8)", borderRadius: 14, padding: "28px 36px", textAlign: "center", minWidth: 180 }}>
                  <div style={{ fontSize: 32, fontWeight: 800, color: "white", marginBottom: 6 }}>{c.value}</div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: "rgba(255,255,255,0.4)", textTransform: "uppercase", letterSpacing: "1px" }}>{c.label}</div>
                </div>
              );
            })}
          </div>
        </div>
      </AbsoluteFill>
    </SceneFadeOut>
  );
};

// ── Scene 3: Live chat demo (8.5–13.5s = frames 255–405) ──
const SceneChat = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const dur = 150;

  const msgs = [
    { delay: 10, text: "Hi, I'm having trouble with my order", side: "left", name: "Sarah M." },
    { delay: 40, text: "I can help with that right away. Let me pull up your account.", side: "right", name: "Alex (Agent)" },
    { delay: 75, text: "Found it. Your order shipped this morning -- tracking link sent to your email.", side: "right", name: "Alex (Agent)" },
    { delay: 110, text: "That was so fast, thank you!", side: "left", name: "Sarah M." },
  ];

  return (
    <SceneFadeOut durationInFrames={dur}>
      <AbsoluteFill style={{ background: BG, justifyContent: "center", alignItems: "center", fontFamily: FONT }}>
        <Grid />
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 30 }}>
          <FadeText style={{ textAlign: "center" }}>
            <div style={{ fontSize: 18, fontWeight: 600, color: PRIMARY, letterSpacing: "3px", textTransform: "uppercase", marginBottom: 12 }}>Real-Time Chat</div>
            <div style={{ fontSize: 42, fontWeight: 800, color: "white", letterSpacing: "-1px" }}>Conversations that flow</div>
          </FadeText>
          <div style={{ width: 520, display: "flex", flexDirection: "column", gap: 10 }}>
            {msgs.map((m, i) => {
              const p = spring({ frame: frame - m.delay, fps, config: { damping: 12, mass: 0.5 } });
              const op = interpolate(frame, [m.delay, m.delay + 8], [0, 1], { extrapolateRight: "clamp" });
              const scale = interpolate(p, [0, 1], [0.8, 1]);
              const y = interpolate(p, [0, 1], [20, 0]);
              const isAgent = m.side === "right";
              return (
                <div key={i} style={{ alignSelf: isAgent ? "flex-end" : "flex-start", opacity: op, transform: `translateY(${y}px) scale(${scale})`, transformOrigin: isAgent ? "bottom right" : "bottom left", maxWidth: 380 }}>
                  <div style={{ fontSize: 10, fontWeight: 600, color: "rgba(255,255,255,0.35)", marginBottom: 3, textAlign: isAgent ? "right" : "left" }}>{m.name}</div>
                  <div style={{ background: isAgent ? PRIMARY : "rgba(241,245,249,0.95)", color: isAgent ? "white" : "#1e293b", padding: "11px 18px", borderRadius: 16, borderBottomRightRadius: isAgent ? 4 : 16, borderBottomLeftRadius: isAgent ? 16 : 4, fontSize: 16, fontWeight: 500, boxShadow: "0 4px 16px rgba(0,0,0,0.15)" }}>
                    {m.text}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </AbsoluteFill>
    </SceneFadeOut>
  );
};

// ── Scene 4: Team & tickets (13.5–17.5s = frames 405–525) ──
const SceneTeam = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const dur = 120;

  const features = [
    { delay: 10, title: "Multi-Agent Support", desc: "Multiple team members on the same conversation" },
    { delay: 30, title: "Priority Tracking", desc: "Urgent, high, normal, and low priority levels" },
    { delay: 50, title: "4-Digit Ticket Codes", desc: "Customers look up their tickets instantly" },
    { delay: 70, title: "Employee Management", desc: "Add your team, track activity, manage access" },
  ];

  return (
    <SceneFadeOut durationInFrames={dur}>
      <AbsoluteFill style={{ background: BG, justifyContent: "center", alignItems: "center", fontFamily: FONT }}>
        <Grid />
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 36 }}>
          <FadeText style={{ textAlign: "center" }}>
            <div style={{ fontSize: 18, fontWeight: 600, color: PRIMARY, letterSpacing: "3px", textTransform: "uppercase", marginBottom: 12 }}>Built for Teams</div>
            <div style={{ fontSize: 42, fontWeight: 800, color: "white", letterSpacing: "-1px" }}>Everything you need</div>
          </FadeText>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, width: 580 }}>
            {features.map((f, i) => {
              const p = spring({ frame: frame - f.delay, fps, config: { damping: 14, mass: 0.5 } });
              const op = interpolate(frame, [f.delay, f.delay + 10], [0, 1], { extrapolateRight: "clamp" });
              const y = interpolate(p, [0, 1], [30, 0]);
              return (
                <div key={i} style={{ opacity: op, transform: `translateY(${y}px)`, background: "rgba(18,18,26,0.9)", border: "1px solid rgba(42,42,58,0.8)", borderRadius: 12, padding: "20px 22px" }}>
                  <div style={{ fontSize: 15, fontWeight: 700, color: "white", marginBottom: 4 }}>{f.title}</div>
                  <div style={{ fontSize: 12, color: "rgba(255,255,255,0.4)", lineHeight: 1.5 }}>{f.desc}</div>
                </div>
              );
            })}
          </div>
        </div>
      </AbsoluteFill>
    </SceneFadeOut>
  );
};

// ── Scene 5: CTA / closing (17.5–20s = frames 525–600) ──
const SceneCTA = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const prog = spring({ frame, fps, config: { damping: 12, mass: 0.5 } });
  const op = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });
  const y = interpolate(prog, [0, 1], [40, 0]);
  const btnOp = interpolate(frame, [25, 38], [0, 1], { extrapolateRight: "clamp" });
  const btnProg = spring({ frame: frame - 25, fps, config: { damping: 14, mass: 0.5 } });
  const btnScale = interpolate(btnProg, [0, 1], [0.8, 1]);
  const glow = interpolate(frame, [0, 75], [0.1, 0.25], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ background: BG, justifyContent: "center", alignItems: "center", fontFamily: FONT }}>
      <Grid />
      <div style={{ position: "absolute", width: 500, height: 500, borderRadius: "50%", background: `radial-gradient(circle, rgba(99,102,241,${glow}) 0%, transparent 70%)` }} />
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", opacity: op, transform: `translateY(${y}px)` }}>
        <div style={{ fontSize: 48, fontWeight: 800, color: "white", letterSpacing: "-1px", textAlign: "center", marginBottom: 12 }}>
          Ready to get started?
        </div>
        <div style={{ fontSize: 18, color: "rgba(255,255,255,0.5)", marginBottom: 32, textAlign: "center" }}>
          Support8 by shortbreadapps<span style={{ fontSize: 11, verticalAlign: "super" }}>®</span>
        </div>
        <div style={{ opacity: btnOp, transform: `scale(${btnScale})`, background: PRIMARY, padding: "16px 48px", borderRadius: 12, fontSize: 18, fontWeight: 700, color: "white", boxShadow: "0 8px 30px rgba(99,102,241,0.4)" }}>
          Get Started Free
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ── Main composition ──
export const ProductPreview = () => {
  return (
    <AbsoluteFill>
      <Sequence from={0} durationInFrames={120}><SceneLogo /></Sequence>
      <Sequence from={120} durationInFrames={135}><SceneDashboard /></Sequence>
      <Sequence from={255} durationInFrames={150}><SceneChat /></Sequence>
      <Sequence from={405} durationInFrames={120}><SceneTeam /></Sequence>
      <Sequence from={525} durationInFrames={75}><SceneCTA /></Sequence>
    </AbsoluteFill>
  );
};
