# 访问要求清单（中文）

最后检查：2026-08-07。本清单记录当前电脑、当前网络和当前账号配置下的实际结果。
第三方网站可能随时调整登录、验证码、robots.txt 或访问策略。

## 一、当前可以直接使用

- **SearXNG**：`http://127.0.0.1:8080`，当前使用 Bing 中国和 360 搜索。
  16 组分类查询已返回 250 条原始结果；百度、搜狗因搜索端出现验证码而停用。
- **浏览器采集器**：Playwright 1.62.0，使用本机 Microsoft Edge；不需要 LLM API。
- **Agent-Reach**：B站、RSS、Jina 网页读取、YouTube/字幕可用。
- **last30days**：Reddit 基础发现、YouTube、Hacker News、Polymarket、GitHub 和网页
  grounding 可识别；实际覆盖仍受网络影响。

## 二、国内网页来源

### 行业、咨询与券商资料

| 来源 | 官方入口 | 自动访问说明 |
|---|---|---|
| 艾瑞咨询 | https://www.iresearch.com.cn/report.shtml | 可采集（HTTP 200） |
| 艾媒咨询 | https://www.iimedia.cn/c400/ | 可采集（HTTP 200） |
| 头豹研究院 | https://www.leadleo.com/report | HTTP 200，但仅提取到 36 个字符；改用 SearXNG 或人工浏览 |
| 易观分析 | https://www.analysys.cn/ | 可采集 |
| QuestMobile | https://www.questmobile.com.cn/research/reports | robots 禁止自动采集，只保留搜索结果链接或人工查看 |
| MobTech | https://www.mob.com/mobdata/report | 可采集 |
| TalkingData | http://mi.talkingdata.com/reports.html | 可采集 |
| 中国信通院 | https://www.caict.ac.cn/kxyj/qwfb/bps/ | 当前自动请求返回 412，建议人工浏览或使用搜索结果 |
| CNNIC | https://www.cnnic.net.cn/6/86/88/index.html | 可采集（HTTP 200） |
| 36氪研究院 | https://www.36kr.com/academe | 可采集（HTTP 200） |
| 中信证券研究 | https://www.cs.ecitic.com/newsite/zxzx/yjbg/ | 可采集（HTTP 200） |
| 国泰君安研究页 | https://www.gtja.com/content/research/marcoeco.html | robots 检查遇旧式 TLS，自动采集暂停；人工浏览 |
| 华泰证券下载中心 | https://www.htsc.com.cn/site-services/downloads | 可采集（HTTP 200） |
| 申万宏源研究 | https://www.swsresearch.com/institute_sw/allIndex/releasedIndex | 可采集（HTTP 200） |

### 学术与论文

| 来源 | 官方入口 | 说明 |
|---|---|---|
| 百度学术 | https://xueshu.baidu.com/ | robots 禁止当前自动采集；用 SearXNG 发现或人工查询 |
| 中国知网 | https://kns.cnki.net/ | robots 禁止当前自动采集；摘要/全文还可能需要机构权限 |
| 万方数据 | https://s.wanfangdata.com.cn/ | 搜索结果页可采集；全文可能需要权限 |
| arXiv | https://arxiv.org/ | 一般不需要登录 |
| ACL Anthology | https://aclanthology.org/ | 可采集 |
| Semantic Scholar | https://www.semanticscholar.org/ | robots 禁止当前自动采集 |
| Google Scholar | https://scholar.google.com/ | 当前网络超时，建议代理或改用 SearXNG/arXiv |

### 国内用户表达

| 来源 | 是否登录 | 当前建议 |
|---|---|---|
| B站 | 基础搜索不需要；部分字幕/互动需要 | 网页 robots 禁止采集，优先使用 Agent-Reach 的 `bili` 后端 |
| 知乎 | 建议登录 | 使用独立 Edge profile；遇验证码立即人工处理 |
| 小红书 | 需要登录 | 使用用户控制的浏览器会话/OpenCLI，不自动读取日常浏览器 Cookie |
| 微信公众号文章 | 文章可能公开 | 评论通常需要微信登录，只做人工抽样，不做无人值守抓取 |
| 掘金/CSDN/少数派 | 多数公开页面不需要 | 通过 SearXNG 发现具体文章后再采集原始链接 |
| 雪球 | 需要登录 Cookie | 当前 API 返回 400，只在明确需要金融用户表达时配置 |

