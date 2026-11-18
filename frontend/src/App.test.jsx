import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { AuthProvider } from "./AuthContext";

vi.mock("./api", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock("@mediapipe/tasks-vision", () => ({
  FilesetResolver: { forVisionTasks: vi.fn().mockResolvedValue({}) },
  FaceDetector: {
    createFromOptions: vi.fn().mockResolvedValue({ close: vi.fn(), detectForVideo: vi.fn().mockReturnValue({ detections: [{}] }) }),
  },
}));

import api from "./api";

describe("SkillSphere application shell", () => {
  let originalMediaDevices;

  beforeEach(() => {
    originalMediaDevices = navigator.mediaDevices;
    localStorage.clear();
    vi.resetAllMocks();
    window.matchMedia = vi.fn().mockImplementation((query) => ({
      matches: query.includes("prefers-reduced-motion"),
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
    window.confirm = vi.fn(() => true);
  });

  afterEach(() => {
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: originalMediaDevices,
    });
  });

  it("renders the landing page", () => {
    render(
      <MemoryRouter>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: /discover roles/i })).toBeTruthy();
  });

  it("does not show candidate-only job actions to a recruiter", async () => {
    localStorage.setItem("skillsphere_token", "recruiter-token");
    localStorage.setItem("skillsphere_role", "recruiter");
    api.get.mockResolvedValue({
      data: {
        id: 7,
        title: "Platform Engineer",
        description: "Build and maintain reliable cloud services.",
        location: "Remote",
        employment_type: "full_time",
        experience_min: 3,
        experience_max: 5,
        salary_min: null,
        salary_max: null,
        salary_currency: null,
        company: "Example Corp",
        skills: ["Python"],
        created_at: "2026-11-09T12:00:00",
      },
    });

    render(
      <MemoryRouter initialEntries={["/jobs/7"]}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "Platform Engineer" })).toBeInTheDocument();
    await waitFor(() => expect(api.get).toHaveBeenCalledWith("/api/jobs/7"));
    expect(screen.queryByRole("button", { name: "Apply Now" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Analyze Resume Match" })).not.toBeInTheDocument();
  });

  it("does not establish an admin session for a non-admin account", async () => {
    api.post.mockResolvedValueOnce({
      data: { access_token: "candidate-token", role: "candidate", full_name: "Test Candidate", id: 1 },
    });

    render(
      <MemoryRouter initialEntries={["/admin/login"]}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "Administrator Login" })).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("Email address"), {
      target: { value: "candidate@example.com" },
    });
    fireEvent.change(screen.getByPlaceholderText("Password"), {
      target: { value: "StrongPass123" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Log in as Administrator" }));

    expect(await screen.findByText("This account does not have administrator access.")).toBeInTheDocument();
    expect(localStorage.getItem("skillsphere_token")).toBeNull();
  });

  it("keeps administrator signup out of the public registration choices", () => {
    render(
      <MemoryRouter initialEntries={["/register"]}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>,
    );

    expect(screen.getByRole("option", { name: "Job Seeker" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Recruiter" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /admin/i })).not.toBeInTheDocument();
  });

  it("renders live admin dashboard data and filters accounts", async () => {
    localStorage.setItem("skillsphere_token", "admin-token");
    localStorage.setItem("skillsphere_role", "admin");
    localStorage.setItem("skillsphere_name", "Platform Admin");
    localStorage.setItem("skillsphere_user_id", "2");
    const responses = {
      "/api/admin/stats": {
        users: 2, candidates: 1, recruiters: 0, jobs: 1,
        active_jobs: 1, applications: 4,
      },
      "/api/admin/jobs": [{
        id: 8, title: "Frontend Engineer", company: "Example Co",
        location: "Remote", status: "published",
      }],
      "/api/admin/users": [
        { id: 1, full_name: "Asha Candidate", email: "asha@example.com", role: "candidate", is_active: true },
        { id: 2, full_name: "Platform Admin", email: "admin@example.com", role: "admin", is_active: true },
      ],
      "/api/admin/companies": [],
      "/api/admin/analytics/trends": { registrations: [], applications: [] },
      "/api/auth/me": { id: 2, role: "admin", full_name: "Platform Admin" },
      "/api/admin/system-status": { smtp_configured: false, missing_smtp_vars: ["SMTP_HOST"], ai_provider: "none", ai_configured: false, tesseract_available: true },
      "/api/admin/question-bank": {
        items: [
          {
            id: 1,
            question_type: "mcq",
            skill: "Python",
            category: "Backend",
            difficulty: "Medium",
            question_text: "Which HTTP status code indicates resource creation?",
            options: ["200", "201", "204", "400"],
            correct_option_index: 1,
            marks: 2,
          },
        ],
        skills: ["Python"],
        categories: ["Backend"],
      },
      "/api/admin/assessment-policy": { reveal_correct_answers_to_candidate: false },
    };
    api.get.mockImplementation((path) => Promise.resolve({ data: responses[path] }));

    render(
      <MemoryRouter initialEntries={["/admin"]}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>,
    );

    expect(await screen.findByText("Dashboard insights")).toBeInTheDocument();
    expect(screen.getByText("Asha Candidate")).toBeInTheDocument();
    expect(screen.getByText("Frontend Engineer")).toBeInTheDocument();
    expect(await screen.findByText("4", { selector: "strong" })).toBeInTheDocument();
    expect(await screen.findByText("Which HTTP status code indicates resource creation?")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Search users" }), {
      target: { value: "asha" },
    });
    expect(screen.getByText("Asha Candidate")).toBeInTheDocument();
    expect(within(screen.getAllByRole("table")[1]).getAllByRole("row")).toHaveLength(2);
  });

  it("allows admin to filter and add a 4-option MCQ in centralized Question Bank", async () => {
    localStorage.setItem("skillsphere_token", "admin-token");
    localStorage.setItem("skillsphere_role", "admin");
    localStorage.setItem("skillsphere_name", "Platform Admin");
    localStorage.setItem("skillsphere_user_id", "2");

    const responses = {
      "/api/admin/stats": { users: 1, candidates: 1, recruiters: 0, jobs: 1, active_jobs: 1, applications: 1 },
      "/api/admin/jobs": [],
      "/api/admin/users": [],
      "/api/admin/companies": [],
      "/api/admin/analytics/trends": { registrations: [], applications: [] },
      "/api/auth/me": { id: 2, role: "admin", full_name: "Platform Admin" },
      "/api/admin/system-status": { smtp_configured: false, missing_smtp_vars: ["SMTP_HOST"], ai_provider: "none", ai_configured: false, tesseract_available: true },
      "/api/admin/question-bank": {
        items: [
          {
            id: 11,
            question_type: "mcq",
            skill: "React",
            category: "Frontend",
            difficulty: "Easy",
            question_text: "Which hook manages local component state?",
            options: ["useEffect", "useState", "useMemo", "useRef"],
            correct_option_index: 1,
            marks: 1,
          },
        ],
        skills: ["React", "Python"],
        categories: ["Frontend", "Backend"],
      },
      "/api/admin/assessment-policy": { reveal_correct_answers_to_candidate: false },
    };
    api.get.mockImplementation((path) => Promise.resolve({ data: responses[path] }));
    api.post.mockResolvedValueOnce({ data: { id: 12 } });

    render(
      <MemoryRouter initialEntries={["/admin"]}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>,
    );

    expect(await screen.findByText("Which hook manages local component state?")).toBeInTheDocument();

    fireEvent.change(screen.getByRole("textbox", { name: "Search Question Bank" }), { target: { value: "React" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Filter Question Bank by skill" }), { target: { value: "React" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Filter Question Bank by difficulty" }), { target: { value: "Easy" } });
    fireEvent.click(screen.getByRole("button", { name: "Filter" }));

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith(
        "/api/admin/question-bank",
        expect.objectContaining({
          params: expect.objectContaining({ q: "React", skill: "React", difficulty: "Easy" }),
        }),
      );
    });

    fireEvent.click(screen.getByRole("button", { name: "+ Add MCQ Question" }));
    fireEvent.change(screen.getByPlaceholderText("Skill (e.g., Python, React, SQL, FastAPI)"), { target: { value: "FastAPI" } });
    fireEvent.change(screen.getByPlaceholderText("Category (e.g., Backend, Frontend, Database)"), { target: { value: "Backend" } });
    fireEvent.change(screen.getByPlaceholderText("Enter MCQ question text..."), { target: { value: "What library validates FastAPI schemas?" } });
    fireEvent.change(screen.getByPlaceholderText("Option A"), { target: { value: "Pydantic" } });
    fireEvent.change(screen.getByPlaceholderText("Option B"), { target: { value: "Jinja2" } });
    fireEvent.change(screen.getByPlaceholderText("Option C"), { target: { value: "Gunicorn" } });
    fireEvent.change(screen.getByPlaceholderText("Option D"), { target: { value: "Celery" } });
    fireEvent.click(screen.getByRole("button", { name: "Save Question" }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/api/admin/question-bank",
        expect.objectContaining({
          question_type: "mcq",
          skill: "FastAPI",
          options: ["Pydantic", "Jinja2", "Gunicorn", "Celery"],
        }),
      );
    });
  });

  it("renders recruiter ATS applicant cards without raw placeholders and opens candidate profile modal", async () => {
    localStorage.setItem("skillsphere_token", "recruiter-token");
    localStorage.setItem("skillsphere_role", "recruiter");
    localStorage.setItem("skillsphere_name", "Hiring Lead");
    localStorage.setItem("skillsphere_user_id", "10");

    const applicantItem = {
      id: 99,
      candidate: "Anjali Candidate",
      email: "anjali@example.com",
      contact_email: "anjali@example.com",
      job_id: 5,
      job_title: "Python Developer",
      company: "TechCo",
      status: "shortlisted",
      shortlist_source: "automatic",
      match_score: 84.5,
      matched_skills: ["Python", "FastAPI"],
      missing_skills: ["Docker"],
      matching_explanation: "Strong match across backend skills.",
      applied_at: "2026-11-11T10:00:00Z",
      education: "[Degree / Diploma / 12th] â€” [College / School Name], [City]",
      experience: "2 years Python",
      projects: null,
      certifications: null,
      location: "Mohali",
      summary: null,
      skills: ["Python", "FastAPI"],
      invitation_status: "sent",
      assessment_status: "submitted",
      assessment_score: 18,
      assessment_max_score: 20,
      assessment_percentage: 90.0,
      assessment_result_status: "Selected for next round",
      assessment_completed_at: "2026-11-11T11:00:00Z",
      status_history: [{ id: 1, previous_status: "applied", new_status: "shortlisted", actor_name: "SkillSphere AI Shortlisting", actor_role: "system", created_at: "2026-11-11T10:00:05Z" }],
      assessment_questions: [],
    };

    api.get.mockImplementation((path) => {
      if (path === "/api/recruiters/jobs") {
        return Promise.resolve({ data: [{ id: 5, title: "Python Developer", status: "published", skills: ["Python", "FastAPI"], applications_count: 1 }] });
      }
      if (path === "/api/recruiters/stats") {
        return Promise.resolve({ data: { jobs: 1, active_jobs: 1, applications: 1, pending_applications: 0 } });
      }
      if (path === "/api/companies/me") {
        return Promise.resolve({ data: { id: 1, name: "TechCo", is_approved: true } });
      }
      if (path === "/api/recruiters/jobs/5/applicants") {
        return Promise.resolve({ data: [applicantItem] });
      }
      if (path === "/api/recruiter/applicants/99") {
        return Promise.resolve({ data: applicantItem });
      }
      return Promise.resolve({ data: [] });
    });

    render(
      <MemoryRouter initialEntries={["/recruiter"]}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>,
    );

    expect(await screen.findByText("Python Developer", { selector: "strong" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "View applicants" }));

    expect(await screen.findByRole("heading", { name: "Anjali Candidate" })).toBeInTheDocument();
    expect(screen.queryByText(/College \/ School Name/)).not.toBeInTheDocument();
    expect(screen.getAllByText(/Auto-Shortlisted/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/18\/20/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "View Candidate Profile" }));
    expect(await screen.findByRole("dialog", { name: "Candidate Profile Details" })).toBeInTheDocument();
  });

  it("supports recruiter Question Bank test builder, manual shortlisted assignment, and results review", async () => {
    localStorage.setItem("skillsphere_token", "recruiter-token");
    localStorage.setItem("skillsphere_role", "recruiter");
    localStorage.setItem("skillsphere_name", "Hiring Lead");
    localStorage.setItem("skillsphere_user_id", "10");

    const shortlistItem = {
      id: 99,
      candidate: "Anjali Candidate",
      email: "anjali@example.com",
      contact_email: "anjali@example.com",
      job_id: 5,
      job_title: "Python Developer",
      company: "TechCo",
      status: "shortlisted",
      shortlist_source: "automatic",
      match_score: 88.0,
      matched_skills: ["Python", "FastAPI"],
      missing_skills: [],
      matching_explanation: "Matched required skills.",
      applied_at: "2026-11-11T10:00:00Z",
      skills: ["Python", "FastAPI"],
      invitation_status: "not_invited",
      assessment_status: "not_assigned",
      status_history: [],
    };

    const publishedAssessment = {
      id: 41,
      job_id: 5,
      job_title: "Python Developer",
      title: "Round 1 Python Technical Test",
      duration_minutes: 30,
      passing_marks: 1,
      total_questions: 1,
      total_marks: 2,
      status: "published",
      assignments_count: 1,
      submitted_count: 1,
    };

    const resultRow = {
      assignment_id: 700,
      candidate_name: "Anjali Candidate",
      candidate_email: "anjali@example.com",
      job_title: "Python Developer",
      assessment_title: "Round 1 Python Technical Test",
      assigned_at: "2026-11-11T10:30:00Z",
      invitation_status: "sent",
      test_status: "submitted",
      submitted_at: "2026-11-11T11:00:00Z",
      obtained_marks: 2,
      total_marks: 2,
      percentage: 100.0,
      is_passed: true,
      result_status: "Selected for next round",
    };

    api.get.mockImplementation((path) => {
      if (path === "/api/recruiters/jobs") {
        return Promise.resolve({ data: [{ id: 5, title: "Python Developer", status: "published", skills: ["Python", "FastAPI"], applications_count: 1 }] });
      }
      if (path === "/api/recruiters/stats") {
        return Promise.resolve({ data: { jobs: 1, active_jobs: 1, applications: 1, pending_applications: 0 } });
      }
      if (path === "/api/companies/me") {
        return Promise.resolve({ data: { id: 1, name: "TechCo", is_approved: true } });
      }
      if (path === "/api/recruiter/assessments") {
        return Promise.resolve({ data: [publishedAssessment] });
      }
      if (path === "/api/recruiter/question-bank") {
        return Promise.resolve({
          data: {
            items: [
              { id: 101, skill: "Python", category: "Backend", difficulty: "Medium", marks: 2, question_text: "What does yield do in Python?" },
            ],
            skills: ["Python"],
            categories: ["Backend"],
            job_skills: ["Python", "FastAPI"],
          },
        });
      }
      if (path === "/api/recruiters/jobs/5/applicants" || path === "/api/recruiter/applicants") {
        return Promise.resolve({ data: [shortlistItem] });
      }
      if (path === "/api/recruiter/assessment-results") {
        return Promise.resolve({ data: [resultRow] });
      }
      if (path === "/api/recruiter/assessment-results/700") {
        return Promise.resolve({
          data: {
            ...resultRow,
            passing_marks: 1,
            questions: [
              {
                id: 501,
                order_index: 1,
                skill: "Python",
                difficulty: "Medium",
                marks: 2,
                marks_awarded: 2,
                is_correct: true,
                question_text: "What does yield do in Python?",
                options: ["Creates a generator", "Stops loop", "Deletes object", "Sorts list"],
                selected_option_index: 0,
                correct_option_index: 0,
              },
            ],
          },
        });
      }
      return Promise.resolve({ data: [] });
    });
    api.post.mockImplementation((path) => {
      if (path === "/api/recruiter/assessments") {
        return Promise.resolve({ data: publishedAssessment });
      }
      if (path === "/api/recruiter/assessments/41/assign") {
        return Promise.resolve({
          data: {
            assigned_count: 1,
            sent_count: 1,
            failed_count: 0,
            skipped_count: 0,
            results: [{ application_id: 99, candidate: "Anjali Candidate", email: "anjali@example.com", invitation_status: "sent", message: "Invitation sent." }],
          },
        });
      }
      return Promise.resolve({ data: {} });
    });

    render(
      <MemoryRouter initialEntries={["/recruiter"]}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>,
    );

    // 1. Build and publish an MCQ assessment from Question Bank
    expect(await screen.findByText("Assessments / Manage Tests")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "+ Create Assessment" }));

    expect(await screen.findByText("What does yield do in Python?")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "Assessment job posting" }), { target: { value: "5" } });
    fireEvent.change(screen.getByPlaceholderText("Assessment Title (e.g., Round 1 Python Technical Test)"), { target: { value: "Round 1 Python Technical Test" } });
    fireEvent.click(screen.getByRole("button", { name: "+ Add" }));
    fireEvent.click(screen.getByRole("button", { name: "Publish Assessment" }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/api/recruiter/assessments",
        expect.objectContaining({
          job_id: 5,
          title: "Round 1 Python Technical Test",
          question_ids: [101],
          status: "published",
        }),
      );
    });

    // 2. Manually assign assessment to shortlisted candidate
    fireEvent.click(screen.getByRole("button", { name: /^Assign Assessment/ }));
    const assignDialog = await screen.findByRole("dialog", { name: "Assign Assessment to Shortlisted Candidates" });
    fireEvent.click(within(assignDialog).getByRole("checkbox"));
    fireEvent.click(within(assignDialog).getByRole("button", { name: "Review Assignment (1 selected)" }));
    fireEvent.click(within(assignDialog).getByRole("button", { name: "Confirm & Send Invitations" }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/api/recruiter/assessments/41/assign",
        expect.objectContaining({ application_ids: [99] }),
      );
    });
    expect(await within(assignDialog).findByText("Assignment Complete")).toBeInTheDocument();
    fireEvent.click(within(assignDialog).getByRole("button", { name: "Done" }));

    // 3. View Assessment Results & Q/A detail modal
    expect(await screen.findByText("Selected for next round", { selector: "span" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "View Answers" }));
    const detailDialog = await screen.findByRole("dialog", { name: "Candidate Assessment Result Details" });
    expect(within(detailDialog).getAllByText("Creates a generator")).toHaveLength(2);
  });

  it("supports the candidate online assessment portal workflow and hides answers when unauthorized", async () => {
    localStorage.setItem("skillsphere_token", "cand-token");
    localStorage.setItem("skillsphere_role", "candidate");

    api.get.mockResolvedValueOnce({
      data: {
        invitation_status: "sent",
        test_status: "assigned",
        job_title: "Python Developer",
        company_name: "TechCo",
        title: "Python Developer Technical Assessment",
        total_questions: 1,
        total_marks: 2,
        passing_marks: 1,
        duration_minutes: 30,
        instructions: "Answer all questions.",
        expires_at: "2026-11-14T10:00:00Z",
        requires_auth: false,
      },
    });
    api.post.mockResolvedValueOnce({
      data: {
        assessment_id: 1,
        title: "Python Developer Technical Assessment",
        total_questions: 1,
        total_marks: 2,
        duration_minutes: 30,
        remaining_seconds: 1800,
        questions: [
          { id: 101, order_index: 1, skill: "Python", difficulty: "Medium", question_text: "What is Python?", options: ["Language", "Database", "Browser", "OS"], selected_option_index: null },
        ],
      },
    });
    api.put.mockResolvedValueOnce({ data: { question_id: 101, selected_option_index: 0 } });
    api.post.mockResolvedValueOnce({
      data: { id: 1, event_type: "tab_switch" },
    });
    api.post.mockResolvedValueOnce({
      data: { message: "Your assessment has been submitted successfully. The recruiter will review your submission and contact you regarding the next steps." },
    });

    const videoTrack = { readyState: "live", addEventListener: vi.fn(), stop: vi.fn() };
    const audioTrack = { readyState: "live", addEventListener: vi.fn(), stop: vi.fn() };
    const stream = {
      getVideoTracks: () => [videoTrack],
      getAudioTracks: () => [audioTrack],
      getTracks: () => [videoTrack, audioTrack],
    };
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: vi.fn().mockResolvedValue(stream) } });
    window.requestAnimationFrame = vi.fn(() => 1);
    window.cancelAnimationFrame = vi.fn();
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
    globalThis.AudioContext = class {
      state = "running";
      resume = vi.fn().mockResolvedValue();
      close = vi.fn().mockResolvedValue();
      createAnalyser = () => ({ fftSize: 256, getByteTimeDomainData: (samples) => samples.fill(128) });
      createMediaStreamSource = () => ({ connect: vi.fn() });
    };
    globalThis.MediaRecorder = class extends EventTarget {
      constructor(_stream, options) { super(); this.mimeType = options.mimeType; this.state = "inactive"; }
      start() { this.state = "recording"; }
      stop() { this.state = "inactive"; this.dispatchEvent(new Event("stop")); }
    };
    globalThis.MediaRecorder.isTypeSupported = () => true;

    render(
      <MemoryRouter initialEntries={["/assessment/test-token"]}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "Python Developer Technical Assessment" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Start Assessment" }));

    expect(await screen.findByText("What is Python?")).toBeInTheDocument();
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    document.dispatchEvent(new Event("visibilitychange"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Please return to the assessment");
    expect(screen.getByRole("alert")).toHaveTextContent("do not automatically disqualify you");
    fireEvent.click(screen.getByRole("radio", { name: /Language/ }));
    fireEvent.click(screen.getByRole("button", { name: "Submit Assessment" }));

    expect(await screen.findByText("Your assessment has been submitted successfully. The recruiter will review your submission and contact you regarding the next steps.")).toBeInTheDocument();
    expect(screen.queryByText(/100\.0%|Selected for next round|Total Marks|Correct answer/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Answer Review (Admin Authorized)")).not.toBeInTheDocument();
  });

  it("keeps the assessment unstarted and explains a denied camera or microphone permission", async () => {
    localStorage.setItem("skillsphere_token", "cand-token");
    localStorage.setItem("skillsphere_role", "candidate");
    api.get.mockResolvedValueOnce({
      data: {
        invitation_status: "sent",
        test_status: "assigned",
        job_title: "Python Developer",
        company_name: "TechCo",
        title: "Python Developer Technical Assessment",
        total_questions: 1,
        duration_minutes: 30,
        instructions: "Answer all questions.",
        expires_at: "2026-11-14T10:00:00Z",
        requires_auth: false,
      },
    });
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: vi.fn().mockRejectedValue(new DOMException("Permission denied", "NotAllowedError")) },
    });
    globalThis.MediaRecorder = class {};
    globalThis.MediaRecorder.isTypeSupported = () => true;

    render(
      <MemoryRouter initialEntries={["/assessment/camera-denied-token"]}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "Python Developer Technical Assessment" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Start Assessment" }));

    expect(await screen.findByText(/permission denied/i)).toBeInTheDocument();
    expect(screen.getByText("Camera Not Started")).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalledWith(
      "/api/assessments/camera-denied-token/start",
      expect.anything(),
    );
  });

  it("displays non-qualifying assessment result when candidate score is not strictly greater than passing marks", async () => {
    localStorage.setItem("skillsphere_token", "cand-token");
    localStorage.setItem("skillsphere_role", "candidate");

    api.get.mockResolvedValueOnce({
      data: {
        invitation_status: "sent",
        test_status: "submitted",
        title: "Round 1 SQL Screening",
        result: {
          message: "Your assessment has been submitted successfully. The recruiter will review your submission and contact you regarding the next steps.",
        },
      },
    });

    render(
      <MemoryRouter initialEntries={["/assessment/fail-token"]}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>,
    );

    expect(await screen.findByText("Your assessment has been submitted successfully. The recruiter will review your submission and contact you regarding the next steps.")).toBeInTheDocument();
    expect(screen.queryByText(/10 \/ 20|Not qualified|50%|Total Marks/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Answer Review (Admin Authorized)")).not.toBeInTheDocument();
  });

  it("handles recruiter Select/Reject confirmation dialogs, duplicate guard, and failed notification retry", async () => {
    localStorage.setItem("skillsphere_token", "recruiter-token");
    localStorage.setItem("skillsphere_role", "recruiter");
    localStorage.setItem("skillsphere_name", "Hiring Lead");
    localStorage.setItem("skillsphere_user_id", "10");

    const applicantOne = {
      id: 99,
      candidate: "Anjali Candidate",
      email: "anjali@example.com",
      job_id: 5,
      job_title: "Python Developer",
      company: "TechCo",
      status: "shortlisted",
      shortlist_source: "automatic",
      match_score: 88.5,
      matched_skills: ["Python", "FastAPI"],
      missing_skills: ["Docker"],
      applied_at: "2026-11-11T10:00:00Z",
      skills: ["Python", "FastAPI"],
      invitation_status: "sent",
      assessment_status: "submitted",
      latest_email_notification: {
        id: 401,
        notification_type: "candidate_shortlisted",
        status: "failed",
        error_message: "SMTP connection timed out",
      },
      status_history: [],
    };
    const applicantTwo = {
      id: 100,
      candidate: "Rohan Applicant",
      email: "rohan@example.com",
      job_id: 5,
      job_title: "Python Developer",
      company: "TechCo",
      status: "under_review",
      match_score: 42.0,
      matched_skills: ["SQL"],
      missing_skills: ["Python", "FastAPI"],
      applied_at: "2026-11-11T11:00:00Z",
      skills: ["SQL"],
      invitation_status: "not_invited",
      assessment_status: "not_assigned",
      status_history: [],
    };

    api.get.mockImplementation((path) => {
      if (path === "/api/recruiters/jobs") {
        return Promise.resolve({ data: [{ id: 5, title: "Python Developer", status: "published", skills: ["Python"], applications_count: 2 }] });
      }
      if (path === "/api/recruiters/stats") {
        return Promise.resolve({ data: { jobs: 1, active_jobs: 1, applications: 2, pending_applications: 1 } });
      }
      if (path === "/api/companies/me") {
        return Promise.resolve({ data: { id: 1, name: "TechCo", is_approved: true } });
      }
      if (path === "/api/recruiters/jobs/5/applicants" || path === "/api/recruiter/applicants") {
        return Promise.resolve({ data: [applicantOne, applicantTwo] });
      }
      if (path === "/api/recruiter/interviews") {
        return Promise.resolve({ data: { items: [], counts_by_status: {} } });
      }
      if (path === "/api/recruiter/notifications") {
        return Promise.resolve({
          data: {
            items: [
              {
                id: 401,
                recipient_name: "Anjali Candidate",
                recipient_email: "anjali@example.com",
                job_title: "Python Developer",
                notification_type: "candidate_shortlisted",
                subject: "Shortlisted",
                status: "failed",
                error_message: "SMTP connection timed out",
                retry_count: 1,
                created_at: "2026-11-11T10:05:00Z",
              },
            ],
            counts_by_status: { sent: 0, failed: 1, pending: 0 },
          },
        });
      }
      return Promise.resolve({ data: [] });
    });

    api.post.mockImplementation((path, body) => {
      if (path === "/api/recruiter/notifications/401/resend") {
        return Promise.resolve({
          data: {
            message: "Notification email resent.",
            notification: { id: 401, notification_type: "candidate_shortlisted", status: "sent" },
          },
        });
      }
      if (path === "/api/recruiter/applications/99/select") {
        return Promise.resolve({
          data: {
            id: 99,
            application_id: 99,
            status: body.status,
            decision_changed: true,
            decision_reason: body.reason,
            decision_note: body.note,
            decided_at: "2026-11-12T10:00:00Z",
            notification_status: "sent",
            applicant: { ...applicantOne, status: body.status, decision_reason: body.reason, decision_note: body.note },
          },
        });
      }
      if (path === "/api/recruiter/applications/100/reject") {
        return Promise.resolve({
          data: {
            id: 100,
            application_id: 100,
            status: "rejected",
            decision_changed: true,
            decision_reason: body.reason,
            decision_note: body.note,
            decided_at: "2026-11-12T10:05:00Z",
            notification_status: "sent",
            applicant: { ...applicantTwo, status: "rejected", decision_reason: body.reason },
          },
        });
      }
      return Promise.resolve({ data: {} });
    });

    render(
      <MemoryRouter initialEntries={["/recruiter"]}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "View applicants" }));
    expect(await screen.findByText(/88\.5%/)).toBeInTheDocument();
    expect(screen.getByText(/Docker/)).toBeInTheDocument();

    const anjaliCard = screen.getByRole("heading", { name: "Anjali Candidate" }).closest("article");
    const rohanCard = screen.getByRole("heading", { name: "Rohan Applicant" }).closest("article");

    fireEvent.click(within(anjaliCard).getByRole("button", { name: "Retry Email" }));
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/api/recruiter/notifications/401/resend");
    });

    fireEvent.click(within(anjaliCard).getByRole("button", { name: "Select" }));
    const selectDialog = await screen.findByRole("dialog", { name: "Confirm Candidate Selection" });
    fireEvent.change(within(selectDialog).getByPlaceholderText(/Strong technical/i), { target: { value: "Strong technical performance" } });
    fireEvent.change(within(selectDialog).getByPlaceholderText(/next steps/i), { target: { value: "Offer next week" } });
    fireEvent.click(within(selectDialog).getByRole("button", { name: "Confirm Selection" }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/api/recruiter/applications/99/select", {
        status: "selected",
        reason: "Strong technical performance",
        note: "Offer next week",
        send_email: true,
      });
    });

    expect(await within(anjaliCard).findByRole("button", { name: "Mark Accepted" })).toBeInTheDocument();

    fireEvent.click(within(rohanCard).getByRole("button", { name: "Reject" }));
    const rejectDialog = await screen.findByRole("dialog", { name: "Confirm Candidate Rejection" });
    fireEvent.change(within(rejectDialog).getByPlaceholderText(/Insufficient backend/i), { target: { value: "Skill mismatch" } });
    fireEvent.click(within(rejectDialog).getByRole("button", { name: "Confirm Rejection" }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/api/recruiter/applications/100/reject", {
        reason: "Skill mismatch",
        note: null,
        send_email: true,
      });
    });
  });

  it("supports recruiter interview scheduling, rescheduling, feedback, and cancellation", async () => {
    localStorage.setItem("skillsphere_token", "recruiter-token");
    localStorage.setItem("skillsphere_role", "recruiter");
    localStorage.setItem("skillsphere_name", "Hiring Lead");
    localStorage.setItem("skillsphere_user_id", "10");

    const scheduledInterview = {
      id: 501,
      application_id: 99,
      application_status: "interview",
      job_id: 5,
      job_title: "Python Developer",
      company: "TechCo",
      candidate_name: "Anjali Candidate",
      candidate_email: "anjali@example.com",
      round_number: 1,
      round_name: "Technical Round 1",
      interview_mode: "online",
      scheduled_at: "2027-01-15T10:00:00Z",
      duration_minutes: 45,
      timezone: "UTC",
      meeting_link: "https://meet.example.com/r1",
      interviewer_name: "Priya Sharma",
      status: "scheduled",
    };

    const applicantItem = {
      id: 99,
      candidate: "Anjali Candidate",
      email: "anjali@example.com",
      job_id: 5,
      job_title: "Python Developer",
      company: "TechCo",
      status: "shortlisted",
      match_score: 90.0,
      matched_skills: ["Python"],
      missing_skills: [],
      applied_at: "2026-11-11T10:00:00Z",
      skills: ["Python"],
      invitation_status: "not_invited",
      assessment_status: "not_assigned",
      status_history: [],
    };

    api.get.mockImplementation((path) => {
      if (path === "/api/recruiters/jobs") {
        return Promise.resolve({ data: [{ id: 5, title: "Python Developer", status: "published", skills: ["Python"], applications_count: 1 }] });
      }
      if (path === "/api/recruiters/stats") {
        return Promise.resolve({ data: { jobs: 1, active_jobs: 1, applications: 1, pending_applications: 0 } });
      }
      if (path === "/api/companies/me") {
        return Promise.resolve({ data: { id: 1, name: "TechCo", is_approved: true } });
      }
      if (path === "/api/recruiters/jobs/5/applicants" || path === "/api/recruiter/applicants") {
        return Promise.resolve({ data: [applicantItem] });
      }
      if (path === "/api/recruiter/interviews") {
        return Promise.resolve({ data: { items: [scheduledInterview], counts_by_status: { scheduled: 1 } } });
      }
      if (path === "/api/recruiter/notifications") {
        return Promise.resolve({ data: { items: [], counts_by_status: {} } });
      }
      return Promise.resolve({ data: [] });
    });

    api.post.mockImplementation((path, body) => {
      if (path === "/api/recruiter/applications/99/interviews") {
        return Promise.resolve({ data: { interview: { ...scheduledInterview, id: 502 }, notification_status: "sent" } });
      }
      if (path === "/api/recruiter/interviews/501/feedback") {
        return Promise.resolve({ data: { ...scheduledInterview, status: body.status, rating: body.rating, recommendation: body.recommendation, feedback: body.feedback } });
      }
      if (path === "/api/recruiter/interviews/501/cancel") {
        return Promise.resolve({ data: { interview: { ...scheduledInterview, status: "cancelled" }, notification_status: "sent" } });
      }
      return Promise.resolve({ data: {} });
    });
    api.put.mockResolvedValue({ data: { interview: { ...scheduledInterview, status: "rescheduled" }, notification_status: "sent" } });

    render(
      <MemoryRouter initialEntries={["/recruiter"]}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "View applicants" }));
    fireEvent.click(await screen.findByRole("button", { name: "Schedule Interview" }));

    const schedDialog = await screen.findByRole("dialog", { name: "Schedule Interview" });
    fireEvent.click(within(schedDialog).getByRole("button", { name: "Schedule Interview" }));
    expect(await within(schedDialog).findByRole("alert")).toHaveTextContent(/valid http:\/\/ or https:\/\/ meeting link/i);

    fireEvent.change(within(schedDialog).getByPlaceholderText("https://meet.google.com/..."), { target: { value: "https://meet.example.com/round2" } });
    fireEvent.change(within(schedDialog).getByPlaceholderText("e.g., Hiring Manager"), { target: { value: "Priya Sharma" } });
    fireEvent.click(within(schedDialog).getByRole("button", { name: "Schedule Interview" }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/api/recruiter/applications/99/interviews",
        expect.objectContaining({
          interview_mode: "online",
          meeting_link: "https://meet.example.com/round2",
          interviewer_name: "Priya Sharma",
          send_email: true,
        }),
      );
    });

    fireEvent.click(await screen.findByRole("button", { name: "Reschedule" }));
    const reschedDialog = await screen.findByRole("dialog", { name: "Reschedule Interview" });
    fireEvent.change(within(reschedDialog).getByPlaceholderText("https://meet.google.com/..."), { target: { value: "https://meet.example.com/r1-v2" } });
    fireEvent.click(within(reschedDialog).getByRole("button", { name: "Save New Schedule" }));
    await waitFor(() => {
      expect(api.put).toHaveBeenCalledWith(
        "/api/recruiter/interviews/501/reschedule",
        expect.objectContaining({ meeting_link: "https://meet.example.com/r1-v2" }),
      );
    });

    fireEvent.click(screen.getByRole("button", { name: "Feedback & Outcome" }));
    const feedbackDialog = await screen.findByRole("dialog", { name: "Interview Feedback & Outcome" });
    fireEvent.change(within(feedbackDialog).getByRole("combobox", { name: "Interview Recommendation" }), { target: { value: "strong_hire" } });
    fireEvent.change(within(feedbackDialog).getByPlaceholderText(/Technical strengths/i), { target: { value: "Excellent system design" } });
    fireEvent.click(within(feedbackDialog).getByRole("button", { name: "Save Feedback & Outcome" }));
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/api/recruiter/interviews/501/feedback",
        expect.objectContaining({
          status: "completed",
          rating: 5,
          recommendation: "strong_hire",
          feedback: "Excellent system design",
        }),
      );
    });

    fireEvent.click(screen.getByRole("button", { name: "Cancel Interview" }));
    const cancelDialog = await screen.findByRole("dialog", { name: "Cancel Interview" });
    fireEvent.change(within(cancelDialog).getByPlaceholderText("Reason for cancellation..."), { target: { value: "Role filled" } });
    fireEvent.click(within(cancelDialog).getByRole("button", { name: "Confirm Cancellation" }));
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/api/recruiter/interviews/501/cancel", {
        cancellation_reason: "Role filled",
        send_email: true,
      });
    });
  });

  it("displays candidate application decisions and interviews while hiding private interviewer notes and feedback", async () => {
    localStorage.setItem("skillsphere_token", "cand-token");
    localStorage.setItem("skillsphere_role", "candidate");
    localStorage.setItem("skillsphere_name", "Asha Candidate");
    localStorage.setItem("skillsphere_user_id", "3");

    api.get.mockImplementation((path) => {
      if (path === "/api/candidates/me") {
        return Promise.resolve({ data: { full_name: "Asha Candidate", skills: ["Python"] } });
      }
      if (path === "/api/applications/me") {
        return Promise.resolve({
          data: [
            {
              id: 71,
              job_id: 5,
              job: "Python Developer",
              company: "TechCo",
              created_at: "2026-11-10T10:00:00Z",
              status: "selected",
              match_score: 91.5,
              decision_reason: "Strong backend round",
              decision_note: "HR will send formal offer",
              decided_at: "2026-11-12T10:00:00Z",
            },
          ],
        });
      }
      if (path === "/api/candidates/interviews") {
        return Promise.resolve({
          data: [
            {
              id: 601,
              application_id: 71,
              job_id: 5,
              job_title: "Python Developer",
              company: "TechCo",
              round_number: 1,
              round_name: "System Design",
              interview_mode: "online",
              scheduled_at: "2027-01-20T11:00:00Z",
              duration_minutes: 60,
              timezone: "UTC",
              meeting_link: "https://meet.example.com/cand",
              interviewer_name: "Vikram Lead",
              notes_for_candidate: "Prepare system architecture examples",
              status: "scheduled",
              internal_notes: "SECRET_INTERNAL_DO_NOT_SHOW",
              feedback: "SECRET_FEEDBACK_TEXT",
              rating: 5,
              recommendation: "strong_hire",
            },
          ],
        });
      }
      return Promise.resolve({ data: [] });
    });

    render(
      <MemoryRouter initialEntries={["/candidate"]}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>,
    );

    expect(await screen.findByText("Strong backend round")).toBeInTheDocument();
    expect(screen.getByText("HR will send formal offer")).toBeInTheDocument();
    expect(screen.getByText("Round 1: System Design")).toBeInTheDocument();
    expect(screen.getByText("https://meet.example.com/cand")).toBeInTheDocument();
    expect(screen.getByText("Vikram Lead")).toBeInTheDocument();
    expect(screen.getByText("Prepare system architecture examples")).toBeInTheDocument();
    expect(screen.queryByText(/SECRET_INTERNAL_DO_NOT_SHOW/)).not.toBeInTheDocument();
    expect(screen.queryByText(/SECRET_FEEDBACK_TEXT/)).not.toBeInTheDocument();
  });

  it("renders read-only admin interviews oversight and notification audit logs without write controls", async () => {
    localStorage.setItem("skillsphere_token", "admin-token");
    localStorage.setItem("skillsphere_role", "admin");
    localStorage.setItem("skillsphere_name", "Platform Admin");
    localStorage.setItem("skillsphere_user_id", "2");

    const adminInterviewRow = {
      id: 801,
      round_number: 1,
      round_name: "Architecture Round",
      candidate_name: "Anjali Candidate",
      candidate_email: "anjali@example.com",
      job_title: "Python Developer",
      company: "TechCo",
      interview_mode: "online",
      scheduled_at: "2027-02-01T09:00:00Z",
      timezone: "UTC",
      meeting_link: "https://meet.example.com/admin-view",
      interviewer_name: "Priya Sharma",
      status: "completed",
      recommendation: "hire",
      feedback: "Good knowledge of FastAPI.",
      notifications: [{ id: 901, notification_type: "interview_scheduled", status: "sent", recipient_email: "anjali@example.com" }],
    };

    const responses = {
      "/api/admin/stats": { users: 2, candidates: 1, recruiters: 1, jobs: 1, active_jobs: 1, applications: 1 },
      "/api/admin/jobs": [],
      "/api/admin/users": [],
      "/api/admin/companies": [],
      "/api/admin/analytics/trends": { registrations: [], applications: [] },
      "/api/auth/me": { id: 2, role: "admin", full_name: "Platform Admin" },
      "/api/admin/system-status": { smtp_configured: true, missing_smtp_vars: [], ai_provider: "none", ai_configured: false, tesseract_available: true },
      "/api/admin/question-bank": { items: [], skills: [], categories: [] },
      "/api/admin/assessment-policy": { reveal_correct_answers_to_candidate: false },
      "/api/admin/interviews/summary": { total: 1, by_status: { scheduled: 0, rescheduled: 0, completed: 1, cancelled: 0, no_show: 0 } },
      "/api/admin/interviews": { items: [adminInterviewRow] },
      "/api/admin/interviews/801": adminInterviewRow,
      "/api/admin/notifications": {
        items: [
          {
            id: 901,
            recipient_name: "Anjali Candidate",
            recipient_email: "anjali@example.com",
            job_title: "Python Developer",
            notification_type: "interview_scheduled",
            subject: "Interview Scheduled",
            status: "sent",
            sent_at: "2026-11-12T09:05:00Z",
            retry_count: 0,
            created_at: "2026-11-12T09:04:00Z",
          },
          {
            id: 902,
            recipient_name: "Rohan Applicant",
            recipient_email: "rohan@example.com",
            job_title: "Python Developer",
            notification_type: "candidate_rejected",
            subject: "Application Update",
            status: "failed",
            error_message: "Mailbox rejected",
            retry_count: 1,
            created_at: "2026-11-12T09:10:00Z",
          },
        ],
        counts_by_status: { sent: 1, failed: 1, pending: 0 },
      },
    };
    api.get.mockImplementation((path) => Promise.resolve({ data: responses[path] }));

    render(
      <MemoryRouter initialEntries={["/admin"]}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>,
    );

    expect(await screen.findByText("Interview Management Overview")).toBeInTheDocument();
    expect(screen.getByText(/TechCo.*Round 1 \(Architecture Round\)/)).toBeInTheDocument();
    expect(screen.getByText("FAILED")).toBeInTheDocument();
    expect(screen.getByText("Mailbox rejected")).toBeInTheDocument();

    expect(screen.queryByRole("button", { name: /^Select$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Reject$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Schedule Interview/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Retry Email/i })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "View Details" }));
    const adminDialog = await screen.findByRole("dialog", { name: "Admin Interview Details" });
    expect(within(adminDialog).getByText(/Good knowledge of FastAPI\./)).toBeInTheDocument();
  });
});


