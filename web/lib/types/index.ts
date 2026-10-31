export type Role = "admin" | "vip" | "user";

export interface User {
  id: string;
  email: string;
  display_name: string;
  role: Role;
  is_verified: boolean;
  theme: string;
  avatar_url?: string | null;
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
}

export interface Approval {
  id: string;
  tool: string;
  risk: string;
  description: string;
  args: Record<string, unknown>;
  expires_at: string;
  action_hash: string;
}

export interface ChatResponse {
  status: "complete" | "awaiting_approval" | "rejected" | "error";
  reply: string;
  run_id: string;
  conversation_id: string;
  approval: Approval | null;
  tool_events: ToolEvent[];
  steps: number;
  provider: string;
  error?: string | null;
}

export interface Conversation {
  id: string;
  title: string;
  updated_at: string;
  created_at: string;
}

export interface ConversationDetail {
  id: string;
  title: string;
  messages: { id: string; role: string; content: string; created_at: string }[];
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
  status: string;
  lint_status: string;
  repo_url: string;
  repo_is_platform_owned: boolean;
  vercel_url: string;
  deploy_status: string;
  turso_db_ref: string;
  updated_at: string;
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
}

export interface HealthStatus {
  status: string;
  app: string;
  env: string;
  database: string;
  planner: { provider: string; model: string; live: boolean; key_pool_size: number; configured_provider: string };
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
