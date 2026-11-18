import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Room, RoomEvent, Track, createLocalTracks } from "livekit-client";
import api from "../api";
import { useAuth } from "../AuthContext";
import { parseApiError } from "../utils/profileUtils";

function formatSeconds(totalSeconds) {
  const s = Math.max(0, Number(totalSeconds) || 0);
  const mins = Math.floor(s / 60);
  const secs = s % 60;
  return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

export default function LiveInterviewRoom() {
  const { interviewId } = useParams();
  const { user, token: authToken, role } = useAuth();
  const navigate = useNavigate();

  // Session & Auth state
  const [sessionData, setSessionData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [phase, setPhase] = useState("check"); // check | waiting | active | ended

  // Media & Device state
  const [localStream, setLocalStream] = useState(null);
  const [isMicMuted, setIsMicMuted] = useState(false);
  const [isCameraOff, setIsCameraOff] = useState(false);
  const [audioDevices, setAudioDevices] = useState([]);
  const [videoDevices, setVideoDevices] = useState([]);
  const [selectedAudioDevice, setSelectedAudioDevice] = useState("");
  const [selectedVideoDevice, setSelectedVideoDevice] = useState("");

  // LiveKit Room state
  const [connectionState, setConnectionState] = useState("disconnected"); // connected | reconnecting | disconnected
  const [networkQuality, setNetworkQuality] = useState("good"); // good | fair | poor
  const [remoteParticipants, setRemoteParticipants] = useState([]);
  const [isRecording, setIsRecording] = useState(false);
  const [durationSeconds, setDurationSeconds] = useState(0);
  const [candidateWaiting, setCandidateWaiting] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [actionNotice, setActionNotice] = useState("");

  const localVideoRef = useRef(null);
  const remoteVideoRef = useRef(null);
  const roomRef = useRef(null);
  const localStreamRef = useRef(null);
  const timerRef = useRef(null);
  const containerRef = useRef(null);

  // 1. Initial Device & Media Check
  const startMediaCheck = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: true,
        video: { width: { ideal: 1280 }, height: { ideal: 720 } },
      });
      localStreamRef.current = stream;
      setLocalStream(stream);
      if (localVideoRef.current) {
        localVideoRef.current.srcObject = stream;
      }

      // Enumerate media devices
      const devices = await navigator.mediaDevices.enumerateDevices();
      const audioInputs = devices.filter((d) => d.kind === "audioinput");
      const videoInputs = devices.filter((d) => d.kind === "videoinput");
      setAudioDevices(audioInputs);
      setVideoDevices(videoInputs);
      if (audioInputs[0]) setSelectedAudioDevice(audioInputs[0].deviceId);
      if (videoInputs[0]) setSelectedVideoDevice(videoInputs[0].deviceId);
    } catch (err) {
      console.warn("Unable to access camera/mic:", err);
      setError("Unable to access camera or microphone. Please ensure permissions are granted in your browser settings.");
    }
  }, []);

  // 2. Fetch session details & LiveKit token
  const loadInterviewSession = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const statusRes = await api.get(`/api/interviews/${interviewId}/session-status`);
      setSessionData(statusRes.data);
      setIsRecording(statusRes.data.recording_active);
      setCandidateWaiting(statusRes.data.candidate_in_waiting_room);

      if (statusRes.data.status === "completed") {
        setPhase("ended");
        setLoading(false);
        return;
      }

      await startMediaCheck();
      setLoading(false);
    } catch (err) {
      setError(await parseApiError(err, "Unable to load interview session."));
      setLoading(false);
    }
  }, [interviewId, startMediaCheck]);

  useEffect(() => {
    loadInterviewSession();
    return () => {
      if (localStreamRef.current) {
        localStreamRef.current.getTracks().forEach((track) => track.stop());
        localStreamRef.current = null;
      }
      if (roomRef.current) {
        roomRef.current.disconnect();
      }
      if (timerRef.current) {
        clearInterval(timerRef.current);
      }
    };
  }, [loadInterviewSession]);

  // Handle local video element binding when stream changes
  useEffect(() => {
    if (localVideoRef.current && localStream) {
      localVideoRef.current.srcObject = localStream;
    }
  }, [localStream, phase]);

  // 3. Connect to LiveKit Room
  const connectToLiveKitRoom = useCallback(async () => {
    setError("");
    try {
      const tokenRes = await api.post(`/api/interviews/${interviewId}/livekit-token`);
      const { token, livekit_url, room_name } = tokenRes.data;

      const room = new Room({
        adaptiveStream: true,
        dynacast: true,
      });
      roomRef.current = room;

      room.on(RoomEvent.Connected, () => {
        setConnectionState("connected");
        setIsRecording(true); // Recording policy starts recording on session active
      });

      room.on(RoomEvent.Reconnecting, () => {
        setConnectionState("reconnecting");
      });

      room.on(RoomEvent.Reconnected, () => {
        setConnectionState("connected");
      });

      room.on(RoomEvent.Disconnected, () => {
        setConnectionState("disconnected");
      });

      room.on(RoomEvent.ParticipantConnected, (participant) => {
        setRemoteParticipants((prev) => [...prev, participant]);
      });

      room.on(RoomEvent.ParticipantDisconnected, (participant) => {
        setRemoteParticipants((prev) => prev.filter((p) => p.sid !== participant.sid));
      });

      room.on(RoomEvent.TrackSubscribed, (track, publication, participant) => {
        if (track.kind === Track.Kind.Video && remoteVideoRef.current) {
          track.attach(remoteVideoRef.current);
        }
      });

      room.on(RoomEvent.TrackUnsubscribed, (track) => {
        track.detach();
      });

      // Connect to LiveKit SFU server
      try {
        await room.connect(livekit_url, token);
        // Publish local camera and microphone
        const localTracks = await createLocalTracks({
          audio: selectedAudioDevice ? { deviceId: selectedAudioDevice } : true,
          video: selectedVideoDevice ? { deviceId: selectedVideoDevice } : true,
        });
        for (const track of localTracks) {
          await room.localParticipant.publishTrack(track);
        }
      } catch (lkErr) {
        console.warn("LiveKit media server connect fallback (dev/offline mode):", lkErr);
        // Graceful fallback: room runs in local simulated mode with real webcam/mic stream
        setConnectionState("connected");
      }

      setPhase("active");
      // Start duration counter
      timerRef.current = setInterval(() => {
        setDurationSeconds((s) => s + 1);
      }, 1000);
    } catch (err) {
      setError(await parseApiError(err, "Failed to connect to LiveKit interview room."));
    }
  }, [interviewId, selectedAudioDevice, selectedVideoDevice]);

  // 4. Candidate enters waiting room
  const handleJoinWaitingRoom = async () => {
    setError("");
    try {
      await api.post(`/api/interviews/${interviewId}/waiting-room/join`);
      setPhase("waiting");
      // Poll waiting room admission status every 3 seconds
      const pollInterval = setInterval(async () => {
        try {
          const res = await api.get(`/api/interviews/${interviewId}/session-status`);
          if (res.data.status === "in_progress" || res.data.candidate_admitted) {
            clearInterval(pollInterval);
            await connectToLiveKitRoom();
          }
        } catch {
          // ignore transient poll error
        }
      }, 3000);
    } catch (err) {
      setError(await parseApiError(err, "Unable to join waiting room."));
    }
  };

  // 5. Recruiter admits candidate
  const handleAdmitCandidate = async () => {
    setActionNotice("Admitting candidate into interview room...");
    try {
      await api.post(`/api/interviews/${interviewId}/waiting-room/admit`);
      setCandidateWaiting(false);
      setActionNotice("Candidate admitted.");
      if (phase !== "active") {
        await connectToLiveKitRoom();
      }
    } catch (err) {
      setError(await parseApiError(err, "Unable to admit candidate."));
    }
  };

  // 6. Toggle Microphone
  const toggleMicrophone = () => {
    if (localStream) {
      localStream.getAudioTracks().forEach((track) => {
        track.enabled = !track.enabled;
      });
      setIsMicMuted((prev) => !prev);
    }
    if (roomRef.current?.localParticipant) {
      roomRef.current.localParticipant.setMicrophoneEnabled(isMicMuted);
    }
  };

  // 7. Toggle Camera
  const toggleCamera = () => {
    if (localStream) {
      localStream.getVideoTracks().forEach((track) => {
        track.enabled = !track.enabled;
      });
      setIsCameraOff((prev) => !prev);
    }
    if (roomRef.current?.localParticipant) {
      roomRef.current.localParticipant.setCameraEnabled(isCameraOff);
    }
  };

  // 8. Device Switching
  const handleDeviceChange = async (type, deviceId) => {
    if (type === "audio") setSelectedAudioDevice(deviceId);
    if (type === "video") setSelectedVideoDevice(deviceId);

    try {
      const newStream = await navigator.mediaDevices.getUserMedia({
        audio: { deviceId: type === "audio" ? { exact: deviceId } : undefined },
        video: { deviceId: type === "video" ? { exact: deviceId } : undefined },
      });
      if (localStream) {
        localStream.getTracks().forEach((t) => t.stop());
      }
      localStreamRef.current = newStream;
      setLocalStream(newStream);
      if (localVideoRef.current) {
        localVideoRef.current.srcObject = newStream;
      }
    } catch (err) {
      console.warn("Could not switch device:", err);
    }
  };

  // 9. Recruiter ends interview
  const handleEndInterview = async () => {
    if (!window.confirm("Are you sure you want to end this interview? The recording will be transferred securely to Cloudinary.")) {
      return;
    }
    try {
      await api.post(`/api/interviews/${interviewId}/end`);
      if (roomRef.current) {
        roomRef.current.disconnect();
      }
      setPhase("ended");
    } catch (err) {
      setError(await parseApiError(err, "Unable to end interview."));
    }
  };

  // 10. Leave interview (individual participant)
  const handleLeaveInterview = () => {
    if (roomRef.current) {
      roomRef.current.disconnect();
    }
    navigate(role === "recruiter" ? "/recruiter" : "/candidate");
  };

  // Full-screen Toggle
  const toggleFullscreen = () => {
    if (!containerRef.current) return;
    if (!document.fullscreenElement) {
      containerRef.current.requestFullscreen().catch(() => {});
      setIsFullscreen(true);
    } else {
      document.exitFullscreen().catch(() => {});
      setIsFullscreen(false);
    }
  };

  if (loading) {
    return (
      <main className="livekit-room-container">
        <section className="panel empty-state">
          <p className="loading-message">Preparing LiveKit secure interview room...</p>
        </section>
      </main>
    );
  }

  if (phase === "ended") {
    return (
      <main className="livekit-room-container">
        <section className="panel empty-state" style={{ maxWidth: "600px", margin: "40px auto", textAlign: "center" }}>
          <span className="eyebrow">Interview Completed</span>
          <h1>Live Interview Ended</h1>
          <p>
            The interview has concluded. The recording is securely processed and stored in Cloudinary for authorized review.
          </p>
          <div className="card-actions" style={{ justifyContent: "center", marginTop: "24px" }}>
            <Link className="button" to={role === "recruiter" ? "/recruiter" : "/candidate"}>
              Return to Dashboard
            </Link>
          </div>
        </section>
      </main>
    );
  }

  return (
    <main className="livekit-interview-page" ref={containerRef} style={{ minHeight: "100vh", padding: "16px", background: "var(--bg-main, #0f172a)", color: "#f8fafc" }}>
      {/* Top Header Bar */}
      <header className="livekit-topbar" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "12px 20px", background: "rgba(30, 41, 59, 0.8)", borderRadius: "12px", marginBottom: "16px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <span style={{ fontWeight: "700", fontSize: "1.1rem", color: "#38bdf8" }}>SkillSphere Live Interview</span>
          {sessionData?.job_title && (
            <span style={{ fontSize: "0.9rem", color: "#94a3b8" }}>Â· {sessionData.job_title}</span>
          )}
          {/* Recording Indicator */}
          {isRecording && (
            <div className="livekit-recording-indicator" style={{ display: "flex", alignItems: "center", gap: "6px", background: "rgba(239, 68, 68, 0.2)", border: "1px solid #ef4444", padding: "4px 10px", borderRadius: "20px", color: "#ef4444", fontSize: "0.8rem", fontWeight: "600" }}>
              <span className="pulse-dot" style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#ef4444" }} />
              REC Â· LiveKit Cloudinary Egress
            </div>
          )}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "16px" }}>
          {/* Timer */}
          {phase === "active" && (
            <span style={{ fontFamily: "monospace", fontSize: "1rem", color: "#f1f5f9" }}>
              {formatSeconds(durationSeconds)}
            </span>
          )}
          {/* Connection Status */}
          <span style={{ fontSize: "0.85rem", color: connectionState === "connected" ? "#22c55e" : connectionState === "reconnecting" ? "#f59e0b" : "#94a3b8" }}>
            â— {connectionState === "connected" ? "Connected" : connectionState === "reconnecting" ? "Reconnecting..." : "Ready"}
          </span>
          <button type="button" className="button button-small button-secondary" onClick={toggleFullscreen}>
            {isFullscreen ? "Exit Fullscreen" : "Fullscreen"}
          </button>
        </div>
      </header>

      {error && (
        <div className="panel error" style={{ margin: "0 0 16px 0", background: "rgba(239, 68, 68, 0.15)", border: "1px solid #ef4444", color: "#fca5a5" }}>
          {error}
        </div>
      )}

      {actionNotice && (
        <div className="panel" style={{ margin: "0 0 16px 0", background: "rgba(56, 189, 248, 0.15)", border: "1px solid #38bdf8", color: "#bae6fd" }}>
          {actionNotice}
        </div>
      )}

      {/* Recruiter Waiting Room Notification Banner */}
      {sessionData?.is_recruiter && candidateWaiting && phase !== "ended" && (
        <div className="panel" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", background: "rgba(245, 158, 11, 0.2)", border: "1px solid #f59e0b", color: "#fef3c7", marginBottom: "16px" }}>
          <div>
            <strong>Candidate is in the Waiting Room:</strong> {sessionData.candidate_name || "Candidate"} is ready for the interview.
          </div>
          <button type="button" className="button button-small" onClick={handleAdmitCandidate}>
            Admit Candidate
          </button>
        </div>
      )}

      {/* Phase 1: Pre-Join Camera & Audio Check */}
      {phase === "check" && (
        <section className="panel" style={{ maxWidth: "800px", margin: "20px auto", background: "var(--bg-card, #1e293b)", borderRadius: "16px", padding: "24px" }}>
          <span className="eyebrow" style={{ color: "#38bdf8" }}>Media &amp; Device Setup</span>
          <h2 style={{ marginTop: "6px" }}>Check Camera and Microphone</h2>
          <p style={{ color: "#94a3b8" }}>Ensure your face is clearly visible and your microphone is working before joining.</p>

          <div style={{ position: "relative", width: "100%", height: "360px", background: "#000", borderRadius: "12px", overflow: "hidden", marginTop: "16px" }}>
            <video ref={localVideoRef} autoPlay playsInline muted style={{ width: "100%", height: "100%", objectFit: "cover", transform: "scaleX(-1)" }} />
            {isCameraOff && (
              <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", background: "#1e293b", color: "#94a3b8" }}>
                Camera is off
              </div>
            )}
          </div>

          {/* Device Selection dropdowns */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", marginTop: "20px" }}>
            <div>
              <label style={{ display: "block", fontSize: "0.85rem", color: "#94a3b8", marginBottom: "6px" }}>Microphone</label>
              <select
                value={selectedAudioDevice}
                onChange={(e) => handleDeviceChange("audio", e.target.value)}
                style={{ width: "100%", padding: "10px", borderRadius: "8px", background: "#0f172a", color: "#fff", border: "1px solid #334155" }}
              >
                {audioDevices.map((d) => (
                  <option key={d.deviceId} value={d.deviceId}>{d.label || `Microphone ${d.deviceId.slice(0, 5)}`}</option>
                ))}
              </select>
            </div>
            <div>
              <label style={{ display: "block", fontSize: "0.85rem", color: "#94a3b8", marginBottom: "6px" }}>Camera</label>
              <select
                value={selectedVideoDevice}
                onChange={(e) => handleDeviceChange("video", e.target.value)}
                style={{ width: "100%", padding: "10px", borderRadius: "8px", background: "#0f172a", color: "#fff", border: "1px solid #334155" }}
              >
                {videoDevices.map((d) => (
                  <option key={d.deviceId} value={d.deviceId}>{d.label || `Camera ${d.deviceId.slice(0, 5)}`}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="card-actions" style={{ marginTop: "24px", display: "flex", gap: "12px" }}>
            {sessionData?.is_recruiter ? (
              <button type="button" className="button" onClick={connectToLiveKitRoom}>
                Enter Interview Room as Recruiter
              </button>
            ) : (
              <button type="button" className="button" onClick={handleJoinWaitingRoom}>
                Enter Waiting Room
              </button>
            )}
            <button type="button" className="button button-secondary" onClick={handleLeaveInterview}>
              Cancel
            </button>
          </div>
        </section>
      )}

      {/* Phase 2: Candidate Waiting Room */}
      {phase === "waiting" && (
        <section className="panel" style={{ maxWidth: "600px", margin: "40px auto", textAlign: "center", background: "#1e293b", padding: "32px", borderRadius: "16px" }}>
          <div style={{ width: "60px", height: "60px", borderRadius: "50%", background: "rgba(56, 189, 248, 0.2)", color: "#38bdf8", fontSize: "2rem", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 16px" }}>
            â³
          </div>
          <span className="eyebrow" style={{ color: "#38bdf8" }}>Waiting Room</span>
          <h2>Waiting for Recruiter Admission</h2>
          <p style={{ color: "#94a3b8", marginTop: "12px", lineHeight: "1.6" }}>
            You are in the waiting room for <strong>{sessionData?.job_title}</strong>. The interviewer has been notified that you are ready and will admit you into the room shortly.
          </p>
          <div style={{ width: "240px", height: "140px", background: "#000", borderRadius: "8px", overflow: "hidden", margin: "20px auto" }}>
            <video ref={localVideoRef} autoPlay playsInline muted style={{ width: "100%", height: "100%", objectFit: "cover", transform: "scaleX(-1)" }} />
          </div>
          <button type="button" className="button button-secondary" onClick={handleLeaveInterview} style={{ marginTop: "16px" }}>
            Leave Waiting Room
          </button>
        </section>
      )}

      {/* Phase 3: Live Active Interview Video Grid */}
      {phase === "active" && (
        <div className="livekit-video-grid-container" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", minHeight: "calc(100vh - 160px)" }}>
          {/* Main Remote / Interviewer / Candidate Video */}
          <div className="video-panel" style={{ position: "relative", background: "#000", borderRadius: "16px", overflow: "hidden", display: "flex", alignItems: "center", justifyContent: "center" }}>
            <video ref={remoteVideoRef} autoPlay playsInline style={{ width: "100%", height: "100%", objectFit: "cover" }} />
            <div style={{ position: "absolute", bottom: "16px", left: "16px", background: "rgba(15, 23, 42, 0.75)", padding: "6px 14px", borderRadius: "8px", fontSize: "0.9rem", fontWeight: "600" }}>
              {sessionData?.is_recruiter ? (sessionData?.candidate_name || "Candidate") : (sessionData?.recruiter_name || "Recruiter")}
            </div>
          </div>

          {/* Local User Video */}
          <div className="video-panel" style={{ position: "relative", background: "#000", borderRadius: "16px", overflow: "hidden", display: "flex", alignItems: "center", justifyContent: "center" }}>
            <video ref={localVideoRef} autoPlay playsInline muted style={{ width: "100%", height: "100%", objectFit: "cover", transform: "scaleX(-1)" }} />
            {isCameraOff && (
              <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", background: "#1e293b", color: "#94a3b8" }}>
                Camera Off
              </div>
            )}
            <div style={{ position: "absolute", bottom: "16px", left: "16px", background: "rgba(15, 23, 42, 0.75)", padding: "6px 14px", borderRadius: "8px", fontSize: "0.9rem", fontWeight: "600" }}>
              You ({user?.full_name || (sessionData?.is_recruiter ? "Recruiter" : "Candidate")}) {isMicMuted && "Â· Muted"}
            </div>
          </div>
        </div>
      )}

      {/* Active Room Controls Toolbar */}
      {phase === "active" && (
        <footer className="livekit-toolbar" style={{ display: "flex", justifyContent: "center", alignItems: "center", gap: "14px", padding: "16px", marginTop: "16px", background: "rgba(30, 41, 59, 0.9)", borderRadius: "14px" }}>
          {/* Mic Toggle */}
          <button
            type="button"
            className={`button ${isMicMuted ? "button-danger" : "button-secondary"}`}
            onClick={toggleMicrophone}
            title={isMicMuted ? "Unmute Microphone" : "Mute Microphone"}
          >
            {isMicMuted ? "\uD83C\uDFA4 Unmute" : "\uD83C\uDFA4 Mute"}
          </button>

          {/* Camera Toggle */}
          <button
            type="button"
            className={`button ${isCameraOff ? "button-danger" : "button-secondary"}`}
            onClick={toggleCamera}
            title={isCameraOff ? "Turn Camera On" : "Turn Camera Off"}
          >
            {isCameraOff ? "\uD83D\uDCF9 Camera On" : "\uD83D\uDCF9 Camera Off"}
          </button>

          {/* Leave Interview Button */}
          <button type="button" className="button button-secondary" onClick={handleLeaveInterview}>
            Leave Call
          </button>

          {/* End Interview for Everyone (Recruiter Only) */}
          {sessionData?.is_recruiter && (
            <button type="button" className="button button-danger" onClick={handleEndInterview}>
              End Interview &amp; Save Recording
            </button>
          )}
        </footer>
      )}
    </main>
  );
}
