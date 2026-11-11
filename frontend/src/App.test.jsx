import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { AuthProvider } from "./AuthContext";

vi.mock("./api", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

import api from "./api";

describe("SkillSphere application shell", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
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
    api.post.mockResolvedValue({
      data: { access_token: "candidate-token", role: "candidate", full_name: "Test Candidate" },
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
    fireEvent.change(screen.getByRole("textbox", { name: "Search users" }), {
      target: { value: "asha" },
    });
    expect(screen.getByText("Asha Candidate")).toBeInTheDocument();
    expect(within(screen.getAllByRole("table")[1]).getAllByRole("row")).toHaveLength(2);
  });
});
