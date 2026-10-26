"""OpenAI-compatible Chat Completions and Responses provider."""
import json
import requests
from agent.providers.base import BaseProvider


class OpenAIProvider(BaseProvider):
    def __init__(self, api_key="", base_url="https://api.openai.com/v1", model="",
                 temperature=0.7, max_tokens=2048, protocol="chat",
                 models_path="/models", auth_mode="bearer",
                 supports_temperature=True, thinking_level="none", thinking_mode="none"):
        self.api_key = api_key
        self.base_url = (base_url or "").rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.protocol = protocol if protocol in ("chat", "responses") else "chat"
        self.models_path = models_path or "/models"
        self.auth_mode = auth_mode or "bearer"
        self.supports_temperature = supports_temperature
        self.thinking_level = thinking_level
        self.thinking_mode = thinking_mode

    def _headers(self):
        header = "api-key" if self.auth_mode == "api_key" else "Authorization"
        value = self.api_key if header == "api-key" else f"Bearer {self.api_key}"
        return {header: value, "Content-Type": "application/json"}

    def _url(self, path):
        return f"{self.base_url}/{path.lstrip('/')}"

    @staticmethod
    def _response_tools(tools):
        result = []
        for tool in tools or []:
            fn = tool.get("function", tool)
            result.append({
                "type": "function",
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters", {"type": "object", "properties": {}}),
            })
        return result

    @staticmethod
    def _response_input(messages):
        result = []
        for message in messages:
            role = message.get("role")
            if role in ("system", "user"):
                result.append({"role": role, "content": message.get("content", "")})
            elif role == "assistant":
                content = message.get("content") or ""
                if content:
                    result.append({"role": "assistant", "content": content})
                for call in message.get("tool_calls", []):
                    fn = call.get("function", {})
                    result.append({"type": "function_call", "call_id": call.get("id", ""),
                                   "name": fn.get("name", ""), "arguments": fn.get("arguments", "{}")})
            elif role == "tool":
                result.append({"type": "function_call_output",
                               "call_id": message.get("tool_call_id", ""),
                               "output": str(message.get("content", ""))})
        return result

    @staticmethod
    def _extract_text(data):
        if data.get("output_text"):
            return data["output_text"]
        chunks = []
        for item in data.get("output", []):
            for content in item.get("content", []) or []:
                if content.get("type") in ("output_text", "text") and content.get("text"):
                    chunks.append(content["text"])
        return "".join(chunks)

    @staticmethod
    def _extract_tool_calls(data):
        calls = []
        for item in data.get("output", []):
            if item.get("type") != "function_call":
                continue
            calls.append({"id": item.get("call_id") or item.get("id", ""),
                          "type": "function",
                          "function": {"name": item.get("name", ""),
                                       "arguments": item.get("arguments", "{}")} })
        return calls

    def _prepare_messages(self, messages):
        if self.thinking_mode != "deepseek" or self.thinking_level == "none":
            return messages
        prepared = []
        for message in messages:
            item = dict(message)
            if item.get("role") == "assistant" and "reasoning_content" not in item:
                item["reasoning_content"] = ""
            prepared.append(item)
        return prepared

    def _apply_thinking(self, payload):
        level = self.thinking_level or "none"
        if self.thinking_mode == "none":
            return
        if self.thinking_mode == "deepseek":
            payload["thinking"] = {"type": "disabled" if level == "none" else "enabled"}
            return
        if level == "none":
            return
        effort = "high" if level == "max" else level
        if self.protocol == "responses":
            payload["reasoning"] = {"effort": effort}
        else:
            payload["reasoning_effort"] = effort

    def _effective_max_tokens(self, override=None):
        """决定这次请求要不要带 max_tokens（以及带多少）。

        返回 None 表示**不带这个参数**。

        为什么要允许"不带"：
          - 有些模型（尤其推理模型）不认 max_tokens，带了直接 400；
          - 用户把它填成 2048000 这种超出模型总上下文的值时，
            上游会算成"输入 12 + 输出 2048000 > 262144" → 400。
            实测过这条：OpenRouter 上的 nemotron 就是这么报的。
          - OpenAI 兼容接口里这个参数本来就是可选的，不带 = 用服务端默认，
            这几乎总是安全的。

        判据：只有用户显式设了一个 > 0 的整数才带。
        0、空、None 一律不带。
        """
        value = override if override is not None else self.max_tokens
        try:
            n = int(value)
        except (TypeError, ValueError):
            return None
        return n if n > 0 else None

    def chat(self, messages, tools=None, max_tokens=None, cancel=None):
        if not self.api_key:
            raise ValueError("API key not configured. Please set it in Settings.")
        if not self.model:
            raise ValueError("Model not configured. Please select or enter a model in Settings.")
        if self.protocol == "responses":
            payload = {"model": self.model, "input": self._response_input(messages)}
            limit = self._effective_max_tokens(max_tokens)
            if limit is not None:
                payload["max_output_tokens"] = limit
            if tools:
                payload["tools"] = self._response_tools(tools)
            if self.supports_temperature:
                payload["temperature"] = self.temperature
            self._apply_thinking(payload)
            data = self._post("/responses", payload, cancel=cancel).json()
            calls = self._extract_tool_calls(data)
            result = {"content": self._extract_text(data), "usage": data.get("usage", {})}
            for key in ("cost", "total_cost"):
                if data.get(key) is not None:
                    result["cost"] = data[key]
            if isinstance(result["usage"], dict) and result["usage"].get("cost") is not None:
                result["cost"] = result["usage"]["cost"]
            if calls:
                result["tool_calls"] = calls
            return result

        payload = {"model": self.model, "messages": self._prepare_messages(messages)}
        limit = self._effective_max_tokens(max_tokens)
        if limit is not None:
            payload["max_tokens"] = limit
        if self.supports_temperature:
            payload["temperature"] = self.temperature
        if tools:
            payload["tools"] = tools
        self._apply_thinking(payload)
        data = self._post("/chat/completions", payload, cancel=cancel).json()
        message = data["choices"][0]["message"]
        result = {
            "content": message.get("content", ""),
            "reasoning_content": message.get("reasoning_content") or "",
            "usage": data.get("usage", {}),
        }
        for key in ("cost", "total_cost"):
            if data.get(key) is not None:
                result["cost"] = data[key]
        if isinstance(result["usage"], dict) and result["usage"].get("cost") is not None:
            result["cost"] = result["usage"]["cost"]
        if message.get("tool_calls"):
            result["tool_calls"] = message["tool_calls"]
        return result

    def get_balance(self, balance_path="", balance_parser="", balance_base_url=""):
        # 每种失败都给一个 error_code：前端按码取本地化文案，
        # 不要直接把英文塞在界面上（切到中文界面会冒出一句英文）。
        if not self.api_key:
            return {"ok": False, "supported": False,
                    "error": "API key not configured.", "error_code": "no_key"}
        if not balance_path:
            return {"ok": True, "supported": False,
                    "error": "Provider has no balance endpoint.",
                    "error_code": "no_endpoint"}
        base = (balance_base_url or self.base_url).rstrip("/")
        url = balance_path if str(balance_path).startswith(("http://", "https://")) else f"{base}/{str(balance_path).lstrip('/')}"
        response = requests.get(url, headers=self._headers(), timeout=15)
        if response.status_code in (404, 405):
            return {"ok": True, "supported": False,
                    "error": "Provider does not support balance queries.",
                    "error_code": "unsupported"}
        response.raise_for_status()
        data = response.json()
        parsed = self._parse_balance(data, balance_parser)
        if parsed is None:
            return {"ok": False, "supported": True,
                    "error": "Balance response has no recognized balance field.",
                    "error_code": "no_field"}
        return parsed

    @staticmethod
    def _parse_balance(data, parser=""):
        if not isinstance(data, dict):
            return None
        if parser == "deepseek":
            infos = data.get("balance_infos") or []
            balances = []
            for item in infos:
                if not isinstance(item, dict):
                    continue
                balances.append({
                    "balance": item.get("total_balance"),
                    "currency": item.get("currency", ""),
                })
            if balances:
                return {"ok": True, "supported": True,
                        "balance": balances[0]["balance"],
                        "currency": balances[0]["currency"],
                        "balances": balances,
                        "used": None, "limit": None}
        if parser == "openrouter":
            payload = data.get("data") if isinstance(data.get("data"), dict) else data
            credits = payload.get("total_credits")
            used = payload.get("total_usage")
            if credits is not None or used is not None:
                return {"ok": True, "supported": True,
                        "balance": (float(credits or 0) - float(used or 0)),
                        "currency": "USD", "used": used, "limit": credits}
        for key in ("balance", "available_balance", "remaining", "total_balance"):
            if data.get(key) is not None:
                return {"ok": True, "supported": True, "balance": data.get(key),
                        "currency": data.get("currency", ""), "used": data.get("used"),
                        "limit": data.get("limit")}
        payload = data.get("data")
        if isinstance(payload, dict):
            return OpenAIProvider._parse_balance(payload, parser)
        return None
    def list_models(self):
        if not self.api_key:
            raise ValueError("API key not configured. Please enter an API key first.")
        response = requests.get(self._url(self.models_path), headers=self._headers(), timeout=30)
        response.raise_for_status()
        data = response.json()
        raw = data.get("data", data.get("models", data)) if isinstance(data, dict) else data
        if not isinstance(raw, list):
            raise ValueError("Model list response has an unsupported format.")
        models = []
        for item in raw:
            model_id = item if isinstance(item, str) else item.get("id")
            if model_id:
                models.append(str(model_id))
        return models

    def _post(self, path, payload, cancel=None):
        """POST 一次。传了 cancel 就能被"外部打断"。

        为什么要 Session：`requests.post` 是模块级函数，请求中间没有句柄
        可以从别的线程关掉。睡眠整理、长超时这类调用一旦卡住，
        用户回来了也只能干等到 180 秒读超时 —— 只能靠 close 掉连接来立刻打断。
        """
        if cancel is None:
            response = requests.post(self._url(path), headers=self._headers(), json=payload,
                                     timeout=(30, 180))
            response.raise_for_status()
            return response

        from agent.cancel import CancelledError

        session = requests.Session()
        cancel.on_cancel(session.close)
        try:
            cancel.raise_if_cancelled()
            response = session.post(self._url(path), headers=self._headers(),
                                    json=payload, timeout=(30, 180))
        except CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            if cancel.cancelled:
                # close() 导致的连接中断，不是真的网络错误
                raise CancelledError("cancelled while waiting for response") from exc
            raise
        finally:
            cancel.remove_cancel_callback(session.close)
            try:
                session.close()
            except Exception:
                pass
        cancel.raise_if_cancelled()
        response.raise_for_status()
        return response

    # -- 流式 ---------------------------------------------------------------

    def stream_chat(self, messages, tools=None, max_tokens=None, on_delta=None, cancel=None):
        """流式聊天，边收边回调。

        参数
            on_delta(text, kind)  kind ∈ {"content", "reasoning"}
                                  每收到一片增量文本就调用一次
            cancel                agent.cancel.CancelToken 或 None

        返回 **和 chat() 完全同构的 dict**：
            {"content", "reasoning_content", "usage", "tool_calls"?, "cost"?}

        关键：工具调用的参数是**分片流式到达**的，所以这里做两件事：

          1. **累积**每个 tool_call 的 name / arguments 分片（按 index 归并）；
          2. **整条流结束（收到 finish_reason 或 [DONE]）之后**才组装出
             完整的 tool_calls 返回给上层。

        也就是说：**工具调用绝不会在首个 token 到达时就被触发**。
        这是硬要求 —— 参数没拼完就执行会得到残缺 JSON，工具必然调不起来。

        取消语义：取消时立刻 close 掉 HTTP 响应（不再读 body、不再计费），
        然后抛 CancelledError。上层负责回滚历史。
        """
        from agent.cancel import CancelledError, CancelToken

        if not self.api_key:
            raise ValueError("API key not configured. Please set it in Settings.")
        if not self.model:
            raise ValueError("Model not configured. Please select or enter a model in Settings.")

        if cancel is None:
            cancel = CancelToken()

        if self.protocol == "responses":
            return self._stream_responses(
                messages, tools, max_tokens, on_delta, cancel
            )

        payload = {
            "model": self.model,
            "messages": self._prepare_messages(messages),
            "stream": True,
        }
        # 只在用户显式设了正数时才带输出上限 —— 见 _effective_max_tokens 的说明。
        # 带一个超出模型总上下文的值会直接被上游 400。
        limit = self._effective_max_tokens(max_tokens)
        if limit is not None:
            payload["max_tokens"] = limit
        if self.supports_temperature:
            payload["temperature"] = self.temperature
        if tools:
            payload["tools"] = tools
        self._apply_thinking(payload)

        content_parts = []
        reasoning_parts = []
        usage = {}
        cost = None
        finish_reason = None

        # index -> 正在累积的工具调用
        pending_calls = {}

        response = None
        try:
            response = requests.post(
                self._url("/chat/completions"),
                headers=self._headers(),
                json=payload,
                stream=True,
                # 读间隔 30 秒：模型不吐字时不该占着线程五分钟。
                # 真正的"秒停"靠下面的 reset_cancel 回调关连接，不靠超时。
                timeout=(30, 30),
            )
            response.raise_for_status()
            # 请求还没开始读就被取消（用户点得很快）：别读完整个流才发现
            cancel.raise_if_cancelled()
            cancel.on_cancel(response.close)

            for raw_line in response.iter_lines(decode_unicode=False):
                # 每读一行都检查取消 —— 这是"停止"能秒响应的关键
                cancel.raise_if_cancelled()

                if not raw_line:
                    continue
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                if line.startswith(":"):
                    continue  # SSE 注释（部分厂商用来发心跳）
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break

                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue

                if chunk.get("usage"):
                    usage = chunk["usage"]
                for key in ("cost", "total_cost"):
                    if chunk.get(key) is not None:
                        cost = chunk[key]

                choices = chunk.get("choices") or []
                if not choices:
                    continue
                choice = choices[0]
                delta = choice.get("delta") or {}

                piece = delta.get("content")
                if piece:
                    content_parts.append(piece)
                    if on_delta:
                        on_delta(piece, "content")

                reason_piece = delta.get("reasoning_content") or delta.get("reasoning")
                if reason_piece:
                    reasoning_parts.append(reason_piece)
                    if on_delta:
                        on_delta(reason_piece, "reasoning")

                # 工具调用分片：只累积，**不执行**
                for call in delta.get("tool_calls") or []:
                    index = call.get("index", 0)
                    slot = pending_calls.setdefault(
                        index,
                        {"id": "", "type": "function",
                         "function": {"name": "", "arguments": ""}},
                    )
                    if call.get("id"):
                        slot["id"] = call["id"]
                    if call.get("type"):
                        slot["type"] = call["type"]
                    fn = call.get("function") or {}
                    if fn.get("name"):
                        slot["function"]["name"] += fn["name"]
                    if fn.get("arguments"):
                        slot["function"]["arguments"] += fn["arguments"]

                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]

        except CancelledError:
            # 主动取消：关掉连接，绝不再读
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass
            raise
        except Exception as exc:
            # 取消回调 close() 掉连接后，iter_lines 抛的异常长得跟网络错误
            # 一模一样。这里必须按「是否已取消」判定，否则用户点了停止，
            # 界面上却显示成「请求失败」。
            if cancel.cancelled:
                raise CancelledError("cancelled while streaming") from exc
            raise
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass

        # 流结束，此时参数才拼完整 —— 可以安全交给上层了
        result = {
            "content": "".join(content_parts),
            "reasoning_content": "".join(reasoning_parts),
            "usage": usage or {},
        }
        if cost is not None:
            result["cost"] = cost
        if isinstance(usage, dict) and usage.get("cost") is not None:
            result["cost"] = usage["cost"]

        calls = []
        for index in sorted(pending_calls):
            slot = pending_calls[index]
            if not slot["function"]["name"]:
                continue
            calls.append({
                "id": slot["id"] or f"call_{index}",
                "type": slot["type"] or "function",
                "function": {
                    "name": slot["function"]["name"],
                    "arguments": slot["function"]["arguments"] or "{}",
                },
            })
        if calls:
            result["tool_calls"] = calls
        result["finish_reason"] = finish_reason
        return result

    def _stream_responses(self, messages, tools, max_tokens, on_delta, cancel):
        """Responses API 的流式分支。

        该协议用 `response.output_text.delta` / `response.function_call_arguments.delta`
        这类事件名，与 chat completions 不同，所以单独实现。
        """
        from agent.cancel import CancelledError

        payload = {
            "model": self.model,
            "input": self._response_input(messages),
            "stream": True,
        }
        limit = self._effective_max_tokens(max_tokens)
        if limit is not None:
            payload["max_output_tokens"] = limit
        if tools:
            payload["tools"] = self._response_tools(tools)
        if self.supports_temperature:
            payload["temperature"] = self.temperature
        self._apply_thinking(payload)

        content_parts = []
        reasoning_parts = []
        usage = {}
        cost = None
        calls = {}          # item_id -> {id, name, arguments}

        response = None
        try:
            response = requests.post(
                self._url("/responses"),
                headers=self._headers(),
                json=payload,
                stream=True,
                timeout=(30, 30),
            )
            response.raise_for_status()
            cancel.raise_if_cancelled()
            cancel.on_cancel(response.close)

            for raw_line in response.iter_lines(decode_unicode=False):
                cancel.raise_if_cancelled()
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue

                etype = event.get("type", "")

                if etype == "response.output_text.delta":
                    piece = event.get("delta") or ""
                    if piece:
                        content_parts.append(piece)
                        if on_delta:
                            on_delta(piece, "content")

                elif etype in ("response.reasoning_summary_text.delta",
                               "response.reasoning_text.delta"):
                    piece = event.get("delta") or ""
                    if piece:
                        reasoning_parts.append(piece)
                        if on_delta:
                            on_delta(piece, "reasoning")

                elif etype == "response.output_item.added":
                    item = event.get("item") or {}
                    if item.get("type") == "function_call":
                        calls[item.get("id") or "0"] = {
                            "id": item.get("call_id") or item.get("id") or "0",
                            "name": item.get("name", ""),
                            "arguments": item.get("arguments", "") or "",
                        }

                elif etype == "response.function_call_arguments.delta":
                    key = event.get("item_id") or "0"
                    slot = calls.setdefault(key, {"id": key, "name": "", "arguments": ""})
                    slot["arguments"] += event.get("delta") or ""

                elif etype == "response.output_item.done":
                    item = event.get("item") or {}
                    if item.get("type") == "function_call":
                        key = item.get("id") or "0"
                        slot = calls.setdefault(key, {"id": key, "name": "", "arguments": ""})
                        slot["name"] = item.get("name", slot["name"])
                        slot["arguments"] = item.get("arguments", slot["arguments"])
                        slot["id"] = item.get("call_id") or item.get("id") or slot["id"]

                elif etype == "response.completed":
                    payload_done = event.get("response") or {}
                    if payload_done.get("usage"):
                        usage = payload_done["usage"]
                    for key in ("cost", "total_cost"):
                        if payload_done.get(key) is not None:
                            cost = payload_done[key]

        except CancelledError:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass
            raise
        except Exception as exc:
            # 同 chat/completions 分支：close() 造成的读异常要按取消处理
            if cancel.cancelled:
                raise CancelledError("cancelled while streaming") from exc
            raise
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass

        result = {
            "content": "".join(content_parts),
            "reasoning_content": "".join(reasoning_parts),
            "usage": usage or {},
        }
        if cost is not None:
            result["cost"] = cost
        if isinstance(usage, dict) and usage.get("cost") is not None:
            result["cost"] = usage["cost"]

        out_calls = []
        for key in calls:
            slot = calls[key]
            if not slot["name"]:
                continue
            out_calls.append({
                "id": slot["id"],
                "type": "function",
                "function": {"name": slot["name"],
                             "arguments": slot["arguments"] or "{}"},
            })
        if out_calls:
            result["tool_calls"] = out_calls
        return result
