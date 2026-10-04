export type ChatRole = 'user' | 'agent' | 'system';

export interface AgentCitation {
  evidence_id: string;
  page_number: number;
  document_type: string;
}

export interface AgentFinding {
  conclusion: string;
  citations: AgentCitation[];
  missing_information: string[];
  user_context: string[];
  conflicts: string[];
  evidence_score: number;
  confidence_level: 'low' | 'medium' | 'high';
  requires_human_review: boolean;
  source_verified: boolean;
}

export interface SpecialistResult {
  agent:
    | 'coverage'
    | 'prior_authorization'
    | 'medical_necessity'
    | 'referral';
  findings: AgentFinding[];
}

export interface AgentResponseData {
  results: SpecialistResult[];
  overall_evidence_score: number | null;
  overall_confidence_level: 'low' | 'medium' | 'high' | null;
  requires_human_review: boolean;
  clarification_question: string | null;
  notice: string;
}

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  timestamp: string;
  result?: AgentResponseData;
}

export interface ChatRequest {
  message: string;
  documentId: string;
  conversationId?: string;
  planName?: string;
  coverageYear?: number;
  serviceDate?: string;
}

export interface ChatResponse {
  success: boolean;
  reply: ChatMessage;
  conversationId?: string;
  evidenceCount?: number;
  error?: string;
}

export interface BackendChatResponse {
  conversation_id: string;
  evidence_count: number;
  response: AgentResponseData;
}
