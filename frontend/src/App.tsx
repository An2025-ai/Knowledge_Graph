import { useEffect, useMemo, useState } from "react";
import { api, type AppSettings } from "./api";
import { runtimeReady } from "./runtime";
import GraphView from "./components/GraphView";
import ImportDialog from "./components/ImportDialog";
import SettingsDialog from "./components/SettingsDialog";
import type { ChatResult, GraphData, GraphNode, Job, Stats } from "./types";

type Message = { role: "assistant" | "user"; content: string; result?: ChatResult };

const emptyStats: Stats = { documents: 0, evidence_units: 0, candidates: 0, entities: 0, relations: 0, layers: {}, jobs: {} };
const welcome: Message = { role: "assistant", content: "你好，我是 Atlas。这里是你的本地知识工作台。\n\n你可以直接问我已导入资料中的产品、能力、客户和行业信息，也可以在左侧查看知识实体与关系。" };

function App() {
  const [view, setView] = useState<"knowledge" | "visualization">("knowledge");
  const [layer, setLayer] = useState<string>("");
  const [graph, setGraph] = useState<GraphData>({ nodes: [], edges: [], stats: { nodes: 0, edges: 0 } });
  const [stats, setStats] = useState<Stats>(emptyStats);
  const [messages, setMessages] = useState<Message[]>([welcome]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [importing, setImporting] = useState(false);
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [settings, setSettings] = useState<AppSettings>({ llm_provider: "none", llm_base_url: "", llm_model: "", embedding_provider: "none", embedding_base_url: "", embedding_model: "" });
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadWorkspace = async () => {
    try {
      const [nextGraph, nextStats] = await Promise.all([api.graph(layer || undefined), api.stats()]);
      setGraph(nextGraph); setStats(nextStats); setError(null);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "无法连接本地服务"); }
  };

  useEffect(() => { void runtimeReady.then(loadWorkspace); }, [layer]);
  useEffect(() => { void runtimeReady.then(() => api.settings().then(setSettings).catch(() => undefined)); }, []);

  const visibleNodes = useMemo(() => graph.nodes.slice(0, 80), [graph.nodes]);

  const sendMessage = async () => {
    const message = input.trim();
    if (!message || sending) return;
    setInput(""); setMessages((current) => [...current, { role: "user", content: message }]); setSending(true);
    try {
      const history = messages.slice(-10).map(({ role, content }) => ({ role, content }));
      const result = await api.chat(message, history);
      setMessages((current) => [...current, { role: "assistant", content: result.answer, result }]);
    }
    catch (reason) { setMessages((current) => [...current, { role: "assistant", content: `暂时无法回答：${reason instanceof Error ? reason.message : "本地服务异常"}` }]); }
    finally { setSending(false); }
  };

  const submitImport = async (payload: Record<string, unknown>) => {
    setImporting(true); setError(null);
    try {
      const { job_id: jobId } = await api.importDocument(payload);
      let job: Job;
      do { await new Promise((resolve) => window.setTimeout(resolve, 350)); job = await api.job(jobId); } while (job.status === "queued" || job.status === "running");
      if (job.status === "failed") throw new Error(job.error || "资料处理失败");
      setShowImport(false); await loadWorkspace();
      setMessages((current) => [...current, { role: "assistant", content: `资料已导入并完成构建：${String(job.result.entity_count ?? 0)} 个实体，${String(job.result.relation_count ?? 0)} 条关系。` }]);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "资料导入失败"); }
    finally { setImporting(false); }
  };

  const submitSettings = async (payload: Record<string, unknown>) => {
    setSettingsBusy(true); setError(null);
    try { const result = await api.updateSettings(payload); setSettings(result.settings); setShowSettings(false); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "设置保存失败"); }
    finally { setSettingsBusy(false); }
  };

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand-lockup"><div className="brand-mark">A</div><div><div className="brand-name">Brand Atlas</div><div className="brand-subtitle">LOCAL KNOWLEDGE OS</div></div></div>
      <div className="workspace-label">我的工作区 <span className="online-dot" /></div>
      <nav className="view-switcher"><button className={view === "knowledge" ? "active" : ""} onClick={() => setView("knowledge")}><span>◈</span>知识内容</button><button className={view === "visualization" ? "active" : ""} onClick={() => setView("visualization")}><span>⌘</span>可视化</button></nav>
      <div className="sidebar-section-header"><span>{view === "knowledge" ? "实体索引" : "图谱概览"}</span><span className="count-pill">{view === "knowledge" ? visibleNodes.length : graph.stats.nodes}</span></div>
      {view === "knowledge" ? <div className="entity-list">{visibleNodes.map((node) => <button key={node.id} className={`entity-row ${selected?.id === node.id ? "selected" : ""}`} onClick={() => setSelected(node)}><span className="entity-dot" style={{ background: node.type === "brand" ? "#f3b562" : node.type === "product" ? "#62c5b5" : "#74a8ff" }} /><span className="entity-copy"><b>{node.name}</b><small>{node.type} · {node.layer === "l3_brand" ? "品牌" : "行业"}</small></span></button>)}{!visibleNodes.length && <div className="sidebar-empty">还没有知识实体<br /><button onClick={() => setShowImport(true)}>导入第一份资料 →</button></div>}</div> : <div className="visual-summary"><div className="mini-stat"><b>{graph.stats.nodes}</b><span>节点</span></div><div className="mini-stat"><b>{graph.stats.edges}</b><span>关系</span></div><p>点击“打开图谱”查看实体之间的关联。你可以从节点进入具体详情。</p><button className="button outline" onClick={() => setView("visualization")}>打开图谱</button></div>}
      <div className="sidebar-bottom"><button className="import-button" onClick={() => setShowImport(true)}><span>＋</span>导入资料</button><div className="local-badge"><span>⌂</span><div><b>数据在本机</b><small>Local-first workspace</small></div></div></div>
    </aside>
    <main className="main-stage">
      <header className="topbar"><div><span className="eyebrow">{view === "knowledge" ? "CONVERSATION" : "GRAPH EXPLORER"}</span><h1>{view === "knowledge" ? "和你的知识库对话" : "探索知识关系"}</h1></div><div className="topbar-actions"><select value={layer} onChange={(event) => setLayer(event.target.value)} aria-label="筛选知识层"><option value="">全部图层</option><option value="l3_brand">L3 品牌</option><option value="l2_industry">L2 行业</option></select><button className="button primary compact" onClick={() => setShowImport(true)}>＋ 新建知识</button></div></header>
      {error && <div className="error-banner">{error}<button onClick={() => setError(null)}>×</button></div>}
      {view === "visualization" ? <section className="graph-stage"><div className="section-intro"><div><span className="eyebrow">NETWORK MAP</span><h2>知识图谱</h2></div><span className="muted">{graph.stats.nodes} nodes · {graph.stats.edges} edges</span></div><GraphView data={graph} onSelect={setSelected} />{selected && <div className="node-inspector"><div><span className="eyebrow">SELECTED NODE</span><h3>{selected.name}</h3><p>{selected.type} · {selected.layer}</p></div><button className="icon-button" onClick={() => setSelected(null)}>×</button></div>}</section> : <section className="conversation"><div className="conversation-scroll">{messages.map((message, index) => <div key={`${message.role}-${index}`} className={`message-row ${message.role}`}><div className={`avatar ${message.role}`}>{message.role === "assistant" ? "A" : "你"}</div><div className="message-content"><div className="message-bubble">{message.content.split("\n").map((line, lineIndex) => <span key={lineIndex}>{line}{lineIndex < message.content.split("\n").length - 1 && <br />}</span>)}</div>{message.result?.sources?.length ? <div className="source-strip"><span>基于本地检索</span>{message.result.sources.slice(0, 3).map((source) => <button key={source.id} onClick={() => { const node = graph.nodes.find((item) => item.id === source.id); if (node) { setSelected(node); setView("knowledge"); } }}>{source.title}</button>)}</div> : null}</div></div>)}{sending && <div className="message-row assistant"><div className="avatar assistant">A</div><div className="typing"><i /><i /><i /></div></div>}</div><div className="suggestions"><button onClick={() => setInput("这份资料里有哪些产品？")}>这份资料里有哪些产品？</button><button onClick={() => setInput("总结当前知识库")}>总结当前知识库</button><button onClick={() => setInput("哪些能力服务于目标客户？")}>哪些能力服务于目标客户？</button></div><div className="composer"><textarea value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void sendMessage(); } }} placeholder="问问你的本地知识库……" rows={1} /><button className="send-button" onClick={() => void sendMessage()} disabled={!input.trim() || sending}>↑</button><div className="composer-hint">Enter 发送 · Shift + Enter 换行</div></div></section>}
    </main>
    <aside className="insight-panel"><div className="panel-title"><span>工作区状态</span><span className="status-chip"><i />就绪</span></div><div className="stat-grid"><div><b>{stats.documents}</b><span>文档</span></div><div><b>{stats.evidence_units}</b><span>证据单元</span></div><div><b>{stats.entities}</b><span>实体</span></div><div><b>{stats.relations}</b><span>关系</span></div></div>{selected ? <div className="detail-card"><span className="eyebrow">ENTITY DETAIL</span><h3>{selected.name}</h3><dl><dt>类型</dt><dd>{selected.type}</dd><dt>图层</dt><dd>{selected.layer}</dd><dt>来源</dt><dd>{String(selected.properties?.source_document_id || "本地资料")}</dd></dl></div> : <div className="privacy-card"><span className="privacy-icon">⌂</span><h3>本地优先</h3><p>资料、图谱和 Agent 运行时都在本机。只有你主动配置的外部模型调用会发送文本片段。</p><button onClick={() => setShowImport(true)}>开始构建 →</button></div>}<div className="panel-footer"><button className="settings-link" onClick={() => setShowSettings(true)}>⚙ 模型与隐私设置</button><span>Brand Atlas v1.0 · SQLite · Local API</span></div></aside>
    {showImport && <ImportDialog busy={importing} onClose={() => !importing && setShowImport(false)} onSubmit={(payload) => void submitImport(payload)} />}
    {showSettings && <SettingsDialog initial={settings} busy={settingsBusy} onClose={() => !settingsBusy && setShowSettings(false)} onTestLlm={(payload) => api.testLlm(payload)} onTestEmbedding={(payload) => api.testEmbedding(payload)} onSubmit={(payload) => void submitSettings(payload)} />}
  </div>;
}

export default App;
