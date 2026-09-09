export type EvidenceCitation = {
  id: string;
  document_id: string;
  document_title?: string | null;
  evidence_unit_id?: string;
  evidence_span_ids: string[];
  quote: string;
  span_texts: string[];
  char_start?: number | null;
  char_end?: number | null;
  heading_path?: string[];
};

export type GraphNode = {
  id: string;
  type: string;
  name: string;
  layer: string;
  brand_id?: string | null;
  properties?: Record<string, unknown>;
  citations?: EvidenceCitation[];
};

export type GraphEdge = {
  id: string;
  source: string;
  target: string;
  type: string;
  confidence: number;
  properties?: Record<string, unknown>;
  citations?: EvidenceCitation[];
};

export type GraphData = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  stats: { nodes: number; edges: number };
};

export type Stats = {
  documents: number;
  evidence_units: number;
  candidates: number;
  entities: number;
  relations: number;
  layers: Record<string, number>;
  jobs: Record<string, number>;
};

export type SearchItem = {
  kind: string;
  id: string;
  title: string;
  type: string;
  layer?: string;
  snippet: string;
  citations?: EvidenceCitation[];
};

export type ChatResult = {
  answer: string;
  mode: "local_retrieval" | "external_llm" | "local_fallback";
  sources: SearchItem[];
};

export type Job = {
  id: string;
  status: "queued" | "running" | "completed" | "failed";
  current_stage: string;
  progress: number;
  result: Record<string, unknown>;
  error?: string | null;
};
