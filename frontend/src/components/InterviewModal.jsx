import { useEffect, useState } from "react";
import api from "../api";
import { parseApiError } from "../utils/profileUtils";

function toLocalDatetimeInputValue(isoString) {
  if (!isoString) return "";
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return "";
  const offset = date.getTimezoneOffset();
  const local = new Date(date.getTime() - offset * 60000);
  return local.toISOString().slice(0, 16);
}

function defaultFutureDatetimeInput() {
  const d = new Date(Date.now() + 24 * 60 * 60 * 1000);
  d.setMinutes(0, 0, 0);
  return toLocalDatetimeInputValue(d.toISOString());
}

export default function InterviewModal({
  mode = "schedule", // schedule | reschedule | cancel | feedback
  applicant = null,
  interview = null,
  existingRoundCount = 0,
  onClose,
  onCompleted,
}) {
  const browserTimezone =
    (typeof Intl !== "undefined" && Intl.DateTimeFormat().resolvedOptions().timeZone) || "UTC";

  const [roundNumber, setRoundNumber] = useState(
    interview?.round_number ?? existingRoundCount + 1
  );
  const [roundName, setRoundName] = useState(
    interview?.round_name || `Interview Round ${existingRoundCount + 1}`
  );
  const [interviewMode, setInterviewMode] = useState(interview?.interview_mode || "online");
  const [isLiveKit, setIsLiveKit] = useState(Boolean(interview?.livekit_room_name));
  const [interviewType, setInterviewType] = useState(interview?.interview_type || "technical");
  const [isWaitingRoomEnabled, setIsWaitingRoomEnabled] = useState(
    interview?.is_waiting_room_enabled ?? true
  );
  const [scheduledAt, setScheduledAt] = useState(
    interview?.scheduled_at ? toLocalDatetimeInputValue(interview.scheduled_at) : defaultFutureDatetimeInput()
  );
  const [durationMinutes, setDurationMinutes] = useState(interview?.duration_minutes ?? 45);
  const [timezone, setTimezone] = useState(interview?.timezone || browserTimezone);
  const [meetingLink, setMeetingLink] = useState(interview?.meeting_link || "");
  const [location, setLocation] = useState(interview?.location || "");
  const [interviewerName, setInterviewerName] = useState(interview?.interviewer_name || "");
  const [interviewerEmail, setInterviewerEmail] = useState(interview?.interviewer_email || "");
  const [notesForCandidate, setNotesForCandidate] = useState(interview?.notes_for_candidate || "");
  const [internalNotes, setInternalNotes] = useState(interview?.internal_notes || "");
  const [sendEmail, setSendEmail] = useState(true);

  const [cancellationReason, setCancellationReason] = useState("");
  const [outcomeStatus, setOutcomeStatus] = useState(
    interview?.status === "no_show" ? "no_show" : "completed"
  );
  const [rating, setRating] = useState(interview?.rating ? String(interview.rating) : "5");
  const [recommendation, setRecommendation] = useState(interview?.recommendation || "hire");
  const [feedback, setFeedback] = useState(interview?.feedback || "");

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (mode !== "schedule" || existingRoundCount > 0 || !applicant?.id) return;
    let active = true;
    api.get(`/api/recruiter/applications/${applicant.id}/interviews`)
      .then((res) => {
        if (!active || !Array.isArray(res?.data) || !res.data.length) return;
        const nextRound = Math.max(...res.data.map((item) => Number(item.round_number) || 0)) + 1;
        setRoundNumber((prev) => (prev === 1 ? nextRound : prev));
        setRoundName((prev) => (prev === "Interview Round 1" ? `Interview Round ${nextRound}` : prev));
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [mode, existingRoundCount, applicant?.id]);

  if (mode === "schedule" && !applicant) return null;
  if (mode !== "schedule" && !interview) return null;

  const candidateLabel = interview?.candidate_name || applicant?.candidate || "Candidate";
  const jobLabel = interview?.job_title || applicant?.job_title || "Role";

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (submitting) return;
    setError("");

    if (mode === "schedule" || mode === "reschedule") {
      const parsedRound = Number(roundNumber);
      if (!Number.isInteger(parsedRound) || parsedRound < 1 || parsedRound > 20) {
        setError("Round number must be between 1 and 20.");
        return;
      }
      if (!roundName.trim()) {
        setError("Round name is required.");
        return;
      }
      const parsedDuration = Number(durationMinutes);
      if (!Number.isInteger(parsedDuration) || parsedDuration < 10 || parsedDuration > 480) {
        setError("Duration must be between 10 and 480 minutes.");
        return;
      }
      if (!timezone.trim()) {
        setError("Timezone cannot be blank.");
        return;
      }
      if (interviewerEmail.trim() && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(interviewerEmail.trim())) {
        setError("Enter a valid interviewer email address or leave it blank.");
        return;
      }
      if (!scheduledAt) {
        setError("Select an interview date and time.");
        return;
      }
      const parsedDate = new Date(scheduledAt);
      if (Number.isNaN(parsedDate.getTime()) || parsedDate.getTime() <= Date.now()) {
        setError("Interview date and time must be in the future.");
        return;
      }
      if (interviewMode === "online" && !isLiveKit && !/^https?:\/\/\S+$/i.test(meetingLink.trim())) {
        setError("Please enter a valid http:// or https:// meeting link for online interviews.");
        return;
      }
      if (interviewMode === "in_person" && location.trim().length < 3) {
        setError("Please enter a physical location (at least 3 characters) for offline / in-person interviews.");
        return;
      }
    }

    setSubmitting(true);
    try {
      let response;
      if (mode === "schedule") {
        if (interviewMode === "online" && isLiveKit) {
          response = await api.post(`/api/recruiter/applications/${applicant.id}/live-interview`, {
            round_number: Number(roundNumber) || 1,
            round_name: roundName.trim() || `Interview Round ${Number(roundNumber) || 1}`,
            interview_type: interviewType,
            scheduled_at: new Date(scheduledAt).toISOString(),
            duration_minutes: Number(durationMinutes) || 45,
            timezone: timezone.trim() || "UTC",
            instructions: notesForCandidate.trim() || null,
            is_waiting_room_enabled: isWaitingRoomEnabled,
            send_email: sendEmail,
          });
        } else {
          response = await api.post(`/api/recruiter/applications/${applicant.id}/interviews`, {
            round_number: Number(roundNumber) || 1,
            round_name: roundName.trim() || `Interview Round ${Number(roundNumber) || 1}`,
            interview_mode: interviewMode,
            scheduled_at: new Date(scheduledAt).toISOString(),
            duration_minutes: Number(durationMinutes) || 45,
            timezone: timezone.trim() || "UTC",
            meeting_link: interviewMode === "in_person" ? null : (meetingLink.trim() || null),
            location: interviewMode === "online" ? null : (location.trim() || null),
            interviewer_name: interviewerName.trim() || null,
            interviewer_email: interviewerEmail.trim() || null,
            notes_for_candidate: notesForCandidate.trim() || null,
            internal_notes: internalNotes.trim() || null,
            send_email: sendEmail,
          });
        }
      } else if (mode === "reschedule") {
        response = await api.put(`/api/recruiter/interviews/${interview.id}/reschedule`, {
          round_number: Number(roundNumber) || interview.round_number,
          round_name: roundName.trim() || interview.round_name,
          interview_mode: interviewMode,
          scheduled_at: new Date(scheduledAt).toISOString(),
          duration_minutes: Number(durationMinutes) || 45,
          timezone: timezone.trim() || "UTC",
          meeting_link: interviewMode === "in_person" ? null : (meetingLink.trim() || null),
          location: interviewMode === "online" ? null : (location.trim() || null),
          interviewer_name: interviewerName.trim() || null,
          interviewer_email: interviewerEmail.trim() || null,
          notes_for_candidate: notesForCandidate.trim() || null,
          internal_notes: internalNotes.trim() || null,
          send_email: sendEmail,
        });
      } else if (mode === "cancel") {
        response = await api.post(`/api/recruiter/interviews/${interview.id}/cancel`, {
          cancellation_reason: cancellationReason.trim() || null,
          send_email: sendEmail,
        });
      } else {
        response = await api.post(`/api/recruiter/interviews/${interview.id}/feedback`, {
          status: outcomeStatus,
          rating: rating ? Number(rating) : null,
          recommendation: recommendation || null,
          feedback: feedback.trim() || null,
          internal_notes: internalNotes.trim() || null,
        });
      }

      onCompleted?.(response.data, mode);
      onClose?.();
    } catch (requestError) {
      setError(await parseApiError(requestError, "Unable to complete interview request."));
    } finally {
      setSubmitting(false);
    }
  };

  const modalTitle = {
    schedule: "Schedule Interview",
    reschedule: "Reschedule Interview",
    cancel: "Cancel Interview",
    feedback: "Interview Feedback & Outcome",
  }[mode];

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={modalTitle}>
      <div className="modal-panel panel">
        <div className="modal-header">
          <div>
            <span className="eyebrow">Interview Management</span>
            <h2>{modalTitle}</h2>
            <p className="modal-subtitle">
              {candidateLabel} · {jobLabel}
              {interview?.round_number ? ` · Round ${interview.round_number}` : ""}
            </p>
          </div>
          <button type="button" className="button button-secondary button-small" onClick={onClose} disabled={submitting}>
            Close ✕
          </button>
        </div>

        <form className="modal-body" noValidate onSubmit={handleSubmit}>
          {(mode === "schedule" || mode === "reschedule") && (
            <div className="profile-form">
              <label className="resume-selector">
                Round Number
                <input
                  type="number"
                  min="1"
                  max="20"
                  required
                  value={roundNumber}
                  onChange={(e) => setRoundNumber(e.target.value)}
                />
              </label>
              <label className="resume-selector">
                Round Name
                <input
                  required
                  maxLength={120}
                  placeholder="e.g., Technical Round 1"
                  value={roundName}
                  onChange={(e) => setRoundName(e.target.value)}
                />
              </label>
              <label className="resume-selector">
                Interview Mode
                <select
                  aria-label="Interview Mode"
                  value={interviewMode}
                  onChange={(e) => setInterviewMode(e.target.value)}
                >
                  <option value="online">Online (Video Call)</option>
                  <option value="in_person">Offline (In-Person)</option>
                  <option value="phone">Phone</option>
                </select>
              </label>
              <label className="resume-selector">
                Date &amp; Time
                <input
                  type="datetime-local"
                  aria-label="Interview Date and Time"
                  required
                  value={scheduledAt}
                  onChange={(e) => setScheduledAt(e.target.value)}
                />
              </label>
              <label className="resume-selector">
                Duration (minutes)
                <input
                  type="number"
                  min="10"
                  max="480"
                  required
                  value={durationMinutes}
                  onChange={(e) => setDurationMinutes(e.target.value)}
                />
              </label>
              <label className="resume-selector">
                Timezone
                <input
                  required
                  maxLength={64}
                  value={timezone}
                  onChange={(e) => setTimezone(e.target.value)}
                />
              </label>
              <label className="resume-selector">
                Interviewer Name
                <input
                  maxLength={150}
                  placeholder="e.g., Hiring Manager"
                  value={interviewerName}
                  onChange={(e) => setInterviewerName(e.target.value)}
                />
              </label>
              <label className="resume-selector">
                Interviewer Email (optional)
                <input
                  type="email"
                  placeholder="interviewer@company.com"
                  value={interviewerEmail}
                  onChange={(e) => setInterviewerEmail(e.target.value)}
                />
              </label>
              {interviewMode === "online" && (
                <div style={{ background: "rgba(59, 130, 246, 0.08)", border: "1px solid rgba(59, 130, 246, 0.25)", borderRadius: "8px", padding: "12px", gridColumn: "1 / -1" }}>
                  <label style={{ display: "flex", alignItems: "center", gap: "8px", fontWeight: "600", cursor: "pointer", color: "var(--text-color, #1e293b)" }}>
                    <input
                      type="checkbox"
                      checked={isLiveKit}
                      onChange={(e) => setIsLiveKit(e.target.checked)}
                    />
                    <span>🎥 Use SkillSphere LiveKit Video Room (Auto-recorded to Cloudinary)</span>
                  </label>
                  {isLiveKit ? (
                    <div style={{ marginTop: "10px", display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
                      <label className="resume-selector">
                        Interview Type
                        <select
                          value={interviewType}
                          onChange={(e) => setInterviewType(e.target.value)}
                        >
                          <option value="technical">Technical Interview</option>
                          <option value="behavioral">Behavioral Interview</option>
                          <option value="screening">Recruiter Screening</option>
                          <option value="system_design">System Design</option>
                          <option value="final_round">Final Round</option>
                        </select>
                      </label>
                      <label style={{ display: "flex", alignItems: "center", gap: "8px", marginTop: "24px", cursor: "pointer", fontSize: "14px" }}>
                        <input
                          type="checkbox"
                          checked={isWaitingRoomEnabled}
                          onChange={(e) => setIsWaitingRoomEnabled(e.target.checked)}
                        />
                        <span>Enable Candidate Waiting Room</span>
                      </label>
                      <p className="small-meta" style={{ gridColumn: "1 / -1", margin: 0, color: "#2563eb", fontWeight: "500" }}>
                        ✓ Room, tokens, and candidate invitation link will be auto-generated. Video will be recorded and stored in Cloudinary.
                      </p>
                    </div>
                  ) : (
                    <label className="resume-selector full-width" style={{ marginTop: "10px" }}>
                      Custom Online Meeting Link (required)
                      <input
                        type="url"
                        required
                        placeholder="https://meet.google.com/..."
                        value={meetingLink}
                        onChange={(e) => setMeetingLink(e.target.value)}
                      />
                    </label>
                  )}
                </div>
              )}
              {interviewMode === "phone" && (
                <label className="resume-selector full-width">
                  Phone / Dial-in Instructions (optional)
                  <input
                    type="text"
                    placeholder="Candidate direct phone number or conference dial-in"
                    value={meetingLink}
                    onChange={(e) => setMeetingLink(e.target.value)}
                  />
                </label>
              )}
              {interviewMode !== "online" && (
                <label className="resume-selector full-width">
                  Location / Venue {interviewMode === "in_person" ? "(required for offline)" : "(optional)"}
                  <input
                    required={interviewMode === "in_person"}
                    placeholder="Office address, floor, or dial-in instructions"
                    value={location}
                    onChange={(e) => setLocation(e.target.value)}
                  />
                </label>
              )}
              <label className="resume-selector full-width">
                Notes for Candidate (shared in email &amp; candidate dashboard)
                <textarea
                  rows={2}
                  maxLength={2000}
                  placeholder="Preparation tips, agenda, documents to bring..."
                  value={notesForCandidate}
                  onChange={(e) => setNotesForCandidate(e.target.value)}
                />
              </label>
              <label className="resume-selector full-width">
                Internal Recruiter Notes (private)
                <textarea
                  rows={2}
                  maxLength={2000}
                  placeholder="Internal evaluation focus areas (never visible to candidate)..."
                  value={internalNotes}
                  onChange={(e) => setInternalNotes(e.target.value)}
                />
              </label>
              <label className="checkbox-row full-width">
                <input
                  type="checkbox"
                  checked={sendEmail}
                  onChange={(e) => setSendEmail(e.target.checked)}
                />
                <span>Send {mode === "reschedule" ? "rescheduled schedule" : "interview invitation"} email to candidate</span>
              </label>
            </div>
          )}

          {mode === "cancel" && (
            <>
              <p>
                Cancel <strong>{interview.round_name} (Round {interview.round_number})</strong> scheduled for{" "}
                <strong>{new Date(interview.scheduled_at).toLocaleString()}</strong>? Cancelled interviews cannot be edited later.
              </p>
              <label className="resume-selector">
                Cancellation Reason (optional)
                <textarea
                  rows={3}
                  maxLength={1000}
                  placeholder="Reason for cancellation..."
                  value={cancellationReason}
                  onChange={(e) => setCancellationReason(e.target.value)}
                />
              </label>
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={sendEmail}
                  onChange={(e) => setSendEmail(e.target.checked)}
                />
                <span>Send cancellation email notification to candidate</span>
              </label>
            </>
          )}

          {mode === "feedback" && (
            <div className="profile-form">
              <label className="resume-selector">
                Interview Status
                <select aria-label="Outcome Status" value={outcomeStatus} onChange={(e) => setOutcomeStatus(e.target.value)}>
                  <option value="completed">Completed</option>
                  <option value="no_show">No Show</option>
                </select>
              </label>
              <label className="resume-selector">
                Rating (1–5)
                <select aria-label="Interview Rating" value={rating} onChange={(e) => setRating(e.target.value)}>
                  <option value="5">5 — Exceptional</option>
                  <option value="4">4 — Strong</option>
                  <option value="3">3 — Satisfactory</option>
                  <option value="2">2 — Below Expectations</option>
                  <option value="1">1 — Unsatisfactory</option>
                </select>
              </label>
              <label className="resume-selector full-width">
                Final Recommendation / Outcome
                <select aria-label="Interview Recommendation" value={recommendation} onChange={(e) => setRecommendation(e.target.value)}>
                  <option value="strong_hire">Strong Hire</option>
                  <option value="hire">Hire</option>
                  <option value="hold">On Hold</option>
                  <option value="no_hire">No Hire</option>
                </select>
              </label>
              <label className="resume-selector full-width">
                Interviewer Feedback (private to hiring team)
                <textarea
                  rows={3}
                  maxLength={4000}
                  placeholder="Technical strengths, problem-solving notes, communication..."
                  value={feedback}
                  onChange={(e) => setFeedback(e.target.value)}
                />
              </label>
              <label className="resume-selector full-width">
                Internal Hiring Notes (private)
                <textarea
                  rows={2}
                  maxLength={2000}
                  placeholder="Internal notes for next round or compensation..."
                  value={internalNotes}
                  onChange={(e) => setInternalNotes(e.target.value)}
                />
              </label>
            </div>
          )}

          {error && <p className="error" role="alert">{error}</p>}

          <div className="card-actions">
            <button
              type="submit"
              className={`button ${mode === "cancel" ? "button-danger" : ""}`}
              disabled={submitting}
            >
              {submitting
                ? "Saving..."
                : mode === "schedule"
                  ? "Schedule Interview"
                  : mode === "reschedule"
                    ? "Save New Schedule"
                    : mode === "cancel"
                      ? "Confirm Cancellation"
                      : "Save Feedback & Outcome"}
            </button>
            <button type="button" className="button button-secondary" onClick={onClose} disabled={submitting}>
              Back
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
