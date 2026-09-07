import { useState } from "react";
import type { AppSettings, ProviderTestResult } from "../api";

type Props = {
  initial: AppSettings;
  busy: boolean;
  onClose: () => void;
  onSubmit: (payload: Record<string, unknown>) => void;
  onTestLlm: (payload: Record<string, unknown>) => Promise<ProviderTestResult>;
  onTestEmbedding: (payload: Record<string, unknown>) => Promise<ProviderTestResult>;
};

function TestResult({ label, result, error }: { label: string; result: ProviderTestResult | null; error: string | null }) {
  if (!result && !error) return null;
  const status = error ? "error" : result?.status || "error";
  const message = error || result?.message || "连接测试失败";
  return <div className={`connection-test-result ${status === "error" ? "error" : ""}`}>
    <div className={`connection-row ${status}`}><span>{status === "ok" ? "✓" : status === "error" ? "!" : "–"}</span><b>{label}</b><small>{message}</small></div>
  </div>;
}

export default function SettingsDialog({ initial, busy, onClose, onSubmit, onTestLlm, onTestEmbedding }: Props) {
  const [provider, setProvider] = useState<AppSettings["llm_provider"]>(initial.llm_provider === "none" && (initial.llm_base_url || initial.llm_model) ? "openai-compatible" : initial.llm_provider);
  const [baseUrl, setBaseUrl] = useState(initial.llm_base_url);
  const [model, setModel] = useState(initial.llm_model);
  const [embeddingProvider, setEmbeddingProvider] = useState<AppSettings["embedding_provider"]>(initial.embedding_provider);
  const [embeddingBaseUrl, setEmbeddingBaseUrl] = useState(initial.embedding_base_url);
  const [embeddingModel, setEmbeddingModel] = useState(initial.embedding_model);
  const [apiKey, setApiKey] = useState("");
  const [llmTesting, setLlmTesting] = useState(false);
  const [embeddingTesting, setEmbeddingTesting] = useState(false);
  const [llmResult, setLlmResult] = useState<ProviderTestResult | null>(null);
  const [embeddingResult, setEmbeddingResult] = useState<ProviderTestResult | null>(null);
  const [llmError, setLlmError] = useState<string | null>(null);
  const [embeddingError, setEmbeddingError] = useState<string | null>(null);

  const providerPayload = (url: string, selectedModel: string) => ({ base_url: url, model: selectedModel, api_key: apiKey || undefined });
  const updateLlmBaseUrl = (value: string) => { setBaseUrl(value); if (value.trim() && provider === "none") setProvider("openai-compatible"); };
  const updateLlmModel = (value: string) => { setModel(value); if (value.trim() && provider === "none") setProvider("openai-compatible"); };
  const runLlmTest = async () => {
    setLlmTesting(true); setLlmError(null); setLlmResult(null);
    try {
      if (!baseUrl.trim() && !model.trim()) setLlmResult({ status: "skipped", message: "请先填写 LLM Base URL 和模型名称" });
      else setLlmResult(await onTestLlm(providerPayload(baseUrl, model)));
    } catch (reason) { setLlmError(reason instanceof Error ? reason.message : "LLM 连接测试失败"); }
    finally { setLlmTesting(false); }
  };
  const runEmbeddingTest = async () => {
    setEmbeddingTesting(true); setEmbeddingError(null); setEmbeddingResult(null);
    try {
      if (embeddingProvider === "none") setEmbeddingResult({ status: "skipped", message: "Embedding 未启用，可继续使用本地关键词检索" });
      else setEmbeddingResult(await onTestEmbedding(providerPayload(embeddingBaseUrl, embeddingModel)));
    } catch (reason) { setEmbeddingError(reason instanceof Error ? reason.message : "Embedding 连接测试失败"); }
    finally { setEmbeddingTesting(false); }
  };
  const payload = () => ({ llm_provider: provider, llm_base_url: baseUrl, llm_model: model, embedding_provider: embeddingProvider, embedding_base_url: embeddingBaseUrl, embedding_model: embeddingModel, api_key: apiKey || undefined });

  return <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
    <section className="modal settings-modal" role="dialog" aria-modal="true" aria-labelledby="settings-title">
      <div className="modal-header"><div><span className="eyebrow">RUNTIME CONFIGURATION</span><h2 id="settings-title">连接外部模型</h2></div><button className="icon-button" onClick={onClose} aria-label="关闭">×</button></div>
      <p className="modal-hint">Agent 运行时仍在本机。启用后，仅将回答所需的检索上下文发送到你配置的 OpenAI-compatible API。API Key 只写入系统凭据管理器，不写进配置文件。</p>
      <label>LLM 提供方<select value={provider} onChange={(event) => setProvider(event.target.value as AppSettings["llm_provider"])}><option value="none">未启用（本地检索模式）</option><option value="openai-compatible">OpenAI-compatible API</option></select></label>
      <div className="form-grid"><label>API Base URL<input value={baseUrl} onChange={(event) => updateLlmBaseUrl(event.target.value)} placeholder="https://api.example.com/v1" /></label><label>模型名称<input value={model} onChange={(event) => updateLlmModel(event.target.value)} placeholder="例如：gpt-4o-mini" /></label></div>
      <label>API Key <span className="muted">（留空表示保留已有 Key）</span><input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="sk-…" autoComplete="off" /></label>
      <div className="provider-test-actions"><button className="button outline" disabled={busy || llmTesting || embeddingTesting} onClick={() => void runLlmTest()}>{llmTesting ? "测试 LLM 中…" : "测试 LLM 连接"}</button></div>
      <TestResult label="LLM" result={llmResult} error={llmError} />

      <div className="subsection-title">Embedding（可选）</div>
      <label>Embedding 提供方<select value={embeddingProvider} onChange={(event) => setEmbeddingProvider(event.target.value as AppSettings["embedding_provider"])}><option value="none">未启用（关键词检索）</option><option value="openai-compatible">OpenAI-compatible API</option></select></label>
      <div className="form-grid"><label>Embedding Base URL<input value={embeddingBaseUrl} onChange={(event) => setEmbeddingBaseUrl(event.target.value)} placeholder="https://api.example.com/v1" /></label><label>Embedding 模型<input value={embeddingModel} onChange={(event) => setEmbeddingModel(event.target.value)} placeholder="embedding-3-small" /></label></div>
      <div className="privacy-note"><span>⌂</span><span>Embedding 会把证据单元发送给你配置的外部服务并存回本地。未启用或连接失败时，仍可继续使用本地关键词检索。</span></div>
      <div className="provider-test-actions"><button className="button outline" disabled={busy || llmTesting || embeddingTesting} onClick={() => void runEmbeddingTest()}>{embeddingTesting ? "测试 Embedding 中…" : "测试 Embedding 连接"}</button></div>
      <TestResult label="Embedding" result={embeddingResult} error={embeddingError} />

      <div className="modal-actions"><button className="button secondary" onClick={onClose}>取消</button><button className="button primary" disabled={busy || llmTesting || embeddingTesting} onClick={() => onSubmit(payload())}>{busy ? "保存中…" : "保存设置"}</button></div>
    </section>
  </div>;
}
