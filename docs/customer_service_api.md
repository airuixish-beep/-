# Customer Service API

## Overview

项目保留原有浏览器客服接口 `/support-chat/*` 和后台接口 `/admin/support-chat/*`，并新增一套可程序化调用的 REST API：

- Base URL: `/api/lobster/customer-service/`

客户侧 API 使用 `public_token` 作为会话访问凭证。后台侧 API 需要已登录且具备 `is_staff` 权限。

## Public API

### Create or resume session

- `POST /api/lobster/customer-service/sessions`

Request body:

```json
{
  "public_token": "optional",
  "visitor_name": "Amy",
  "visitor_email": "amy@example.com",
  "language": "en-US"
}
```

Response:

```json
{
  "created": true,
  "session": {
    "id": 1,
    "public_token": "token",
    "status": "open",
    "visitor_name": "Amy",
    "visitor_email": "amy@example.com",
    "visitor_language": "en",
    "operator_language": "zh-hans",
    "last_message_at": null,
    "unread_for_operator": 0,
    "unread_for_visitor": 0,
    "last_message_preview": "",
    "last_message_preview_visitor": "",
    "last_message_sender_type": "",
    "has_contact_details": true
  },
  "messages": [],
  "poll_interval_ms": 3000,
  "background_poll_interval_ms": 9000,
  "widget_enabled": true
}
```

### Get session detail

- `GET /api/lobster/customer-service/sessions/{public_token}`

### Get incremental messages

- `GET /api/lobster/customer-service/sessions/{public_token}/messages?after=0`

Response:

```json
{
  "messages": [
    {
      "id": 14,
      "sender_type": "visitor",
      "text": "Hello from local test",
      "original_text": "Hello from local test",
      "original_language": "en",
      "translation_status": "translated",
      "created_at": "2026-04-23T07:35:47.105353+00:00"
    }
  ],
  "session": {
    "id": 1,
    "public_token": "token",
    "status": "waiting_operator"
  }
}
```

### Send visitor message

- `POST /api/lobster/customer-service/sessions/{public_token}/messages/send`

Request body:

```json
{
  "text": "Need help with sizing"
}
```

Response:

```json
{
  "message": {
    "id": 15,
    "sender_type": "visitor",
    "text": "Need help with sizing",
    "original_text": "Need help with sizing",
    "original_language": "en",
    "translation_status": "translated",
    "created_at": "2026-04-23T07:35:47.105353+00:00"
  }
}
```

### Mark session as read

- `POST /api/lobster/customer-service/sessions/{public_token}/read`

Response:

```json
{
  "ok": true
}
```

## Admin API

Admin API requires Django login and `is_staff=true`.

### List sessions

- `GET /api/lobster/customer-service/admin/sessions`

Supported query params:
- `status`
- `visitor_email`
- `visitor_name`
- `limit`

### Get session messages

- `GET /api/lobster/customer-service/admin/sessions/{id}/messages?after=0`

### Send operator reply

- `POST /api/lobster/customer-service/admin/sessions/{id}/messages/send`

Request body:

```json
{
  "text": "你好，我来帮你处理。"
}
```

### Close session

- `POST /api/lobster/customer-service/admin/sessions/{id}/close`

Response:

```json
{
  "ok": true,
  "session": {
    "id": 1,
    "status": "closed"
  }
}
```

## Error responses

```json
{
  "error": "Message text cannot be empty."
}
```

Status codes:

- `400` invalid parameter or empty message
- `403` admin API without staff permission
- `404` session not found
- `409` session already closed
- `429` rate limited

## Notes

- `public_token` should be treated as sensitive session access data.
- Existing `/support-chat/*` browser flow remains unchanged.
- Existing `/admin/support-chat/*` operator flow remains unchanged.
- Translation output depends on the configured provider and may fall back to mock output in development.
