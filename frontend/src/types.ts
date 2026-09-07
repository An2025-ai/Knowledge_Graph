export type GraphNode = {
  id: string;
  type: string;
  name: string;
  layer: string;
  brand_id?: string | null;
  properties?: Record<string, unknown>;
};

export type GraphEdge = {
  id: string;
  source: string;
  target: string;
  type: string;
  confidence: number;
  properties?: Record<string, unknown>;
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
