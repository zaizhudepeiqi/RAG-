# 安全与合规阶段性真源

> 文档职责：定义管理员认证、密钥保护、外部 API 安全、文件安全、Prompt 注入防护、日志敏感数据、网络边界和 MinerU 云端合规。

## 1. 第一版安全边界

第一版：

- 单管理员、单工作区、企业私有化部署。
- 不做多管理员、RBAC、组织架构、部门/用户级知识权限和文档级 ACL。
- 不创建假 `tenantId`/空权限表来声称已经多租户化；未来多租户需要独立设计和迁移。

单管理员不等于可以省略认证、密钥保护、审计、限流、文件校验和备份。生产部署不得把 PostgreSQL、Redis、Chroma 或 Worker 管理端口暴露到公网。

## 2. 初始管理员

环境变量：

```env
INITIAL_ADMIN_USERNAME=admin
INITIAL_ADMIN_PASSWORD=<strong-secret>
```

规则：

- 仅在数据库不存在管理员时初始化一次。
- 已存在管理员时启动绝不覆盖。
- 生产环境拒绝 `change-me`、`admin123` 等弱默认值。
- 密码使用 Argon2id 哈希并带独立随机 salt，不可逆加密和明文均禁止。
- 用户名不区分大小写唯一。
- 初始密码首次登录后必须修改；修改前只能访问修改密码、退出和健康摘要。
- 启动日志只说明初始化成功/已存在，不打印用户名以外的秘密。

## 3. 密码策略

- 最少 12 字符，最多 128 字符。
- 至少包含三类：大写、小写、数字、符号；中文字符可计入非 ASCII 类。
- 禁止与用户名相同，禁止常见弱密码列表。
- 修改必须验证旧密码和确认新密码。
- 成功后使其他所有后台登录态失效，当前会话重新签发。
- 失败响应统一为“账号或密码错误”，不泄露用户名是否存在。

## 4. 后台登录会话

第一版使用 JWT Access Token，不做 Refresh Token。

推荐同源生产部署：

- JWT 保存于 `HttpOnly; Secure; SameSite=Lax` Cookie，不暴露给前端 JavaScript。
- 写接口使用双提交 CSRF token：可读 CSRF cookie + `X-CSRF-Token` 请求头。
- Access Token 第一版默认 7 天，生产部署可通过环境变量缩短；默认值与部署示例保持一致。
- JWT 包含管理员 `authVersion`；logout 和密码修改在 PostgreSQL 递增 authVersion，旧 Token 即使 Redis 丢失也不能复活。

开发环境跨端口时仍使用 Cookie/CORS credentials；不退回 localStorage 长期保存 Bearer Token。若部署拓扑强制使用 Authorization Bearer，Token 只能放内存/`sessionStorage`，禁止 localStorage，并在部署文档明确风险。

JWT：

- 使用独立 `JWT_SIGNING_KEY`，不能复用凭据加密主密钥。
- 包含 `sub / jti / iat / exp / tokenType=admin`。
- 包含 `ver=administrator.authVersion`，每次鉴权比较当前版本。
- 使用固定允许算法，不能信任 token header 任意选择算法。

## 5. 登录防护

- 按 `usernameHash + sourceIp` 使用 Redis 滑动窗口限流。
- 15 分钟内最多 10 次失败，超限返回 429，`Retry-After`。
- 第一版不永久锁账号、不做验证码。
- Redis 不可用时采用进程内保守降级并告警，不能完全绕过限流。
- 登录成功/失败、限流和密码修改写审计日志；绝不记录密码。

## 6. 凭据加密

需要可逆保存的 Provider/MinerU/callback secret 使用：

- 独立 `CREDENTIAL_ENCRYPTION_KEY`，至少 256 bit，由部署 secret 提供。
- AES-256-GCM，每条记录使用 96-bit 随机 nonce，associated data 包含对象类型和 ID。
- 数据库存储 ciphertext、nonce、keyVersion，不存主密钥。
- 加密主密钥丢失意味着凭据不可恢复；必须纳入秘密备份。
- 第一版不做后台主密钥轮换 UI；部署脚本提供受控离线轮换流程后才允许换 keyVersion。

高熵 API Key 只需不可逆哈希校验，不可逆字段不能错误使用可逆加密。

## 7. 外部 Webhook/API 安全

- API Key 至少 256-bit CSPRNG，只展示一次，数据库只存校验 hash/前缀。
- 每个渠道独立 Key，轮换后旧 Key 立即失效。
- 统一限流、并发限制、请求大小限制和 Idempotency-Key。
- API Key 失败使用常量时间比较，响应不说明 instance 是否存在。
- 外部接口和后台 JWT 鉴权依赖完全分离。
- 生产必须经过 TLS；反向代理将 HTTP 重定向 HTTPS。
- callback 使用独立 HMAC secret 和时间戳，接收方应拒绝超过 5 分钟的消息。

第一版不做入站 IP 白名单和通用 HMAC 请求签名；这是已知边界。公网暴露时 API Key + TLS + 限流是最低要求。

## 8. 文件上传安全

所有后台、渠道临时附件和渠道数据源上传复用同一安全组件：

