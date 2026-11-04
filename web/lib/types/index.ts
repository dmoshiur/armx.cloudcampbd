export type Role = "admin" | "vip" | "user";

export interface User {
  id: string;
  email: string;
  display_name: string;
  role: Role;
  is_verified: boolean;
  is_active: boolean;
  theme: string;
  avatar_url?: string | null;
  last_login_at?: string | null;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface ToolEvent {
  tool: string;
  risk: string;
  ok: boolean;
  result?: { ok: boolean; data?: Record<string, unknown>; message?: string; error?: string };
  blocked?: string;
  error?: string;
  approved?: boolean;
  dry_run?: boolean;
}

export interface Approval {
  id: string;
  tool: string;
  risk: string;
  description: string;
  args: Record<string, unknown>;
  expires_at: string;
  action_hash: string;
  run_id?: string;
  seconds_remaining?: number;
  status?: string;
  can_retry?: boolean;
}

export interface ChatResponse {
  status: "complete" | "awaiting_approval" | "rejected" | "error" | "stopped";
  request_id?: string;
  reply: string;
  run_id: string;
  conversation_id: string;
  approval: Approval | null;
  tool_events: ToolEvent[];
  steps: number;
  provider: string;
  model: string;
  error?: string | null;
  error_code?: string | null;
  hint?: string | null;
  message_id?: string | null;
  usage?: { input: number; output: number };
  fallback_reason?: string | null;
  streamed?: boolean;
}

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  archived: boolean;
  pinned: boolean;
  model: string;
  token_usage: number;
  project_id: string | null;
  message_count: number;
  summary: string;
}

export interface ChatMessage {
  id: string;
  role: string;
  content: string;
  created_at: string;
  model?: string;
  provider?: string;
  input_tokens?: number;
  output_tokens?: number;
  status?: string;
  error?: string;
  edited_at?: string | null;
}

export interface ConversationDetail extends Conversation {
  messages: ChatMessage[];
  has_more: boolean;
  total_messages: number;
}

export interface ToolInfo {
  name: string;
  description: string;
  risk: "low" | "medium" | "high";
  category: string;
  scopes: string[];
  confirm: boolean;
  dry_run_supported: boolean;
  enabled: boolean;
  reason: string;
}

export interface ToolRegistryEntry {
  id: string;
  name: string;
  description: string;
  category: string;
  risk: string;
  permissions: string[];
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  requires_approval: boolean;
  timeout_seconds: number;
  rate_limit_per_minute: number;
  dry_run_supported: boolean;
  enabled: boolean;
  reason: string;
  status: string;
}

export interface IntegrationStatus {
  provider: string;
  configured: boolean;
  mode: string;
  detail: string;
  simulated?: boolean;
}

export interface Project {
  id: string;
  name: string;
  slug: string;
  description?: string;
  status: string;
  lint_status: string;
  repo_url: string;
  repo_is_platform_owned: boolean;
  vercel_url: string;
  deploy_status: string;
  deploy_provider?: string;
  deploy_confirmed_at?: string | null;
  deploy_message?: string;
  turso_db_ref: string;
  updated_at: string;
  simulated?: boolean;
  deployment_id?: string;
}

export interface ProjectDetail extends Project {
  description: string;
  files: string[];
  lint: { ok?: boolean; score?: number; errors?: { message: string }[]; warnings?: { message: string }[] };
  preview_url: string;
}

export interface Device {
  id: string;
  name: string;
  platform: string;
  status: string;
  capabilities: string[];
  persistent_notification: boolean;
  last_seen_at: string | null;
  created_at: string;
  ip_address?: string;
  pairing_completed_at?: string | null;
}

export interface HealthStatus {
  status: string;
  app: string;
  env: string;
  database: string;
  planner: {
    provider: string;
    model: string;
    live: boolean;
    ready: boolean;
    readiness: "verified" | "unverified" | "degraded" | "offline";
    enabled_models: number;
    healthy_models: number;
    unverified_models: number;
    key_pool_size: number;
    configured_provider: string;
    models?: { id: string; provider: string; model: string; display_name: string; status: string; last_error: string }[];
  };
  kill_switch: string;
  tools: number;
  pipeline_mode: string;
}

export interface AdminOverview {
  users: number;
  active_users: number;
  devices: number;
  linked_devices: number;
  pending_approvals: number;
  audit_events: number;
  generated_projects: number;
  active_sessions: number;
  kill_switch: string;
  tools: { total: number; enabled: number };
}

export interface AuditEntry {
  id: string;
  ts: string;
  actor_email: string;
  actor_role: string;
  action: string;
  tool: string;
  risk: string;
  target: string;
  status: string;
  ip_address: string;
  detail: Record<string, unknown>;
  entry_hash: string;
}

export interface MemoryItem {
  id: string;
  category: string;
  content: string;
  source: string;
  source_conversation_id: string | null;
  importance: number;
  keywords: string[];
  use_count: number;
  last_used_at: string | null;
  active: boolean;
  pinned: boolean;
  created_at: string;
  updated_at: string;
  score?: number;
  created?: boolean;
}

export interface AutomationRule {
  id: string;
  name: string;
  trigger: string;
  action: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface ActivityItem {
  id: string;
  ts: string;
  source: "audit" | "llm";
  kind: string;
  status: string;
  tool?: string;
  risk?: string;
  actor?: string;
  provider?: string;
  model?: string;
  latency_ms?: number;
  tokens?: number;
  error_code?: string;
  detail: Record<string, unknown>;
}

export interface MatrixStatus {
  available: boolean;
  running: boolean;
  mode: string;
  binary: string;
  version: string;
  pty_supported: boolean;
  reason: string;
  implementation: string;
  license: { project: string; license: string; source: string };
  cols: number;
  rows: number;
  speed: number;
  fps: number;
  subscribers: number;
  transports: string[];
}

export type StreamEvent = {
  type: "open" | "start" | "status" | "delta" | "tool" | "approval" | "result" | "error" | "stopped";
  text?: string;
  run_id?: string;
  conversation_id?: string;
  request_id?: string;
  event?: ToolEvent;
  approval?: Approval;
  outcome?: ChatResponse;
  error?: string;
  code?: string;
  hint?: string;
  stage?: string;
  provider?: string;
  model?: string;
  step?: number;
  retryable?: boolean;
  can_retry?: boolean;
  retry_url?: string;
};

export interface UploadResult {
  asset_id: string;
  url: string;
  filename: string;
  content_type: string;
  kind: "image" | "document";
  bytes: number;
  text: string;
}
