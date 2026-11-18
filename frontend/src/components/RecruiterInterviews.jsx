import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api from "../api";
import {
  formatInterviewMode,
  formatInterviewStatus,
  formatNotificationType,
  formatRecommendation,
  getStatusBadgeClass,
  parseApiError,
} from "../utils/profileUtils";

export default function RecruiterInterviews({
  jobs = [],
  refreshSignal = 0,
  onOpenInterviewAction,
  onNotificationsUpdated,
  onFeedback,
}) {
  const [interviews, setInterviews] = useState([]);
  const [countsByStatus, setCountsByStatus] = useState({});
  const [loading, setLoading] = useState(true);

  const [playbackRecording, setPlaybackRecording] = useState(null);
  const [playbackLoadingId, setPlaybackLoadingId] = useState(null);
  const [failedTransfers, setFailedTransfers] = useState([]);
  const [retryingTransferId, setRetryingTransferId] = useState(null);

  const [search, setSearch] = useState("");
  const [jobFilter, setJobFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [modeFilter, setModeFilter] = useState("");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");

  const [notifications, setNotifications] = useState([]);
  const [notifCounts, setNotifCounts] = useState({});
  const [notifLoading, setNotifLoading] = useState(true);
  const [notifStatusFilter, setNotifStatusFilter] = useState("");
  const [notifTypeFilter, setNotifTypeFilter] = useState("");
  const [retryingId, setRetryingId] = useState(null);

  const loadInterviews = useCallback(async (overrides = {}) => {
    setLoading(true);
    try {
      const res = await api.get("/api/recruiter/interviews", {
        params: {
          q: (overrides.q !== undefined ? overrides.q : search) || undefined,
          job_id: (overrides.job_id !== undefined ? overrides.job_id : jobFilter) || undefined,
          status: (overrides.status !== undefined ? overrides.status : statusFilter) || undefined,
          interview_mode: (overrides.interview_mode !== undefined ? overrides.interview_mode : modeFilter) || undefined,
          from_date: (overrides.from_date !== undefined ? overrides.from_date : fromDate) || undefined,
          to_date: (overrides.to_date !== undefined ? overrides.to_date : toDate) || undefined,
        },
      });
      setInterviews(Array.isArray(res?.data?.items) ? res.data.items : []);
      setCountsByStatus(res?.data?.counts_by_status || {});
    } catch (requestError) {
      onFeedback?.(await parseApiError(requestError, "Unable to load interviews."), true);
    } finally {
      setLoading(false);
    }
  }, [search, jobFilter, statusFilter, modeFilter, fromDate, toDate, onFeedback]);

  const loadNotifications = useCallback(async (overrides = {}) => {
    setNotifLoading(true);
    try {
      const res = await api.get("/api/recruiter/notifications", {
        params: {
          status: (overrides.status !== undefined ? overrides.status : notifStatusFilter) || undefined,
          notification_type: (overrides.notification_type !== undefined ? overrides.notification_type : notifTypeFilter) || undefined,
        },
      });
      setNotifications(Array.isArray(res?.data?.items) ? res.data.items : []);
      setNotifCounts(res?.data?.counts_by_status || {});
    } catch (requestError) {
      onFeedback?.(await parseApiError(requestError, "Unable to load email notifications."), true);
    } finally {
      setNotifLoading(false);
    }
  }, [notifStatusFilter, notifTypeFilter, onFeedback]);

  const loadFailedTransfers = useCallback(async () => {
    try {
      const res = await api.get("/api/recruiter/interviews-failed-transfers");
      setFailedTransfers(Array.isArray(res.data) ? res.data : []);
    } catch {
      // Ignored if empty or unauthorized
    }
  }, []);

  useEffect(() => {
    loadInterviews();
    loadNotifications();
    loadFailedTransfers();
  }, [loadInterviews, loadNotifications, loadFailedTransfers, refreshSignal]);

  const handlePlayInterviewRecording = async (interviewId) => {
    setPlaybackLoadingId(interviewId);
    try {
      const res = await api.get(`/api/recruiter/interviews/${interviewId}/recordings/playback`);
      if (res.data?.playback_url) {
        setPlaybackRecording({
          interviewId,
          url: res.data.playback_url,
          duration: res.data.duration,
          format: res.data.format,
          fileSize: res.data.file_size,
        });
      } else {
        onFeedback?.("No processed recording available for this interview yet.", true);
      }
    } catch (err) {
      onFeedback?.(await parseApiError(err, "Unable to load interview recording playback."), true);
    } finally {
      setPlaybackLoadingId(null);
    }
  };

  const handleRetryTransfer = async (interviewId, recordingId) => {
    setRetryingTransferId(recordingId);
    try {
      const res = await api.post(`/api/recruiter/interviews/${interviewId}/recordings/${recordingId}/retry`);
      onFeedback?.(res.data?.message || "Recording transfer retry initiated.", false);
      await Promise.all([loadInterviews(), loadFailedTransfers()]);
    } catch (err) {
      onFeedback?.(await parseApiError(err, "Failed to retry recording transfer."), true);
    } finally {
      setRetryingTransferId(null);
    }
  };

  const resetInterviewFilters = () => {
    setSearch("");
    setJobFilter("");
    setStatusFilter("");
    setModeFilter("");
    setFromDate("");
    setToDate("");
    loadInterviews({ q: "", job_id: "", status: "", interview_mode: "", from_date: "", to_date: "" });
  };

  const handleRetryNotification = async (notificationId) => {
    if (retryingId === notificationId) return;
    setRetryingId(notificationId);
    try {
      const res = await api.post(`/api/recruiter/notifications/${notificationId}/resend`);
      onFeedback?.(res?.data?.message || "Notification resent successfully.", false);
      await Promise.all([loadNotifications(), loadInterviews()]);
      onNotificationsUpdated?.();
    } catch (requestError) {
      onFeedback?.(await parseApiError(requestError, "Failed to resend email notification."), true);
      await loadNotifications();
    } finally {
      setRetryingId(null);
    }
  };

  return (
    <>
      <section className="panel" id="recruiter-interviews">
        <div className="section-heading">
          <div>
            <span className="eyebrow">Round Scheduling &amp; Feedback</span>
            <h2>Interview Management</h2>
          </div>
          <span className="table-count">{interviews.length} interviews</span>
        </div>

        <div className="applicant-counts-bar" style={{ marginBottom: "14px" }}>
          <span>Scheduled: <strong>{countsByStatus.scheduled || 0}</strong></span>
          <span>Rescheduled: <strong>{countsByStatus.rescheduled || 0}</strong></span>
          <span>Completed: <strong>{countsByStatus.completed || 0}</strong></span>
          <span>Cancelled: <strong>{countsByStatus.cancelled || 0}</strong></span>
          <span>No Show: <strong>{countsByStatus.no_show || 0}</strong></span>
        </div>

        <form
          className="applicant-filters-grid"
          onSubmit={(e) => { e.preventDefault(); loadInterviews(); }}
        >
          <input
            aria-label="Search interviews"
            placeholder="Search candidate, job, round, or interviewer"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <select aria-label="Filter interviews by job" value={jobFilter} onChange={(e) => setJobFilter(e.target.value)}>
            <option value="">All jobs</option>
            {jobs.map((job) => <option key={job.id} value={job.id}>{job.title}</option>)}
          </select>
          <select aria-label="Filter interviews by status" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">All interview statuses</option>
            <option value="scheduled">Scheduled</option>
            <option value="rescheduled">Rescheduled</option>
            <option value="completed">Completed</option>
            <option value="cancelled">Cancelled</option>
            <option value="no_show">No Show</option>
          </select>
          <select aria-label="Filter interviews by mode" value={modeFilter} onChange={(e) => setModeFilter(e.target.value)}>
            <option value="">All modes</option>
            <option value="online">Online</option>
            <option value="in_person">Offline (In-Person)</option>
            <option value="phone">Phone</option>
          </select>
          <input type="date" aria-label="Interviews from date" value={fromDate} onChange={(e) => setFromDate(e.target.value)} />
          <input type="date" aria-label="Interviews to date" value={toDate} onChange={(e) => setToDate(e.target.value)} />
          <div className="card-actions">
            <button type="submit" className="button button-small">Filter</button>
            <button type="button" className="button button-secondary button-small" onClick={resetInterviewFilters}>Reset</button>
          </div>
        </form>

        {loading && <p className="loading-message" role="status">Loading interviews...</p>}

        {failedTransfers.length > 0 && (
          <div style={{ background: "#fef2f2", border: "1px solid #f87171", borderRadius: "8px", padding: "14px", marginBottom: "16px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <strong style={{ color: "#991b1b" }}>⚠️ Attention: {failedTransfers.length} LiveKit Recording Transfer(s) Pending or Failed</strong>
            </div>
            <p className="small-meta" style={{ color: "#7f1d1d", margin: "6px 0 10px" }}>
              Temporary recording files are securely retained on the server. Click retry to re-upload to Cloudinary.
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
              {failedTransfers.map((item) => (
                <div key={item.recording_id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", background: "#fff", padding: "8px 12px", borderRadius: "6px", border: "1px solid #fecaca", flexWrap: "wrap", gap: "8px" }}>
                  <div>
                    <strong>Interview #{item.interview_id}</strong> — Candidate: {item.candidate_name || "N/A"}
                    <span className="small-meta" style={{ marginLeft: "8px", color: "#b91c1c" }}>{item.error_message || "Transfer pending retry"}</span>
                  </div>
                  <button
                    type="button"
                    className="button button-danger button-small"
                    disabled={retryingTransferId === item.recording_id}
                    onClick={() => handleRetryTransfer(item.interview_id, item.recording_id)}
                  >
                    {retryingTransferId === item.recording_id ? "Retrying..." : "🔄 Retry Cloudinary Upload"}
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {playbackRecording && (
          <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Interview Recording Playback">
            <div className="modal-panel panel" style={{ maxWidth: "800px", width: "95%" }}>
              <div className="modal-header">
                <div>
                  <span className="eyebrow">Cloudinary Video Playback</span>
                  <h3>Interview Recording #{playbackRecording.interviewId}</h3>
                </div>
                <button
                  type="button"
                  className="button button-secondary button-small"
                  onClick={() => setPlaybackRecording(null)}
                >
                  Close ✕
                </button>
              </div>
              <div style={{ padding: "16px 0" }}>
                <video
                  controls
                  autoPlay
                  playsInline
                  src={playbackRecording.url}
                  style={{ width: "100%", maxHeight: "500px", borderRadius: "8px", background: "#000" }}
                >
                  Your browser does not support HTML5 video playback.
                </video>
                <div className="small-meta" style={{ marginTop: "10px", display: "flex", gap: "16px" }}>
                  <span>Duration: {playbackRecording.duration ? `${playbackRecording.duration}s` : "N/A"}</span>
                  <span>Format: {playbackRecording.format?.toUpperCase() || "MP4"}</span>
                  {playbackRecording.fileSize && <span>Size: {(playbackRecording.fileSize / (1024 * 1024)).toFixed(2)} MB</span>}
                  <span style={{ color: "#16a34a", fontWeight: "600" }}>✓ Secure Cloudinary Stream</span>
                </div>
              </div>
            </div>
          </div>
        )}

        {!loading && (
          <div className="applicant-cards-list">
            {interviews.length ? interviews.map((interview) => {
              const canRescheduleOrCancel = ["scheduled", "rescheduled"].includes(interview.status);
              const canRecordFeedback = interview.status !== "cancelled";
              const latestNotif = interview.latest_notification;

              return (
                <article className="applicant-card" key={interview.id}>
                  <div className="applicant-card-header">
                    <div>
                      <h3>
                        Round {interview.round_number}: {interview.round_name}
                      </h3>
                      <p className="small-meta">
                        <strong>{interview.candidate_name}</strong> ({interview.candidate_email}) · {interview.job_title}
                      </p>
                    </div>
                    <div className="badge-row">
                      <span className={getStatusBadgeClass(interview.status)}>
                        {formatInterviewStatus(interview.status)}
                      </span>
                      <span className="role-pill">{formatInterviewMode(interview.interview_mode)}</span>
                      {interview.recommendation && (
                        <span className={getStatusBadgeClass(interview.recommendation)}>
                          Outcome: {formatRecommendation(interview.recommendation)}
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="applicant-card-grid">
                    <div>
                      <strong>Date &amp; Time:</strong>{" "}
                      <span>{new Date(interview.scheduled_at).toLocaleString()} ({interview.timezone}) · {interview.duration_minutes} mins</span>
                    </div>
                    <div>
                      <strong>Interviewer:</strong>{" "}
                      <span>{interview.interviewer_name || "Not specified"}</span>
                    </div>
                    {interview.meeting_link && (
                      <div>
                        <strong>Meeting Link:</strong>{" "}
                        <a href={interview.meeting_link} target="_blank" rel="noreferrer">{interview.meeting_link}</a>
                      </div>
                    )}
                    {interview.location && (
                      <div>
                        <strong>Location:</strong> <span>{interview.location}</span>
                      </div>
                    )}
                    {interview.rating != null && (
                      <div>
                        <strong>Rating:</strong> <span>{interview.rating} / 5</span>
                      </div>
                    )}
                    {interview.feedback && (
                      <div>
                        <strong>Feedback:</strong> <span>{interview.feedback}</span>
                      </div>
                    )}
                    {interview.cancellation_reason && (
                      <div>
                        <strong>Cancellation Reason:</strong> <span>{interview.cancellation_reason}</span>
                      </div>
                    )}
                  </div>

                  {latestNotif && (
                    <div className="small-meta" style={{ marginTop: "8px", display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
                      <strong>Email Notification ({formatNotificationType(latestNotif.notification_type)}):</strong>
                      <span className={getStatusBadgeClass(latestNotif.status)}>
                        {latestNotif.status.toUpperCase()}
                      </span>
                      {latestNotif.error_message && (
                        <span className="resume-error">{latestNotif.error_message}</span>
                      )}
                      {latestNotif.status === "failed" && (
                        <button
                          type="button"
                          className="button button-secondary button-small"
                          disabled={retryingId === latestNotif.id}
                          onClick={() => handleRetryNotification(latestNotif.id)}
                        >
                          {retryingId === latestNotif.id ? "Retrying..." : "Retry Email"}
                        </button>
                      )}
                    </div>
                  )}

                  <div className="card-actions" style={{ marginTop: "12px", display: "flex", flexWrap: "wrap", gap: "8px" }}>
                    {(interview.interview_mode === "online" || interview.livekit_room_name || interview.meeting_link?.includes("/live-interview/")) && interview.status !== "cancelled" && (
                      <Link
                        to={`/live-interview/${interview.id}`}
                        className="button button-small"
                        style={{ display: "inline-flex", alignItems: "center", gap: "6px", background: "#2563eb", color: "#fff", textDecoration: "none", fontWeight: "600" }}
                      >
                        🎥 Enter Live Room
                      </Link>
                    )}
                    {interview.status === "completed" && (
                      <button
                        type="button"
                        className="button button-secondary button-small"
                        disabled={playbackLoadingId === interview.id}
                        onClick={() => handlePlayInterviewRecording(interview.id)}
                      >
                        {playbackLoadingId === interview.id ? "Loading..." : "▶ Watch Recording"}
                      </button>
                    )}
                    {canRescheduleOrCancel && (
                      <button
                        type="button"
                        className="button button-secondary button-small"
                        onClick={() => onOpenInterviewAction?.("reschedule", interview)}
                      >
                        Reschedule
                      </button>
                    )}
                    {canRecordFeedback && (
                      <button
                        type="button"
                        className="button button-small"
                        onClick={() => onOpenInterviewAction?.("feedback", interview)}
                      >
                        {interview.feedback || interview.recommendation ? "Update Feedback" : "Feedback & Outcome"}
                      </button>
                    )}
                    {canRescheduleOrCancel && (
                      <button
                        type="button"
                        className="button button-danger button-small"
                        onClick={() => onOpenInterviewAction?.("cancel", interview)}
                      >
                        Cancel Interview
                      </button>
                    )}
                  </div>
                </article>
              );
            }) : (
              <p className="small-meta">
                No interviews scheduled yet. Open Applicants above and click “Schedule Interview” on an eligible candidate.
              </p>
            )}
          </div>
        )}
      </section>

      <section className="panel admin-table-panel" id="recruiter-notifications">
        <div className="section-heading">
          <div>
            <span className="eyebrow">Candidate Email Audit Trail</span>
            <h2>Email Notifications</h2>
          </div>
          <div className="badge-row">
            <span className="status-badge status-badge-success">Sent: {notifCounts.sent || 0}</span>
            <span className="status-badge status-badge-danger">Failed: {notifCounts.failed || 0}</span>
            <span className="status-badge status-badge-neutral">Pending: {notifCounts.pending || 0}</span>
          </div>
        </div>

        <form
          className="admin-filters"
          onSubmit={(e) => { e.preventDefault(); loadNotifications(); }}
        >
          <select aria-label="Filter notification logs by status" value={notifStatusFilter} onChange={(e) => setNotifStatusFilter(e.target.value)}>
            <option value="">All delivery statuses</option>
            <option value="sent">Sent</option>
            <option value="failed">Failed</option>
            <option value="pending">Pending</option>
          </select>
          <select aria-label="Filter notification logs by type" value={notifTypeFilter} onChange={(e) => setNotifTypeFilter(e.target.value)}>
            <option value="">All notification types</option>
            <option value="application_shortlisted">Shortlisted</option>
            <option value="application_selected">Selected</option>
            <option value="application_rejected">Rejected</option>
            <option value="interview_scheduled">Interview Scheduled</option>
            <option value="interview_rescheduled">Interview Rescheduled</option>
            <option value="interview_cancelled">Interview Cancelled</option>
          </select>
          <button type="submit" className="button button-small">Filter</button>
          <button
            type="button"
            className="button button-secondary button-small"
            onClick={() => {
              setNotifStatusFilter("");
              setNotifTypeFilter("");
              loadNotifications({ status: "", notification_type: "" });
            }}
          >
            Reset
          </button>
        </form>

        {notifLoading && <p className="loading-message" role="status">Loading notification logs...</p>}

        {!notifLoading && (
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Recipient</th>
                  <th>Type</th>
                  <th>Subject</th>
                  <th>Status</th>
                  <th>Retries / Sent At</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {notifications.map((item) => (
                  <tr key={item.id}>
                    <td data-label="Recipient">
                      <strong>{item.recipient_name || "Candidate"}</strong>
                      <span>{item.recipient_email}</span>
                    </td>
                    <td data-label="Type">{formatNotificationType(item.notification_type)}</td>
                    <td data-label="Subject">
                      <span>{item.subject}</span>
                      {item.error_message && <div className="resume-error small-meta">{item.error_message}</div>}
                    </td>
                    <td data-label="Status">
                      <span className={getStatusBadgeClass(item.status)}>{item.status.toUpperCase()}</span>
                    </td>
                    <td data-label="Retries / Sent At">
                      <span>Retries: {item.retry_count ?? 0}</span>
                      <div className="small-meta">
                        {item.sent_at ? new Date(item.sent_at).toLocaleString() : new Date(item.created_at).toLocaleString()}
                      </div>
                    </td>
                    <td data-label="Action">
                      {item.status === "failed" ? (
                        <button
                          type="button"
                          className="button button-small"
                          disabled={retryingId === item.id}
                          onClick={() => handleRetryNotification(item.id)}
                        >
                          {retryingId === item.id ? "Retrying..." : "Retry"}
                        </button>
                      ) : (
                        <span className="small-meta">—</span>
                      )}
                    </td>
                  </tr>
                ))}
                {!notifications.length && (
                  <tr><td colSpan="6" className="table-empty">No decision or interview email notifications logged yet.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
