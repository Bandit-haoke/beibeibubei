package com.beibei.common;

import java.io.Serializable;

/**
 * 统一响应体。
 *
 * <p>与 {@code beibei-agent} 的 Pydantic {@code Envelope} 对齐：
 * <pre>
 * { "code": 0, "msg": "ok", "data": {...}, "traceId": "a1b2c3d4" }
 * </pre>
 *
 * <p>约定 code：0 成功；400x 参数/业务错误；401 未登录；500 服务异常；
 * 5031 智能体未启动；5032 语音服务不可用。
 */
public record Result<T>(int code, String msg, T data, String traceId) implements Serializable {

    public static final int OK = 0;
    public static final int BAD_REQUEST = 4000;
    public static final int UNAUTHORIZED = 401;
    public static final int SERVER_ERROR = 500;
    /** 智能体未启动 */
    public static final int AGENT_DOWN = 5031;
    /** 语音服务不可用 */
    public static final int ASR_UNAVAILABLE = 5032;

    public static <T> Result<T> ok(T data) {
        return new Result<>(OK, "ok", data, null);
    }

    public static <T> Result<T> ok() {
        return new Result<>(OK, "ok", null, null);
    }

    public static <T> Result<T> fail(int code, String msg) {
        return new Result<>(code, msg, null, null);
    }

    public static <T> Result<T> fail(String msg) {
        return new Result<>(SERVER_ERROR, msg, null, null);
    }

    public Result<T> withTraceId(String traceId) {
        return new Result<>(this.code, this.msg, this.data, traceId);
    }
}
