import { useCallback, useEffect, useState } from "react";
import { Link, Navigate, Route, Routes, useNavigate, useParams, useSearchParams } from "react-router-dom";
import api from "./api";
import { useAuth } from "./AuthContext";
import AdminInterviewsAndNotifications from "./components/AdminInterviewsAndNotifications";
import AdminQuestionBank from "./components/AdminQuestionBank";
import ApplicantProfileModal from "./components/ApplicantProfileModal";
import AssessmentPortal from "./components/AssessmentPortal";
import AssignAssessmentModal from "./components/AssignAssessmentModal";
import DecisionActionModal from "./components/DecisionActionModal";
import InterviewModal from "./components/InterviewModal";
import LiveInterviewRoom from "./components/LiveInterviewRoom";
import RecruiterAssessmentResults from "./components/RecruiterAssessmentResults";
import RecruiterAssessments from "./components/RecruiterAssessments";
import RecruiterInterviews from "./components/RecruiterInterviews";
import VideoAssessmentPortal from "./components/VideoAssessmentPortal";
import {
  APPLICATION_STATUS_OPTIONS,
  displayValue,
  formatAssessmentStatus,
  formatInterviewMode,
  formatInterviewStatus,
  formatInvitationStatus,
  formatNotificationType,
  formatStatusLabel,
  getStatusBadgeClass,
  parseApiError,
  sanitizeDisplayText,
} from "./utils/profileUtils";

const ALLOWED_RESUME_MIME_TYPES = new Set([
  "application/pdf",
  "image/jpeg",
  "image/png",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/msword",
]);

function Navbar() {
  const { token, role, logout } = useAuth();
  const [theme, setTheme] = useState(() => localStorage.getItem("skillsphere_theme") || "light");

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("skillsphere_theme", theme);
  }, [theme]);

  return (
    <nav className="navbar">
      <Link className="brand" to="/">SkillSphere</Link>
      <div className="nav-links">
        <Link to="/jobs">Find Jobs</Link>
        {!token && <Link to="/login">Log In</Link>}
        {!token && <Link className="button button-small" to="/register">Create Account</Link>}
        {token && <Link to={`/${role}`}>Dashboard</Link>}
        <button
          className="theme-toggle"
          type="button"
          aria-label={`Switch to ${theme === "light" ? "dark" : "light"} theme`}
          onClick={() => setTheme((current) => current === "light" ? "dark" : "light")}
        >
          {theme === "light" ? "\u263E" : "\u2600"}
        </button>
        {token && <button className="button button-small" onClick={logout}>Log Out</button>}
      </div>
    </nav>
  );
}

function LandingPage() {
  return (
    <main>
      <section className="hero">
        <div className="hero-copy">
          <span className="eyebrow">Careers made clearer</span>
          <h1>Discover roles that match your skills.</h1>
          <p>Explore opportunities and get transparent resume-to-job skill insights.</p>
          <div className="hero-actions">
            <Link className="button" to="/jobs">Explore Jobs</Link>
            <Link className="button button-secondary" to="/register">Join SkillSphere</Link>
          </div>
        </div>
        <div className="hero-card">
          <div className="hero-card-header">
            <span>Skill match overview</span>
            <strong>92%</strong>
          </div>
          <div className="match-track"><span /></div>
          <div className="feature-row">
            <div className="feature-icon">01</div>
            <div><strong>One profile</strong><span>Multiple opportunities</span></div>
          </div>
          <div className="feature-row">
            <div className="feature-icon">02</div>
            <div><strong>Clear matching</strong><span>Matched and missing skills</span></div>
          </div>
        </div>
      </section>
    </main>
  );
}

function AuthPage({ register = false, adminLogin = false }) {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const nextPath = searchParams.get("next");
  const { loginSession, logout } = useAuth();
  const [form, setForm] = useState({ full_name: "", email: "", password: "", role: "candidate" });
  const [error, setError] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showResetHelp, setShowResetHelp] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const completeSession = async (data) => {
    if (adminLogin && data.role !== "admin") {
      logout();
      setError("This account does not have administrator access.");
      return;
    }
    loginSession(data);
    if (nextPath && nextPath.startsWith("/")) {
      navigate(nextPath);
    } else {
      navigate(`/${data.role}`);
    }
  };

  const submit = async (event) => {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      if (register) {
        await api.post("/api/auth/register", form);
      }
      const response = await api.post("/api/auth/login", { email: form.email, password: form.password });
      await completeSession(response.data);
    } catch (requestError) {
      setError(await parseApiError(requestError, "Unable to complete the request."));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="auth-page">
      <section className="auth-shell">
        <div className="auth-brand-panel">
          <Link className="auth-brand" to="/">SkillSphere</Link>
          <div>
            <span className="auth-kicker">Your career, clearly mapped</span>
            <h2>{register ? "Build the profile recruiters remember." : adminLogin ? "Manage the SkillSphere platform." : "Turn your skills into opportunities."}</h2>
            <p>{register ? "Create your career profile, upload a resume, and discover roles tailored to your strengths." : adminLogin ? "Sign in with the administrator account configured for this platform." : "Sign in to manage applications, explore matching jobs, and move your career forward."}</p>
          </div>
          <div className="auth-trust">
            <span><strong>10k+</strong> opportunities explored</span>
            <span><strong>Smart</strong> skill matching</span>
          </div>
        </div>
        <form className="auth-card" onSubmit={submit}>
            <span className="eyebrow">{register ? "Create your profile" : adminLogin ? "Platform administration" : "Welcome back"}</span>
            <h1>{register ? "Join SkillSphere" : adminLogin ? "Administrator Login" : "Log in"}</h1>
            {register && <input required minLength="2" placeholder="Full name" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />}
            <input required type="email" placeholder="Email address" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
            <div className="password-field">
              <input required minLength="8" type={showPassword ? "text" : "password"} placeholder="Password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
              <button className="password-toggle" type="button" aria-label={showPassword ? "Hide password" : "Show password"} onClick={() => setShowPassword((visible) => !visible)}>
                {showPassword ? "Hide" : "Show"}
              </button>
            </div>
            {register && (
              <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                <option value="candidate">Job Seeker</option>
                <option value="recruiter">Recruiter</option>
              </select>
            )}
            {error && <p className="error" role="alert">{error}</p>}
            {!register && (
              <div className="forgot-password-row">
                <button className="text-button" type="button" onClick={() => setShowResetHelp((visible) => !visible)}>Forgot password?</button>
              </div>
            )}
            {showResetHelp && <p className="reset-help">Contact your SkillSphere administrator with your registered email address to reset your password securely.</p>}
            <button className="button" type="submit" disabled={submitting}>{submitting ? "Please wait..." : register ? "Create Account" : adminLogin ? "Log in as Administrator" : "Log In"}</button>
            <Link to={register ? "/login" : adminLogin ? "/login" : "/register"}>{register ? "Already have an account? Log in" : adminLogin ? "Return to regular login" : "New here? Create an account"}</Link>
            {!register && !adminLogin && <Link to="/admin/login">Administrator login</Link>}
            {register && <p className="reset-help">Administrator accounts are provisioned by the platform operator; public admin signup is disabled.</p>}
        </form>
      </section>
    </main>
  );
}

function JobsPage() {
  const [jobsPage, setJobsPage] = useState({ items: [], total: 0, page: 1, pages: 0 });
  const [query, setQuery] = useState("");
  const [location, setLocation] = useState("");
  const [employmentType, setEmploymentType] = useState("");
  const [experience, setExperience] = useState("");
  const [experienceMin, setExperienceMin] = useState("");
  const [experienceMax, setExperienceMax] = useState("");
  const [requiredSkill, setRequiredSkill] = useState("");
  const [sortBy, setSortBy] = useState("newest");
  const [message, setMessage] = useState("");
  const [existingApplication, setExistingApplication] = useState(null);
  const [loadingJobs, setLoadingJobs] = useState(true);
  const [matchResult, setMatchResult] = useState(null);
  const [matchHistory, setMatchHistory] = useState([]);
  const [resumes, setResumes] = useState([]);
  const [selectedResumeId, setSelectedResumeId] = useState("");
  const [savedJobIds, setSavedJobIds] = useState([]);
  const { token, role } = useAuth();
  const navigate = useNavigate();
  const processedResumes = resumes.filter((resume) => resume.processing_status === "processed");

  const loadJobs = useCallback(async (page = 1) => {
    if (experienceMin !== "" && experienceMax !== "" && Number(experienceMin) > Number(experienceMax)) {
      setJobsPage({ items: [], total: 0, page: 1, pages: 0 });
      setMessage("Minimum experience cannot exceed maximum experience.");
      setLoadingJobs(false);
      return;
    }
    setLoadingJobs(true);
    try {
      const response = await api.get("/api/jobs", {
        params: {
          q: query || undefined,
          location: location || undefined,
          employment_type: employmentType || undefined,
          experience: experience || undefined,
          skill: requiredSkill || undefined,
          experience_min: experienceMin === "" ? undefined : Number(experienceMin),
          experience_max: experienceMax === "" ? undefined : Number(experienceMax),
          sort_by: sortBy,
          page,
          page_size: 9,
        },
      });
      setJobsPage(response.data);
      setMessage("");
    } catch (requestError) {
      setJobsPage({ items: [], total: 0, page: 1, pages: 0 });
      setMessage(requestError.response?.data?.detail || "Jobs are unavailable until the backend is running and MySQL is configured.");
    } finally {
      setLoadingJobs(false);
    }
  }, [query, location, employmentType, experience, experienceMin, experienceMax, requiredSkill, sortBy]);
  useEffect(() => { loadJobs(1); }, [loadJobs]);
  useEffect(() => {
    if (!token || role !== "candidate") return;
    api.get("/api/resumes/me")
      .then((response) => {
        setResumes(response.data);
        const processed = response.data.find((resume) => resume.processing_status === "processed");
        if (processed) setSelectedResumeId(String(processed.id));
      })
      .catch(() => setMessage("Unable to load your resumes. Please refresh or open your dashboard."));
  }, [token, role]);
  useEffect(() => {
    if (!token || role !== "candidate") {
      setSavedJobIds([]);
      return;
    }
    api.get("/api/candidates/saved-jobs")
      .then((response) => setSavedJobIds(response.data.map((job) => job.id)))
      .catch((requestError) => setMessage(requestError.response?.data?.detail || "Unable to load saved jobs."));
  }, [token, role]);
  useEffect(() => {
    if (!selectedResumeId) {
      setMatchHistory([]);
      return;
    }
    api.get(`/api/matches/resume/${selectedResumeId}`)
      .then((response) => setMatchHistory(response.data))
      .catch((requestError) => {
        setMatchHistory([]);
        setMessage(requestError.response?.data?.detail || "Unable to load previous resume match analyses.");
      });
  }, [selectedResumeId]);

  const apply = async (job) => {
    if (!token) {
      navigate("/login");
      return;
    }
    try {
      const response = await api.post("/api/applications", null, {
        params: {
          job_id: job.id,
          resume_id: selectedResumeId ? Number(selectedResumeId) : undefined,
        },
      });
      const scoreText = response.data?.match_score != null ? ` AI match: ${Number(response.data.match_score).toFixed(1)}%.` : "";
      const statusText = response.data?.status === "shortlisted" ? "You have been automatically shortlisted." : "";
      setMessage(`Application submitted for ${job.title}.${scoreText}${statusText}`);
    } catch (requestError) {
      setMessage(requestError.response?.data?.detail || "Unable to submit the application.");
    }
  };

  const analyzeJob = async (job) => {
    if (!token) {
      navigate("/login");
      return;
    }
    try {
      if (!selectedResumeId) {
        setMessage("Upload a resume before analyzing a job match.");
        return;
      }
      const response = await api.post(`/api/matches/resume/${selectedResumeId}/job/${job.id}`);
      setMatchResult({ jobTitle: job.title, ...response.data });
      setMatchHistory((await api.get(`/api/matches/resume/${selectedResumeId}`)).data);
      setMessage("");
    } catch (requestError) {
      setMessage(requestError.response?.data?.detail || "Unable to analyze this job.");
    }
  };

  const toggleSavedJob = async (job) => {
    if (!token) {
      navigate("/login");
      return;
    }
    if (role !== "candidate") return;
    const isSaved = savedJobIds.includes(job.id);
    try {
      if (isSaved) {
        await api.delete(`/api/candidates/saved-jobs/${job.id}`);
        setSavedJobIds((current) => current.filter((id) => id !== job.id));
        setMessage("Job removed from saved jobs.");
      } else {
        await api.put(`/api/candidates/saved-jobs/${job.id}`);
        setSavedJobIds((current) => [...current, job.id]);
        setMessage("Job saved to your list.");
      }
    } catch (requestError) {
      setMessage(requestError.response?.data?.detail || "Unable to update saved jobs.");
    }
  };

  return (
    <main className="page-content">
      <div className="page-heading"><div><span className="eyebrow">Opportunities</span><h1>Find your next role</h1></div></div>
      <form className="search-bar" onSubmit={(event) => { event.preventDefault(); loadJobs(1); }}>
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search by job title, skill, or location" />
        <input value={location} onChange={(e) => setLocation(e.target.value)} placeholder="Filter by location" />
        <input value={experience} onChange={(e) => setExperience(e.target.value)} placeholder="Experience keywords" />
        <input type="number" min="0" max="60" value={experienceMin} onChange={(e) => setExperienceMin(e.target.value)} placeholder="Min experience (years)" />
        <input type="number" min="0" max="60" value={experienceMax} onChange={(e) => setExperienceMax(e.target.value)} placeholder="Max experience (years)" />
        <input value={requiredSkill} onChange={(e) => setRequiredSkill(e.target.value)} placeholder="Required skill" />
        <select value={employmentType} onChange={(e) => setEmploymentType(e.target.value)} aria-label="Filter by job type">
          <option value="">All job types</option>
          <option value="full_time">Full Time</option>
          <option value="part_time">Part Time</option>
          <option value="contract">Contract</option>
          <option value="internship">Internship</option>
        </select>
        <select value={sortBy} onChange={(e) => setSortBy(e.target.value)} aria-label="Sort job results">
          <option value="newest">Newest first</option>
          <option value="oldest">Oldest first</option>
          <option value="salary_desc">Salary: high to low</option>
          <option value="salary_asc">Salary: low to high</option>
          <option value="title_asc">Job title: A to Z</option>
        </select>
        <button className="button" type="submit">Search</button>
      </form>
      {message && <p className="info-message">{message}</p>}
      {token && processedResumes.length > 0 && (
        <label className="resume-selector">
          Resume for applications
          <select value={selectedResumeId} onChange={(event) => setSelectedResumeId(event.target.value)}>
            {processedResumes.map((resume) => (
              <option key={resume.id} value={resume.id}>{resume.original_filename}</option>
            ))}
          </select>
        </label>
      )}
      {matchResult && (
        <div className="panel match-result">
          <strong>{matchResult.jobTitle}: {matchResult.match_percentage}% match</strong>
          <p>Matched: {matchResult.matched_skills.join(", ") || "None"}</p>
          <p>Missing: {matchResult.missing_skills.join(", ") || "None"}</p>
          {matchResult.relevant_experience && <p>Experience fit: {matchResult.relevant_experience}</p>}
          {matchResult.matching_explanation && <p>{matchResult.matching_explanation}</p>}
          <p>Recommendations: {matchResult.recommendations.join(" ")}</p>
        </div>
      )}
      {matchHistory.length > 0 && (
        <section className="panel match-history">
          <h2>Recent resume matches</h2>
          {matchHistory.filter((match, index, matches) => matches.findIndex((item) => String(item.job_id) === String(match.job_id)) === index).map((match, index) => (
            <div className="match-history-row" key={`${match.job_id}-${match.created_at}-${index}`}>
              <Link to={`/jobs/${match.job_id}`}>{match.job_title} Â· {match.company}</Link>
              <strong>{match.match_percentage}%</strong>
              <span>Matched: {match.matched_skills.join(", ") || "None"}</span>
              <span>Missing: {match.missing_skills.join(", ") || "None"}</span>
            </div>
          ))}
        </section>
      )}
      <div className="job-grid">
        {jobsPage.items.map((job) => (
          <article className="panel job-card" key={job.id}>
            <span className="status">{job.employment_type.replaceAll("_", " ")}</span>
            <h2><Link to={`/jobs/${job.id}`}>{job.title}</Link></h2>
            <div className="job-company"><span className="company-avatar">{job.company.slice(0, 1).toUpperCase()}</span><div><strong>{job.company}</strong><span>{job.location || "Location not specified"}</span></div></div>
            <p className="job-posted">Posted {new Date(job.created_at).toLocaleDateString()}</p>
            <p>{formatExperience(job)} Â· {formatSalary(job)}</p>
            <p>{job.description}</p>
            <div className="chips">{job.skills.map((skill) => <span key={skill}>{skill}</span>)}</div>
            <div className="card-actions">
              <Link className="button button-secondary" to={`/jobs/${job.id}`}>View Details</Link>
              {(!token || role === "candidate") && (
                <>
                  <button className="button" onClick={() => analyzeJob(job)}>Analyze Match</button>
                  <button className="button button-secondary" onClick={() => apply(job)}>Apply</button>
                  {role === "candidate" && <button className="button button-secondary" onClick={() => toggleSavedJob(job)}>{savedJobIds.includes(job.id) ? "Saved" : "Save job"}</button>}
                </>
              )}
            </div>
          </article>
        ))}
      </div>
      {jobsPage.pages > 1 && (
        <div className="pagination">
          <button className="button button-secondary" disabled={jobsPage.page <= 1} onClick={() => loadJobs(jobsPage.page - 1)}>Previous</button>
          <span>Page {jobsPage.page} of {jobsPage.pages} Â· {jobsPage.total} jobs</span>
          <button className="button button-secondary" disabled={jobsPage.page >= jobsPage.pages} onClick={() => loadJobs(jobsPage.page + 1)}>Next</button>
        </div>
      )}
      {loadingJobs && <p className="loading-message" role="status">Loading jobs...</p>}
      {!loadingJobs && !jobsPage.items.length && !message && (
        <div className="panel empty-state">
          <h2>{query ? "No matching jobs found" : "No published jobs yet"}</h2>
          <p>{query
            ? "Try another title, skill, or location."
            : "Recruiters can post jobs after their company is approved. Approved jobs will appear here after admin publication."}</p>
        </div>
      )}
    </main>
  );
}

