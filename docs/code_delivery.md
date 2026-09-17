# 验证码双渠道投递

登录页 `/codeLogin/` 和重置页 `/forgetpw/` 的发送按钮默认提交 `action=send`。
每次请求只签发一个对应用途的六位码，然后在有界后台队列里分别尝试邮箱和企业微信。
登录码与重置码仍不可互换。邮箱无效或单渠道失败，不阻止另一渠道；页面使用统一提示，
不披露账号是否存在、是否绑定邮箱，也不保证两边一定收到。

发送只接受 `action=send`；`action=email/wechat` 已删除，不再触发任何投递。
双渠道只消耗一次签发请求额度、创建一条凭证；不会因为分别发送两次而使第一条消息的码失效。
请求重发仍会作废同用途的旧码。

## 企业微信链接自动填入

两种企业微信卡片共用同一套链接格式和页面脚本：

- 登录：`/codeLogin/#username=<编码后的账号>&token=<六位登录码>`。
- 重置：`/forgetpw/#username=<编码后的账号>&token=<六位重置码>`。

账号和验证码放在 fragment 中，不使用查询参数；HTTP GET 不包含这些凭证。
页面在加载其他脚本前清除当前地址和当前历史项中的 fragment，然后在 DOM 就绪后填入账号、
验证码。登录页聚焦登录按钮，重置页聚焦新密码；都不自动提交或消费验证码。
登录表单内部仍使用 code 字段，重置表单使用 token 字段，后端用途校验不变。

重复参数、非法账号或非六位 ASCII 数字验证码不会自动填入。若客户端丢弃 fragment，
仍可手动输入消息中展示的码。不得将此链接写入消息正文日志或持久化调度任务。

## 日志

新默认投递链写入配置的日志目录下 `code_delivery.log`；当前本地为 `log/code_delivery.log`。
每条渠道记录包含时间、`delivery_id`、内部 `account_id`、`purpose`（login/password_reset）、
`channel`（email/wechat）、`status`、`reason` 和 `elapsed_ms`。同一请求的两条渠道记录共用
delivery_id。日志不含学号、姓名、完整邮箱、验证码、密码、消息正文、带凭证链接或服务商响应正文。

- `prepared`：签发成功，等待后台投递。
- `accepted` / `provider_accepted`：服务商接口接受发送，不能据此断言已进入收件箱或被阅读。
- `failed`：发送异常；reason 仅记录异常类型，不记录异常文本。
- `skipped` / `no_valid_email`：邮箱缺失或无效。
- `skipped` / `not_configured`：渠道接口地址为空。
- 请求级 `skipped`：未生成凭证，例如账号不符合条件或请求限流。
- `queue_rejected`：队列未接受任务，本次没有生成新码。
- `preparation_failed`：签发阶段异常。

队列与渠道结果统一写入 code_delivery.log；password_reset_delivery.log 只保留历史记录，
新的发送链不再写入。企业微信底层另有泛化的敏感消息投递成功/失败记录。

## 实现边界

两个视图直接调用 `extern.code_delivery.queue_code_delivery`，用 `partial` 绑定各自的签发函数。
签发函数统一返回账号与两个收件渠道的信息及一个验证码，不接受 channel 参数。
code_delivery.py 负责有界队列、逐渠道尝试和日志；code_email.py 只负责邮件传输，企业微信
沿用 wechat.py。已删除旧的 extern/login_code.py、extern/password_reset.py 及其单渠道 wrapper。

验证码业务按职责分为三个模块：

- `app/login_utils.py`：登录码签发、消费及个人账号检查。
- `app/password_reset_utils.py`：重置码签发、密码校验及原子改密；保留既有函数名
  `create_password_reset_token`、`prepare_password_reset_delivery`、`reset_password_from_token`。
- `app/auth_code_utils.py`：共享请求限流、摘要、跨用途码值去重、失败计数和过期清理。

上述逻辑已从 `app/utils.py` 完全移出；视图直接导入对应业务函数，登录与重置模块互不依赖。
配置仍使用既有 password_reset 键，数据库表、摘要 salt 和限流标识保持兼容，不需要迁移。
定时清理调用 `auth_code_utils.cleanup_code_state`，保留既有 job ID 和任务函数名，
避免影响已注册的调度任务。重置操作仍在账号锁内签发、替换或消费验证码。

临时 SMTP 适配器仅用于本地测试，不代表企业微信接口已经配置。未配置的企业微信渠道会跳过。
相关测试：`python manage.py test app.test.test_code_delivery app.test.test_code_login app.test.test_forget_password`。

2026-09-11 验证：相关 93 项、全量 558 项 Django 测试通过；两个页面的预填脚本 32 项通过。
测试服务返回的两个页面已确认共用同一段预填脚本及正确的输入框标记；微信客户端实机点击仍待验证。
