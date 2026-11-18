import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import api from "../api";
import { useAuth } from "../AuthContext";
import { parseApiError } from "../utils/profileUtils";

function formatSeconds(seconds) {
  const s = Math.max(0, Number(seconds) || 0);
  const mins = Math.floor(s / 60);
  const secs = s % 60;
  return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

export default function VideoAssessmentPortal() {
  const { token } = useParams();
  const { user, token: authToken, role } = useAuth();
  const navigate = useNavigate();

  const [assessmentInfo, setAssessmentInfo] = useState(null);
  const [questions, setQuestions] = useState([]);
  const [currentIdx, setCurrentIdx] = useState(0);
  const [phase, setPhase] = useState("loading"); // loading | intro | prep | recording | review | completed | error
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [uploadProgress, setUploadProgress] = useState("");

  // Media streams & recorders
  const [stream, setStream] = useState(null);
  const [cameraReady, setCameraReady] = useState(false);
  const [recordedBlobs, setRecordedBlobs] = useState({}); // question_id -> blob
  const [uploadedQuestionIds, setUploadedQuestionIds] = useState(new Set());
  const [currentReviewUrl, setCurrentReviewUrl] = useState("");

  // Timers
  const [prepSecondsLeft, setPrepSecondsLeft] = useState(30);
  const [responseSecondsLeft, setResponseSecondsLeft] = useState(120);

  const videoPreviewRef = useRef(null);
  const reviewVideoRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const chunksRef = useRef([]);
  const prepTimerRef = useRef(null);
  const responseTimerRef = useRef(null);
  const streamRef = useRef(null);

  const clearTimers = useCallback(() => {
    if (prepTimerRef.current) clearInterval(prepTimerRef.current);
    if (responseTimerRef.current) clearInterval(responseTimerRef.current);
    prepTimerRef.current = null;
    responseTimerRef.current = null;
  }, []);

  const stopCamera = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
    setStream(null);
    if (videoPreviewRef.current) {
      videoPreviewRef.current.srcObject = null;
    }
    setCameraReady(false);
  }, []);

  // 1. Load Assessment info & Existing Submissions
  const loadAssessment = useCallback(async () => {
    setPhase("loading");
    setError("");
    try {
        const infoRes = await api.get(`/api/assessments/${token}`);
        setAssessmentInfo(infoRes.data);

        if (infoRes.data.test_status === "submitted") {
          setPhase("completed");
          return;
        }

        // Fetch already recorded question responses for recovery / resilience
        try {
          const recRes = await api.get(`/api/assessments/${token}/recordings`);
          if (Array.isArray(recRes.data)) {
            const completedIds = new Set(
              recRes.data
                .filter((r) => r.upload_status === "completed" && r.question_id)
                .map((r) => r.question_id)
            );
            setUploadedQuestionIds(completedIds);
          }
        } catch {
          // ignore if no previous recordings
        }

        setPhase("intro");
    } catch (err) {
      setError(await parseApiError(err, "Unable to load video assessment."));
      setPhase("error");
    }
  }, [token]);

  useEffect(() => {
    loadAssessment();
    return () => {
      stopCamera();
      clearTimers();
    };
  }, [clearTimers, loadAssessment, stopCamera]);

  const startCamera = async () => {
    try {
      const s = await navigator.mediaDevices.getUserMedia({
        audio: true,
        video: { width: { ideal: 1280 }, height: { ideal: 720 } },
      });
      streamRef.current = s;
      setStream(s);
      setCameraReady(true);
      if (videoPreviewRef.current) {
        videoPreviewRef.current.srcObject = s;
      }
      return true;
    } catch (err) {
      setError("Unable to access camera and microphone. Please allow permissions to complete this video assessment.");
      return false;
    }
  };

  // 2. Start Assessment
  const handleStartAssessment = async () => {
    setBusy(true);
    setError("");
    const camOk = await startCamera();
    if (!camOk) {
      setBusy(false);
      return;
    }

    try {
      const startRes = await api.post(`/api/assessments/${token}/start`);
      const qList = startRes.data.questions || [];
      setQuestions(qList);

      // Find first unrecorded question
      const firstUnanswered = qList.findIndex((q) => !uploadedQuestionIds.has(q.id));
      const targetIdx = firstUnanswered !== -1 ? firstUnanswered : 0;
      setCurrentIdx(targetIdx);

      setBusy(false);
      startPrepForQuestion(qList[targetIdx]);
    } catch (err) {
      setError(await parseApiError(err, "Failed to start assessment."));
      setBusy(false);
    }
  };

  // 3. Prep Timer
  const startPrepForQuestion = (question) => {
    clearTimers();
    const prepDuration = question?.prep_time_seconds || assessmentInfo?.prep_time_seconds || 30;
    setPrepSecondsLeft(prepDuration);
    setPhase("prep");

    prepTimerRef.current = setInterval(() => {
      setPrepSecondsLeft((prev) => {
        if (prev <= 1) {
          clearInterval(prepTimerRef.current);
          startRecording(question);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
  };

  // 4. Start Recording Response
  const startRecording = (question) => {
    clearTimers();
    if (!stream) return;

    chunksRef.current = [];
    const mimeType = MediaRecorder.isTypeSupported("video/webm;codecs=vp9,opus")
      ? "video/webm;codecs=vp9,opus"
      : MediaRecorder.isTypeSupported("video/webm")
      ? "video/webm"
      : "video/mp4";

    const recorder = new MediaRecorder(stream, { mimeType });
    recorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) {
        chunksRef.current.push(e.data);
      }
    };

    recorder.onstop = () => {
      const blob = new Blob(chunksRef.current, { type: mimeType });
      const currentQ = question || questions[currentIdx];
      if (currentQ) {
        setRecordedBlobs((prev) => ({ ...prev, [currentQ.id]: blob }));
      }
      const reviewUrl = URL.createObjectURL(blob);
      setCurrentReviewUrl(reviewUrl);
      setPhase("review");
    };

    recorder.start(1000);
    mediaRecorderRef.current = recorder;

    const respDuration = question?.response_time_seconds || assessmentInfo?.response_time_seconds || 120;
    setResponseSecondsLeft(respDuration);
    setPhase("recording");

    responseTimerRef.current = setInterval(() => {
      setResponseSecondsLeft((prev) => {
        if (prev <= 1) {
          clearInterval(responseTimerRef.current);
          stopRecording();
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
  };

  // 5. Stop Recording Response
  const stopRecording = () => {
    clearTimers();
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
      mediaRecorderRef.current.stop();
    }
  };

  // 6. Upload Recording to Cloudinary
  const handleUploadAndNext = async () => {
    const currentQ = questions[currentIdx];
    const blob = recordedBlobs[currentQ.id];
    if (!blob) {
      setError("No recording found for this question. Please re-record.");
      return;
    }

    setBusy(true);
    setUploadProgress("Uploading your response securely to Cloudinary...");
    setError("");

    try {
      const ext = blob.type.includes("mp4") ? "mp4" : "webm";
      const formData = new FormData();
      formData.append("file", blob, `question_${currentQ.id}_response.${ext}`);
      formData.append("duration_seconds", String((currentQ.response_time_seconds || 120) - responseSecondsLeft));

      await api.post(`/api/assessments/${token}/questions/${currentQ.id}/recording`, formData);

      setUploadedQuestionIds((prev) => new Set([...prev, currentQ.id]));
      setUploadProgress("");
      setBusy(false);

      // Clean up review URL
      if (currentReviewUrl) {
        URL.revokeObjectURL(currentReviewUrl);
        setCurrentReviewUrl("");
      }

      // Check if there are more questions
      if (currentIdx + 1 < questions.length) {
        const nextIdx = currentIdx + 1;
        setCurrentIdx(nextIdx);
        startPrepForQuestion(questions[nextIdx]);
      } else {
        // All questions completed, submit assessment
        await handleFinalSubmit();
      }
    } catch (err) {
      setBusy(false);
      setUploadProgress("");
      setError(await parseApiError(err, "Failed to upload recording to Cloudinary. Please try again. Your recording is preserved locally."));
    }
  };

  // 7. Re-record question
  const handleReRecord = () => {
    if (currentReviewUrl) {
      URL.revokeObjectURL(currentReviewUrl);
      setCurrentReviewUrl("");
    }
    const currentQ = questions[currentIdx];
    startPrepForQuestion(currentQ);
  };

  // 8. Final Submit Assessment
  const handleFinalSubmit = async () => {
    setBusy(true);
    try {
      await api.post(`/api/assessments/${token}/submit`, {});
      stopCamera();
      setPhase("completed");
    } catch (err) {
      setError(await parseApiError(err, "Error submitting assessment."));
    } finally {
      setBusy(false);
    }
  };

  if (phase === "loading") {
    return (
      <main className="container" style={{ padding: "40px 16px", textAlign: "center" }}>
        <p className="loading-message">Loading video assessment...</p>
      </main>
    );
  }

  if (phase === "error") {
    return (
      <main className="container" style={{ maxWidth: "600px", margin: "40px auto" }}>
        <section className="panel empty-state">
          <span className="eyebrow">Video Assessment</span>
          <h1>Unable to Open Assessment</h1>
          <p className="error">{error}</p>
          <div className="card-actions" style={{ justifyContent: "center", marginTop: "16px" }}>
            <Link className="button" to={authToken && role ? `/${role}` : "/login"}>
              {authToken && role ? "Return to Dashboard" : "Sign In"}
            </Link>
          </div>
        </section>
      </main>
    );
  }

  if (phase === "completed") {
    return (
      <main className="container" style={{ maxWidth: "650px", margin: "40px auto" }}>
        <section className="panel" style={{ textAlign: "center", padding: "40px 24px" }}>
          <div style={{ width: "64px", height: "64px", borderRadius: "50%", background: "rgba(34, 197, 94, 0.2)", color: "#22c55e", fontSize: "2.5rem", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 16px" }}>
            âœ“
          </div>
          <span className="eyebrow" style={{ color: "#22c55e" }}>Assessment Submitted</span>
          <h2>Your assessment has been successfully submitted.</h2>
          <p style={{ marginTop: "16px", color: "var(--text-muted, #64748b)", lineHeight: "1.6" }}>
            Your responses have been recorded and are under review. Our recruitment team will notify you about the next steps.
          </p>
          <div className="card-actions" style={{ justifyContent: "center", marginTop: "24px" }}>
            <Link className="button" to="/candidate">
              Return to Candidate Dashboard
            </Link>
          </div>
        </section>
      </main>
    );
  }

  const currentQ = questions[currentIdx];

  return (
    <main className="container" style={{ maxWidth: "900px", margin: "24px auto", padding: "0 16px" }}>
      {/* Intro Phase */}
      {phase === "intro" && assessmentInfo && (
        <section className="panel">
          <span className="eyebrow">Asynchronous Video Assessment</span>
          <h1>{assessmentInfo.title}</h1>
          <p style={{ color: "var(--text-muted, #64748b)" }}>{assessmentInfo.job_title} Â· {assessmentInfo.company_name}</p>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "16px", margin: "20px 0", padding: "16px", background: "var(--bg-subtle, #f8fafc)", borderRadius: "10px" }}>
            <div><span style={{ fontSize: "0.85rem", color: "#64748b" }}>Questions</span><div><strong>{assessmentInfo.total_questions} Questions</strong></div></div>
            <div><span style={{ fontSize: "0.85rem", color: "#64748b" }}>Preparation Time</span><div><strong>{assessmentInfo.prep_time_seconds}s per question</strong></div></div>
            <div><span style={{ fontSize: "0.85rem", color: "#64748b" }}>Response Limit</span><div><strong>{assessmentInfo.response_time_seconds}s per question</strong></div></div>
            <div><span style={{ fontSize: "0.85rem", color: "#64748b" }}>Review Allowed</span><div><strong>{assessmentInfo.allow_review ? "Yes" : "No"}</strong></div></div>
          </div>

          <div className="subpanel" style={{ marginTop: "16px" }}>
            <h3>Instructions</h3>
            <p style={{ lineHeight: "1.6", marginTop: "8px" }}>{assessmentInfo.instructions}</p>
            <ul style={{ paddingLeft: "20px", marginTop: "12px", lineHeight: "1.6", color: "var(--text-muted, #64748b)" }}>
              <li>Ensure your webcam and microphone are working and you are in a quiet room.</li>
              <li>For each question, you will have a preparation countdown before recording begins.</li>
              <li>Responses are uploaded securely to Cloudinary immediately upon completion.</li>
              <li>Do not close or reload the browser during recording or uploads.</li>
            </ul>
          </div>

          {error && <p className="error" style={{ marginTop: "16px" }}>{error}</p>}

          <div className="card-actions" style={{ marginTop: "24px" }}>
            <button type="button" className="button" disabled={busy} onClick={handleStartAssessment}>
              {busy ? "Accessing Camera..." : "Start Video Assessment"}
            </button>
            <Link className="button button-secondary" to="/candidate">Back to Dashboard</Link>
          </div>
        </section>
      )}

      {/* Active Question Workflow (Prep, Recording, Review) */}
      {(phase === "prep" || phase === "recording" || phase === "review") && currentQ && (
        <section className="panel" style={{ padding: "24px" }}>
          {/* Top Status Tracker */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid var(--border-color, #e2e8f0)", paddingBottom: "16px", marginBottom: "20px" }}>
            <div>
              <span className="eyebrow">Question {currentIdx + 1} of {questions.length}</span>
              <h2 style={{ margin: "4px 0 0 0" }}>{currentQ.question_text}</h2>
              {currentQ.instructions && (
                <p style={{ color: "var(--text-muted, #64748b)", fontSize: "0.9rem", marginTop: "4px" }}>{currentQ.instructions}</p>
              )}
            </div>

            {/* Countdown Timers */}
            <div>
              {phase === "prep" && (
                <div style={{ textAlign: "right" }}>
                  <span style={{ fontSize: "0.8rem", color: "#f59e0b", fontWeight: "600", textTransform: "uppercase" }}>Preparation Countdown</span>
                  <div style={{ fontSize: "1.8rem", fontWeight: "700", color: "#f59e0b", fontFamily: "monospace" }}>
                    {formatSeconds(prepSecondsLeft)}
                  </div>
                </div>
              )}
              {phase === "recording" && (
                <div style={{ textAlign: "right" }}>
                  <span style={{ fontSize: "0.8rem", color: "#ef4444", fontWeight: "600", textTransform: "uppercase" }}>â—  Recording Response</span>
                  <div style={{ fontSize: "1.8rem", fontWeight: "700", color: "#ef4444", fontFamily: "monospace" }}>
                    {formatSeconds(responseSecondsLeft)}
                  </div>
                </div>
              )}
              {phase === "review" && (
                <div style={{ textAlign: "right" }}>
                  <span className="badge" style={{ background: "#22c55e", color: "#fff" }}>Recorded</span>
                </div>
              )}
            </div>
          </div>

          {/* Video Container */}
          <div style={{ position: "relative", width: "100%", height: "420px", background: "#000", borderRadius: "12px", overflow: "hidden" }}>
            {phase !== "review" ? (
              <video
                ref={videoPreviewRef}
                autoPlay
                playsInline
                muted
                style={{ width: "100%", height: "100%", objectFit: "cover", transform: "scaleX(-1)" }}
              />
            ) : (
              <video
                ref={reviewVideoRef}
                src={currentReviewUrl}
                controls
                autoPlay
                playsInline
                style={{ width: "100%", height: "100%", objectFit: "contain" }}
              />
            )}

            {/* Overlay Notice */}
            {phase === "prep" && (
              <div style={{ position: "absolute", top: "16px", left: "16px", background: "rgba(0,0,0,0.65)", color: "#fef3c7", padding: "6px 14px", borderRadius: "6px", fontSize: "0.85rem" }}>
                Take this time to formulate your answer. Recording will begin automatically when the timer reaches 0.
              </div>
            )}
            {phase === "recording" && (
              <div style={{ position: "absolute", top: "16px", left: "16px", background: "rgba(239,68,68,0.85)", color: "#fff", padding: "6px 14px", borderRadius: "6px", fontSize: "0.85rem", fontWeight: "600" }}>
                â—  Recording in progress
              </div>
            )}
          </div>

          {error && <p className="error" style={{ marginTop: "16px" }}>{error}</p>}
          {uploadProgress && <p className="loading-message" style={{ marginTop: "16px" }}>{uploadProgress}</p>}

          {/* Action Buttons */}
          <div className="card-actions" style={{ marginTop: "20px", display: "flex", justifyContent: "space-between" }}>
            {phase === "prep" && (
              <button
                type="button"
                className="button"
                onClick={() => {
                  clearInterval(prepTimerRef.current);
                  startRecording(currentQ);
                }}
              >
                Start Recording Now â†’
              </button>
            )}

            {phase === "recording" && (
              <button
                type="button"
                className="button button-danger"
                onClick={stopRecording}
              >
                Stop Recording â– 
              </button>
            )}

            {phase === "review" && (
              <div style={{ display: "flex", gap: "12px", width: "100%", justifyContent: "space-between" }}>
                {assessmentInfo.allow_review && (
                  <button
                    type="button"
                    className="button button-secondary"
                    disabled={busy}
                    onClick={handleReRecord}
                  >
                    â†º Re-record Response
                  </button>
                )}
                <button
                  type="button"
                  className="button"
                  disabled={busy}
                  onClick={handleUploadAndNext}
                >
                  {busy ? "Uploading to Cloudinary..." : currentIdx + 1 < questions.length ? "Confirm & Next Question â†’" : "Confirm & Submit Assessment"}
                </button>
              </div>
            )}
          </div>
        </section>
      )}
    </main>
  );
}