## 三、哪些需要你登录浏览器

本项目只要求登录：**知乎、小红书**。Reddit、X、Facebook、Instagram 不要求你登录。

### 项目浏览器登录步骤

1. 打开 PowerShell，进入项目：

```powershell
cd 'D:\Brand Atlas\geo-research'
```

2. 运行对应命令，例如知乎：

```powershell
.\login-browser.ps1 -Platform zhihu
```

可选平台只有：`zhihu`、`xiaohongshu`。

3. 系统会打开一个独立 Edge 窗口。你在窗口里自行输入账号、密码、短信验证码或扫码。
   不要把密码、验证码或 Cookie 发给 Codex。
4. 页面确认登录成功后，回到 PowerShell，按一次 Enter。登录状态会保存在项目本地的
   `.browser-profile`，该目录已被 `.gitignore` 排除。
5. 需要多个平台时，逐个平台重复第 2-4 步。

### 登录后采集

```powershell
.\.venv-browser\Scripts\python.exe -m src.browser_collect collect `
  --dataset user-voice `
  --headed `
  --include-login `
  --profile '.browser-profile' `
  --browser-channel msedge
```

如果出现验证码、二次验证、访问频率提示或平台授权页面，停止自动流程并人工处理。

### Agent-Reach / OpenCLI 登录方式

小红书的 Agent-Reach 路线还需要在日常 Edge/Chrome 中安装
[OpenCLI 浏览器扩展](https://chromewebstore.google.com/detail/opencli/ildkmabpimmkaediidaifkhjpohdnifk)，
登录目标平台并保持浏览器打开。当前体检状态是：OpenCLI 命令已安装，但扩展尚未连接。

项目 `.browser-profile` 与 OpenCLI 的日常浏览器会话是两条独立路线：前者供 Playwright
采集器使用，后者供 Agent-Reach 的平台命令使用。

## 四、API 是否需要安装

基础方案目前**不需要购买或安装搜索 API**。

| API/凭据 | 什么时候才需要 | 当前是否需要 |
|---|---|---|
| Exa 或 Brave Search | SearXNG 召回率或稳定性不够 | 否 |
| ScrapeCreators | 明确需要 TikTok/Instagram 数据 | 否 |
| Groq | 需要小宇宙播客音频转写 | 否 |
| OpenAI/OpenRouter/Perplexity | 需要无人值守模型归纳或 Deep Research | 否 |
| XAI 或 X Cookie | 需要稳定搜索 X/Twitter | 否 |
| GitHub 登录 | 提高 GitHub API 限额 | 可选，执行 `gh auth login` |

`browser-use` 当前未安装。它是在 Playwright 上增加 LLM 决策，适合无法写成固定规则的多步
交互流程；普通公开页面采集使用 Playwright 更稳定、成本更低、结果更容易复现。

## 五、代理与进不去的情况

- 当前网络很可能需要代理：Google Scholar、Reddit、V2EX、X/Twitter 和部分海外站点。
- 代理不能自动解决登录、验证码或站点访问控制：G2、Product Hunt、Capterra、Otterly
  对自动访问返回 HTTP 403，优先用搜索结果摘要、官方 API 或人工浏览。
- Scrunch 返回 HTTP 200，但浏览器未提取到有效正文，需要人工查看或增加专用适配器。
- QuestMobile、Semantic Scholar 的 robots.txt 不允许当前自动采集，不绕过。
- 中国信通院当前返回 HTTP 412，保留 SearXNG 结果链接并人工查看。
- 头豹页面返回 HTTP 200，但通用浏览器仅提取到极少正文；需要专用页面选择器或人工查看。
- 国泰君安旧站的 robots 检查遇到旧式 TLS 协商问题，默认按禁止处理，不降低安全设置。

### 本轮国内浏览器体检汇总

| 状态 | 来源 |
|---|---|
| 可直接采集 | 艾瑞、艾媒、易观、MobTech、TalkingData、CNNIC、36氪研究院、中信证券、华泰证券、申万宏源、万方、ACL Anthology |
| robots 禁止 | QuestMobile、百度学术、知网、Semantic Scholar、B站网页搜索 |
| HTTP/内容错误 | 中国信通院（412）、头豹（正文过短）、国泰君安旧站（TLS/robots 检查失败） |
| 需要登录 | 知乎、小红书 |

## 六、常用命令

```powershell
# 检查浏览器采集环境
.\run.ps1 browser-diagnose

