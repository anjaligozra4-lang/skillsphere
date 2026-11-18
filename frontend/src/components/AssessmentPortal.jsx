import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import api from "../api";
import { useAuth } from "../AuthContext";
import { parseApiError } from "../utils/profileUtils";
import { FilesetResolver, FaceDetector } from "@mediapipe/tasks-vision";

function formatTimer(seconds) {
  const s = Math.max(0, Number(seconds) || 0);
  const mins = Math.floor(s / 60);
  const secs = s % 60;
  return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

export default function AssessmentPortal() {
  const { token: inviteToken } = useParams();
  const { token: authToken, role } = useAuth();
  const navigate = useNavigate();

  const [info, setInfo] = useState(null);
  const [questions, setQuestions] = useState([]);
  const [answers, setAnswers] = useState({});
  const [currentIndex, setCurrentIndex] = useState(0);
  const [remainingSeconds, setRemainingSeconds] = useState(null);
  const [phase, setPhase] = useState("loading"); // loading | verify | active | completed | error
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [saveNotice, setSaveNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [cameraReady, setCameraReady] = useState(false);
  const [cameraError, setCameraError] = useState("");
  const [proctoringWarning, setProctoringWarning] = useState("");
  const [microphoneLevel, setMicrophoneLevel] = useState(0);
  const [recordingConsent, setRecordingConsent] = useState(false);
  const [recordingStatus, setRecordingStatus] = useState("not_started");
  const [isResuming, setIsResuming] = useState(false);

  const videoRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const recordingChunksRef = useRef([]);
  const recordingSegmentsRef = useRef([]);
  const recordingStartedAtRef = useRef(null);
  const recordingStopHandledRef = useRef(false);
  const intentionalStopRef = useRef(false);
  const streamRef = useRef(null);
  const detectorRef = useRef(null);
  const cameraTrackRef = useRef(null);
  const audioContextRef = useRef(null);
  const microphoneMeterFrameRef = useRef(null);
  const proctoringEventRef = useRef(null);
  const faceMissingSinceRef = useRef(null);
  const faceMissingAlertedRef = useRef(false);
  const multipleFacesAlertedRef = useRef(false);
  const fullscreenWasActiveRef = useRef(false);
  const autoSubmitFiredRef = useRef(false);
  const answersRef = useRef(answers);
  answersRef.current = answers;
  const phaseRef = useRef(phase);
  phaseRef.current = phase;

  const stopCamera = useCallback(() => {
    if (microphoneMeterFrameRef.current != null) {
      window.cancelAnimationFrame(microphoneMeterFrameRef.current);
      microphoneMeterFrameRef.current = null;
    }
    if (audioContextRef.current) {
      audioContextRef.current.close().catch(() => {});
      audioContextRef.current = null;
    }
    setMicrophoneLevel(0);
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
    cameraTrackRef.current = null;
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    setCameraReady(false);
  }, []);

  const recordProctoringEvent = useCallback(async (eventType, details = {}) => {
    const warningMessages = {
      window_blur: "Please keep focus on the assessment window. Switching windows or applications has been recorded.",
      tab_switch: "Please return to the assessment. Leaving this tab has been recorded.",
      fullscreen_exit: "Please return to full screen. Exiting full screen has been recorded.",
      camera_missing: "Camera access is unavailable. Reconnect your camera to continue.",
      camera_disconnected: "Your camera disconnected. Reconnect it to continue the assessment.",
      microphone_disconnected: "Your microphone disconnected. Reconnect it to continue the assessment.",
      recording_error: "Webcam recording encountered an error. Proctoring has recorded this event.",
      recording_stopped: "Video recording stopped unexpectedly. Attempting to restore recording...",
      network_offline: "Network connection lost. Please do not close this window. Your answers are saved locally.",
      face_not_detected: "Keep your face visible in the camera during the assessment.",
      multiple_faces_detected: "Only the candidate should be visible in the camera frame.",
    };
    if (warningMessages[eventType]) setProctoringWarning(warningMessages[eventType]);
    try {
      await api.post(`/api/assessments/${inviteToken}/proctoring-events`, {
        event_type: eventType,
        details,
      });
    } catch (eventError) {
      console.warn("Unable to record proctoring event:", eventError);
    }
  }, [inviteToken]);

  proctoringEventRef.current = recordProctoringEvent;

  const initializeCamera = useCallback(async () => {
    setCameraError("");
    setCameraReady(false);

    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error("Camera access is unavailable. Please use HTTPS or localhost in a supported browser.");
      }

      stopCamera();

      if (detectorRef.current) {
        detectorRef.current.close();
        detectorRef.current = null;
      }

      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user" },
        audio: { echoCancellation: true, noiseSuppression: true },
      });

      streamRef.current = stream;
      const track = stream.getVideoTracks()[0];
      cameraTrackRef.current = track;

      track.addEventListener("ended", () => {
        setCameraReady(false);
        setCameraError("Camera disconnected. Reconnect your camera and try again.");
        if (proctoringEventRef.current) {
          proctoringEventRef.current("camera_disconnected");
        }
      });

      const audioTrack = stream.getAudioTracks()[0];
      audioTrack.addEventListener("ended", () => {
        setCameraReady(false);
        setCameraError("Microphone disconnected. Reconnect your microphone and try again.");
        if (proctoringEventRef.current) {
          proctoringEventRef.current("microphone_disconnected");
        }
      });

      const audioContext = new window.AudioContext();
      audioContextRef.current = audioContext;
      await audioContext.resume();
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 256;
      audioContext.createMediaStreamSource(stream).connect(analyser);
      const audioSamples = new Uint8Array(analyser.fftSize);
      const updateMicrophoneLevel = () => {
        analyser.getByteTimeDomainData(audioSamples);
        let power = 0;
        for (const sample of audioSamples) {
          const centered = (sample - 128) / 128;
          power += centered * centered;
        }
        setMicrophoneLevel(Math.min(100, Math.round(Math.sqrt(power / audioSamples.length) * 300)));
        microphoneMeterFrameRef.current = window.requestAnimationFrame(updateMicrophoneLevel);
      };
      updateMicrophoneLevel();

      if (!videoRef.current) {
        throw new Error("Camera preview could not be initialized. Please try again.");
      }

      videoRef.current.srcObject = stream;
      await videoRef.current.play();

      const vision = await FilesetResolver.forVisionTasks("/wasm");
      let detector;
      try {
        detector = await FaceDetector.createFromOptions(vision, {
          baseOptions: {
            modelAssetPath: "/models/blaze_face_short_range.tflite",
            delegate: "GPU",
          },
          runningMode: "VIDEO",
        });
      } catch {
        detector = await FaceDetector.createFromOptions(vision, {
          baseOptions: {
            modelAssetPath: "/models/blaze_face_short_range.tflite",
            delegate: "CPU",
          },
          runningMode: "VIDEO",
        });
      }

      detectorRef.current = detector;
      setCameraReady(true);
      return true;
    } catch (cameraFailure) {
      stopCamera();
      let errorMsg = cameraFailure?.message || "Unable to access the camera.";
      if (cameraFailure?.name === "NotAllowedError" || cameraFailure?.name === "PermissionDeniedError") {
        errorMsg = "Camera and microphone permission denied. Please allow permission by clicking the lock or camera icon in your address bar, enable Camera and Microphone, and click 'Retry Permission Check'.";
      } else if (cameraFailure?.name === "NotFoundError" || cameraFailure?.name === "DevicesNotFoundError") {
        errorMsg = "No webcam or microphone was detected. Please connect a working camera and microphone to take this proctored assessment.";
      }
      setCameraError(errorMsg);
      return false;
    }
  }, [stopCamera]);

  const startVideoRecording = useCallback(() => {
    const sourceStream = streamRef.current;
    if (!sourceStream?.getVideoTracks().length || !sourceStream?.getAudioTracks().length) {
      throw new Error("Camera and microphone streams are required for recording.");
    }

    const mimeCandidates = [
      "video/webm;codecs=vp8,opus",
      "video/webm;codecs=vp9,opus",
      "video/webm",
      "video/mp4;codecs=avc1,mp4a.40.2",
      "video/mp4",
    ];
    const mimeType = mimeCandidates.find((type) => MediaRecorder.isTypeSupported(type));

    if (!mimeType) {
      throw new Error("Your browser does not support a compatible video recording format.");
    }

    recordingChunksRef.current = [];
    recordingStopHandledRef.current = false;
    const recorder = new MediaRecorder(sourceStream, { mimeType });
    mediaRecorderRef.current = recorder;

    recorder.ondataavailable = (event) => {
      if (event.data?.size > 0) {
        recordingChunksRef.current.push(event.data);
      }
    };

    recorder.onerror = (e) => {
      setRecordingStatus("error");
      setProctoringWarning("Webcam video recording encountered an error. Proctoring has noted this event.");
      proctoringEventRef.current?.("recording_error", { error: e?.message || "MediaRecorder error" });
    };

    recorder.addEventListener("stop", () => {
      if (!intentionalStopRef.current && !recordingStopHandledRef.current && phaseRef.current === "active") {
        setProctoringWarning("Video recording stopped unexpectedly. Attempting to resume...");
        proctoringEventRef.current?.("recording_stopped");
        try {
          if (streamRef.current?.active) {
            startVideoRecording();
          }
        } catch (restartErr) {
          console.warn("Could not restart recording:", restartErr);
        }
      }
      recordingStopHandledRef.current = true;
      const mime = recorder.mimeType || "video/webm";
      const blob = new Blob(recordingChunksRef.current, { type: mime });
      const duration = recordingStartedAtRef.current
        ? Math.max(1, Math.round((Date.now() - recordingStartedAtRef.current) / 1000))
        : 0;

      if (blob.size > 0) {
        recordingSegmentsRef.current.push({
          blob,
          mimeType: mime,
          durationSeconds: duration,
        });
      }

      recordingChunksRef.current = [];
      recordingStartedAtRef.current = null;
    }, { once: true });

    intentionalStopRef.current = false;
    recorder.start(1000);
    recordingStartedAtRef.current = Date.now();
    setRecordingStatus("recording");
  }, []);
  const startOrResume = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const response = await api.post(`/api/assessments/${inviteToken}/start`);
      const data = response.data;
      startVideoRecording();
      let localSaved = {};
      try {
        const stored = localStorage.getItem(`skillsphere_answers_${inviteToken}`);
        if (stored) localSaved = JSON.parse(stored);
      } catch {
        // ignore
      }
      const initialAnswers = { ...localSaved };
      (data.questions || []).forEach((q) => {
        if (q.selected_option_index != null) {
          initialAnswers[q.id] = q.selected_option_index;
        }
      });
      setQuestions(data.questions || []);
      setAnswers(initialAnswers);
      setRemainingSeconds(data.remaining_seconds ?? data.duration_minutes * 60);
      setCurrentIndex(0);
      autoSubmitFiredRef.current = false;
      setPhase("active");
    } catch (requestError) {
      const msg = await parseApiError(requestError, "Unable to start assessment.");
      if (requestError?.response?.status === 409) {
        try {
          const check = await api.get(`/api/assessments/${inviteToken}`);
          if (check.data?.result) {
            setResult(check.data.result);
            setInfo(check.data);
            setPhase("completed");
            if (detectorRef.current) {
              detectorRef.current.close();
              detectorRef.current = null;
            }
            stopCamera();
            if (document.fullscreenElement) {
              document.exitFullscreen().catch(() => {});
            }
            return;
          }
        } catch {
          // ignore secondary check failure
        }
      }
      setError(msg);
      setPhase("error");
      if (detectorRef.current) {
        detectorRef.current.close();
        detectorRef.current = null;
      }
      stopCamera();
      if (document.fullscreenElement) {
        document.exitFullscreen().catch(() => {});
      }
    } finally {
      setBusy(false);
    }
  }, [inviteToken, stopCamera, startVideoRecording]);

  const loadInvitation = useCallback(async () => {
    setPhase("loading");
    setError("");
    try {
      const response = await api.get(`/api/assessments/${inviteToken}`);
      const data = response.data;
      if (data.assessment_type === "video") {
        navigate(`/video-assessment/${inviteToken}`, { replace: true });
        return;
      }
      setInfo(data);
      const status = data.test_status || data.assessment_status;
      if (status === "submitted" && data.result) {
        setResult(data.result);
        setPhase("completed");
        return;
      }
      if (status === "expired" || data.invitation_status === "expired") {
        setError("This assessment invitation link has expired.");
        setPhase("error");
        return;
      }
      if (status === "submitted") {
        setError("This assessment has already been submitted. Retakes are not allowed.");
        setPhase("error");
        return;
      }
      if (status === "started" && !data.requires_auth) {
        setIsResuming(true);
      }
      setPhase("verify");
    } catch (requestError) {
      setError(await parseApiError(requestError, "Invalid or unavailable assessment link."));
      setPhase("error");
    }
  }, [inviteToken, navigate]);

  useEffect(() => {
    loadInvitation();
  }, [loadInvitation, authToken]);

  useEffect(() => {
    if (phase !== "active" || !cameraReady || !detectorRef.current || !videoRef.current) {
      return undefined;
    }

    let animationFrame;
    let stopped = false;

    const detectFaces = () => {
      if (stopped) return;

      const video = videoRef.current;
      const detector = detectorRef.current;

      if (video && detector && video.readyState >= 2) {
        try {
          const result = detector.detectForVideo(video, performance.now());
          const faceCount = result.detections?.length || 0;

          if (faceCount === 0) {
            if (faceMissingSinceRef.current == null) {
              faceMissingSinceRef.current = Date.now();
            } else if (
              Date.now() - faceMissingSinceRef.current >= 3000 &&
              !faceMissingAlertedRef.current
            ) {
              faceMissingAlertedRef.current = true;
              proctoringEventRef.current?.("face_not_detected");
            }
            multipleFacesAlertedRef.current = false;
          } else {
            faceMissingSinceRef.current = null;
            faceMissingAlertedRef.current = false;

            if (faceCount > 1 && !multipleFacesAlertedRef.current) {
              multipleFacesAlertedRef.current = true;
              proctoringEventRef.current?.("multiple_faces_detected", { face_count: faceCount });
            } else if (faceCount <= 1) {
              multipleFacesAlertedRef.current = false;
            }
          }
        } catch (detectionError) {
          console.warn("Face detection check failed:", detectionError);
        }
      }

      animationFrame = window.requestAnimationFrame(detectFaces);
    };

    animationFrame = window.requestAnimationFrame(detectFaces);

    return () => {
      stopped = true;
      window.cancelAnimationFrame(animationFrame);
      faceMissingSinceRef.current = null;
      faceMissingAlertedRef.current = false;
      multipleFacesAlertedRef.current = false;
    };
  }, [phase, cameraReady]);

  useEffect(() => {
    const handleOnline = () => {
      setProctoringWarning("");
      setSaveNotice("Network connection restored.");
    };

    const handleOffline = () => {
      setProctoringWarning("Network connection lost. Please do not close or reload this page. Your answers are saved locally and will synchronize once connection returns.");
      proctoringEventRef.current?.("network_offline");
    };

    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);

    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  useEffect(() => {
    if (phase !== "active") return undefined;

    const handleVisibilityChange = () => {
      if (document.visibilityState === "hidden") {
        proctoringEventRef.current?.("tab_switch");
      }
    };

    const handleWindowBlur = () => {
      proctoringEventRef.current?.("window_blur");
    };

    const handleFullscreenChange = () => {
      const isFullscreen = Boolean(document.fullscreenElement);

      if (fullscreenWasActiveRef.current && !isFullscreen) {
        proctoringEventRef.current?.("fullscreen_exit");
      }

      fullscreenWasActiveRef.current = isFullscreen;
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);
    window.addEventListener("blur", handleWindowBlur);
    document.addEventListener("fullscreenchange", handleFullscreenChange);

    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("blur", handleWindowBlur);
      document.removeEventListener("fullscreenchange", handleFullscreenChange);
      fullscreenWasActiveRef.current = false;
    };
  }, [phase]);

  useEffect(() => () => {
    if (detectorRef.current) {
      detectorRef.current.close();
      detectorRef.current = null;
    }
    stopCamera();
  }, [stopCamera]);

  const stopRecordingAndUpload = useCallback(async () => {
    intentionalStopRef.current = true;
    const recorder = mediaRecorderRef.current;

    if (recorder && !recordingStopHandledRef.current) {
      await new Promise((resolve) => {
        recorder.addEventListener("stop", resolve, { once: true });

        if (recorder.state !== "inactive") {
          try {
            recorder.stop();
          } catch (stopError) {
            console.error("Unable to stop assessment recording:", stopError);
            resolve();
          }
        }
      });
    }

    mediaRecorderRef.current = null;

    if (!recordingSegmentsRef.current.length) {
      if (recordingStatus !== "uploaded") {
        setRecordingStatus("failed");
      }
      return recordingStatus === "uploaded";
    }

    setRecordingStatus("uploading");

    while (recordingSegmentsRef.current.length > 0) {
      const segment = recordingSegmentsRef.current[0];

      try {
        const extension = segment.mimeType.includes("mp4") ? "mp4" : "webm";
        const formData = new FormData();

        formData.append("file", segment.blob, `assessment-recording.${extension}`);
        formData.append("consent_given", "true");
        formData.append("duration_seconds", String(segment.durationSeconds));

        await api.post(`/api/assessments/${inviteToken}/recording`, formData);
        recordingSegmentsRef.current.shift();
      } catch (uploadError) {
        console.error("Assessment recording upload failed:", uploadError);
        setRecordingStatus("failed");
        setError("Assessment recording could not be uploaded. Your answers will still be submitted.");
        return false;
      }
    }

    setRecordingStatus("uploaded");
    return true;
  }, [inviteToken, recordingStatus]);
  const submitAssessment = useCallback(async (autoSubmitted = false) => {
    if (!autoSubmitted) {
      const answeredCount = Object.keys(answersRef.current).length;
      const msg = answeredCount < questions.length
        ? `You have answered ${answeredCount} of ${questions.length} questions. Submit assessment now?`
        : "Submit your assessment answers now? You cannot edit answers or retake the test after submission.";
      if (!window.confirm(msg)) return;
    }
    setBusy(true);
    setError("");
    try {
            await stopRecordingAndUpload();
const response = await api.post(`/api/assessments/${inviteToken}/submit`, {
        answers: answersRef.current,
        auto_submitted: autoSubmitted,
      });
      setResult(response.data);
      setPhase("completed");
      try {
        localStorage.removeItem(`skillsphere_answers_${inviteToken}`);
      } catch {
        // ignore
      }

      if (detectorRef.current) {
        detectorRef.current.close();
        detectorRef.current = null;
      }
      stopCamera();

      if (document.fullscreenElement) {
        document.exitFullscreen().catch(() => {});
      }
    } catch (requestError) {
      setError(await parseApiError(requestError, "Unable to submit assessment."));
    } finally {
      setBusy(false);
    }
  }, [inviteToken, questions.length, stopCamera, stopRecordingAndUpload]);

  useEffect(() => {
    if (phase !== "active" || remainingSeconds == null) return undefined;
    const interval = window.setInterval(() => {
      setRemainingSeconds((prev) => {
        if (prev == null) return null;
        if (prev <= 1) {
          if (!autoSubmitFiredRef.current) {
            autoSubmitFiredRef.current = true;
            submitAssessment(true);
          }
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => window.clearInterval(interval);
  }, [phase, remainingSeconds, submitAssessment]);

  const handleSelectOption = async (questionId, optionIndex) => {
    setAnswers((prev) => {
      const next = { ...prev, [questionId]: optionIndex };
      try {
        localStorage.setItem(`skillsphere_answers_${inviteToken}`, JSON.stringify(next));
      } catch {
        // ignore
      }
      return next;
    });
    setSaveNotice("Saving...");
    try {
      await api.put(`/api/assessments/${inviteToken}/answer`, {
        question_id: questionId,
        selected_option_index: optionIndex,
      });
      setSaveNotice("Answer saved");
    } catch (requestError) {
      const msg = await parseApiError(requestError, "Unable to save answer to server. Preserved locally.");
      setSaveNotice("Saved locally");
      setError(msg);
      if (requestError?.response?.status === 409) {
        loadInvitation();
      }
    }
  };

  const handleStartClick = async () => {
    if (!recordingConsent) {
      setError("Please consent to webcam video and microphone audio recording before starting.");
      return;
    }
    if (typeof MediaRecorder === "undefined") {
      setError("Your browser does not support webcam recording. Please use an updated browser.");
      return;
    }
    if (!authToken) {
      navigate(`/login?next=${encodeURIComponent(`/assessment/${inviteToken}`)}`);
      return;
    }
    if (role !== "candidate") {
      setError("Please sign in with the invited candidate account to take this assessment.");
      return;
    }
    if (!window.confirm(`${isResuming ? "Resume" : "Start"} the ${info?.duration_minutes || 30}-minute assessment now? The countdown will continue immediately.`)) {
      return;
    }

    setBusy(true);
    setError("");

    const cameraStarted = cameraReady || (await initializeCamera());
    if (!cameraStarted) {
      setBusy(false);
      return;
    }

    try {
      if (document.documentElement.requestFullscreen) {
        await document.documentElement.requestFullscreen();
      }
    } catch {
      // Fullscreen is recommended but not required by the browser.
    }

    fullscreenWasActiveRef.current = Boolean(document.fullscreenElement);
    setBusy(false);
    await startOrResume();
  };

  const currentQuestion = questions[currentIndex];
  const answeredCount = Object.keys(answers).length;

  return (
    <main className="page-content assessment-portal">
      {(phase === "verify" || phase === "active") && (
        <div className="panel proctoring-panel" style={{ marginBottom: "16px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "12px", flexWrap: "wrap" }}>
            <div>
              <strong>Webcam &amp; Audio Proctoring</strong>
              <p className="small-meta">Video and audio monitoring is active during this assessment to maintain testing integrity.</p>
            </div>
            <div className="card-actions">
              <span className={`role-pill ${cameraReady ? "status-badge-success" : ""}`}>
                {cameraReady ? "Camera Active" : "Camera Not Started"}
              </span>
              <span className={`role-pill ${streamRef.current?.getAudioTracks().some((track) => track.readyState === "live") ? "status-badge-success" : ""}`}>
                {streamRef.current?.getAudioTracks().some((track) => track.readyState === "live") ? "Microphone Active" : "Microphone Not Started"}
              </span>
            </div>
          </div>

          <video
            ref={videoRef}
            autoPlay
            muted
            playsInline
            style={{
              display: cameraReady ? "block" : "none",
              width: "min(100%, 320px)",
              aspectRatio: "4 / 3",
              objectFit: "cover",
              borderRadius: "12px",
              background: "#111",
              marginTop: "12px",
              border: "2px solid var(--accent, #3b82f6)",
            }}
          />

          {cameraError && (
            <div className="proctoring-candidate-warning" role="alert" style={{ background: "#fef2f2", borderColor: "#f87171", color: "#991b1b", marginTop: "12px", padding: "12px 16px", borderRadius: "8px", border: "1px solid" }}>
              <strong>Camera / Microphone Access Warning:</strong> {cameraError}
              <div style={{ marginTop: "10px" }}>
                <button
                  type="button"
                  className="button button-small"
                  onClick={initializeCamera}
                  disabled={busy}
                >
                  {busy ? "Checking Permissions..." : "Retry Camera & Mic Access"}
                </button>
              </div>
            </div>
          )}

          {phase === "verify" && !cameraReady && !cameraError && (
            <div style={{ marginTop: "12px" }}>
              <button
                type="button"
                className="button button-small button-secondary"
                disabled={busy}
                onClick={initializeCamera}
              >
                {busy ? "Checking..." : "Pre-Check Camera & Microphone"}
              </button>
              <span className="small-meta" style={{ marginLeft: "10px" }}>
                Verify your webcam preview and microphone before starting the timed assessment.
              </span>
            </div>
          )}

          {phase === "active" && !cameraReady && (
            <div style={{ marginTop: "12px" }}>
              <button
                type="button"
                className="button button-small btn-primary"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    await stopRecordingAndUpload();
                    const reconnected = await initializeCamera();

                    if (!reconnected) {
                      await recordProctoringEvent("camera_missing", { reason: "reconnect_failed" });
                    } else if (phaseRef.current === "active" && recordingConsent) {
                      startVideoRecording();
                    }
                  } catch (reconnectError) {
                    setCameraError(reconnectError?.message || "Camera reconnect failed.");
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                {busy ? "Reconnecting..." : "Reconnect Camera"}
              </button>
            </div>
          )}

          <p className="small-meta" style={{ marginTop: "10px" }}>
            Webcam video and microphone audio are recorded and reviewed by authorized recruitment staff. Face presence and tab focus are monitored in real time.
          </p>

          {cameraReady && (
            <label className="small-meta" style={{ display: "flex", alignItems: "center", gap: "10px", marginTop: "8px" }}>
              Microphone input preview
              <progress aria-label="Microphone input level" max="100" value={microphoneLevel} style={{ width: "160px" }} />
            </label>
          )}

          {phase === "active" && (
            <p className="small-meta" role="status">
              Recording status: {recordingStatus === "recording" ? "Recording in progress" : recordingStatus === "uploading" ? "Uploading recording..." : recordingStatus === "uploaded" ? "Recording uploaded" : recordingStatus === "failed" ? "Recording upload failed" : "Preparing recording"}
            </p>
          )}

          {phase === "active" && proctoringWarning && (
            <div className="proctoring-candidate-warning" role="alert" style={{ marginTop: "10px", padding: "10px 14px", borderRadius: "8px", border: "1px solid #f59e0b", background: "#fffbeb", color: "#b45309" }}>
              <strong>Proctoring Notice:</strong> {proctoringWarning}
              <div className="small-meta" style={{ marginTop: "4px" }}>Proctoring notices are logged for recruiter review and do not automatically disqualify you.</div>
            </div>
          )}
        </div>
      )}
      {phase === "loading" && <p className="loading-message" role="status">Verifying assessment invitation...</p>}

      {phase === "error" && (
        <section className="panel empty-state">
          <span className="eyebrow">Assessment Invitation</span>
          <h1>Unable to Open Assessment</h1>
          <p className="error">{error}</p>
          <div className="card-actions" style={{ justifyContent: "center", marginTop: "16px" }}>
            <Link className="button" to={authToken && role ? `/${role}` : "/login"}>
              {authToken && role ? "Return to Dashboard" : "Sign In"}
            </Link>
          </div>
        </section>
      )}

      {phase === "verify" && info && (
        <section className="panel assessment-intro-card">
          <span className="eyebrow">SkillSphere Online MCQ Assessment</span>
          <h1>{info.title}</h1>
          <p className="job-detail-company">{info.job_title} Â· {info.company_name}</p>
          {info.description && <p>{info.description}</p>}

          <div className="assessment-meta-grid">
            <div><span>Questions</span><strong>{info.total_questions} MCQs</strong></div>
            <div><span>Time Limit</span><strong>{info.duration_minutes} Minutes</strong></div>
            <div><span>Link Expires</span><strong>{info.expires_at ? new Date(info.expires_at).toLocaleString() : "â€”"}</strong></div>
          </div>

          <div className="subpanel" style={{ marginTop: "18px" }}>
            <h3>Assessment Instructions &amp; Proctoring Guidelines</h3>
            <ul style={{ paddingLeft: "20px", marginTop: "8px", lineHeight: "1.6" }}>
              <li><strong>Continuous Camera &amp; Mic Access:</strong> Keep your webcam video and microphone audio connected throughout the test.</li>
              <li><strong>Face In Frame:</strong> Sit upright directly facing your camera. Multiple faces or missing faces are automatically logged.</li>
              <li><strong>No Window or Tab Switching:</strong> Leaving this browser tab, switching windows, or exiting full screen triggers instant warnings and logs proctoring events.</li>
              <li><strong>Single Timed Attempt:</strong> Once started, the countdown timer cannot be paused. Your answers are auto-saved.</li>
            </ul>
            {info.instructions && (
              <div style={{ marginTop: "12px", paddingTop: "12px", borderTop: "1px solid var(--border-color, #e2e8f0)" }}>
                <h4>Recruiter Instructions</h4>
                <p className="multiline-text">{info.instructions}</p>
              </div>
            )}
          </div>

          {error && <p className="error">{error}</p>}

          {!info.requires_auth && (
            <label className="checkbox-label" style={{ display: "flex", alignItems: "flex-start", gap: "10px", marginTop: "16px" }}>
              <input
                type="checkbox"
                checked={recordingConsent}
                onChange={(event) => setRecordingConsent(event.target.checked)}
              />
              <span>I consent to webcam video and microphone audio being recorded during this assessment and reviewed by authorized recruitment staff.</span>
            </label>
          )}

          <div className="card-actions" style={{ marginTop: "20px" }}>
            {info.requires_auth ? (
              <button
                type="button"
                className="button"
                onClick={() => navigate(`/login?next=${encodeURIComponent(`/assessment/${inviteToken}`)}`)}
              >
                Sign In to Start Assessment
              </button>
            ) : (
              <button type="button" className="button" disabled={busy || !recordingConsent} onClick={handleStartClick}>
                {busy ? "Preparing Camera..." : isResuming ? "Resume Assessment" : "Start Assessment"}
              </button>
            )}
            <Link className="button button-secondary" to="/candidate">Candidate Dashboard</Link>
          </div>
        </section>
      )}

      {phase === "active" && currentQuestion && (
        <section className="assessment-active-layout">
          <div className="panel assessment-main-card">
            <div className="assessment-topbar">
              <div>
                <span className="eyebrow">{info?.job_title || "Technical Assessment"}</span>
                <h2>Question {currentIndex + 1} of {questions.length}</h2>
              </div>
              <div className="assessment-timer-box">
                <span className={remainingSeconds <= 180 ? "timer-warning" : ""}>
                  â± {formatTimer(remainingSeconds)}
                </span>
                <small>{saveNotice || `${answeredCount}/${questions.length} answered`}</small>
              </div>
            </div>

            <div className="question-tags">
              <span className="role-pill">{currentQuestion.skill}</span>
              <span className="role-pill">{currentQuestion.difficulty}</span>
            </div>

            <p className="assessment-question-text">{currentQuestion.question_text}</p>

            <div className="assessment-options" role="radiogroup" aria-label={`Question ${currentIndex + 1} options`}>
              {currentQuestion.options.map((opt, optIdx) => {
                const selected = answers[currentQuestion.id] === optIdx;
                return (
                  <button
                    key={optIdx}
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    className={`assessment-option-btn${selected ? " is-selected" : ""}`}
                    onClick={() => handleSelectOption(currentQuestion.id, optIdx)}
                  >
                    <span className="option-letter">{String.fromCharCode(65 + optIdx)}</span>
                    <span>{opt}</span>
                  </button>
                );
              })}
            </div>

            {error && <p className="error">{error}</p>}

            <div className="assessment-nav-actions">
              <button
                type="button"
                className="button button-secondary"
                disabled={currentIndex === 0}
                onClick={() => setCurrentIndex((idx) => Math.max(0, idx - 1))}
              >
                â† Previous
              </button>
              <div className="card-actions">
                {currentIndex < questions.length - 1 ? (
                  <button
                    type="button"
                    className="button"
                    onClick={() => setCurrentIndex((idx) => Math.min(questions.length - 1, idx + 1))}
                  >
                    Next Question â†’
                  </button>
                ) : null}
                <button
                  type="button"
                  className="button"
                  disabled={busy}
                  onClick={() => submitAssessment(false)}
                >
                  {busy ? "Submitting..." : "Submit Assessment"}
                </button>
              </div>
            </div>
          </div>

          <aside className="panel assessment-nav-sidebar">
            <h3>Question Navigator</h3>
            <p className="small-meta">
              Answered: <strong>{answeredCount}</strong> Â· Unanswered: <strong>{questions.length - answeredCount}</strong>
            </p>
            <div className="question-grid-nav">
              {questions.map((q, idx) => {
                const isAnswered = answers[q.id] != null;
                const isCurrent = idx === currentIndex;
                return (
                  <button
                    key={q.id}
                    type="button"
                    className={`q-nav-pill${isCurrent ? " is-current" : ""}${isAnswered ? " is-answered" : ""}`}
                    onClick={() => setCurrentIndex(idx)}
                  >
                    {idx + 1}
                  </button>
                );
              })}
            </div>
            <button
              type="button"
              className="button full-width"
              style={{ marginTop: "18px" }}
              disabled={busy}
              onClick={() => submitAssessment(false)}
            >
              {busy ? "Submitting..." : "Finish & Submit"}
            </button>
          </aside>
        </section>
      )}

      {phase === "completed" && result && (
        <section className="panel assessment-result-card">
          <span className="eyebrow">Assessment Submitted</span>
          <h1>Assessment Submitted</h1>
          <p className="success-banner" role="status">
            <strong>{result.message}</strong>
          </p>
          <div className="card-actions" style={{ marginTop: "20px" }}>
            <Link className="button" to="/candidate">Back to Candidate Dashboard</Link>
          </div>
        </section>
      )}
    </main>
  );
}

