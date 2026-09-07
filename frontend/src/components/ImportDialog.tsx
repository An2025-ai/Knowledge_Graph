import { useState } from "react";

type Props = { busy: boolean; onClose: () => void; onSubmit: (payload: Record<string, unknown>) => void };

export default function ImportDialog({ busy, onClose, onSubmit }: Props) {
  const [title, setTitle] = useState("");
  const [brand, setBrand] = useState("");
  const [layer, setLayer] = useState("l3_brand");
  const [content, setContent] = useState("");
  const [fileName, setFileName] = useState("");

  return <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
    <section className="modal" role="dialog" aria-modal="true" aria-labelledby="import-title">
      <div className="modal-header"><div><span className="eyebrow">KNOWLEDGE INGESTION</span><h2 id="import-title">导入一份资料</h2></div><button className="icon-button" onClick={onClose} aria-label="关闭">×</button></div>
      <p className="modal-hint">资料会保存在本机，并经过证据切分、候选抽取和关系构建。未配置外部模型时仍可使用本地规则检索。</p>
      <div className="form-grid"><label>资料标题<input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如：DeepCleer 官网内容" /></label><label>知识层<select value={layer} onChange={(event) => setLayer(event.target.value)}><option value="l3_brand">L3 品牌认知</option><option value="l2_industry">L2 行业知识</option></select></label></div>
      <label>品牌标识 <span className="muted">（L3 建议填写）</span><input value={brand} onChange={(event) => setBrand(event.target.value)} placeholder="例如：DeepCleer" /></label>
      <label>正文内容<textarea value={content} onChange={(event) => { setContent(event.target.value); setFileName(""); }} placeholder="粘贴 Markdown、网页正文或产品资料……" rows={10} /></label>
      <label className="file-picker">或从本机读取文本文件 <span className="muted">（.md / .txt / .html）</span><input type="file" accept=".md,.markdown,.txt,.html,.htm" onChange={(event) => { const file = event.target.files?.[0]; if (!file) return; setFileName(file.name); if (!title) setTitle(file.name.replace(/\.[^.]+$/, "")); void file.text().then(setContent); }} />{fileName && <span className="file-name">已选择：{fileName}</span>}</label>
      <div className="privacy-note"><span>⌂</span><span>默认仅写入本机数据目录。只有配置并启用外部 LLM / Embedding 时，相关文本片段才会离开本机。</span></div>
      <div className="modal-actions"><button className="button secondary" onClick={onClose}>取消</button><button className="button primary" disabled={busy || !content.trim()} onClick={() => onSubmit({ title: title || undefined, content, layer, brand_id: brand || undefined, source_type: "pasted_text", tenant_id: "local" })}>{busy ? "正在处理…" : "导入并构建"}</button></div>
    </section>
  </div>;
}