# 采集某一层公开网页
.\run.ps1 browser -Dataset market
.\run.ps1 browser -Dataset academic
.\run.ps1 browser -Dataset user-voice

# 使用 SearXNG 搜索并按四层目录保存
$env:SEARXNG_URL = 'http://127.0.0.1:8080'
python -m src.research search

# 重新生成总报告
python -m src.research report
```

## 七、模型搜索与详细行业报告

模型接口支持 OpenAI 兼容的 `chat/completions`。你只需要配置接口 URL 和模型名：

```powershell
.\configure-llm.ps1 -BaseUrl 'https://你的接口地址/v1' -Model '模型名称'
```

API Key 可以通过隐藏输入保存到已被 `.gitignore` 排除的本机配置文件：

```powershell
.\configure-llm.ps1 -BaseUrl 'https://你的接口地址/v1' -Model '模型名称' -StoreApiKey
```

重新运行同一命令即可替换 Key。不使用 `-StoreApiKey` 时会保留已有 Key；如果配置文件中
没有 Key，运行报告脚本仍会隐藏提示临时输入，并在任务结束后自动清除：

```powershell
# 不使用登录站点
.\run-research-report.ps1 -Request '请调研某行业的市场、竞品、研究证据和用户痛点'

# 使用已经登录的知乎和小红书浏览器会话
.\run-research-report.ps1 -Request '请调研某行业的市场、竞品、研究证据和用户痛点' `
  -IncludeLogin -ShowBrowser
```

默认使用 `-QueryProfile auto`：GEO/AEO/AI 搜索请求采用 GEO 专项来源清单，其他行业采用
通用市场研究清单。也可以显式传入 `-QueryProfile general` 或 `-QueryProfile geo`。运行脚本
提示输入的 Key 只进入临时进程变量 `BRAND_ATLAS_LLM_API_KEY`，不会写入项目文件；旧变量
`GEO_LLM_API_KEY` 仍兼容。

通用市场研究清单不会降低信源要求。所有行业和品牌都优先检查：信通院、艾瑞、爱分析、
头豹、QuestMobile、极光、CBNData、腾讯/阿里研究院、199IT；央广、21财经、经济日报、
中青报、央视/3·15；36Kr、虎嗅、Morketing、梅花、BMR；知乎、小红书、知识星球、B站；
竞品官网和融资新闻；最后补中信、中金、华泰、申万宏源和东方财富研报入口。报告必须披露
每个域名是否搜索、是否打开、是否采用及未采用原因。

执行顺序为：模型拆解需求并规划关键词、本地 SearXNG 搜索、Edge/Playwright 按 robots
规则采集、模型只依据已归档证据整理中文报告、校验 `[S#]` 引用并转换为可点击原始网址。
最新结果位于 `reports/latest-search-report.md`，每次运行的计划、搜索结果和网页证据位于
`data/runs/<时间戳>/`。自动采集不会绕过验证码、登录墙、付费墙、robots.txt 或平台限制。

登录操作只需做一次，并且只针对以下两个站点：

```powershell
.\login-browser.ps1 -Platform zhihu
.\login-browser.ps1 -Platform xiaohongshu
```

每条命令会打开专用 Edge 窗口。你在窗口内正常登录，确认网页已显示登录状态后回到
PowerShell 按 Enter；登录会话保存在项目的 `.browser-profile`，不要把该目录上传或分享。
