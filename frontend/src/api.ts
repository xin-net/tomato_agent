import type {
  CaseDetail,
  CaseListItem,
  ConversationMessageResponse,
  FollowupTrend,
  AuthResponse,
  Reminder,
  User,
} from './types';

const TOKEN_KEY = 'tomatoAgentAccessToken';

export function getStoredToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function setStoredToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const token = getStoredToken();
  const response = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options?.headers,
    },
    ...options,
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `请求失败：${response.status}`);
  }

  return response.json() as Promise<T>;
}

export function register(input: { username: string; password: string }) {
  return request<AuthResponse>('/api/auth/register', {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export function login(input: { username: string; password: string }) {
  return request<AuthResponse>('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export function me() {
  return request<User>('/api/auth/me');
}

export function listCases(status?: string) {
  const query = status ? `?status=${encodeURIComponent(status)}` : '';
  return request<CaseListItem[]>(`/api/cases${query}`);
}

export function getCase(caseId: number) {
  return request<CaseDetail>(`/api/cases/${caseId}`);
}

export function getSystemStatus() {
  return request<{
    status: string;
    app: string;
    version: string;
    frontend_dist_available: boolean;
  }>('/api/system/status');
}

export function sendConversationMessage(input: {
  user_id: string;
  message: string;
  case_id?: number | null;
  image_urls?: string[];
}) {
  return request<ConversationMessageResponse>('/api/conversation/messages', {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export function submitFollowup(
  caseId: number,
  input: {
    description: string;
    actions_done?: string[];
    has_new_spots?: boolean | null;
    spots_expanded?: boolean | null;
    spread_to_new_parts?: boolean | null;
    fruit_affected?: boolean | null;
  },
) {
  return request(`/api/cases/${caseId}/followup`, {
    method: 'POST',
    body: JSON.stringify(input),
  }) as Promise<{
    case_id: number;
    status: string;
    response_type: string;
    message: string;
    trend?: FollowupTrend | null;
  }>;
}

export function closeCase(caseId: number, summary?: string) {
  return request(`/api/cases/${caseId}/close`, {
    method: 'POST',
    body: JSON.stringify({ summary }),
  });
}

export async function downloadCaseReport(caseId: number) {
  const token = getStoredToken();
  const response = await fetch(`/api/cases/${caseId}/report`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `tomato-case-${caseId}.md`;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function listReminders(status?: string) {
  const query = status ? `?status=${encodeURIComponent(status)}` : '';
  return request<Reminder[]>(`/api/reminders${query}`);
}

export function listDueReminders() {
  return request<Reminder[]>('/api/reminders/due');
}
