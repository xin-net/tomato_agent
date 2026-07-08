export type CaseStatus =
  | 'NEW'
  | 'NEED_MORE_INFO'
  | 'DIAGNOSED'
  | 'FOLLOWUP_PENDING'
  | 'FOLLOWUP_REVIEW'
  | 'IMPROVING'
  | 'WORSENING'
  | 'ESCALATED'
  | 'CLOSED';

export type AgentAction =
  | 'ASK_MORE_INFO'
  | 'DIAGNOSE_AND_PLAN'
  | 'COMPARE_FOLLOWUP'
  | 'ESCALATE'
  | 'CLOSE_CASE';

export type FollowupTrend =
  | 'IMPROVING'
  | 'UNCHANGED'
  | 'WORSENING'
  | 'INSUFFICIENT_INFO'
  | 'NEEDS_HUMAN_CONFIRMATION';

export interface AgentDecision {
  next_action: AgentAction;
  reason: string;
  confidence: string;
  requested_state?: CaseStatus | null;
  questions: string[];
  user_intent?: string;
  response_focus?: string[];
  followup_trend?: FollowupTrend | null;
  followup_evidence?: string[];
}

export interface Diagnosis {
  suspected_problem?: string | null;
  likelihood?: string | null;
  evidence: string[];
  confusions: string[];
}

export interface HandlingPlan {
  summary: string;
  immediate_actions: string[];
  observation_points: string[];
  escalation_conditions: string[];
  safety_warnings: string[];
  followup_after_days?: number | null;
}

export interface ClosedLoopAdvice {
  information_sufficient: boolean;
  problem_category?: string | null;
  severity: string;
  action_mode: string;
  chemical_advice: string;
  harvest_safety: string;
  plain_summary: string;
  immediate_actions: string[];
  observation_points: string[];
  escalation_conditions: string[];
  followup_timing?: string | null;
  followup_if_better: string[];
  followup_if_worse: string[];
  process_record: string[];
  environment_confirmation?: string | null;
}

export interface SafetyResult {
  chemical_detail_allowed: boolean;
  risk_level: string;
  warnings: string[];
  must_escalate: boolean;
}

export interface Followup {
  id: number;
  due_date: string;
  checklist: unknown[];
  status: string;
  submitted_at?: string | null;
  user_description?: string | null;
  result?: string | null;
}

export interface CaseResponse {
  case_id: number;
  status: CaseStatus;
  response_type: string;
  message: string;
  decision?: AgentDecision | null;
  diagnosis?: Diagnosis | null;
  plan?: HandlingPlan | null;
  safety?: SafetyResult | null;
  followup?: Followup | null;
  trend?: FollowupTrend | null;
  advice?: ClosedLoopAdvice | null;
}

export interface ConversationMessageResponse {
  case_id: number;
  created_case: boolean;
  response: CaseResponse;
}

export interface CaseListItem {
  id: number;
  title: string;
  crop: string;
  suspected_problem?: string | null;
  status: CaseStatus;
  followup_date?: string | null;
  created_at: string;
  updated_at: string;
}

export interface CaseEvent {
  id: number;
  event_type: string;
  user_input?: string | null;
  system_output: Record<string, unknown>;
  structured_data: Record<string, unknown>;
  created_at: string;
}

export interface AgentTrace {
  observe?: Record<string, unknown> & {
    input?: Record<string, unknown>;
    output?: Record<string, unknown>;
  };
  decide?: {
    input?: Record<string, unknown>;
    output?: Record<string, unknown>;
    source?: string;
    next_action?: string;
    requested_state?: string | null;
    confidence?: string;
    reason?: string;
    fallback_reason?: string | null;
    observations_used?: string[];
    user_intent?: string;
    response_focus?: string[];
  };
  act?: {
    input?: Record<string, unknown>;
    output?: Record<string, unknown>;
    planned_tools?: string[];
    questions?: string[];
  };
  guard?: {
    input?: Record<string, unknown>;
    output?: Record<string, unknown>;
    guardrails?: string[];
  };
  memory?: {
    input?: Record<string, unknown>;
    output?: Record<string, unknown>;
    will_write_events?: string[];
  };
}

export interface CaseDetail extends CaseListItem {
  user_id?: string | null;
  environment?: string | null;
  growth_stage?: string | null;
  symptoms: string;
  affected_parts: unknown[];
  severity?: string | null;
  recent_weather?: string | null;
  recent_fertilizer_use?: string | null;
  recent_pesticide_use?: string | null;
  days_to_harvest?: number | null;
  likelihood?: string | null;
  structured_data: Record<string, unknown>;
  current_plan: Partial<HandlingPlan>;
  events: CaseEvent[];
  followups: Followup[];
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'agent';
  content: string;
  imageUrls?: string[];
  response?: CaseResponse;
  pending?: boolean;
}

export interface User {
  id: number;
  username: string;
  role: string;
  is_active: boolean;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface Reminder {
  id: number;
  case_id: number;
  followup_id?: number | null;
  due_at: string;
  channel: string;
  status: string;
  reason?: string | null;
  calendar_url?: string | null;
  ics_url?: string | null;
  created_at: string;
  updated_at: string;
}