function formatExperience(job) {
  if (job.experience_min == null && job.experience_max == null) return "Experience not specified";
  if (job.experience_min == null) return `Up to ${job.experience_max} years`;
  if (job.experience_max == null) return `${job.experience_min}+ years`;
  return `${job.experience_min}â€“${job.experience_max} years`;
}

function formatSalary(job) {
  if (job.salary_min == null && job.salary_max == null) return "Salary not specified";
  const currency = job.salary_currency || "USD";
  const minimum = job.salary_min == null ? null : new Intl.NumberFormat(undefined, { style: "currency", currency }).format(job.salary_min);
  const maximum = job.salary_max == null ? null : new Intl.NumberFormat(undefined, { style: "currency", currency }).format(job.salary_max);
  if (!minimum) return `Up to ${maximum}`;
  if (!maximum) return `From ${minimum}`;
  return `${minimum} - ${maximum}`;
}
function AnalyticsChart({ title, data, color }) {
  const maximum = Math.max(1, ...data.map((item) => item.count));
  return (
    <section className="panel analytics-panel">
      <div className="section-heading">
        <div><span className="eyebrow">Last 14 days</span><h2>{title}</h2></div>
        <span className="chart-total">{data.reduce((total, item) => total + item.count, 0)} total</span>
      </div>
      <div className={`chart-bars ${color}`} role="img" aria-label={`${title} over the last 14 days`}>
        {data.map((item) => (
          <div className="chart-bar-group" key={item.date} title={`${item.date}: ${item.count}`}>
            <span className="chart-value">{item.count || ""}</span>
            <span className="chart-bar" style={{ "--bar-height": `${Math.max(4, (item.count / maximum) * 100)}%` }} />
            <span className="chart-date">{item.date.slice(5)}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function AnimatedNumber({ value }) {
  const [displayNumber, setDisplayNumber] = useState(0);
  const target = Number(value) || 0;

  useEffect(() => {
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      setDisplayNumber(target);
      return undefined;
    }
    let frame;
    const startedAt = performance.now();
    const duration = 700;
    const animate = (now) => {
      const progress = Math.min((now - startedAt) / duration, 1);
      setDisplayNumber(Math.round(target * (1 - (1 - progress) ** 3)));
      if (progress < 1) frame = requestAnimationFrame(animate);
    };
    frame = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(frame);
  }, [target]);

  return <strong>{displayNumber}</strong>;
}

function ApplicationProgress({ status }) {
  const stages = [
    ["applied", "Applied"],
    ["under_review", "Under review"],
    ["shortlisted", "Shortlisted"],
    ["interview", "Interview"],
    ["selected", "Selected"],
  ];
  const normalizedStatus = status === "interview_scheduled" ? "interview" : status;
  const completedStage = ["accepted", "hired"].includes(normalizedStatus)
    ? stages.length - 1
    : normalizedStatus === "screening" ? 1 : stages.findIndex(([value]) => value === normalizedStatus);
  const terminalStatus = ["rejected", "withdrawn"].includes(status);

  return (
    <div className={`application-progress${terminalStatus ? " is-terminal" : ""}`} aria-label={`Application progress: ${status.replaceAll("_", " ")}`}>
      {terminalStatus
        ? <span className={`table-status ${status === "rejected" ? "status-rejected" : "status-closed"}`}>{status}</span>
        : stages.map(([value, label], index) => (
          <div className={`progress-step${index <= completedStage ? " is-complete" : ""}`} key={value}>
            <span className="progress-dot" />
            <span>{label}</span>
          </div>
        ))}
      {!terminalStatus && ["accepted", "hired"].includes(status) && (
        <span className="table-status status-active">{status === "hired" ? "Hired (legacy)" : "Accepted"}</span>
      )}
    </div>
  );
}

function JobDetailPage() {
  const { jobId } = useParams();
  const { token, role } = useAuth();
  const navigate = useNavigate();
  const [job, setJob] = useState(null);
  const [loadingJob, setLoadingJob] = useState(true);
  const [resumes, setResumes] = useState([]);
  const [resumeId, setResumeId] = useState("");
  const [match, setMatch] = useState(null);
  const [message, setMessage] = useState("");
  const [existingApplication, setExistingApplication] = useState(null);

  useEffect(() => {
    api.get(`/api/jobs/${jobId}`)
      .then((response) => setJob(response.data))
      .catch((requestError) => setMessage(requestError.response?.data?.detail || "Unable to load this job."))
      .finally(() => setLoadingJob(false));
  }, [jobId]);
  useEffect(() => {
    if (!token || role !== "candidate") return;
    api.get("/api/resumes/me")
      .then((response) => {
        const processedResumes = response.data.filter((resume) => resume.processing_status === "processed");
        setResumes(processedResumes);
        if (processedResumes.length) setResumeId(String(processedResumes[0].id));
      })
      .catch((requestError) => setMessage(requestError.response?.data?.detail || "Unable to load your resumes."));
  }, [token, role]);

  useEffect(() => {
    if (!token || role !== "candidate") {
      setExistingApplication(null);
      return;
    }
    api.get("/api/applications/me")
      .then((response) => {
        const found = response.data.find(
          (item) => String(item.job_id) === String(jobId) && item.status !== "withdrawn"
        );
        setExistingApplication(found || null);
      })
      .catch((error) => console.error("Unable to check existing application:", error));
  }, [token, role, jobId]);

  const apply = async () => {
    if (existingApplication) return;
    if (!token) {
      navigate("/login");
      return;
    }
    try {
      const response = await api.post("/api/applications", null, {
        params: { job_id: job.id, resume_id: resumeId ? Number(resumeId) : undefined },
      });
      const scoreInfo = response.data?.match_score != null ? ` AI match score: ${Number(response.data.match_score).toFixed(1)}%.` : "";
      const shortlistInfo = response.data?.status === "shortlisted" ? " Automatically shortlisted!" : "";
      setMessage(`Application submitted successfully.${scoreInfo}${shortlistInfo}`);
    } catch (requestError) {
      setMessage(requestError.response?.data?.detail || "Unable to submit the application.");
    }
  };

  const analyze = async () => {
    if (!token) {
      navigate("/login");
      return;
    }
    if (!resumeId) {
      setMessage("Upload and process a resume before analyzing this job.");
      return;
    }
    try {
      const response = await api.post(`/api/matches/resume/${resumeId}/job/${job.id}`);
      setMatch(response.data);
      setMessage("");
    } catch (requestError) {
      setMessage(requestError.response?.data?.detail || "Unable to analyze this job.");
    }
  };

  return (
    <main className="page-content">
      <Link to="/jobs" className="back-link">â† Back to Jobs</Link>

      {message && <p className="info-message" role="status">{message}</p>}
      {message && <p className="info-message">{message}</p>}
      {loadingJob && <p className="loading-message" role="status">Loading job details...</p>}
      {job && (
        <article className="panel job-detail">
          <span className="status">{job.employment_type.replaceAll("_", " ")}</span>
          <h1>{job.title}</h1>
          <p className="job-detail-company">{job.company} Â· {job.location || "Location not specified"}</p>
          <div className="job-facts">
            <span>{formatExperience(job)}</span>
            <span>{formatSalary(job)}</span>
            <span>Posted {new Date(job.created_at).toLocaleDateString()}</span>
          </div>
          <h2>About this role</h2>
          <p className="job-description">{job.description}</p>
          <h2>Required skills</h2>
          <div className="chips">{job.skills.length ? job.skills.map((skill) => <span key={skill}>{skill}</span>) : <span>See job description</span>}</div>
          {token && role === "candidate" && resumes.length > 0 && (
            <label className="resume-selector">
              Resume
              <select value={resumeId} onChange={(event) => setResumeId(event.target.value)}>
                {resumes.map((resume) => <option key={resume.id} value={resume.id}>{resume.original_filename}</option>)}
              </select>
            </label>
          )}
          {(!token || role === "candidate") && (
            <div className="card-actions">
              <button className="button" onClick={apply} disabled={!!existingApplication}>{existingApplication ? "Already Applied" : "Apply Now"}</button>
              <button className="button button-secondary" onClick={analyze}>Analyze Resume Match</button>
            </div>
          )}
          {match && (
            <section className="match-result">
              <h2>{match.match_percentage}% skills match</h2>
              <p><strong>Matched:</strong> {match.matched_skills.join(", ") || "None"}</p>
              <p><strong>Missing:</strong> {match.missing_skills.join(", ") || "None"}</p>
              {match.relevant_experience && <p><strong>Experience:</strong> {match.relevant_experience}</p>}
              {match.matching_explanation && <p>{match.matching_explanation}</p>}
              <p><strong>Recommendations:</strong> {match.recommendations.join(" ")}</p>
            </section>
          )}
        </article>
      )}
    </main>
  );
}

function Dashboard({ role }) {
  const navigate = useNavigate();
  const { token, role: sessionRole, fullName, userId, logout } = useAuth();
  const [currentUserId, setCurrentUserId] = useState(userId ? Number(userId) : null);
  const [profile, setProfile] = useState(null);
  const [items, setItems] = useState([]);
  const [stats, setStats] = useState(null);
  const [adminJobs, setAdminJobs] = useState([]);
  const [adminUsers, setAdminUsers] = useState([]);
  const [adminCompanies, setAdminCompanies] = useState([]);
  const [adminTrends, setAdminTrends] = useState({ registrations: [], applications: [] });
  const [assessmentRecordings, setAssessmentRecordings] = useState([]);
  const [activeRecording, setActiveRecording] = useState(null);
  const [recordingPlaybackLoading, setRecordingPlaybackLoading] = useState(null);
  const [systemStatus, setSystemStatus] = useState(null);
  const [recruiterStats, setRecruiterStats] = useState(null);
  const [userSearch, setUserSearch] = useState("");
  const [userRoleFilter, setUserRoleFilter] = useState("");
  const [userStatusFilter, setUserStatusFilter] = useState("");
  const [userPage, setUserPage] = useState(1);
  const [jobSearch, setJobSearch] = useState("");
  const [jobStatusFilter, setJobStatusFilter] = useState("");
  const [jobCompanyFilter, setJobCompanyFilter] = useState("");
  const [jobPage, setJobPage] = useState(1);
  const [message, setMessage] = useState("");
  const [existingApplication, setExistingApplication] = useState(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [profileDraft, setProfileDraft] = useState({
    contact_email: "", phone: "", headline: "", education: "", experience: "",
    projects: "", certifications: "", location: "", summary: "", skills: "",
  });
  const [resumeFile, setResumeFile] = useState(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [saving, setSaving] = useState(false);
  const [companyDraft, setCompanyDraft] = useState({ name: "", description: "", website: "", location: "" });
  const [jobDraft, setJobDraft] = useState({
    title: "", description: "", location: "", employment_type: "full_time",
    experience_min: "", experience_max: "", salary_min: "", salary_max: "",
    salary_currency: "USD", skills: "",
  });
  const [editingJobId, setEditingJobId] = useState(null);

  // Recruiter ATS state
  const [applicants, setApplicants] = useState([]);
  const [applicantsLoading, setApplicantsLoading] = useState(false);
  const [selectedJobId, setSelectedJobId] = useState("");
  const [applicantSkill, setApplicantSkill] = useState("");
  const [applicantExperience, setApplicantExperience] = useState("");
  const [applicantSearch, setApplicantSearch] = useState("");
  const [applicantStatusFilter, setApplicantStatusFilter] = useState("");
  const [applicantSortBy, setApplicantSortBy] = useState("newest");
  const [selectedApplicantDetail, setSelectedApplicantDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [applicantActionBusy, setApplicantActionBusy] = useState(false);
  const [recruiterAssessments, setRecruiterAssessments] = useState([]);
  const [assignModalOpen, setAssignModalOpen] = useState(false);
  const [assignInitialIds, setAssignInitialIds] = useState([]);
  const [resultsRefreshSignal, setResultsRefreshSignal] = useState(0);
  const [candidateInterviews, setCandidateInterviews] = useState([]);
  const [decisionModalState, setDecisionModalState] = useState(null);
  const [interviewModalState, setInterviewModalState] = useState(null);
  const [interviewRefreshSignal, setInterviewRefreshSignal] = useState(0);
  const [retryingCardNotifId, setRetryingCardNotifId] = useState(null);

  const [editingResumeId, setEditingResumeId] = useState(null);
  const [resumeDraft, setResumeDraft] = useState({});
  const [dashboardLoading, setDashboardLoading] = useState(true);
  const [proctoringEvents, setProctoringEvents] = useState([]);
  const [launchingAssessmentId, setLaunchingAssessmentId] = useState(null);

  const clearFeedback = useCallback(() => {
    setMessage("");
    setErrorMessage("");
  }, []);

  const handleCandidateLaunchAssessment = async (application) => {
    if (application.assessment_token) {
      if (application.assessment_type === "video") {
        navigate(`/video-assessment/${application.assessment_token}`);
      } else {
        navigate(`/assessment/${application.assessment_token}`);
      }
      return;
    }
    setLaunchingAssessmentId(application.id);
    clearFeedback();
    try {
      const res = await api.get(`/api/assessments/application/${application.id}/token`);
      if (res.data?.token) {
        if (res.data.assessment_type === "video") {
          navigate(`/video-assessment/${res.data.token}`);
        } else {
          navigate(`/assessment/${res.data.token}`);
        }
      } else {
        setErrorMessage("Assessment link is currently unavailable. Please check your registered email.");
      }
    } catch (launchErr) {
      const msg = await parseApiError(
        launchErr,
        "Unable to start assessment. Please check your registered email or contact support."
      );
      setErrorMessage(msg);
    } finally {
      setLaunchingAssessmentId(null);
    }
  };

  const handleChildFeedback = useCallback((text, isError = false) => {
    if (isError) {
      setMessage("");
      setErrorMessage(text);
    } else {
      setErrorMessage("");
      setMessage(text);
    }
  }, []);

  const openRecordingPlayback = async (recordingId) => {
    setRecordingPlaybackLoading(recordingId);
    setActiveRecording(null);
    try {
      const response = await api.get(`/api/admin/assessment-recordings/${recordingId}/playback`);
      setActiveRecording({ id: recordingId, url: response.data.playback_url });
    } catch (requestError) {
      setErrorMessage(await parseApiError(requestError, "Unable to load recording playback."));
    } finally {
      setRecordingPlaybackLoading(null);
    }
  };
  useEffect(() => {
    if (!token || sessionRole !== role) return;
    const load = async () => {
      setDashboardLoading(true);
      try {
        if (role === "candidate") {
          const [candidate, applications, resumes, savedJobs, interviewsRes] = await Promise.all([
            api.get("/api/candidates/me"),
            api.get("/api/applications/me"),
            api.get("/api/resumes/me"),
            api.get("/api/candidates/saved-jobs"),
            api.get("/api/candidates/interviews").catch(() => ({ data: [] })),
          ]);
          setProfile(candidate.data);
          setItems({
            applications: applications.data,
            resumes: resumes.data,
            savedJobs: savedJobs.data,
          });
          setCandidateInterviews(Array.isArray(interviewsRes?.data) ? interviewsRes.data : []);
          setProfileDraft({
            contact_email: candidate.data.contact_email || "",
            phone: sanitizeDisplayText(candidate.data.phone),
            headline: sanitizeDisplayText(candidate.data.headline),
            education: sanitizeDisplayText(candidate.data.education),
            experience: sanitizeDisplayText(candidate.data.experience),
            projects: sanitizeDisplayText(candidate.data.projects),
            certifications: sanitizeDisplayText(candidate.data.certifications),
            location: sanitizeDisplayText(candidate.data.location),
            summary: sanitizeDisplayText(candidate.data.summary),
            skills: candidate.data.skills?.join(", ") || "",
          });
        } else if (role === "recruiter") {
          const [jobs, recruiterStatsResponse, proctoringEventsResponse] = await Promise.all([
            api.get("/api/recruiters/jobs"),
            api.get("/api/recruiters/stats"),
            api.get("/api/recruiter/proctoring-events").catch(() => ({ data: { items: [] } })),
          ]);
          setItems(jobs.data);
          setRecruiterStats(recruiterStatsResponse.data);
          setProctoringEvents(proctoringEventsResponse.data?.items || []);
          try {
            const comp = (await api.get("/api/companies/me")).data;
            setProfile(comp);
            setCompanyDraft(comp);
          } catch (requestError) {
            if (requestError.response?.status !== 404) throw requestError;
          }
        } else {
          const [statsResponse, jobsResponse, usersResponse, companiesResponse, trendsResponse, identityResponse, proctoringEventsResponse, recordingsResponse] = await Promise.all([
            api.get("/api/admin/stats"),
            api.get("/api/admin/jobs"),
            api.get("/api/admin/users"),
            api.get("/api/admin/companies"),
            api.get("/api/admin/analytics/trends"),
            api.get("/api/auth/me"),
            api.get("/api/admin/proctoring-events").catch(() => ({ data: { items: [] } })),
            api.get('/api/admin/assessment-recordings').catch(() => ({ data: { items: [] } })),
          ]);
          setProctoringEvents(proctoringEventsResponse.data?.items || []);
          setAssessmentRecordings(recordingsResponse.data?.items || []);
          setStats(statsResponse.data);
          setAdminJobs(jobsResponse.data);
          setAdminUsers(usersResponse.data);
          setAdminCompanies(companiesResponse.data);
          setAdminTrends(trendsResponse.data);
          setCurrentUserId(identityResponse.data.id);
          try {
            const sysRes = await api.get("/api/admin/system-status");
            setSystemStatus(sysRes.data);
          } catch {
            // Optional when mocked in unit tests
          }
        }
      } catch (requestError) {
        setErrorMessage(await parseApiError(requestError, "Unable to load dashboard data."));
      } finally {
        setDashboardLoading(false);
      }
    };
    load();
  }, [role, sessionRole, token]);

  const saveProfile = async (event) => {
    event.preventDefault();
    setSaving(true);
    clearFeedback();
    try {
      await api.put("/api/candidates/me", {
        ...profileDraft,
        contact_email: profileDraft.contact_email || null,
        skills: profileDraft.skills.split(",").map((skill) => skill.trim()).filter(Boolean),
      });
      const candidate = await api.get("/api/candidates/me");
      setProfile(candidate.data);
      setMessage("Profile saved successfully.");
    } catch (requestError) {
      setErrorMessage(await parseApiError(requestError, "Unable to save the profile."));
    } finally {
      setSaving(false);
    }
  };

  const uploadResume = async (event) => {
    event.preventDefault();
    clearFeedback();
    if (!resumeFile) {
      setErrorMessage("Please select a PDF, DOC, DOCX, JPG, JPEG, or PNG resume first.");
      return;
    }
    const ext = `.${(resumeFile.name.split(".").pop() || "").toLowerCase()}`;
    if (!ALLOWED_RESUME_MIME_TYPES.has(resumeFile.type) && ![".pdf", ".doc", ".docx", ".jpg", ".jpeg", ".png"].includes(ext)) {
      setErrorMessage("The selected file must be a PDF, DOC, DOCX, JPG, JPEG, or PNG.");
      return;
    }
    if (resumeFile.size > 10 * 1024 * 1024) {
      setErrorMessage("Resume must not exceed 10 MB.");
      return;
    }
    setSaving(true);
    try {
      const formData = new FormData();
      formData.append("file", resumeFile);
      await api.post("/api/resumes/upload", formData, {
        onUploadProgress: (progressEvent) => {
          if (progressEvent.total) {
            setUploadProgress(Math.round((progressEvent.loaded / progressEvent.total) * 100));
          }
        },
      });
      const resumes = await api.get("/api/resumes/me");
      setItems((current) => ({ ...current, resumes: resumes.data }));
      setResumeFile(null);
      setUploadProgress(0);
      event.target.reset();
      const newResume = resumes.data[0];
      setMessage(newResume.processing_status === "processed"
        ? "Resume uploaded and processed successfully."
        : newResume.processing_error || "Resume processing failed.");
    } catch (requestError) {
      const uploadError = await parseApiError(requestError, "Unable to upload the resume.");
      try {
        const resumes = await api.get("/api/resumes/me");
        setItems((current) => ({ ...current, resumes: resumes.data }));
        setErrorMessage(uploadError);
      } catch {
        setErrorMessage(`${uploadError} Also could not refresh the resume list.`);
      }
    } finally {
      setSaving(false);
      setUploadProgress(0);
    }
  };

  const saveCompany = async (event) => {
    event.preventDefault();
    setSaving(true);
    clearFeedback();
    try {
      await api[profile ? "put" : "post"]("/api/companies", companyDraft);
      setProfile((await api.get("/api/companies/me")).data);
      setMessage("Company profile saved successfully.");
    } catch (requestError) {
      setErrorMessage(await parseApiError(requestError, "Unable to save company profile."));
    } finally {
      setSaving(false);
    }
  };

  const downloadResume = async (resume) => {
    clearFeedback();
    if (!resume?.id) {
      setErrorMessage("No resume file is attached to this application.");
      return;
    }
    try {
      const response = await api.get(`/api/resumes/${resume.id}/download`, { responseType: "blob" });
      const url = window.URL.createObjectURL(response.data);
      const link = document.createElement("a");
      link.href = url;
      link.download = resume.original_filename || "resume.pdf";
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
      setMessage(`Downloading ${resume.original_filename || "resume"}...`);
    } catch (requestError) {
      setErrorMessage(await parseApiError(requestError, "Unable to download resume."));
    }
  };

  const deleteResume = async (resume) => {
    if (!window.confirm(`Delete "${resume.original_filename}"?`)) return;
    clearFeedback();
    try {
      await api.delete(`/api/resumes/${resume.id}`);
      setItems((current) => ({
        ...current,
        resumes: current.resumes.filter((item) => item.id !== resume.id),
      }));
      setMessage("Resume deleted.");
    } catch (requestError) {
      setErrorMessage(await parseApiError(requestError, "Unable to delete this resume."));
    }
  };

  const removeSavedJob = async (job) => {
    clearFeedback();
    try {
      await api.delete(`/api/candidates/saved-jobs/${job.id}`);
      setItems((current) => ({
        ...current,
        savedJobs: (current.savedJobs || []).filter((item) => item.id !== job.id),
      }));
      setMessage("Job removed from saved jobs.");
    } catch (requestError) {
      setErrorMessage(await parseApiError(requestError, "Unable to remove saved job."));
    }
  };

  const reviewResume = async (resume, extractedData) => {
    clearFeedback();
    try {
      const data = {
        ...extractedData,
        email: extractedData.email || null,
        skills: extractedData.skills.split(",").map((skill) => skill.trim()).filter(Boolean),
      };
      await api.patch(`/api/resumes/${resume.id}/review`, data);
      const candidate = await api.get("/api/candidates/me");
      setProfile(candidate.data);
      setProfileDraft((current) => ({
        ...current,
        contact_email: candidate.data.contact_email || "",
        phone: sanitizeDisplayText(candidate.data.phone),
        education: sanitizeDisplayText(candidate.data.education),
        experience: sanitizeDisplayText(candidate.data.experience),
        projects: sanitizeDisplayText(candidate.data.projects),
        certifications: sanitizeDisplayText(candidate.data.certifications),
        skills: candidate.data.skills.join(", "),
      }));
      setItems((current) => ({
        ...current,
        resumes: current.resumes.map((item) => item.id === resume.id
          ? { ...item, extracted_data: data, is_reviewed: true }
          : item),
      }));
      setEditingResumeId(null);
      setMessage("Resume review saved.");
    } catch (requestError) {
      setErrorMessage(await parseApiError(requestError, "Unable to review resume."));
    }
  };

  const createJob = async (event) => {
    event.preventDefault();
    clearFeedback();
    if (
      jobDraft.experience_min !== "" &&
      jobDraft.experience_max !== "" &&
      Number(jobDraft.experience_min) > Number(jobDraft.experience_max)
    ) {
      setErrorMessage("Minimum experience cannot exceed maximum experience.");
      return;
    }
    if (
      jobDraft.salary_min !== "" &&
      jobDraft.salary_max !== "" &&
      Number(jobDraft.salary_min) > Number(jobDraft.salary_max)
    ) {
      setErrorMessage("Minimum salary cannot exceed maximum salary.");
      return;
    }
    if ((jobDraft.salary_min || jobDraft.salary_max) && !/^[A-Z]{3}$/.test(jobDraft.salary_currency)) {
      setErrorMessage("Enter a three-letter currency code, for example INR or USD.");
      return;
    }
    setSaving(true);
    try {
      const payload = {
        ...jobDraft,
        experience_min: jobDraft.experience_min === "" ? null : Number(jobDraft.experience_min),
        experience_max: jobDraft.experience_max === "" ? null : Number(jobDraft.experience_max),
        salary_min: jobDraft.salary_min === "" ? null : Number(jobDraft.salary_min),
        salary_max: jobDraft.salary_max === "" ? null : Number(jobDraft.salary_max),
        salary_currency: jobDraft.salary_min || jobDraft.salary_max ? jobDraft.salary_currency : null,
        skills: jobDraft.skills.split(",").map((skill) => skill.trim()).filter(Boolean),
      };
      if (editingJobId) {
        await api.put(`/api/recruiters/jobs/${editingJobId}`, payload);
      } else {
        await api.post("/api/recruiters/jobs", payload);
      }
      setItems((await api.get("/api/recruiters/jobs")).data);
      setRecruiterStats((await api.get("/api/recruiters/stats")).data);
      setJobDraft({
        title: "", description: "", location: "", employment_type: "full_time",
        experience_min: "", experience_max: "", salary_min: "", salary_max: "",
        salary_currency: "USD", skills: "",
      });
      setMessage(editingJobId
        ? "Job updated. Changes to a published job require admin approval."
        : "Job posted for admin approval.");
      setEditingJobId(null);
    } catch (requestError) {
      setErrorMessage(await parseApiError(requestError, "Unable to create job."));
    } finally {
      setSaving(false);
    }
  };

  const loadApplicants = async (jobId = selectedJobId, overrides = {}) => {
    const targetJobId = jobId === "all" ? "" : jobId;
    setApplicantsLoading(true);
    clearFeedback();
    try {
      const params = {
        q: overrides.q !== undefined ? (overrides.q || undefined) : (applicantSearch || undefined),
        skill: overrides.skill !== undefined ? (overrides.skill || undefined) : (applicantSkill || undefined),
        experience: overrides.experience !== undefined ? (overrides.experience || undefined) : (applicantExperience || undefined),
        status: overrides.status !== undefined ? (overrides.status || undefined) : (applicantStatusFilter || undefined),
        sort_by: overrides.sort_by || applicantSortBy || "newest",
      };
      const endpoint = targetJobId
        ? `/api/recruiters/jobs/${targetJobId}/applicants`
        : "/api/recruiter/applicants";
      const response = await api.get(endpoint, { params });
      setApplicants(response.data);
      setSelectedJobId(targetJobId ? String(targetJobId) : "all");
    } catch (requestError) {
      setErrorMessage(await parseApiError(requestError, "Unable to load applicants."));
    } finally {
      setApplicantsLoading(false);
    }
  };

  const resetApplicantFilters = () => {
    setApplicantSearch("");
    setApplicantSkill("");
    setApplicantExperience("");
    setApplicantStatusFilter("");
    setApplicantSortBy("newest");
    loadApplicants(selectedJobId || "all", {
      q: "",
      skill: "",
      experience: "",
      status: "",
      sort_by: "newest",
    });
  };

  const openCandidateProfile = async (applicationId) => {
    clearFeedback();
    setDetailLoading(true);
    const preview = applicants.find((a) => a.id === applicationId) || null;
    setSelectedApplicantDetail(preview);
    try {
      const response = await api.get(`/api/recruiter/applicants/${applicationId}`);
      setSelectedApplicantDetail(response.data);
    } catch (requestError) {
      setErrorMessage(await parseApiError(requestError, "Unable to load full candidate profile."));
    } finally {
      setDetailLoading(false);
    }
  };

  const openAssignModal = async (initialIds = []) => {
    setAssignInitialIds(initialIds);
    if (!selectedJobId && !applicants.length) {
      await loadApplicants("all");
    }
    setAssignModalOpen(true);
  };

  const triggerApplicantMatch = async (applicationId) => {
    clearFeedback();
    setApplicantActionBusy(true);
    try {
      const response = await api.post(`/api/recruiter/applicants/${applicationId}/match`, null, {
        params: { force_refresh: true },
      });
      const updatedApplicant = response.data.applicant;
      setApplicants((current) =>
        current.map((item) => (item.id === applicationId ? { ...item, ...updatedApplicant } : item))
      );
      if (selectedApplicantDetail?.id === applicationId) {
        setSelectedApplicantDetail(updatedApplicant);
      }
      setRecruiterStats((await api.get("/api/recruiters/stats")).data);
      const invErr = response.data?.invitation?.error;
      if (invErr) {
        setMessage(`Match evaluated (${Number(response.data.match_score).toFixed(1)}%). ${response.data.shortlist_note || ""}`);
        setErrorMessage(`Assessment email not sent: ${invErr}`);
      } else {
        setMessage(`AI match updated (${Number(response.data.match_score).toFixed(1)}%). ${response.data.shortlist_note || ""}`);
      }
    } catch (requestError) {
      setErrorMessage(await parseApiError(requestError, "Unable to evaluate AI match."));
    } finally {
      setApplicantActionBusy(false);
    }
  };

  const triggerBatchMatch = async () => {
    if (!selectedJobId || selectedJobId === "all") {
      setErrorMessage("Select a specific job posting to batch-evaluate its applicants.");
      return;
    }
    clearFeedback();
    setApplicantActionBusy(true);
    try {
      const res = await api.post(`/api/recruiter/jobs/${selectedJobId}/match-all`, null, {
        params: { force_refresh: false },
      });
      await loadApplicants(selectedJobId);
      setRecruiterStats((await api.get("/api/recruiters/stats")).data);
      setMessage(
        `Evaluated ${res.data.processed} applicant(s). Auto-shortlisted: ${res.data.auto_shortlisted}. Select shortlisted candidates and click "Assign Assessment" when ready.`
      );
    } catch (requestError) {
      setErrorMessage(await parseApiError(requestError, "Unable to batch-evaluate applicants."));
    } finally {
      setApplicantActionBusy(false);
    }
  };

  const editJob = (job) => {
    setEditingJobId(job.id);
    setJobDraft({
      title: job.title,
      description: job.description,
      location: job.location || "",
      employment_type: job.employment_type,
      experience_min: job.experience_min ?? "",
      experience_max: job.experience_max ?? "",
      salary_min: job.salary_min ?? "",
      salary_max: job.salary_max ?? "",
      salary_currency: job.salary_currency || "USD",
      skills: job.skills.join(", "),
    });
  };

  const updateRecruiterJobStatus = async (job, statusValue) => {
    clearFeedback();
    try {
      await api.patch(`/api/recruiters/jobs/${job.id}/status`, null, { params: { status_value: statusValue } });
      setItems((current) => current.map((item) => item.id === job.id ? { ...item, status: statusValue } : item));
      setMessage(statusValue === "closed" ? "Job posting closed." : "Job posting reopened.");
    } catch (requestError) {
      setErrorMessage(await parseApiError(requestError, "Unable to update job posting."));
    }
  };

  const deleteRecruiterJob = async (job) => {
    if (!window.confirm(`Delete "${job.title}"? This cannot be undone.`)) return;
    clearFeedback();
    try {
      await api.delete(`/api/recruiters/jobs/${job.id}`);
      setItems((current) => current.filter((item) => item.id !== job.id));
      setMessage("Job deleted.");
    } catch (requestError) {
      setErrorMessage(await parseApiError(requestError, "Unable to delete this job."));
    }
  };

  const withdrawApplication = async (application) => {
    if (!window.confirm(`Withdraw your application for "${application.job}"?`)) return;
    clearFeedback();
    try {
      await api.delete(`/api/applications/${application.id}`);
      setItems((current) => ({
        ...current,
        applications: current.applications.map((item) =>
          item.id === application.id ? { ...item, status: "withdrawn" } : item),
      }));
      setMessage("Application withdrawn.");
    } catch (requestError) {
      setErrorMessage(await parseApiError(requestError, "Unable to withdraw this application."));
    }
  };

  const updateApplicantStatus = async (applicationId, statusValue) => {
    if (statusValue === "rejected" && !window.confirm("Mark this applicant as Rejected?")) {
      return;
    }
    clearFeedback();
    setApplicantActionBusy(true);
    try {
      const response = await api.put(`/api/applications/${applicationId}/status`, { status: statusValue });
      setApplicants((current) =>
        current.map((applicant) =>
          applicant.id === applicationId
            ? {
                ...applicant,
                status: response.data.status,
                shortlist_source: response.data.shortlist_source,
                manual_status_override: response.data.manual_status_override,
                status_history: response.data.status_history || applicant.status_history,
              }
            : applicant
        )
      );
      if (selectedApplicantDetail?.id === applicationId) {
        setSelectedApplicantDetail((prev) =>
          prev
            ? {
                ...prev,
                status: response.data.status,
                shortlist_source: response.data.shortlist_source,
                manual_status_override: response.data.manual_status_override,
                status_history: response.data.status_history || prev.status_history,
              }
            : prev
        );
      }
      setRecruiterStats((await api.get("/api/recruiters/stats")).data);
      setMessage(`Application status updated to ${formatStatusLabel(statusValue)}.`);
    } catch (requestError) {
      setErrorMessage(await parseApiError(requestError, "Unable to update application."));
    } finally {
      setApplicantActionBusy(false);
    }
  };

  const handleDecisionCompleted = async (result) => {
    const targetId = result?.application_id || result?.id || result?.applicant?.id;
    const updatedApplicant = result?.applicant;
    if (targetId) {
      const mergeDecisionFields = (prev) => ({
        ...prev,
        ...(updatedApplicant || {}),
        status: result.status ?? updatedApplicant?.status ?? prev.status,
        decision_reason: result.decision_reason ?? updatedApplicant?.decision_reason ?? prev.decision_reason,
        decision_note: result.decision_note ?? updatedApplicant?.decision_note ?? prev.decision_note,
        decided_at: result.decided_at ?? updatedApplicant?.decided_at ?? prev.decided_at,
        decided_by_user_id: result.decided_by_user_id ?? updatedApplicant?.decided_by_user_id ?? prev.decided_by_user_id,
        shortlist_source: result.shortlist_source ?? updatedApplicant?.shortlist_source ?? prev.shortlist_source,
        manual_status_override: result.manual_status_override ?? updatedApplicant?.manual_status_override ?? prev.manual_status_override,
        status_history: result.status_history || updatedApplicant?.status_history || prev.status_history,
        latest_email_notification: result.notification || updatedApplicant?.latest_email_notification || prev.latest_email_notification,
      });
      setApplicants((current) =>
        current.map((applicant) => (applicant.id === targetId ? mergeDecisionFields(applicant) : applicant))
      );
      if (selectedApplicantDetail?.id === targetId) {
        setSelectedApplicantDetail((prev) => (prev ? mergeDecisionFields(prev) : prev));
      }
    }
    try {
      setRecruiterStats((await api.get("/api/recruiters/stats")).data);
    } catch {
      // Non-blocking refresh after committed decision.
    }
    setInterviewRefreshSignal((n) => n + 1);
    clearFeedback();
    const resolvedStatus = result?.status || updatedApplicant?.status || "updated";
    const statusText = result?.decision_changed === false
      ? `Candidate status remains ${formatStatusLabel(resolvedStatus)}.`
      : `Candidate status updated to ${formatStatusLabel(resolvedStatus)}.`;
    const sentSuffix = result?.notification_status === "sent" ? " Candidate email sent." : "";
    setMessage(`${statusText}${sentSuffix}`);
    if (result?.notification_status === "failed" || result?.notification?.status === "failed") {
      const detail = result?.notification?.error_message || "SMTP delivery failed.";
      setErrorMessage(`Decision saved, but email notification failed (${detail}). Retry from Email Logs.`);
    }
  };

  const handleInterviewCompleted = async (result, mode) => {
    const interviewObj = result?.interview || result;
    const appId = interviewObj?.application_id;
    const appStatus = interviewObj?.application_status;

    setInterviewRefreshSignal((n) => n + 1);
    if (selectedJobId) {
      await loadApplicants(selectedJobId);
    } else if (appId && appStatus) {
      setApplicants((current) =>
        current.map((item) =>
          item.id === appId
            ? {
                ...item,
                status: appStatus,
                latest_email_notification: result?.notification || item.latest_email_notification,
              }
            : item
        )
      );
    }
    if (selectedApplicantDetail?.id && appId === selectedApplicantDetail.id && appStatus) {
      setSelectedApplicantDetail((prev) =>
        prev ? { ...prev, status: appStatus } : prev
      );
    }
    try {
      setRecruiterStats((await api.get("/api/recruiters/stats")).data);
    } catch {
      // Non-blocking refresh.
    }
    clearFeedback();
    const labels = {
      schedule: "Interview scheduled successfully.",
      reschedule:
        result?.changed === false
          ? "No changes detected on interview."
          : result?.rescheduled === false
            ? "Internal interview details updated."
            : "Interview rescheduled successfully.",
      cancel: "Interview cancelled.",
      feedback: "Interview feedback and outcome saved.",
    };
    const sentSuffix = result?.notification_status === "sent" ? " Candidate email sent." : "";
    setMessage(`${labels[mode] || "Interview updated."}${sentSuffix}`);
    if (result?.notification_status === "failed" || result?.notification?.status === "failed") {
      const detail = result?.notification?.error_message || "SMTP delivery failed.";
      setErrorMessage(`Interview saved, but email notification failed (${detail}). Retry from Email Logs.`);
    }
  };

  const handleRetryCardNotification = async (notificationId) => {
    if (!notificationId || retryingCardNotifId === notificationId) return;
    setRetryingCardNotifId(notificationId);
    try {
      const res = await api.post(`/api/recruiter/notifications/${notificationId}/resend`);
      setInterviewRefreshSignal((n) => n + 1);
      if (selectedJobId) {
        await loadApplicants(selectedJobId);
      } else if (res?.data?.notification) {
        setApplicants((current) =>
          current.map((item) =>
            item.latest_email_notification?.id === notificationId
              ? { ...item, latest_email_notification: res.data.notification }
              : item
          )
        );
      }
      clearFeedback();
      setMessage(res?.data?.message || "Email notification resent.");
    } catch (requestError) {
      clearFeedback();
      setErrorMessage(await parseApiError(requestError, "Failed to resend email notification."));
      setInterviewRefreshSignal((n) => n + 1);
    } finally {
      setRetryingCardNotifId(null);
    }
  };

  const updateJobStatus = async (jobId, statusValue) => {
    const job = adminJobs.find((item) => item.id === jobId);
    if (statusValue === "disabled" && job?.status !== "disabled"
      && !window.confirm(`Disable "${job.title}"? It will no longer appear in job search.`)) return;
    clearFeedback();
    try {
      await api.patch(`/api/admin/jobs/${jobId}/status`, null, { params: { status_value: statusValue } });
      setAdminJobs((current) => current.map((j) => j.id === jobId ? { ...j, status: statusValue } : j));
      setMessage("Job status updated.");
    } catch (requestError) {
      setErrorMessage(await parseApiError(requestError, "Unable to update job status."));
    }
  };

  const updateUserStatus = async (userId, isActive) => {
    const target = adminUsers.find((item) => item.id === userId);
    if (isActive && !window.confirm(`Disable the account for ${target?.full_name || "this user"}?`)) return;
    clearFeedback();
    try {
      await api.patch(`/api/admin/users/${userId}/status`, null, { params: { is_active: !isActive } });
      setAdminUsers((current) => current.map((user) => user.id === userId ? { ...user, is_active: !isActive } : user));
      setMessage(`User ${isActive ? "disabled" : "enabled"} successfully.`);
    } catch (requestError) {
      setErrorMessage(await parseApiError(requestError, "Unable to update user status."));
    }
  };

  const updateCompanyStatus = async (companyId, isApproved) => {
    clearFeedback();
    try {
      await api.patch(`/api/admin/companies/${companyId}/status`, null, { params: { is_approved: !isApproved } });
      setAdminCompanies((current) => current.map((company) =>
        company.id === companyId ? { ...company, is_approved: !isApproved } : company));
      setMessage(`Company ${isApproved ? "rejected" : "approved"} successfully.`);
    } catch (requestError) {
      setErrorMessage(await parseApiError(requestError, "Unable to update company status."));
    }
  };

  const adminPageSize = 6;
  const filteredUsers = adminUsers.filter((user) => {
    const matchesSearch = `${user.full_name} ${user.email}`.toLowerCase().includes(userSearch.toLowerCase());
    const matchesRole = !userRoleFilter || user.role === userRoleFilter;
    const matchesStatus = !userStatusFilter || String(user.is_active) === userStatusFilter;
    return matchesSearch && matchesRole && matchesStatus;
  });
  const filteredJobs = adminJobs.filter((job) => {
    const matchesSearch = `${job.title} ${job.company}`.toLowerCase().includes(jobSearch.toLowerCase());
    return matchesSearch
      && (!jobStatusFilter || job.status === jobStatusFilter)
      && (!jobCompanyFilter || job.company === jobCompanyFilter);
  });
  const userPageCount = Math.ceil(filteredUsers.length / adminPageSize);
  const jobPageCount = Math.ceil(filteredJobs.length / adminPageSize);
  const pagedUsers = filteredUsers.slice((userPage - 1) * adminPageSize, userPage * adminPageSize);
  const pagedJobs = filteredJobs.slice((jobPage - 1) * adminPageSize, jobPage * adminPageSize);

  const normalizedApplicantSearch = applicantSearch.trim().toLowerCase();
  const filteredApplicants = applicants
    .filter((applicant) => {
      const candidateName = String(applicant.candidate || "").toLowerCase();
      const candidateEmail = String(applicant.email || "").toLowerCase();
      const jobTitle = String(applicant.job_title || "").toLowerCase();
      const skillsText = (applicant.skills || []).join(" ").toLowerCase();
      const matchesSearch = !normalizedApplicantSearch
        || candidateName.includes(normalizedApplicantSearch)
        || candidateEmail.includes(normalizedApplicantSearch)
        || jobTitle.includes(normalizedApplicantSearch)
        || skillsText.includes(normalizedApplicantSearch);
      const matchesSkill = !applicantSkill.trim()
        || (applicant.skills || []).some((s) => s.toLowerCase().includes(applicantSkill.trim().toLowerCase()));
      const matchesExperience = !applicantExperience.trim()
        || String(applicant.experience || "").toLowerCase().includes(applicantExperience.trim().toLowerCase());
      const matchesStatus = !applicantStatusFilter || applicant.status === applicantStatusFilter;
      return matchesSearch && matchesSkill && matchesExperience && matchesStatus;
    })
    .sort((a, b) => {
      if (applicantSortBy === "oldest") {
        return new Date(a.applied_at) - new Date(b.applied_at);
      }
      if (applicantSortBy === "match_desc") {
        return (b.match_score ?? -1) - (a.match_score ?? -1);
      }
      if (applicantSortBy === "match_asc") {
        return (a.match_score ?? 999) - (b.match_score ?? 999);
      }
      return new Date(b.applied_at) - new Date(a.applied_at);
    });

  const pipelineStages = APPLICATION_STATUS_OPTIONS.map((opt) => [opt.value, opt.label]);

  if (!token) return <Navigate to="/login" replace />;
  if (sessionRole !== role) return <Navigate to={sessionRole ? `/${sessionRole}` : "/login"} replace />;
  return (
    <main className="page-content" id={`${role}-dashboard`}>
      <div className="page-heading"><div><span className="eyebrow">{role} workspace</span><h1>Welcome, {fullName}</h1></div></div>
      {message && <p className="info-message" role="status">{message}</p>}
      {errorMessage && <p className="error" role="alert">{errorMessage}</p>}
      {dashboardLoading && <p className="loading-message" role="status">Loading dashboard...</p>}
      <div className={role === "admin" ? "dashboard-grid admin-shell" : role === "candidate" || role === "recruiter" ? "dashboard-grid workspace-shell" : "dashboard-grid"}>
        {role === "candidate" && <>
          <aside className="workspace-sidebar">
            <div className="admin-identity"><span className="admin-avatar">{(fullName || "C").slice(0, 1).toUpperCase()}</span><div><strong>{fullName}</strong><span>Candidate</span></div></div>
            <a className="active" href="#candidate-dashboard">Dashboard</a>
            <Link to="/jobs">Find jobs</Link>
            <a href="#candidate-saved-jobs">Saved jobs</a>
            <a href="#candidate-applications">Applications</a>
            <a href="#candidate-interviews">Interviews ({candidateInterviews.length})</a>
            <a href="#candidate-profile">My profile</a>
            <a href="#candidate-resume">Resume and edit</a>
          </aside>
          <div className="workspace-main">
          <section className="panel profile-form-panel" id="candidate-profile">
            <h2>My Profile</h2>
            <form className="profile-form" onSubmit={saveProfile}>
              <input type="email" placeholder="Contact email" value={profileDraft.contact_email} onChange={(event) => setProfileDraft({ ...profileDraft, contact_email: event.target.value })} />
              <input placeholder="Headline" value={profileDraft.headline} onChange={(event) => setProfileDraft({ ...profileDraft, headline: event.target.value })} />
              <input placeholder="Phone number" value={profileDraft.phone} onChange={(event) => setProfileDraft({ ...profileDraft, phone: event.target.value })} />
              <input placeholder="Location" value={profileDraft.location} onChange={(event) => setProfileDraft({ ...profileDraft, location: event.target.value })} />
              <textarea placeholder="Education" value={profileDraft.education} onChange={(event) => setProfileDraft({ ...profileDraft, education: event.target.value })} />
              <textarea placeholder="Experience" value={profileDraft.experience} onChange={(event) => setProfileDraft({ ...profileDraft, experience: event.target.value })} />
              <textarea placeholder="Projects" value={profileDraft.projects} onChange={(event) => setProfileDraft({ ...profileDraft, projects: event.target.value })} />
              <textarea placeholder="Certifications" value={profileDraft.certifications} onChange={(event) => setProfileDraft({ ...profileDraft, certifications: event.target.value })} />
              <textarea className="full-width" placeholder="Professional summary" value={profileDraft.summary} onChange={(event) => setProfileDraft({ ...profileDraft, summary: event.target.value })} />
              <input className="full-width" placeholder="Skills (comma separated)" value={profileDraft.skills} onChange={(event) => setProfileDraft({ ...profileDraft, skills: event.target.value })} />
              <button className="button full-width" type="submit" disabled={saving}>{saving ? "Saving..." : "Save Profile"}</button>
            </form>
          </section>
          <section className="panel" id="candidate-resume">
            <h2>Resume</h2>
            <form className="resume-upload" onSubmit={uploadResume}>
              <input type="file" accept=".pdf,.doc,.docx,.jpg,.jpeg,.png,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,image/jpeg,image/png" onChange={(event) => setResumeFile(event.target.files?.[0] || null)} />
              <button className="button" type="submit" disabled={saving}>
                {saving ? "Uploading..." : resumeFile ? "Upload Resume" : "Select Resume & Upload"}
              </button>
              {saving && resumeFile && <div className="upload-progress" role="status"><span style={{ width: `${uploadProgress}%` }} /><small>{uploadProgress}% uploaded Â· resume processing continues on the server</small></div>}
            </form>
            {items.resumes?.length ? items.resumes.map((resume) => (
              <div className="resume-row" key={resume.id}>
                <strong>{resume.original_filename}</strong>
                <span className={resume.processing_status === "failed" ? "resume-error" : ""}>
                  {resume.processing_status === "failed"
                    ? resume.processing_error || "Resume processing failed."
                    : resume.is_reviewed ? "Reviewed" : "Processed"}
                </span>
                <div className="card-actions">
                  <button type="button" className="button button-secondary" onClick={() => downloadResume(resume)}>Download</button>
                  <button type="button" className="button button-secondary" onClick={() => deleteResume(resume)}>Delete</button>
                  {resume.processing_status === "processed" && (
                    <button
                      type="button"
                      className="button"
                      onClick={() => {
                        setEditingResumeId(resume.id);
                        setResumeDraft({
                          full_name: sanitizeDisplayText(resume.extracted_data.full_name),
                          email: resume.extracted_data.email || "",
                          phone: sanitizeDisplayText(resume.extracted_data.phone),
                          education: sanitizeDisplayText(resume.extracted_data.education),
                          experience: sanitizeDisplayText(resume.extracted_data.experience),
                          projects: sanitizeDisplayText(resume.extracted_data.projects),
                          certifications: sanitizeDisplayText(resume.extracted_data.certifications),
                          skills: (resume.extracted_data.skills || []).join(", "),
                        });
                      }}
                    >
                      {resume.is_reviewed ? "Edit extracted data" : "Review extracted data"}
                    </button>
                  )}
                </div>
                {resume.page_text?.length > 0 && (
                  <details>
                    <summary>View extracted text by page</summary>
                    {resume.page_text.map((pageText, pageIndex) => (
                      <div className="resume-page-text" key={`${resume.id}-page-${pageIndex}`}>
                        <strong>Page {pageIndex + 1}</strong>
                        <pre>{pageText || "No text found on this page."}</pre>
                      </div>
                    ))}
                  </details>
                )}
                {editingResumeId === resume.id && (
                  <form
                    className="profile-form resume-review-form"
                    onSubmit={(event) => {
                      event.preventDefault();
                      reviewResume(resume, resumeDraft);
                    }}
                  >
                    <input placeholder="Full name" value={resumeDraft.full_name} onChange={(event) => setResumeDraft({ ...resumeDraft, full_name: event.target.value })} />
                    <input type="email" placeholder="Email" value={resumeDraft.email} onChange={(event) => setResumeDraft({ ...resumeDraft, email: event.target.value })} />
                    <input placeholder="Phone" value={resumeDraft.phone} onChange={(event) => setResumeDraft({ ...resumeDraft, phone: event.target.value })} />
                    <input placeholder="Education" value={resumeDraft.education} onChange={(event) => setResumeDraft({ ...resumeDraft, education: event.target.value })} />
                    <textarea placeholder="Experience" value={resumeDraft.experience} onChange={(event) => setResumeDraft({ ...resumeDraft, experience: event.target.value })} />
                    <textarea placeholder="Projects" value={resumeDraft.projects} onChange={(event) => setResumeDraft({ ...resumeDraft, projects: event.target.value })} />
                    <textarea placeholder="Certifications" value={resumeDraft.certifications} onChange={(event) => setResumeDraft({ ...resumeDraft, certifications: event.target.value })} />
                    <input className="full-width" placeholder="Skills (comma separated)" value={resumeDraft.skills} onChange={(event) => setResumeDraft({ ...resumeDraft, skills: event.target.value })} />
                    <button className="button" type="submit">Save corrections</button>
                    <button className="button button-secondary" type="button" onClick={() => setEditingResumeId(null)}>Cancel</button>
                  </form>
                )}
              </div>
            )) : <p>No resume uploaded yet.</p>}
          </section>
          <section className="panel" id="candidate-applications">
            <h2>Applications</h2>
            {items.applications?.length ? items.applications.map((application) => {
              const appInterviews = candidateInterviews
                .filter((iv) => iv.application_id === application.id)
                .sort((a, b) => new Date(a.scheduled_at) - new Date(b.scheduled_at));
              return (
                <div className="application-row" key={application.id}>
                  <div style={{ flex: 1 }}>
                    <p>
                      <Link to={`/jobs/${application.job_id}`}>{application.job}</Link> at {application.company}{" "}
                      <span className={getStatusBadgeClass(application.status)}>{formatStatusLabel(application.status)}</span>
                      {application.shortlist_source === "automatic" && <span className="status-badge status-badge-ai">Auto-Shortlisted</span>}
                      {application.match_score != null && <span className="score-pill score-high">{Number(application.match_score).toFixed(1)}% match</span>}
                    </p>
                    <span>Applied {new Date(application.created_at).toLocaleDateString()}</span>
                    {application.invitation_status && application.invitation_status !== "not_invited" && (
                      <div className="candidate-assessment-status-box" style={{ marginTop: "8px", padding: "10px 14px", background: "var(--bg-subtle, #f8fafc)", border: "1px solid var(--border-color, #e2e8f0)", borderRadius: "8px" }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "10px" }}>
                          <div>
                            <span style={{ fontSize: "0.85rem", fontWeight: "600", color: "var(--text-main, #1e293b)" }}>
                              Assessment{application.assessment_title ? `: ${application.assessment_title}` : ""}
                            </span>
                            <div className="small-meta" style={{ marginTop: "2px" }}>
                              Status: <strong className={getStatusBadgeClass(application.assessment_status)}>{formatAssessmentStatus(application.assessment_status)}</strong>
                              {application.assessment_status === "submitted" && application.assessment_score != null && (
                                <span> · Score: <strong>{application.assessment_score}/{application.assessment_max_score}</strong> ({Number(application.assessment_percentage).toFixed(1)}%)</span>
                              )}
                              {application.assessment_status === "expired" && (
                                <span className="error"> · Invitation link has expired</span>
                              )}
                            </div>
                          </div>
                          {(application.assessment_status === "assigned" || application.assessment_status === "started") && (
                            <button
                              type="button"
                              className="button button-small btn-primary"
                              disabled={launchingAssessmentId === application.id}
                              onClick={() => handleCandidateLaunchAssessment(application)}
                              style={{ fontWeight: "700", whiteSpace: "nowrap" }}
                            >
                              {launchingAssessmentId === application.id
                                ? "Opening Assessment..."
                                : application.assessment_status === "started"
                                ? "Resume Assessment →"
                                : "Start Assessment →"}
                            </button>
                          )}
                        </div>
                        {application.assessment_status === "submitted" && (
                          <div style={{ marginTop: "6px" }}>
                            <span className={`status-badge ${application.assessment_is_passed ? "status-badge-success" : "status-badge-danger"}`}>
                              {application.assessment_result_status || (application.assessment_is_passed ? "Selected for next round" : "Not qualified")}
                            </span>
                          </div>
                        )}
                        {(application.assessment_status === "assigned" || application.assessment_status === "started") && (
                          <p className="small-meta" style={{ marginTop: "4px", color: "var(--text-muted, #64748b)" }}>
                            Proctored assessment: camera and microphone access required. You have a single attempt.
                          </p>
                        )}
                      </div>
                    )}
                    {(application.decision_reason || application.decision_note || application.decided_at) && (
                      <div className="decision-summary-strip">
                        <div>
                          <strong>Hiring Decision Update:</strong>{" "}
                          <span>{application.decision_reason || formatStatusLabel(application.status)}</span>
                          {application.decided_at && (
                            <span className="small-meta"> Â· Decided {new Date(application.decided_at).toLocaleDateString()}</span>
                          )}
                        </div>
                        {application.decision_note && <p className="small-meta">{application.decision_note}</p>}
                      </div>
                    )}
                    {appInterviews.length > 0 && (
                      <div className="small-meta" style={{ marginTop: "6px" }}>
                        <strong>Interview Rounds:</strong>{" "}
                        {appInterviews.map((iv, idx) => (
                          <span key={iv.id}>
                            {idx > 0 ? "Â·" : ""}
                            Round {iv.round_number} ({iv.round_name}): {formatInterviewStatus(iv.status)} on{" "}
                            {new Date(iv.scheduled_at).toLocaleString()} ({formatInterviewMode(iv.interview_mode)})
                          </span>
                        ))}
                      </div>
                    )}
                    <ApplicationProgress status={application.status} />
                    {application.resume_id && <button className="text-button" onClick={() => downloadResume({ id: application.resume_id, original_filename: application.resume_filename || "application-resume.pdf" })}>Download submitted resume</button>}
                  </div>
                  {["applied", "under_review", "screening"].includes(application.status) && (
                    <button className="button button-secondary" onClick={() => withdrawApplication(application)}>Withdraw</button>
                  )}
                </div>
              );
            }) : <p>No applications yet.</p>}
          </section>
          <section className="panel" id="candidate-interviews">
            <div className="section-heading">
              <div>
                <span className="eyebrow">Scheduled Rounds</span>
                <h2>My Interviews</h2>
              </div>
              <span className="table-count">{candidateInterviews.length} total</span>
            </div>
            {candidateInterviews.length ? (
              <div className="applicant-cards-list">
                {[...candidateInterviews]
                  .sort((a, b) => new Date(a.scheduled_at) - new Date(b.scheduled_at))
                  .map((interview) => (
                    <article className="applicant-card" key={interview.id}>
                      <div className="applicant-card-header">
                        <div>
                          <h3>Round {interview.round_number}: {interview.round_name}</h3>
                          <p className="small-meta">
                            <Link to={`/jobs/${interview.job_id}`}>{interview.job_title}</Link>
                            {interview.company ? ` at ${interview.company}` : ""}
                          </p>
                        </div>
                        <div className="badge-row">
                          <span className={getStatusBadgeClass(interview.status)}>
                            {formatInterviewStatus(interview.status)}
                          </span>
                          <span className="role-pill">{formatInterviewMode(interview.interview_mode)}</span>
                        </div>
                      </div>
                      <div className="applicant-card-grid">
                        <div>
                          <strong>Date &amp; Time:</strong>{" "}
                          <span>{new Date(interview.scheduled_at).toLocaleString()} ({interview.timezone}) Â· {interview.duration_minutes} mins</span>
                        </div>
                        {interview.interviewer_name && (
                          <div>
                            <strong>Interviewer:</strong> <span>{interview.interviewer_name}</span>
                          </div>
                        )}
                        {interview.meeting_link && interview.status !== "cancelled" && (
                          <div>
                            <strong>Meeting Link:</strong>{" "}
                            {interview.meeting_link.startsWith("/live-interview/") || interview.livekit_room_name ? (
                              <Link to={`/live-interview/${interview.id}`} className="button button-small" style={{ display: "inline-block", marginTop: "4px", background: "#2563eb", color: "#fff", textDecoration: "none", fontWeight: "600" }}>
                                🎥 Join Live Interview Room
                              </Link>
                            ) : (
                              <a href={interview.meeting_link} target="_blank" rel="noreferrer">{interview.meeting_link}</a>
                            )}
                          </div>
                        )}
                        {!interview.meeting_link && interview.interview_mode === "online" && interview.status !== "cancelled" && (
                          <div>
                            <Link to={`/live-interview/${interview.id}`} className="button button-small" style={{ display: "inline-block", marginTop: "4px", background: "#2563eb", color: "#fff", textDecoration: "none", fontWeight: "600" }}>
                              🎥 Join Live Interview Room
                            </Link>
                          </div>
                        )}
                        {interview.location && interview.status !== "cancelled" && (
                          <div>
                            <strong>Location:</strong> <span>{interview.location}</span>
                          </div>
                        )}
                        {interview.notes_for_candidate && (
                          <div>
                            <strong>Preparation Notes:</strong> <span>{interview.notes_for_candidate}</span>
                          </div>
                        )}
                        {interview.cancellation_reason && (
                          <div>
                            <strong>Cancellation Reason:</strong> <span>{interview.cancellation_reason}</span>
                          </div>
                        )}
                      </div>
                    </article>
                  ))}
              </div>
            ) : (
              <p>No interviews scheduled yet.</p>
            )}
          </section>
          <section className="panel" id="candidate-saved-jobs">
            <div className="section-heading"><div><span className="eyebrow">Keep exploring</span><h2>Saved jobs</h2></div><span className="table-count">{items.savedJobs?.length || 0} saved</span></div>
            {items.savedJobs?.length ? items.savedJobs.map((job) => (
              <div className="saved-job-row" key={job.id}>
                <div className="job-company"><span className="company-avatar">{job.company.slice(0, 1).toUpperCase()}</span><div><Link to={`/jobs/${job.id}`}><strong>{job.title}</strong></Link><span>{job.company} Â· {job.location || "Location not specified"}</span></div></div>
                <div className="card-actions"><Link className="button button-secondary" to={`/jobs/${job.id}`}>View details</Link><button className="button" onClick={() => removeSavedJob(job)}>Remove</button></div>
              </div>
            )) : <p>No saved jobs yet. Browse jobs and select "Save job" to keep jobs handy.</p>}
          </section>
          </div>
        </>}
        {role === "recruiter" && <>
          <aside className="workspace-sidebar">
            <div className="admin-identity"><span className="admin-avatar">{(fullName || "R").slice(0, 1).toUpperCase()}</span><div><strong>{fullName}</strong><span>Recruiter</span></div></div>
            <a className="active" href="#recruiter-dashboard">Dashboard</a>
            <a href="#recruiter-pipeline">Hiring pipeline</a>
            <a href="#recruiter-applicants">Applicants & AI Match</a>
            <a href="#recruiter-interviews">Interviews</a>
            <a href="#recruiter-notifications">Email Logs</a>
            <a href="#recruiter-assessments">Manage Tests</a>
            <a href="#recruiter-results">Assessment Results</a>
            <a href="#recruiter-jobs">Job postings</a>
            <Link to="/jobs">Browse jobs</Link>
            <a href="#recruiter-company">Company profile</a>
          </aside>
          <div className="workspace-main">

          <section className="panel profile-form-panel recruiter-overview" id="recruiter-dashboard">
  <div className="section-heading">
    <div>
      <span className="eyebrow">Recruiter workspace</span>
      <h2>Hiring overview</h2>
    </div>
  </div>
  <div className="stats-grid">
    {[
      ["jobs", "Posted jobs"],
      ["active_jobs", "Active jobs"],
      ["applications", "Total applications"],
      ["pending_applications", "Pending applications"],
    ].map(([key, label], index) => (
      <div className={`stat-card stat-card-${index + 1}`} key={key}>
        <AnimatedNumber value={recruiterStats?.[key] ?? 0} />
        <span>{label}</span>
      </div>
    ))}
  </div>
</section>
<section className="panel profile-form-panel" id="recruiter-company">
            <h2>Company Profile</h2>
            <form className="profile-form" onSubmit={saveCompany}>
              <input required placeholder="Company name" value={companyDraft.name} onChange={(event) => setCompanyDraft({ ...companyDraft, name: event.target.value })} />
              <input placeholder="Website" value={companyDraft.website || ""} onChange={(event) => setCompanyDraft({ ...companyDraft, website: event.target.value })} />
              <input placeholder="Location" value={companyDraft.location || ""} onChange={(event) => setCompanyDraft({ ...companyDraft, location: event.target.value })} />
              <textarea className="full-width" placeholder="Company description" value={companyDraft.description || ""} onChange={(event) => setCompanyDraft({ ...companyDraft, description: event.target.value })} />
              <button className="button full-width" type="submit" disabled={saving}>{profile ? "Update Company" : "Create Company"}</button>
            </form>
          </section>
          <section className="panel profile-form-panel" id="recruiter-post-job">
            <h2>Post a Job</h2>
            <form className="profile-form" onSubmit={createJob}>
              <input required minLength="3" placeholder="Job title" value={jobDraft.title} onChange={(event) => setJobDraft({ ...jobDraft, title: event.target.value })} />
              <input placeholder="Location" value={jobDraft.location} onChange={(event) => setJobDraft({ ...jobDraft, location: event.target.value })} />
              <input type="number" min="0" max="60" placeholder="Minimum experience (years)" value={jobDraft.experience_min} onChange={(event) => setJobDraft({ ...jobDraft, experience_min: event.target.value })} />
              <input type="number" min="0" max="60" placeholder="Maximum experience (years)" value={jobDraft.experience_max} onChange={(event) => setJobDraft({ ...jobDraft, experience_max: event.target.value })} />
              <select value={jobDraft.employment_type} onChange={(event) => setJobDraft({ ...jobDraft, employment_type: event.target.value })}>
                <option value="full_time">Full Time</option><option value="part_time">Part Time</option><option value="contract">Contract</option><option value="internship">Internship</option>
              </select>
              <input type="number" min="0" step="0.01" placeholder="Minimum salary" value={jobDraft.salary_min} onChange={(event) => setJobDraft({ ...jobDraft, salary_min: event.target.value })} />
              <input type="number" min="0" step="0.01" placeholder="Maximum salary" value={jobDraft.salary_max} onChange={(event) => setJobDraft({ ...jobDraft, salary_max: event.target.value })} />
              <input minLength="3" maxLength="3" placeholder="Currency (e.g. INR)" value={jobDraft.salary_currency} onChange={(event) => setJobDraft({ ...jobDraft, salary_currency: event.target.value.toUpperCase() })} />
              <textarea required minLength="10" className="full-width" placeholder="Job description" value={jobDraft.description} onChange={(event) => setJobDraft({ ...jobDraft, description: event.target.value })} />
              <input className="full-width" placeholder="Required skills (comma separated)" value={jobDraft.skills} onChange={(event) => setJobDraft({ ...jobDraft, skills: event.target.value })} />
              <div className="card-actions full-width">
                <button className="button" type="submit" disabled={saving || !profile}>
                  {editingJobId ? "Save Changes" : "Submit for Approval"}
                </button>
                {editingJobId && <button className="button button-secondary" type="button" onClick={() => {
                  setEditingJobId(null);
                  setJobDraft({
                    title: "", description: "", location: "", employment_type: "full_time",
                    experience_min: "", experience_max: "", salary_min: "", salary_max: "",
                    salary_currency: "USD", skills: "",
                  });
                }}>Cancel Edit</button>}
              </div>
            </form>
          </section>
          <section className="panel" id="recruiter-jobs">
            <h2>Job Postings</h2>
            {items.length ? items.map((job) => (
              <div className="job-select" key={job.id}>
                <div>
                  <strong>{job.title}</strong>
                  <span className="small-meta"> Â· {job.status} Â· {job.applications_count} applicants</span>
                </div>
                <div className="card-actions">
                  <button className="button button-secondary" onClick={() => loadApplicants(job.id)}>View applicants</button>
                  <button className="button button-secondary" onClick={() => editJob(job)}>Edit</button>
                  {job.status === "published" && <button className="button button-secondary" onClick={() => updateRecruiterJobStatus(job, "closed")}>Close</button>}
                  {job.status === "closed" && <button className="button" onClick={() => updateRecruiterJobStatus(job, "published")}>Reopen</button>}
                  {!job.applications_count && <button className="button button-danger" onClick={() => deleteRecruiterJob(job)}>Delete</button>}
                </div>
              </div>
            )) : <p>No jobs posted yet.</p>}
          </section>
          <section className="panel" id="recruiter-pipeline">
            <div className="section-heading"><div><span className="eyebrow">Applicant progress</span><h2>Hiring pipeline</h2></div><span className="table-count">{selectedJobId ? `${applicants.length} loaded` : "Choose a job"}</span></div>
            {!selectedJobId && <p>Select "View applicants" on one of your jobs or pick a job below to load its pipeline.</p>}
            {selectedJobId && <div className="pipeline-board">
              {pipelineStages.map(([stage, label]) => {
                const stageApplicants = applicants.filter((applicant) => applicant.status === stage);
                return (
                  <section className="pipeline-column" key={stage}>
                    <div className="pipeline-column-heading"><strong>{label}</strong><span>{stageApplicants.length}</span></div>
                    {stageApplicants.map((applicant) => (
                      <article className="pipeline-card" key={applicant.id}>
                        <strong>{applicant.candidate || "Candidate"}</strong>
                        {applicant.email && <span className="applicant-email">{applicant.email}</span>}
                        <span className="small-meta">{applicant.job_title}{applicant.match_score != null ? ` Â· ${Number(applicant.match_score).toFixed(0)}%` : ""}</span>
                        {applicant.shortlist_source === "automatic" && <span className="status-badge status-badge-ai">Auto â‰¥70%</span>}
                        <select
                          aria-label={`Move ${applicant.candidate} to stage`}
                          value={applicant.status}
                          disabled={applicant.status === "withdrawn" || applicantActionBusy}
                          onChange={(event) => updateApplicantStatus(applicant.id, event.target.value)}
                        >
                          {APPLICATION_STATUS_OPTIONS.map((opt) => (
                            <option value={opt.value} key={opt.value} disabled={opt.value === "withdrawn" && applicant.status !== "withdrawn"}>
                              {opt.label}
                            </option>
                          ))}
                        </select>
                      </article>
                    ))}
                    {!stageApplicants.length && <span className="pipeline-empty">No applicants</span>}
                  </section>
                );
              })}
            </div>}
          </section>
          <section className="panel" id="recruiter-applicants">
            <div className="section-heading">
              <div>
                <span className="eyebrow">Applicant Tracking System</span>
                <h2>Applicants{selectedJobId && selectedJobId !== "all" ? " - Selected Job" : selectedJobId === "all" ? " - All Jobs" : ""}</h2>
              </div>
              <div className="card-actions">
                <select
                  aria-label="Select job to view applicants"
                  value={selectedJobId}
                  onChange={(event) => {
                    const val = event.target.value;
                    if (val) loadApplicants(val);
                  }}
                >
                  <option value="">Select job...</option>
                  <option value="all">All my jobs</option>
                  {items.map((job) => (
                    <option key={job.id} value={job.id}>{job.title} ({job.applications_count})</option>
                  ))}
                </select>
                {selectedJobId && selectedJobId !== "all" && (
                  <button
                    type="button"
                    className="button button-small"
                    disabled={applicantActionBusy}
                    onClick={triggerBatchMatch}
                  >
                    {applicantActionBusy ? "Matching..." : "Run AI Match for Job"}
                  </button>
                )}
                <button
                  type="button"
                  className="button button-secondary button-small"
                  disabled={applicantActionBusy || (!items.length && !applicants.length)}
                  onClick={() => openAssignModal([])}
                >
                  Assign Assessment
                </button>
              </div>
            </div>

            {selectedJobId && (
              <>
                <form className="applicant-filters-grid" onSubmit={(event) => { event.preventDefault(); loadApplicants(selectedJobId); }}>
                  <input
                    value={applicantSearch}
                    onChange={(event) => setApplicantSearch(event.target.value)}
                    placeholder="Search name, email, skills, or job title"
                    aria-label="Search applicants by name, email, skills, or job title"
                  />
                  <input
                    value={applicantSkill}
                    onChange={(event) => setApplicantSkill(event.target.value)}
                    placeholder="Filter by skill"
                  />
                  <input
                    value={applicantExperience}
                    onChange={(event) => setApplicantExperience(event.target.value)}
                    placeholder="Filter by experience"
                  />
                  <select
                    value={applicantStatusFilter}
                    onChange={(event) => setApplicantStatusFilter(event.target.value)}
                    aria-label="Filter applicants by status"
                  >
                    <option value="">All statuses</option>
                    {APPLICATION_STATUS_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>{opt.label}</option>
                    ))}
                  </select>
                  <select
                    value={applicantSortBy}
                    onChange={(event) => setApplicantSortBy(event.target.value)}
                    aria-label="Sort applicants"
                  >
                    <option value="newest">Newest applications</option>
                    <option value="oldest">Oldest applications</option>
                    <option value="match_desc">Highest AI match</option>
                    <option value="match_asc">Lowest AI match</option>
                  </select>
                  <div className="card-actions">
                    <button className="button button-small" type="submit">Apply Filters</button>
                    <button className="button button-secondary button-small" type="button" onClick={resetApplicantFilters}>Reset</button>
                  </div>
                </form>

                
              <div className="applicant-counts-bar">
                <span>
                  Showing <strong>{filteredApplicants.length}</strong> of{" "}
                  <strong>{applicants.length}</strong> applicants
                </span>

                <span>
                    Shortlisted:{" "}
                    <strong>
                        {applicants.filter((a) => a.status === "shortlisted").length}
                    </strong>
                  </span>

                <span>
                    Auto-Shortlisted (â‰¥70%):{" "}
                  <strong>
                   {applicants.filter((a) => a.shortlist_source === "automatic").length}
                  </strong>
                </span>

  <span>
    Eligible:{" "}
    <strong>
      {applicants.filter(
        (a) => a.match_score != null && Number(a.match_score) >= 70
      ).length}
    </strong>
  </span>
  <span>
    Not Eligible:{" "}
    <strong>
      {applicants.filter(
        (a) => a.match_score != null && Number(a.match_score) < 70
      ).length}
    </strong>
  </span>

  <span>
    Assessments Completed:{" "}
    <strong>
      {applicants.filter((a) => ["submitted", "completed"].includes(a.assessment_status)).length}
    </strong>
  </span>
</div>

              </>
            )}

            {applicantsLoading && <p className="loading-message" role="status">Loading applicants...</p>}

            {!applicantsLoading && filteredApplicants.length ? (
              <div className="applicant-cards-list">
                {filteredApplicants.map((applicant) => (
                  <article className="applicant-card" key={applicant.id}>
                    <div className="applicant-card-header">
                      <div>
                        <h3>{displayValue(applicant.candidate, "Candidate")}</h3>
                        <p className="small-meta">
                          {displayValue(applicant.email)} Â· {applicant.job_title} Â· Location: {displayValue(applicant.location)} Â· Applied {new Date(applicant.applied_at).toLocaleDateString()}
                        </p>
                      </div>
                      <div className="badge-row">
                        <span className={getStatusBadgeClass(applicant.status)}>{formatStatusLabel(applicant.status)}</span>
                        {applicant.shortlist_source === "automatic" && (
                          <span className="status-badge status-badge-ai">Auto-Shortlisted (â‰¥70%)</span>
                        )}
                        {applicant.shortlist_source === "manual" && (
                          <span className="status-badge status-badge-neutral">Manual Shortlist</span>
                        )}
                        
                       {applicant.match_score != null ? (
  <>
    <span className={`status-badge ${
      Number(applicant.match_score) >= 70
        ? "status-badge-ai"
        : "status-badge-neutral"
    }`}>
      {Number(applicant.match_score) >= 70
        ? "Eligible"
        : "Not Eligible"}
    </span>

    <span className={`score-pill ${
      Number(applicant.match_score) >= 70
        ? "score-high"
        : Number(applicant.match_score) >= 45
        ? "score-mid"
        : "score-low"
    }`}>
      ATS Match: {Number(applicant.match_score).toFixed(1)}%
    </span>
  </>
                       ) : (
                       <span className="score-pill score-neutral">
                           Match Pending
                        </span>
                         )}

                      </div>
                    </div>

                    <div className="applicant-card-grid">
                      <div><strong>Summary:</strong> <span>{displayValue(applicant.summary)}</span></div>
                      <div><strong>Education:</strong> <span>{displayValue(applicant.education)}</span></div>
                      <div><strong>Experience:</strong> <span>{displayValue(applicant.experience)}</span></div>
                      <div><strong>Projects:</strong> <span>{displayValue(applicant.projects)}</span></div>
                      <div><strong>Certifications:</strong> <span>{displayValue(applicant.certifications)}</span></div>
                      <div>
                        <strong>Technical Skills:</strong>{" "}
                        {applicant.skills?.length ? applicant.skills.join(", ") : "Not provided"}
                      </div>
                    </div>

                    <div className="applicant-ai-strip">
                      <div>
                        <strong>Matched Skills:</strong> {applicant.matched_skills?.join(", ") || "None"}
                        {" Â· "}
                        <strong>Missing Skills:</strong> {applicant.missing_skills?.join(", ") || "None"}
                      </div>
                      {applicant.matching_explanation && (
                        <p className="small-meta">{applicant.matching_explanation}</p>
                      )}
                      <div className="small-meta">
                        {applicant.assessment_title && (
                          <><strong>Assessment:</strong> {applicant.assessment_title} Â· </>
                        )}
                        <strong>Test Invite:</strong> {formatInvitationStatus(applicant.invitation_status)}
                        {" Â· "}
                        <strong>Test Status:</strong> {formatAssessmentStatus(applicant.assessment_status)}
                        {applicant.assessment_score != null && (
                          <> Â· <strong>Result:</strong> {applicant.assessment_score}/{applicant.assessment_max_score ?? "â€”"}</>
                        )}
                        {applicant.assessment_completed_at && (
                          <> Â· Completed {new Date(applicant.assessment_completed_at).toLocaleDateString()}</>
                        )}
                      </div>
                      {applicant.invitation_error && (
                        <p className="resume-error small-meta">Email warning: {applicant.invitation_error}</p>
                      )}
                      {(applicant.decision_reason || applicant.decision_note || applicant.decided_at) && (
                        <div className="decision-summary-strip">
                          <div>
                            <strong>Decision Record:</strong>{" "}
                            <span>{applicant.decision_reason || formatStatusLabel(applicant.status)}</span>
                            {applicant.decided_at && (
                              <span className="small-meta"> Â· {new Date(applicant.decided_at).toLocaleString()}</span>
                            )}
                            {applicant.decided_by_name && (
                              <span className="small-meta"> Â· By {applicant.decided_by_name}</span>
                            )}
                          </div>
                          {applicant.decision_note && <p className="small-meta">{applicant.decision_note}</p>}
                        </div>
                      )}
                      {applicant.latest_email_notification && (
                        <div className="notif-inline-strip">
                          <strong>Last Email ({formatNotificationType(applicant.latest_email_notification.notification_type)}):</strong>
                          <span className={getStatusBadgeClass(applicant.latest_email_notification.status)}>
                            {applicant.latest_email_notification.status.toUpperCase()}
                          </span>
                          {applicant.latest_email_notification.error_message && (
                            <span className="resume-error small-meta">{applicant.latest_email_notification.error_message}</span>
                          )}
                          {applicant.latest_email_notification.status === "failed" && (
                            <button
                              type="button"
                              className="button button-secondary button-small"
                              disabled={retryingCardNotifId === applicant.latest_email_notification.id}
                              onClick={() => handleRetryCardNotification(applicant.latest_email_notification.id)}
                            >
                              {retryingCardNotifId === applicant.latest_email_notification.id ? "Retrying..." : "Retry Email"}
                            </button>
                          )}
                        </div>
                      )}
                    </div>

                    <div className="applicant-card-actions">
                      <div className="card-actions">
                        <button type="button" className="button button-small" onClick={() => openCandidateProfile(applicant.id)}>
                          View Candidate Profile
                        </button>
                        <button
                          type="button"
                          className="button button-secondary button-small"
                          onClick={() => downloadResume(applicant.resume_id ? { id: applicant.resume_id, original_filename: applicant.resume_filename || `${applicant.candidate}-resume` } : null)}
                        >
                          Download Resume
                        </button>
                        <button
                          type="button"
                          className="button button-secondary button-small"
                          disabled={applicantActionBusy || applicant.status === "withdrawn"}
                          onClick={() => triggerApplicantMatch(applicant.id)}
                        >
                          Refresh ATS Match
                        </button>
                        {applicant.status === "shortlisted" && (
                          <button
                            type="button"
                            className="button button-secondary button-small"
                            disabled={applicantActionBusy}
                            onClick={() => openAssignModal([applicant.id])}
                          >
                            Assign Assessment
                          </button>
                        )}
                        {!["withdrawn", "rejected", "accepted", "hired"].includes(applicant.status) && (
                          <button
                            type="button"
                            className="button button-secondary button-small"
                            disabled={applicantActionBusy}
                            onClick={() => setInterviewModalState({ mode: "schedule", applicant, existingRoundCount: 0 })}
                          >
                            Schedule Interview
                          </button>
                        )}
                        {!["withdrawn", "rejected", "selected", "accepted", "hired"].includes(applicant.status) && (
                          <button
                            type="button"
                            className="button button-small"
                            disabled={applicantActionBusy}
                            onClick={() => setDecisionModalState({ applicant, initialMode: "select" })}
                          >
                            Select
                          </button>
                        )}
                        {applicant.status === "selected" && (
                          <button
                            type="button"
                            className="button button-small"
                            disabled={applicantActionBusy}
                            onClick={() => setDecisionModalState({ applicant, initialMode: "accept" })}
                          >
                            Mark Accepted
                          </button>
                        )}
                        {!["withdrawn", "rejected", "accepted", "hired"].includes(applicant.status) && (
                          <button
                            type="button"
                            className="button button-danger button-small"
                            disabled={applicantActionBusy}
                            onClick={() => setDecisionModalState({ applicant, initialMode: "reject" })}
                          >
                            Reject
                          </button>
                        )}
                      </div>
                      <select
                        aria-label={`Update status for ${applicant.candidate}`}
                        value={applicant.status}
                        disabled={applicant.status === "withdrawn" || applicantActionBusy}
                        onChange={(event) => updateApplicantStatus(applicant.id, event.target.value)}
                      >
                        {APPLICATION_STATUS_OPTIONS.map((opt) => (
                          <option key={opt.value} value={opt.value} disabled={opt.value === "withdrawn" && applicant.status !== "withdrawn"}>
                            {opt.label}
                          </option>
                        ))}
                      </select>
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              !applicantsLoading && <p>{selectedJobId ? "No applicants match these filters." : "Select a job above or click View applicants on a job posting to review candidates."}</p>
            )}
          </section>
          <RecruiterInterviews
            jobs={items}
            refreshSignal={interviewRefreshSignal}
            onOpenInterviewAction={(mode, interview) => setInterviewModalState({ mode, interview })}
            onNotificationsUpdated={() => setInterviewRefreshSignal((n) => n + 1)}
            onFeedback={handleChildFeedback}
          />
          <RecruiterAssessments
            jobs={items}
            onAssessmentsChanged={setRecruiterAssessments}
            onFeedback={handleChildFeedback}
          />
          <RecruiterAssessmentResults
            jobs={items}
            refreshSignal={resultsRefreshSignal}
            onFeedback={handleChildFeedback}
          />
          </div>
          <section className="panel profile-form-panel" id="recruiter-proctoring-events">
            <div className="section-heading">
              <div><span className="eyebrow">Assessment monitoring</span><h2>Proctoring Events</h2></div>
              <span className="table-count">{proctoringEvents.length} alerts</span>
            </div>
            {proctoringEvents.length ? proctoringEvents.map((event) => (
              <div className="admin-row proctoring-event-row" key={event.id}>
                <div>
                  <strong>{({
                    camera_missing: "Camera unavailable",
                    camera_disconnected: "Camera disconnected",
                    face_not_detected: "Face not detected",
                    multiple_faces_detected: "Multiple faces detected",
                    tab_switch: "Tab switched",
                    fullscreen_exit: "Fullscreen exited",
                  })[event.event_type] || event.event_type}</strong>
                  <span>{event.candidate_name} Â· {event.job_title} Â· {event.assessment_title}</span>
                  <span>{event.created_at ? new Date(event.created_at).toLocaleString() : "Time unavailable"}</span>
                </div>
                <span className="role-pill">Alert</span>
              </div>
            )) : <p>No proctoring events recorded yet.</p>}
            <p className="small-meta">Proctoring alerts are for review only and do not automatically disqualify candidates.</p>
          </section>
          {assignModalOpen && (
            <AssignAssessmentModal
              open={assignModalOpen}
              onClose={() => { setAssignModalOpen(false); setAssignInitialIds([]); }}
              shortlistedApplicants={applicants.filter((a) => a.status === "shortlisted")}
              assessments={recruiterAssessments}
              initialSelectedIds={assignInitialIds}
              onAssigned={async (summary) => {
                setResultsRefreshSignal((n) => n + 1);
                if (selectedJobId) {
                  await loadApplicants(selectedJobId);
                }
                const parts = [];
                if (summary?.sent_count) parts.push(`${summary.sent_count} invitation(s) sent`);
                if (summary?.failed_count) parts.push(`${summary.failed_count} failed email delivery`);
                if (summary?.skipped_count) parts.push(`${summary.skipped_count} already assigned`);
                handleChildFeedback(
                  parts.length ? `Assessment assignment updated: ${parts.join(", ")}.` : "Assessment assignment processed.",
                  Boolean(summary?.failed_count && !summary?.sent_count)
                );
              }}
            />
          )}
          <ApplicantProfileModal
            applicant={selectedApplicantDetail}
            loading={detailLoading}
            refreshKey={interviewRefreshSignal}
            onClose={() => setSelectedApplicantDetail(null)}
            onStatusChange={updateApplicantStatus}
            onDownloadResume={downloadResume}
            onRefreshMatch={triggerApplicantMatch}
            onOpenDecision={(app, initialMode) => setDecisionModalState({ applicant: app, initialMode })}
            onScheduleInterview={(app, existingRoundCount) =>
              setInterviewModalState({ mode: "schedule", applicant: app, existingRoundCount: existingRoundCount || 0 })
            }
            onInterviewAction={(mode, interview) => setInterviewModalState({ mode, interview })}
            onNotificationRetried={() => setInterviewRefreshSignal((n) => n + 1)}
            onFeedback={handleChildFeedback}
            actionBusy={applicantActionBusy}
          />
          {decisionModalState && (
            <DecisionActionModal
              applicant={decisionModalState.applicant}
              initialMode={decisionModalState.initialMode}
              onClose={() => setDecisionModalState(null)}
              onCompleted={handleDecisionCompleted}
            />
          )}
          {interviewModalState && (
            <InterviewModal
              mode={interviewModalState.mode}
              applicant={interviewModalState.applicant || null}
              interview={interviewModalState.interview || null}
              existingRoundCount={interviewModalState.existingRoundCount || 0}
              onClose={() => setInterviewModalState(null)}
              onCompleted={handleInterviewCompleted}
            />
          )}
        </>}
        {role === "admin" && <>
          <aside className="admin-sidebar">
            <div className="admin-identity"><span className="admin-avatar">{(fullName || "A").slice(0, 1).toUpperCase()}</span><div><strong>{fullName}</strong><span>Platform admin</span></div></div>
            <a className="active" href="#admin-overview">Dashboard</a>
            <Link to="/jobs">Browse Jobs</Link>
            <a href="#admin-users">Users Management</a>
            <a href="#admin-jobs">Jobs Management</a>
            <a href="#admin-question-bank">Question Bank</a>
            <a href="#admin-interviews">Interviews</a>
            <a href="#admin-notifications">Email Logs</a>
            <button type="button" className="admin-logout" onClick={logout}>Log out</button>
          </aside>
          <div className="admin-main">
            <section className="admin-overview" id="admin-overview">
              <div className="section-heading"><div><span className="eyebrow">Platform overview</span><h2>Dashboard insights</h2></div><span className="live-indicator">Live database</span></div>
              {systemStatus && (
                <div className="badge-row" style={{ marginBottom: "14px" }}>
                  <span className={`status-badge ${systemStatus.smtp_configured ? "status-badge-success" : "status-badge-danger"}`}>
                    SMTP Email: {systemStatus.smtp_configured ? "Configured" : `Missing ${systemStatus.missing_smtp_vars.join(", ")}`}
                  </span>
                  <span className="status-badge status-badge-info">
                    Assessment Generator: {systemStatus.ai_configured ? `External (${systemStatus.ai_provider})` : "Built-in Skill Engine"}
                  </span>
                  <span className={`status-badge ${systemStatus.tesseract_available ? "status-badge-success" : "status-badge-neutral"}`}>
                    OCR: {systemStatus.tesseract_available ? "Tesseract Ready" : "Not on PATH"}
                  </span>
                </div>
              )}
              <div className="stats-grid">
                {[
                  ["users", "Total users", "ðŸ‘¥"],
                  ["candidates", "Candidates", "ðŸŽ“"],
                  ["recruiters", "Recruiters", "ðŸ¢"],
                  ["jobs", "Total jobs", "ðŸ’¼"],
                  ["active_jobs", "Active jobs", "ðŸ“‹"],
                  ["applications", "Applications", "ðŸ“"],
                ].map(([key, label, icon], index) => (
                  <div className={`stat-card stat-card-${index + 1}`} key={key}>
                    
                    <AnimatedNumber value={stats?.[key] ?? 0} />
                    <span>{label}</span>
                  </div>
                ))}
              </div>
              <div className="analytics-grid">
                <AnalyticsChart title="New registrations" data={adminTrends.registrations} color="chart-purple" />
                <AnalyticsChart title="Job applications" data={adminTrends.applications} color="chart-mint" />
              </div>
            </section>
            <section className="panel admin-table-panel" id="admin-jobs">
              <div className="section-heading"><div><span className="eyebrow">Moderation</span><h2>Job management</h2></div><span className="table-count">{filteredJobs.length} jobs</span></div>
              <div className="admin-filters">
                <input aria-label="Search jobs" placeholder="Search title or company" value={jobSearch} onChange={(event) => { setJobSearch(event.target.value); setJobPage(1); }} />
                <select aria-label="Filter jobs by status" value={jobStatusFilter} onChange={(event) => { setJobStatusFilter(event.target.value); setJobPage(1); }}>
                  <option value="">All statuses</option><option value="pending">Pending</option><option value="published">Published</option><option value="closed">Closed</option><option value="draft">Draft</option><option value="disabled">Disabled</option>
                </select>
                <select aria-label="Filter jobs by company" value={jobCompanyFilter} onChange={(event) => { setJobCompanyFilter(event.target.value); setJobPage(1); }}>
                  <option value="">All companies</option>{[...new Set(adminJobs.map((job) => job.company))].sort().map((company) => <option key={company} value={company}>{company}</option>)}
                </select>
              </div>
              <div className="admin-table-wrap"><table className="admin-table"><thead><tr><th>Job title</th><th>Company</th><th>Status</th><th>Action</th></tr></thead><tbody>
                {pagedJobs.map((job) => <tr key={job.id}><td data-label="Job title"><strong>{job.title}</strong><span>{job.location || "Location not specified"}</span></td><td data-label="Company">{job.company}</td><td data-label="Status"><span className={`table-status status-${job.status}`}>{job.status.replaceAll("_", " ")}</span></td><td data-label="Action"><select aria-label={`Update status for ${job.title}`} value={job.status} onChange={(event) => updateJobStatus(job.id, event.target.value)}><option value="draft">Draft</option><option value="pending">Pending</option><option value="published">Published</option><option value="closed">Closed</option><option value="disabled">Disabled</option></select></td></tr>)}
                {!pagedJobs.length && <tr><td colSpan="4" className="table-empty">No jobs match these filters.</td></tr>}
              </tbody></table></div>
              {jobPageCount > 1 && <div className="table-pagination"><span>Page {jobPage} of {jobPageCount}</span><button className="button button-secondary" disabled={jobPage <= 1} onClick={() => setJobPage((page) => page - 1)}>Previous</button><button className="button button-secondary" disabled={jobPage >= jobPageCount} onClick={() => setJobPage((page) => page + 1)}>Next</button></div>}
            </section>
            <section className="panel admin-table-panel" id="admin-assessment-recordings">
              <div className="section-heading">
                <div><span className="eyebrow">Assessment monitoring</span><h2>Assessment Recordings</h2></div>
                <span className="table-count">{assessmentRecordings.length} recordings</span>
              </div>
              {activeRecording && (
                <div className="recording-playback">
                  <div className="section-heading">
                    <h3>Recording playback</h3>
                    <button className="button button-secondary" onClick={() => setActiveRecording(null)}>Close</button>
                  </div>
                  <video key={activeRecording.id} controls playsInline preload="metadata" src={activeRecording.url} style={{ width: "100%", maxHeight: "480px", background: "#111", borderRadius: "12px" }}>
                    Your browser does not support video playback.
                  </video>
                </div>
              )}
              <div className="admin-table-wrap">
                <table className="admin-table">
                  <thead><tr><th>Candidate</th><th>Assessment / Job</th><th>Duration</th><th>File size</th><th>Consent</th><th>Uploaded</th><th>Status</th><th>Action</th></tr></thead>
                  <tbody>
                    {assessmentRecordings.map((recording) => (
                      <tr key={recording.id}>
                        <td data-label="Candidate"><strong>{recording.candidate_name || "Unknown"}</strong><span>{recording.candidate_email || "No email"}</span></td>
                        <td data-label="Assessment / Job"><strong>{recording.assessment_title || "Assessment"}</strong><span>{recording.job_title || "Job not available"}</span></td>
                        <td data-label="Duration">{Math.floor((recording.duration_seconds || 0) / 60)}m {(recording.duration_seconds || 0) % 60}s</td>
                        <td data-label="File size">{((recording.file_size_bytes || 0) / (1024 * 1024)).toFixed(2)} MB</td>
                        <td data-label="Consent"><span className={`table-status ${recording.consent_given ? "status-active" : "status-disabled"}`}>{recording.consent_given ? "Given" : "Not given"}</span></td>
                        <td data-label="Uploaded">{recording.uploaded_at ? new Date(recording.uploaded_at).toLocaleString() : "—"}</td>
                        <td data-label="Status"><span className={`table-status status-${recording.status}`}>{recording.status}</span></td>
                        <td data-label="Action">
                          <button className="button button-secondary" disabled={recording.status !== "uploaded" || recordingPlaybackLoading === recording.id} onClick={() => openRecordingPlayback(recording.id)}>
                            {recordingPlaybackLoading === recording.id ? "Loading..." : "Play"}
                          </button>
                        </td>
                      </tr>
                    ))}
                    {!assessmentRecordings.length && <tr><td colSpan="8" className="table-empty">No assessment recordings uploaded yet.</td></tr>}
                  </tbody>
                </table>
              </div>
            </section>
            <section className="panel admin-table-panel" id="admin-users">
              <div className="section-heading"><div><span className="eyebrow">Access control</span><h2>User management</h2></div><span className="table-count">{filteredUsers.length} accounts</span></div>
              <div className="admin-filters">
                <input aria-label="Search users" placeholder="Search name or email" value={userSearch} onChange={(event) => { setUserSearch(event.target.value); setUserPage(1); }} />
                <select aria-label="Filter users by role" value={userRoleFilter} onChange={(event) => { setUserRoleFilter(event.target.value); setUserPage(1); }}>
                  <option value="">All roles</option><option value="admin">Admin</option><option value="candidate">Candidate</option><option value="recruiter">Recruiter</option>
                </select>
                <select aria-label="Filter users by status" value={userStatusFilter} onChange={(event) => { setUserStatusFilter(event.target.value); setUserPage(1); }}>
                  <option value="">All account statuses</option><option value="true">Active</option><option value="false">Disabled</option>
                </select>
              </div>
              <div className="admin-table-wrap"><table className="admin-table"><thead><tr><th>User</th><th>Email address</th><th>Role</th><th>Account status</th><th>Action</th></tr></thead><tbody>
                {pagedUsers.map((user) => <tr key={user.id}><td data-label="User"><strong>{user.full_name}</strong></td><td data-label="Email address">{user.email}</td><td data-label="Role"><span className="role-pill">{user.role}</span></td><td data-label="Account status"><span className={`table-status ${user.is_active ? "status-active" : "status-disabled"}`}>{user.is_active ? "Active" : "Disabled"}</span></td><td data-label="Action"><button className={`button ${user.is_active ? "button-secondary" : ""}`} disabled={user.id === currentUserId} onClick={() => updateUserStatus(user.id, user.is_active)}>{user.is_active ? "Disable" : "Enable"}</button></td></tr>)}
                {!pagedUsers.length && <tr><td colSpan="5" className="table-empty">No accounts match these filters.</td></tr>}
              </tbody></table></div>
              {userPageCount > 1 && <div className="table-pagination"><span>Page {userPage} of {userPageCount}</span><button className="button button-secondary" disabled={userPage <= 1} onClick={() => setUserPage((page) => page - 1)}>Previous</button><button className="button button-secondary" disabled={userPage >= userPageCount} onClick={() => setUserPage((page) => page + 1)}>Next</button></div>}
            </section>
            <section className="panel admin-table-panel">
              <div className="section-heading"><div><span className="eyebrow">Company review</span><h2>Company approvals</h2></div></div>
              {adminCompanies.length ? adminCompanies.map((company) => <div className="admin-row company-approval-row" key={company.id}><div><strong>{company.name}</strong><span>{company.location || "Location not specified"} Â· {company.is_approved ? "Approved" : "Pending approval"}</span></div><button className={company.is_approved ? "button button-secondary" : "button"} onClick={() => updateCompanyStatus(company.id, company.is_approved)}>{company.is_approved ? "Revoke approval" : "Approve company"}</button></div>) : <p>No companies available.</p>}
            </section>
            <section className="panel admin-table-panel" id="admin-proctoring-events">
              <div className="section-heading">
                <div><span className="eyebrow">Assessment monitoring</span><h2>Proctoring Events</h2></div>
                <span className="table-count">{proctoringEvents.length} alerts</span>
              </div>
              {proctoringEvents.length ? proctoringEvents.map((event) => (
                <div className="admin-row proctoring-event-row" key={event.id}>
                  <div>
                    <strong>{({
                      camera_missing: "Camera unavailable",
                      camera_disconnected: "Camera disconnected",
                      face_not_detected: "Face not detected",
                      multiple_faces_detected: "Multiple faces detected",
                      tab_switch: "Tab switched",
                      fullscreen_exit: "Fullscreen exited",
                    })[event.event_type] || event.event_type}</strong>
                    <span>{event.candidate_name} Â· {event.job_title} Â· {event.assessment_title}</span>
                    <span>{event.created_at ? new Date(event.created_at).toLocaleString() : "Time unavailable"}</span>
                  </div>
                  <span className="role-pill">Alert</span>
                </div>
              )) : <p>No proctoring events recorded yet.</p>}
              <p className="small-meta">These alerts are for review only and do not automatically disqualify candidates.</p>
            </section>
            <AdminQuestionBank onFeedback={handleChildFeedback} />
            <AdminInterviewsAndNotifications onFeedback={handleChildFeedback} />
          </div>
        </>}
      </div>
    </main>
  );
}

export default function App() {
  return (
    <>
      <Navbar />
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/jobs" element={<JobsPage />} />
        <Route path="/jobs/:jobId" element={<JobDetailPage />} />
        <Route path="/login" element={<AuthPage />} />
        <Route path="/admin/login" element={<AuthPage adminLogin />} />
        <Route path="/register" element={<AuthPage register />} />
        <Route path="/assessment/:token" element={<AssessmentPortal />} />
        <Route path="/video-assessment/:token" element={<VideoAssessmentPortal />} />
        <Route path="/live-interview/:interviewId" element={<LiveInterviewRoom />} />
        <Route path="/candidate" element={<Dashboard role="candidate" />} />
        <Route path="/recruiter" element={<Dashboard role="recruiter" />} />
        <Route path="/admin" element={<Dashboard role="admin" />} />
        <Route path="*" element={<main className="placeholder-page"><h1>Page not found</h1></main>} />
      </Routes>
    </>
  );
}

