- 流式读取和总大小限制。
- 扩展名、客户端 MIME、服务端 MIME/魔数三方校验。
- 安全规范化文件名，物理路径只使用内部 UUID/SHA，不使用用户路径拼接。
- ZIP 路径穿越、绝对路径、盘符、符号链接、设备文件、加密包、嵌套包、压缩炸弹检查。
- 解压目录独立，失败后安全清理。
- 浏览器预览 HTML/Markdown 必须 sanitize，禁止脚本、事件属性、iframe 和危险 URL scheme。
- 原始 Office/HTML 默认以 attachment 下载，不以内联方式执行。
- 资产端点鉴权并使用安全 Content-Type、`X-Content-Type-Options: nosniff`。

第一版不集成杀毒引擎，部署文档必须写明：系统不执行上传文件，但不能保证文件无恶意载荷；高安全企业应在入口增加 ClamAV/网关扫描 Adapter 后再开放外部上传。

## 9. SSRF 和外部 URL

- 第一版用户数据源只允许文件上传，不开放任意 URL 抓取。
- OpenAI-Compatible Base URL 和 callback URL 需要 scheme/host/port allow rules。
- DNS 解析后检查 loopback、link-local、multicast、云元数据和保留网段，重定向后重新检查。
- callback 私网访问必须由部署显式开关。
- MinerU signed upload/download URL 只由官方 Adapter 消费，不向前端透传、不写日志。
- HTTP 客户端限制重定向、连接/读取超时、响应体大小和 TLS 校验。

## 10. Prompt 注入和模型数据边界

检索到的文档、临时附件和用户输入均为不可信内容：

- 系统规则和用户可编辑 systemPrompt 分层，用户不能覆盖安全指令。
- 知识上下文用明确边界和来源 ID 包裹，并声明其中指令不得执行。
- 第一版机器人没有工具调用、数据库写入、文件执行和网络访问能力，降低注入影响。
- 模型输出中的 HTML/Markdown 在前端 sanitize。
- 只接受已知 citation IDs，未知引用不得映射到真实文件。
- 不向回答模型提供 Provider 凭据、本地路径、管理配置或完整 Trace。

RAG 不能彻底消除 Prompt 注入；日志和评测必须覆盖恶意文档样例。

## 11. 文档外发和 MinerU 合规

MinerU Cloud Precision API 会把企业文件上传到第三方：

- 系统设置首次启用必须勾选确认。
- 上传/解析页面持续显示当前 Parser 为云端。
- 部署说明写明网络流向、文件类型、保留取决于 MinerU 服务条款。
- 绝密、受监管或纯内网数据不得使用云 Parser，应等待本地/私有 Parser Adapter。
- Token 权限和配额由管理员负责，不在日志或前端回显。

不得把“整个系统私有化部署”表述成“文档永不离开内网”，除非使用本地 Parser 和本地模型。

## 12. 日志和敏感数据

- 普通运行日志不包含用户问题、文档正文、Prompt、模型完整响应和附件内容。
- ChatTrace 需要完整排查载荷时使用应用级加密字段，只有管理员可读。
- 点击查看敏感正文二次确认并写审计。
- Token/API Key/密码/签名 URL 永远不进入 Trace，即使开启全文模式。
- IP 可按部署策略保存；默认保存规范化地址 30 天，导出前脱敏。
- 错误响应只返回 traceId 和安全详情，不返回 SQL、路径、堆栈和供应商原始敏感响应。

## 13. Web 安全

生产响应至少设置：

- Content Security Policy，限制 script/style/connect/img 来源。
- `X-Content-Type-Options: nosniff`。
- `Referrer-Policy: no-referrer`。
- `Permissions-Policy` 关闭不需要能力。
- Content-Security-Policy 使用 `frame-ancestors 'none'` 防点击劫持。
- HSTS 在确认全站 HTTPS 后启用。

CORS 使用明确 origin allowlist，不允许 credentials 与 `*` 同时出现。OpenAPI/Swagger 在生产默认关闭或仅内网管理员可访问。

## 14. 数据库和存储

- PostgreSQL/Redis/Chroma 仅内部网络。
- 数据库账号最小权限，迁移账号和运行账号可分离。
- 本地存储目录只允许应用服务账户访问。
- 文件路径不通过 API 返回；下载通过鉴权流式端点。
- 数据库备份、凭据主密钥和存储快照必须一起纳入恢复方案。
- 删除使用业务规则和异步清理，不直接拼接路径执行递归删除。

## 15. 依赖和供应链

- Python、Node 和 Docker 依赖锁定精确版本，不使用浮动 `latest`。
- CI 运行依赖漏洞和 secret 扫描；高危漏洞在发布前处理或记录接受理由。
- 前端不加载未知 CDN 脚本；图标和字体随应用部署或使用受控来源。
- 上传文件、解析产物和模型响应绝不能作为代码执行或动态 import。

## 16. 安全验收

- 初始弱密码生产启动失败，首次登录强制改密。
- 密码、JWT、Provider/MinerU Token、渠道 API Key 不出现在数据库明文、日志或前端响应。
- 被盗用 API Key 受到限流，轮换后旧 Key 失效。
- ZIP 路径穿越、压缩炸弹、伪 MIME、危险 HTML 均被测试覆盖。
- 任意 URL SSRF 和 callback DNS 重绑定被阻止。
- 文档 Prompt 注入测试不能让模型泄露系统提示词或执行外部操作。
- MinerU 云端外发在设置、页面和部署文档中明确。
- 查看敏感 Trace 有审计记录。
