import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import LiveInterviewRoom from "./LiveInterviewRoom";
import VideoAssessmentPortal from "./VideoAssessmentPortal";
import RecruiterAssessments from "./RecruiterAssessments";

vi.mock("../api", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));
import api from "../api";

vi.mock("../AuthContext", () => ({
  useAuth: () => ({
    token: "mock-token",
    role: "candidate",
    name: "Test Candidate",
    email: "candidate@example.com",
    userId: 99,
  }),
}));

// Mock LiveKit Client
vi.mock("livekit-client", () => {
  return {
    Room: vi.fn().mockImplementation(() => ({
      on: vi.fn(),
      connect: vi.fn().mockResolvedValue(),
      disconnect: vi.fn().mockResolvedValue(),
      localParticipant: {
        setCameraEnabled: vi.fn().mockResolvedValue(),
        setMicrophoneEnabled: vi.fn().mockResolvedValue(),
      },
      participants: new Map(),
    })),
    RoomEvent: {
      Connected: "connected",
      Disconnected: "disconnected",
      ParticipantConnected: "participantConnected",
      ParticipantDisconnected: "participantDisconnected",
      TrackSubscribed: "trackSubscribed",
      TrackUnsubscribed: "trackUnsubscribed",
      ConnectionQualityChanged: "connectionQualityChanged",
      Reconnecting: "reconnecting",
      Reconnected: "reconnected",
      RoomMetadataChanged: "roomMetadataChanged",
    },
    VideoPresets: {
      h720: {},
    },
  };
});

describe("LiveInterviewRoom Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Mock navigator.mediaDevices in jsdom
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: {
        getUserMedia: vi.fn().mockResolvedValue({
          getTracks: () => [{ stop: vi.fn() }],
          getVideoTracks: () => [{ stop: vi.fn() }],
          getAudioTracks: () => [{ stop: vi.fn() }],
        }),
        enumerateDevices: vi.fn().mockResolvedValue([
          { deviceId: "default", kind: "videoinput", label: "Front Camera" },
          { deviceId: "default", kind: "audioinput", label: "Default Mic" },
        ]),
      },
      writable: true,
      configurable: true,
    });
  });

  it("fetches interview session status and displays pre-join device check", async () => {
    api.get.mockImplementation((url) => {
      if (url.includes("/session-status")) {
        return Promise.resolve({
          data: {
            interview_id: 42,
            room_name: "skillsphere-app-1-int-42",
            interview_type: "technical",
            status: "scheduled",
            role: "candidate",
            is_candidate_admitted: false,
            is_waiting_room_enabled: true,
            is_recording: false,
          },
        });
      }
      return Promise.resolve({ data: {} });
    });

    render(
      <MemoryRouter initialEntries={["/live-interview/42"]}>
        <Routes>
          <Route path="/live-interview/:interviewId" element={<LiveInterviewRoom />} />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByText(/Check Camera and Microphone/i)).toBeInTheDocument();
    expect(screen.getByText(/Media & Device Setup/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Enter Waiting Room/i })).toBeInTheDocument();
  });

  it("enters candidate waiting room when waiting room is enabled", async () => {
    api.get.mockImplementation((url) => {
      if (url.includes("/session-status")) {
        return Promise.resolve({
          data: {
            interview_id: 42,
            room_name: "skillsphere-app-1-int-42",
            interview_type: "technical",
            status: "scheduled",
            role: "candidate",
            is_candidate_admitted: false,
            is_waiting_room_enabled: true,
            is_recording: false,
          },
        });
      }
      return Promise.resolve({ data: {} });
    });

    api.post.mockImplementation((url) => {
      if (url.includes("/waiting-room/join")) {
        return Promise.resolve({
          data: {
            status: "waiting",
            message: "Joined waiting room",
            admitted: false,
          },
        });
      }
      return Promise.resolve({ data: {} });
    });

    render(
      <MemoryRouter initialEntries={["/live-interview/42"]}>
        <Routes>
          <Route path="/live-interview/:interviewId" element={<LiveInterviewRoom />} />
        </Routes>
      </MemoryRouter>
    );

    const joinBtn = await screen.findByRole("button", { name: /Enter Waiting Room/i });
    fireEvent.click(joinBtn);

    expect(await screen.findByText(/Waiting for Recruiter Admission/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Leave Waiting Room/i })).toBeInTheDocument();
  });
});

describe("VideoAssessmentPortal Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("loads video assessment info and displays system check", async () => {
    api.get.mockImplementation((url) => {
      if (url.includes("/api/assessments/test-token-123")) {
        return Promise.resolve({
          data: {
            title: "Async Senior Frontend Video Screen",
            description: "Recorded assessment with 2 questions.",
            assessment_type: "video",
            prep_time_seconds: 30,
            response_time_seconds: 120,
            allow_review: true,
            max_recordings_per_question: 2,
            test_status: "assigned",
            invitation_status: "sent",
            candidate_name: "Jane Doe",
            job_title: "Staff Engineer",
          },
        });
      }
      return Promise.resolve({ data: {} });
    });

    render(
      <MemoryRouter initialEntries={["/video-assessment/test-token-123"]}>
        <Routes>
          <Route path="/video-assessment/:token" element={<VideoAssessmentPortal />} />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByText(/Async Senior Frontend Video Screen/i)).toBeInTheDocument();
    expect(screen.getByText(/Asynchronous Video Assessment/i)).toBeInTheDocument();
    expect(screen.getByText(/30s per question/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Start Video Assessment/i })).toBeInTheDocument();
  });
});

describe("Recruiter Video Assessment Creation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("opens video assessment builder and submits payload with prep & response limits", async () => {
    api.get.mockImplementation((url) => {
      if (url.includes("/assessments")) {
        return Promise.resolve({ data: [] });
      }
      return Promise.resolve({ data: [] });
    });
    api.post.mockResolvedValue({ data: { id: 101, title: "Backend Lead Video Screen" } });

    render(
      <RecruiterAssessments
        jobs={[{ id: 9, title: "Backend Lead", status: "published" }]}
      />
    );

    const videoBtn = await screen.findByRole("button", { name: /Video Assessment/i });
    fireEvent.click(videoBtn);

    expect(await screen.findByText("Create Video Assessment")).toBeInTheDocument();

    // Fill title
    fireEvent.change(screen.getByPlaceholderText(/e.g., Senior Full-Stack Technical Video Screen/i), {
      target: { value: "Backend Lead Video Screen" },
    });

    // Fill question prompt
    fireEvent.change(
      screen.getByPlaceholderText(/Interview prompt \/ question/i),
      { target: { value: "Explain how you handle distributed database transactions." } }
    );

    // Click Publish
    const publishBtn = screen.getByRole("button", { name: "Publish Video Assessment" });
    fireEvent.click(publishBtn);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/api/recruiter/video-assessments",
        expect.objectContaining({
          job_id: 9,
          title: "Backend Lead Video Screen",
          status: "published",
          prep_time_seconds: 30,
          response_time_seconds: 120,
          allow_review: true,
          questions: expect.arrayContaining([
            expect.objectContaining({
              question_text: "Explain how you handle distributed database transactions.",
            }),
          ]),
        })
      );
    });
  });
});
